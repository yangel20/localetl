"""Pipeline execution: extract -> transform -> validate -> load -> publish (ETL-07).

``run_pipeline`` is usable on its own, without the API or the worker::

    import uuid
    from pathlib import Path

    import sqlalchemy as sa

    from app.etl import CsvOptions, run_pipeline, validate_pipeline_config

    config = validate_pipeline_config(
        {
            "version": 1,
            "columns": [
                {"source": "id", "name": "id", "type": "integer", "nullable": False},
                {"source": "name", "name": "name", "type": "string"},
            ],
            "target": {"table": "people", "mode": "replace"},
        }
    )
    engine = sa.create_engine("postgresql+psycopg://user:pass@127.0.0.1:5432/localetl")
    result = run_pipeline(
        config, Path("people.csv"), CsvOptions(), engine, uuid.uuid4(),
        on_event=lambda e: print(e.stage, e.status, e.counters),
    )
    print(result.published.table, result.loaded_count, result.rejected_count)

The schemas ``staging`` and ``datasets`` must exist (migrations create them). The
engine writes only there, never to ``public``.

Semantics (docs/architecture.md section 5, decisions Q3, Q4, Q7, Q11):

* Chunks flow through the stages one at a time. Counters are cumulative and only
  updated when a chunk has completed every stage, so events, counters and
  rejections always describe *completed chunks* (checkpoints).
* After each completed chunk, four ``progress`` events (extract, transform,
  validate, load) are emitted with identical post-chunk counters. A chunk that
  does not complete emits none.
* Under ``on_validation_failure: fail_run`` the earliest stage in pipeline order
  raises for a chunk (extract ``parse_error``, then transform, then validate).
* On any exception a ``failed`` event is emitted for the current stage (message
  ``interrupted`` for ``RunInterrupted``), the staging table is dropped, and the
  raised ``EtlError`` carries ``rejected_sample``.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import sqlalchemy as sa

from .config import validate_pipeline_config
from .errors import EtlError, LoadError, RejectionLimitExceeded, RunInterrupted, SourceMismatchError
from .extract import iter_csv_chunks
from .load import Loader
from .transform import Transformer
from .types import (
    ColumnType,
    CsvOptions,
    EventStatus,
    PipelineConfig,
    RejectedRow,
    RunCounters,
    RunResult,
    Stage,
    StageEvent,
)
from .validate import Validator, check_rejection_ratio

MAX_REJECTED_SAMPLE = 1_000
_CHUNK_STAGES: tuple[Stage, ...] = ("extract", "transform", "validate", "load")
_STAGE_ORDER: tuple[Stage, ...] = (*_CHUNK_STAGES, "publish")
_INTERRUPTED = "interrupted"


@dataclass
class _State:
    stage: Stage = "extract"
    extracted: int = 0
    staged: int = 0
    loaded: int = 0  # 0 until the publish transaction commits
    rejected: int = 0
    duplicate_dropped: int = 0
    null_dropped: int = 0
    sample: list[RejectedRow] = field(default_factory=list)
    durations: dict[Stage, float] = field(default_factory=lambda: dict.fromkeys(_STAGE_ORDER, 0.0))
    rows_in: dict[Stage, int] = field(default_factory=lambda: dict.fromkeys(_STAGE_ORDER, 0))
    rows_out: dict[Stage, int] = field(default_factory=lambda: dict.fromkeys(_STAGE_ORDER, 0))

    def counters(self) -> RunCounters:
        return RunCounters(
            extracted_count=self.extracted,
            loaded_count=self.loaded,
            rejected_count=self.rejected,
            duplicate_dropped_count=self.duplicate_dropped,
            null_dropped_count=self.null_dropped,
        )


def _assert_balanced(
    extracted: int, staged: int, rejected: int, duplicate_dropped: int, null_dropped: int
) -> None:
    """Q3 rules 3 and 4: every extracted row has exactly one outcome."""
    if extracted != staged + rejected + duplicate_dropped + null_dropped:
        raise EtlError(
            "row accounting mismatch: "
            f"extracted {extracted} != staged {staged} + rejected {rejected} "
            f"+ duplicate-dropped {duplicate_dropped} + null-dropped {null_dropped}"
        )


def run_pipeline(
    config: PipelineConfig,
    source_path: Path,
    csv_options: CsvOptions,
    engine: sa.Engine,
    run_id: UUID,
    *,
    chunk_rows: int = 50_000,
    on_event: Callable[[StageEvent], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> RunResult:
    state = _State()
    loader: Loader | None = None

    def emit(
        stage: Stage,
        status: EventStatus,
        rows_in: int | None,
        rows_out: int | None,
        message: str | None = None,
    ) -> None:
        if on_event is not None:
            on_event(
                StageEvent(
                    stage=stage,
                    status=status,
                    rows_in=rows_in,
                    rows_out=rows_out,
                    message=message,
                    at=datetime.now(UTC),
                    counters=state.counters(),
                )
            )

    def checkpoint(stage: Stage) -> None:
        state.stage = stage
        if should_stop is not None and should_stop():
            raise RunInterrupted(_INTERRUPTED)

    def timed(stage: Stage, started: float) -> None:
        state.durations[stage] += time.perf_counter() - started

    try:
        for stage in _CHUNK_STAGES:
            emit(stage, "started", None, None)
        state.stage = "extract"
        config = validate_pipeline_config(config.raw)
        raw = config.raw
        fail_run = raw.get("on_validation_failure", "reject_row") == "fail_run"
        columns: list[tuple[str, ColumnType]] = [(c["name"], c["type"]) for c in raw["columns"]]
        state.stage = "transform"
        transformer = Transformer(config)
        state.stage = "validate"
        validator = Validator(config)
        state.stage = "load"
        loader = Loader(engine, run_id, columns)
        loader.create()

        chunks = iter_csv_chunks(source_path, csv_options, chunk_rows=chunk_rows)
        first = True
        while True:
            checkpoint("extract")
            started = time.perf_counter()
            chunk = next(chunks, None)
            timed("extract", started)
            if chunk is None:
                break
            if first:
                first = False
                missing = [
                    c["source"] for c in raw["columns"] if c["source"] not in chunk.frame.columns
                ]
                if missing:
                    raise SourceMismatchError(
                        "source columns missing from the CSV: "
                        + ", ".join(repr(m) for m in missing)
                    )
            if fail_run and chunk.rejected:
                head = min(chunk.rejected, key=lambda r: r.row_number)
                raise RejectionLimitExceeded(
                    f"on_validation_failure=fail_run: row {head.row_number} failed "
                    f"{head.rule}: {head.message}"
                )

            checkpoint("transform")
            started = time.perf_counter()
            tr = transformer.transform_chunk(chunk.frame, chunk.row_numbers)
            timed("transform", started)

            checkpoint("validate")
            started = time.perf_counter()
            va = validator.validate_chunk(tr.frame, tr.row_numbers)
            timed("validate", started)

            checkpoint("load")
            started = time.perf_counter()
            valid_numbers = [tr.row_numbers[int(i)] for i in va.valid.index]
            written = loader.load_chunk(va.valid, valid_numbers)
            timed("load", started)

            # The chunk is complete: fold it into the cumulative counters (checkpoint).
            rejected_here = len(chunk.rejected) + tr.rejected_rows + va.rejected_rows
            totals = (
                state.extracted + chunk.records,
                state.staged + written,
                state.rejected + rejected_here,
                state.duplicate_dropped + tr.duplicate_dropped,
                state.null_dropped + tr.null_dropped,
            )
            _assert_balanced(*totals)
            entries = [(r.row_number, 0, r) for r in chunk.rejected]
            entries += [(r.row_number, 1, r) for r in tr.rejections]
            entries += [(r.row_number, 2, r) for r in va.rejections]
            entries.sort(key=lambda e: (e[0], e[1]))
            room = MAX_REJECTED_SAMPLE - len(state.sample)
            if room > 0:
                state.sample.extend(e[2] for e in entries[:room])
            (
                state.extracted,
                state.staged,
                state.rejected,
                state.duplicate_dropped,
                state.null_dropped,
            ) = totals
            numbers_in = {
                "extract": (None, chunk.records),
                "transform": (tr.rows_in, tr.rows_out),
                "validate": (tr.rows_out, len(va.valid)),
                "load": (len(va.valid), written),
            }
            for stage in _CHUNK_STAGES:
                rin, rout = numbers_in[stage]
                state.rows_in[stage] += rin or 0
                state.rows_out[stage] += rout
                emit(stage, "progress", rin, rout)

        checkpoint("validate")
        check_rejection_ratio(config, state.rejected, state.extracted)
        for stage in _CHUNK_STAGES:
            emit(stage, "completed", state.rows_in[stage] or None, state.rows_out[stage])

        checkpoint("publish")
        emit("publish", "started", None, None)
        _assert_balanced(
            state.extracted,
            loader.staged_rows,
            state.rejected,
            state.duplicate_dropped,
            state.null_dropped,
        )
        started = time.perf_counter()
        outcome = loader.publish(raw["target"]["table"], raw["target"]["mode"])
        timed("publish", started)
        state.loaded = outcome.loaded_rows
        emit("publish", "completed", state.staged, outcome.published.row_count)
        return RunResult(
            extracted_count=state.extracted,
            loaded_count=state.loaded,
            rejected_count=state.rejected,
            duplicate_dropped_count=state.duplicate_dropped,
            null_dropped_count=state.null_dropped,
            rejected_sample=list(state.sample),
            published=outcome.published,
            stage_durations_ms={s: int(state.durations[s] * 1000) for s in _STAGE_ORDER},
        )
    except Exception as exc:
        if isinstance(exc, EtlError):
            exc.rejected_sample = list(state.sample)
        try:
            emit(
                state.stage,
                "failed",
                None,
                None,
                _INTERRUPTED if isinstance(exc, RunInterrupted) else str(exc),
            )
        except Exception:  # a failing callback must not mask the original error
            pass
        raise
    finally:
        if loader is not None:
            try:
                loader.drop()
            except LoadError:
                pass
