"""Execute a claimed run: call the ETL engine and persist events, counters and results.

Transactions follow architecture section 7.2 (progress, success, failure). Every write is
guarded by `status='running' AND worker_id=:wid`, so a worker that lost its run (for example
after being recovered as stale) cannot overwrite it.
"""

import json
import logging
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import sqlalchemy as sa

from app.etl import (
    ConfigValidationError,
    CsvOptions,
    EtlError,
    RejectedRow,
    RunInterrupted,
    RunResult,
    StageEvent,
    run_pipeline,
    validate_pipeline_config,
)

log = logging.getLogger("localetl.worker")

MAX_REJECTIONS = 1000


class RunNotOwned(RuntimeError):
    """The run is no longer `running` under this worker (e.g. recovered as stale)."""


_LOAD_RUN = sa.text(
    """
    SELECT r.pipeline_id, r.config_snapshot, s.stored_path, s.csv_options, s.columns
    FROM runs r LEFT JOIN data_sources s ON s.id = r.source_id
    WHERE r.id = :id AND r.status = 'running' AND r.worker_id = :wid
    """
)
_EVENT = sa.text(
    """
    INSERT INTO run_events (run_id, stage, status, rows_in, rows_out, message, created_at)
    VALUES (:id, :stage, :status, :rows_in, :rows_out, :message, :at)
    """
)
_PROGRESS = sa.text(
    """
    UPDATE runs SET extracted_count=:e, loaded_count=:l, rejected_count=:r,
        duplicate_dropped_count=:d, null_dropped_count=:n, current_stage=:stage, heartbeat_at=now()
    WHERE id=:id AND status='running' AND worker_id=:wid
    """
)
_REJECTION = sa.text(
    """
    INSERT INTO run_rejections (run_id, row_number, column_name, rule, message, value)
    VALUES (:run_id, :row_number, :column_name, :rule, :message, :value)
    """
)
_UPSERT_DATASET = sa.text(
    """
    INSERT INTO datasets
        (id, table_name, pipeline_id, last_run_id, row_count, columns, published_at)
    VALUES (gen_random_uuid(), :table, :pid, :rid, :rows, CAST(:cols AS jsonb), now())
    ON CONFLICT (table_name) DO UPDATE SET pipeline_id = EXCLUDED.pipeline_id,
        last_run_id = EXCLUDED.last_run_id, row_count = EXCLUDED.row_count,
        columns = EXCLUDED.columns, published_at = EXCLUDED.published_at
    RETURNING id
    """
)
_SUCCEED = sa.text(
    """
    UPDATE runs SET status='succeeded', finished_at=now(), error_message=NULL,
        extracted_count=:e, loaded_count=:l, rejected_count=:r,
        duplicate_dropped_count=:d, null_dropped_count=:n, dataset_id=:ds
    WHERE id=:id AND status='running' AND worker_id=:wid
    """
)
_FAIL = sa.text(
    """
    UPDATE runs SET status=:status, finished_at=now(), error_message=:msg
    WHERE id=:id AND status='running' AND worker_id=:wid
    """
)


def _insert_rejections(conn: sa.Connection, run_id: uuid.UUID, rows: list[RejectedRow]) -> None:
    params = [
        {
            "run_id": run_id,
            "row_number": r.row_number,
            "column_name": r.column,
            "rule": r.rule,
            "message": r.message,
            "value": r.value,
        }
        for r in rows[:MAX_REJECTIONS]
    ]
    if params:
        conn.execute(_REJECTION, params)


def record_event(engine: sa.Engine, run_id: uuid.UUID, worker_id: str, ev: StageEvent) -> None:
    """Progress transaction: event row, counters, current_stage and heartbeat together."""
    c = ev.counters
    with engine.begin() as conn:
        res = conn.execute(
            _PROGRESS,
            {
                "id": run_id,
                "wid": worker_id,
                "stage": ev.stage,
                "e": c.extracted_count,
                "l": 0,  # CHECK runs_unsuccessful_loaded_zero: set by the success transaction
                "r": c.rejected_count,
                "d": c.duplicate_dropped_count,
                "n": c.null_dropped_count,
            },
        )
        if res.rowcount != 1:
            raise RunNotOwned(str(run_id))
        conn.execute(
            _EVENT,
            {
                "id": run_id,
                "stage": ev.stage,
                "status": ev.status,
                "rows_in": ev.rows_in,
                "rows_out": ev.rows_out,
                "message": ev.message,
                "at": ev.at,
            },
        )


def record_success(
    engine: sa.Engine,
    run_id: uuid.UUID,
    worker_id: str,
    pipeline_id: uuid.UUID | None,
    res: RunResult,
) -> None:
    with engine.begin() as conn:
        pub = res.published
        dataset_id: uuid.UUID = conn.execute(
            _UPSERT_DATASET,
            {
                "table": pub.table,
                "pid": pipeline_id,
                "rid": run_id,
                "rows": pub.row_count,
                "cols": json.dumps([{"name": n, "type": t} for n, t in pub.columns]),
            },
        ).scalar_one()
        out = conn.execute(
            _SUCCEED,
            {
                "id": run_id,
                "wid": worker_id,
                "e": res.extracted_count,
                "l": res.loaded_count,
                "r": res.rejected_count,
                "d": res.duplicate_dropped_count,
                "n": res.null_dropped_count,
                "ds": dataset_id,
            },
        )
        if out.rowcount != 1:
            raise RunNotOwned(str(run_id))  # rolls back the registry upsert
        _insert_rejections(conn, run_id, res.rejected_sample)


def record_failure(
    engine: sa.Engine,
    run_id: uuid.UUID,
    worker_id: str,
    status: str,
    message: str,
    rejected: list[RejectedRow],
) -> bool:
    """Failure transaction; counters stay as last persisted by progress events."""
    with engine.begin() as conn:
        out = conn.execute(
            _FAIL, {"id": run_id, "wid": worker_id, "status": status, "msg": message}
        )
        if out.rowcount != 1:
            return False
        _insert_rejections(conn, run_id, rejected)
    return True


def _describe(exc: BaseException) -> str:
    if isinstance(exc, ConfigValidationError) and exc.errors:
        detail = "; ".join(f"{e.path}: {e.message}" for e in exc.errors[:5])
        return f"{exc} ({detail})" if str(exc) else detail
    text = str(exc)
    return text or type(exc).__name__


def resolve_source_path(data_dir: Path, stored_path: str) -> Path:
    """`data_dir / stored_path`, refusing absolute paths and anything escaping data_dir."""
    root = data_dir.resolve()
    path = (root / stored_path).resolve()
    if Path(stored_path).is_absolute() or not path.is_relative_to(root):
        raise ValueError("source path is outside the data directory")
    return path


def execute_run(
    engine: sa.Engine,
    run_id: uuid.UUID,
    worker_id: str,
    *,
    data_dir: Path,
    chunk_rows: int,
    should_stop: Callable[[], bool] | None = None,
) -> None:
    """Run one claimed run to a terminal state. Never raises for run-level problems."""
    try:
        with engine.connect() as conn:
            row = conn.execute(_LOAD_RUN, {"id": run_id, "wid": worker_id}).first()
        if row is None:
            log.warning("run %s is not running under %s; skipping", run_id, worker_id)
            return
        if row.stored_path is None:
            raise EtlError("data source no longer exists")
        snapshot: dict[str, Any] = row.config_snapshot
        source_columns = [c["name"] for c in row.columns]
        config = validate_pipeline_config(snapshot, source_columns=source_columns)
        result = run_pipeline(
            config,
            resolve_source_path(data_dir, row.stored_path),
            CsvOptions(**row.csv_options),
            engine,
            run_id,
            chunk_rows=chunk_rows,
            on_event=lambda ev: record_event(engine, run_id, worker_id, ev),
            should_stop=should_stop,
        )
        record_success(engine, run_id, worker_id, row.pipeline_id, result)
    except RunNotOwned:
        log.warning("run %s lost by %s; not writing a result", run_id, worker_id)
    except RunInterrupted as exc:
        record_failure(engine, run_id, worker_id, "interrupted", _describe(exc), _sample(exc))
    except EtlError as exc:
        record_failure(engine, run_id, worker_id, "failed", _describe(exc), _sample(exc))
    except Exception as exc:  # unexpected: the run must not stay `running`
        log.exception("run %s crashed", run_id)
        record_failure(
            engine, run_id, worker_id, "failed", f"{type(exc).__name__}: {exc}", _sample(exc)
        )


def _sample(exc: BaseException) -> list[RejectedRow]:
    return list(getattr(exc, "rejected_sample", []))


__all__ = ["RunNotOwned", "execute_run", "record_event", "record_failure", "record_success"]
