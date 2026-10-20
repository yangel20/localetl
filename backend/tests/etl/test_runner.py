"""ETL-07: run_pipeline end to end on a throwaway PostgreSQL database."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import sqlalchemy as sa

from app.etl import (
    ConfigValidationError,
    CsvFormatError,
    CsvOptions,
    EtlError,
    LoadError,
    PipelineConfig,
    RejectionLimitExceeded,
    RunInterrupted,
    RunResult,
    SourceMismatchError,
    StageEvent,
    run_pipeline,
    validate_pipeline_config,
)
from app.etl.load import Loader

pytestmark = pytest.mark.db

COUNTER_FIELDS = (
    "extracted_count",
    "loaded_count",
    "rejected_count",
    "duplicate_dropped_count",
    "null_dropped_count",
)


# ------------------------------------------------------------------- helpers


@pytest.fixture
def fx(repo_root: Path) -> Path:
    return repo_root / "tests" / "fixtures"


@pytest.fixture
def expected(fx: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((fx / "expected.json").read_text())
    return data


def load_config(repo_root: Path, rel: str) -> PipelineConfig:
    if rel.startswith("pipelines/"):  # expected.json paths are relative to tests/fixtures
        rel = f"tests/fixtures/{rel}"
    return validate_pipeline_config(json.loads((repo_root / rel).read_text()))


def counters_of(obj: Any) -> dict[str, int]:
    return {f: getattr(obj, f) for f in COUNTER_FIELDS}


def counters_of_event(event: StageEvent) -> dict[str, int]:
    return counters_of(event.counters)


class Run:
    """Outcome of one run_pipeline call: result or error, plus every event."""

    def __init__(self) -> None:
        self.events: list[StageEvent] = []
        self.result: RunResult | None = None
        self.error: Exception | None = None

    @property
    def progress(self) -> list[StageEvent]:
        return [e for e in self.events if e.status == "progress"]


def go(
    engine: sa.Engine,
    config: PipelineConfig,
    csv_path: Path,
    *,
    chunk_rows: int = 50_000,
    options: CsvOptions | None = None,
    should_stop: Any = None,
    expect_error: bool = False,
) -> Run:
    out = Run()
    try:
        out.result = run_pipeline(
            config,
            csv_path,
            options or CsvOptions(),
            engine,
            uuid.uuid4(),
            chunk_rows=chunk_rows,
            on_event=out.events.append,
            should_stop=should_stop,
        )
    except Exception as exc:
        if not expect_error:
            raise
        out.error = exc
    else:
        assert not expect_error, "expected the run to fail"
    return out


def tables(engine: sa.Engine, schema: str) -> list[str]:
    return sorted(sa.inspect(engine).get_table_names(schema=schema))


def table_ids(engine: sa.Engine, table: str, column: str = "order_id") -> list[int]:
    with engine.connect() as conn:
        rows = conn.execute(sa.text(f'SELECT "{column}" FROM datasets."{table}" ORDER BY 1'))
        return [int(r[0]) for r in rows]


def assert_balanced(c: dict[str, int]) -> None:
    assert c["extracted_count"] == (
        c["loaded_count"]
        + c["rejected_count"]
        + c["duplicate_dropped_count"]
        + c["null_dropped_count"]
    )


# --------------------------------------------- fixtures: counters vs expected

CHUNKS = [1, 2, 7, 50_000]


@pytest.mark.parametrize("chunk_rows", CHUNKS)
def test_orders_clean_replace(
    etl_engine: sa.Engine, repo_root: Path, fx: Path, expected: dict[str, Any], chunk_rows: int
) -> None:
    config = load_config(repo_root, "contracts/examples/pipeline/valid/orders_full.json")
    run = go(etl_engine, config, fx / "csv" / "orders_clean.csv", chunk_rows=chunk_rows)
    assert run.result is not None
    assert counters_of(run.result) == expected["orders_clean.csv"]["counters"]
    assert run.result.published.row_count == 200 and run.result.published.table == "orders"
    assert tables(etl_engine, "staging") == [] and tables(etl_engine, "datasets") == ["orders"]
    assert table_ids(etl_engine, "orders") == list(range(1, 201))


def test_orders_clean_append_twice(
    etl_engine: sa.Engine, repo_root: Path, fx: Path, expected: dict[str, Any]
) -> None:
    config = load_config(repo_root, "tests/fixtures/pipelines/orders_append.json")
    first = go(etl_engine, config, fx / "csv" / "orders_clean.csv")
    second = go(etl_engine, config, fx / "csv" / "orders_clean.csv", chunk_rows=7)
    assert second.result is not None and first.result is not None
    want = expected["orders_clean.csv"]["append_twice"]
    assert counters_of(second.result) == want["second_run_counters"]
    assert second.result.published.row_count == want["published_row_count"] == 400
    assert first.result.published.row_count == 200


def test_append_mismatch_raises_load_error_and_leaves_table_untouched(
    etl_engine: sa.Engine, repo_root: Path, fx: Path
) -> None:
    go(
        etl_engine,
        load_config(repo_root, "tests/fixtures/pipelines/orders_append.json"),
        fx / "csv" / "orders_clean.csv",
    )
    bad = load_config(repo_root, "tests/fixtures/pipelines/orders_append_mismatch.json")
    run = go(etl_engine, bad, fx / "csv" / "orders_clean.csv", expect_error=True)
    assert isinstance(run.error, LoadError)
    assert run.events[-1].status == "failed" and run.events[-1].stage == "publish"
    assert run.events[-1].counters.loaded_count == 0
    assert len(table_ids(etl_engine, "orders")) == 200 and tables(etl_engine, "staging") == []


@pytest.mark.parametrize("chunk_rows", CHUNKS)
def test_orders_nulls(
    etl_engine: sa.Engine, repo_root: Path, fx: Path, expected: dict[str, Any], chunk_rows: int
) -> None:
    config = load_config(repo_root, "tests/fixtures/pipelines/orders_nulls.json")
    run = go(etl_engine, config, fx / "csv" / "orders_nulls.csv", chunk_rows=chunk_rows)
    assert run.result is not None
    assert counters_of(run.result) == expected["orders_nulls.csv"]["counters"]
    assert {r.rule for r in run.result.rejected_sample} == {"not_null"}


@pytest.mark.parametrize("chunk_rows", [1, 2, 3, 5, 7, 9, 50_000])
def test_chunk_dupes_identical_counters(
    etl_engine: sa.Engine, repo_root: Path, fx: Path, expected: dict[str, Any], chunk_rows: int
) -> None:
    e = expected["orders_chunk_dupes.csv"]
    config = load_config(repo_root, e["config"])
    run = go(etl_engine, config, fx / "csv" / "orders_chunk_dupes.csv", chunk_rows=chunk_rows)
    assert run.result is not None
    assert counters_of(run.result) == e["counters_identical_for_every_chunk_size"]
    assert [r.row_number for r in run.result.rejected_sample] == e["rejected_row_numbers"]


@pytest.mark.parametrize("chunk_rows", CHUNKS)
@pytest.mark.parametrize(
    "scenario", ["pipelines/orders_dirty_reject.json", "pipelines/orders_dirty_unique.json"]
)
def test_orders_dirty(
    etl_engine: sa.Engine,
    repo_root: Path,
    fx: Path,
    expected: dict[str, Any],
    scenario: str,
    chunk_rows: int,
) -> None:
    want = expected["orders_dirty.csv"]["scenarios"][scenario]
    config = load_config(repo_root, f"tests/fixtures/{scenario}")
    run = go(etl_engine, config, fx / "csv" / "orders_dirty.csv", chunk_rows=chunk_rows)
    assert run.result is not None
    assert counters_of(run.result) == want["counters"]
    sample = run.result.rejected_sample
    assert [r.row_number for r in sample] == sorted(r.row_number for r in sample)
    by_rule: dict[str, int] = {}
    for r in sample:
        by_rule[r.rule] = by_rule.get(r.rule, 0) + 1
    assert by_rule == want["rejections_by_rule"]


def test_orders_dirty_ratio_exceeded_publishes_nothing(
    etl_engine: sa.Engine, repo_root: Path, fx: Path
) -> None:
    config = load_config(repo_root, "contracts/examples/pipeline/valid/orders_full.json")
    run = go(etl_engine, config, fx / "csv" / "orders_dirty.csv", expect_error=True)
    assert isinstance(run.error, RejectionLimitExceeded)
    assert "max_rejected_ratio" in str(run.error)
    last = run.events[-1]
    assert (last.stage, last.status) == ("validate", "failed")
    assert last.counters.loaded_count == 0 and last.counters.extracted_count == 96
    assert tables(etl_engine, "datasets") == [] and tables(etl_engine, "staging") == []
    assert len(run.error.rejected_sample) == 23


@pytest.mark.parametrize("chunk_rows", CHUNKS)
def test_orders_dirty_failrun(
    etl_engine: sa.Engine, repo_root: Path, fx: Path, chunk_rows: int
) -> None:
    config = load_config(repo_root, "tests/fixtures/pipelines/orders_dirty_failrun.json")
    run = go(
        etl_engine,
        config,
        fx / "csv" / "orders_dirty.csv",
        chunk_rows=chunk_rows,
        expect_error=True,
    )
    assert isinstance(run.error, RejectionLimitExceeded)
    assert tables(etl_engine, "datasets") == [] and tables(etl_engine, "staging") == []
    assert counters_of_event(run.events[-1])["loaded_count"] == 0


# ------------------------------------------------------------ Q4 parse errors


@pytest.mark.parametrize("chunk_rows", CHUNKS)
def test_ragged_rows_parse_errors_count_as_rejections(
    etl_engine: sa.Engine, repo_root: Path, fx: Path, expected: dict[str, Any], chunk_rows: int
) -> None:
    e = expected["ragged_rows.csv"]
    run = go(
        etl_engine,
        load_config(repo_root, e["config"]),
        fx / "csv" / "ragged_rows.csv",
        chunk_rows=chunk_rows,
    )
    assert run.result is not None
    assert counters_of(run.result) == e["counters"]
    assert [r.row_number for r in run.result.rejected_sample] == e["rejected_row_numbers"]
    assert {r.rule for r in run.result.rejected_sample} == {"parse_error"}
    assert all(r.column is None for r in run.result.rejected_sample)


@pytest.mark.parametrize("chunk_rows", [1, 2, 3, 50_000])
def test_malformed_chunk_straddle(
    etl_engine: sa.Engine, repo_root: Path, fx: Path, expected: dict[str, Any], chunk_rows: int
) -> None:
    e = expected["malformed_chunk_straddle.csv"]
    run = go(
        etl_engine,
        load_config(repo_root, e["config"]),
        fx / "csv" / "malformed_chunk_straddle.csv",
        chunk_rows=chunk_rows,
    )
    assert run.result is not None
    assert counters_of(run.result) == e["counters_identical_for_every_chunk_size"]
    assert [r.row_number for r in run.result.rejected_sample] == e["rejected_row_numbers"]


def test_cumulative_counters_after_each_chunk(
    etl_engine: sa.Engine, repo_root: Path, fx: Path, expected: dict[str, Any]
) -> None:
    e = expected["malformed_chunk_straddle.csv"]
    run = go(
        etl_engine,
        load_config(repo_root, e["config"]),
        fx / "csv" / "malformed_chunk_straddle.csv",
        chunk_rows=2,
    )
    per_chunk = [run.progress[i : i + 4] for i in range(0, len(run.progress), 4)]
    assert len(per_chunk) == len(e["cumulative_after_each_chunk_rows_2"])
    for group, want in zip(per_chunk, e["cumulative_after_each_chunk_rows_2"], strict=True):
        assert [x.stage for x in group] == ["extract", "transform", "validate", "load"]
        got = [counters_of_event(x) for x in group]
        assert all(g == got[0] for g in got)
        assert got[0]["extracted_count"] == want["extracted_count"]
        assert got[0]["rejected_count"] == want["rejected_count"]
        assert got[0]["loaded_count"] == 0  # until publish


def test_parse_error_row_registers_no_dedupe_key(
    etl_engine: sa.Engine, repo_root: Path, fx: Path, expected: dict[str, Any]
) -> None:
    e = expected["parse_error_dedupe.csv"]
    run = go(
        etl_engine,
        load_config(repo_root, e["config"]),
        fx / "csv" / "parse_error_dedupe.csv",
        chunk_rows=2,
    )
    assert run.result is not None
    assert counters_of(run.result) == e["counters"]


def test_fail_run_on_parse_error_counters_per_chunk_size(
    etl_engine: sa.Engine, repo_root: Path, fx: Path, expected: dict[str, Any]
) -> None:
    scenario = expected["ragged_rows.csv"]["scenarios"]["pipelines/ragged_failrun.json"]
    config = load_config(repo_root, "tests/fixtures/pipelines/ragged_failrun.json")
    for chunk_rows, want in scenario["counters_at_failure_by_chunk_rows"].items():
        run = go(
            etl_engine,
            config,
            fx / "csv" / "ragged_rows.csv",
            chunk_rows=int(chunk_rows),
            expect_error=True,
        )
        assert isinstance(run.error, RejectionLimitExceeded)
        assert f"row {scenario['first_rejection']['row_number']}" in str(run.error)
        assert "parse_error" in str(run.error)
        last = run.events[-1]
        assert (last.stage, last.status) == ("extract", "failed")
        assert counters_of_event(last) == want
        assert tables(etl_engine, "datasets") == [] and tables(etl_engine, "staging") == []


def write_csv(tmp_path: Path, text: str, name: str = "in.csv") -> Path:
    path = tmp_path / name
    path.write_text(text)
    return path


def simple_config(**extra: Any) -> PipelineConfig:
    return validate_pipeline_config(
        {
            "version": 1,
            "columns": [
                {"source": "id", "name": "id", "type": "integer"},
                {"source": "name", "name": "name", "type": "string"},
            ],
            "target": {"table": "t", "mode": "replace"},
            **extra,
        }
    )


def test_q11a_earliest_stage_raises_parse_error_before_cast_failure(
    etl_engine: sa.Engine, tmp_path: Path
) -> None:
    # row 2: cast failure (transform); row 4: parse_error (extract). Same chunk.
    path = write_csv(tmp_path, "id,name\n1,a\nbad,b\n3,c\n4\n5,e\n")
    run = go(etl_engine, simple_config(on_validation_failure="fail_run"), path, expect_error=True)
    assert isinstance(run.error, RejectionLimitExceeded)
    assert "row 4" in str(run.error) and "parse_error" in str(run.error)
    assert run.events[-1].stage == "extract"


def test_q11a_cast_failure_before_validation_failure(etl_engine: sa.Engine, tmp_path: Path) -> None:
    config = simple_config(
        on_validation_failure="fail_run",
        validations=[{"rule": "range", "column": "id", "max": 3}],
    )
    path = write_csv(tmp_path, "id,name\n1,a\n9,b\nbad,c\n")  # row 2 fails range, row 3 fails cast
    run = go(etl_engine, config, path, expect_error=True)
    assert "row 3" in str(run.error) and "type_cast" in str(run.error)
    assert run.events[-1].stage == "transform"


def test_fail_run_validation_failure_names_first_row_of_the_chunk(
    etl_engine: sa.Engine, tmp_path: Path
) -> None:
    config = simple_config(
        on_validation_failure="fail_run",
        validations=[{"rule": "range", "column": "id", "max": 3}],
    )
    path = write_csv(tmp_path, "id,name\n1,a\n9,b\n8,c\n")
    run = go(etl_engine, config, path, expect_error=True)
    assert "row 2" in str(run.error) and "range" in str(run.error)
    assert (run.events[-1].stage, run.events[-1].status) == ("validate", "failed")
    assert not run.progress  # the failing chunk is never reported


def test_fail_run_reports_completed_chunks_only(etl_engine: sa.Engine, tmp_path: Path) -> None:
    config = simple_config(on_validation_failure="fail_run")
    path = write_csv(tmp_path, "id,name\n1,a\n2,b\n3,c\nbad,d\n5,e\n")
    run = go(etl_engine, config, path, chunk_rows=2, expect_error=True)
    assert len(run.progress) == 4  # only the first chunk (rows 1-2) completed
    last = run.events[-1]
    assert last.status == "failed" and counters_of_event(last) == {
        "extracted_count": 2,
        "loaded_count": 0,
        "rejected_count": 0,
        "duplicate_dropped_count": 0,
        "null_dropped_count": 0,
    }
    assert tables(etl_engine, "staging") == [] and tables(etl_engine, "datasets") == []


# ----------------------------------------------------- file-level faults (Q4)


def test_file_level_fault_in_chunk_k(etl_engine: sa.Engine, tmp_path: Path) -> None:
    path = write_csv(tmp_path, 'id,name\n1,a\n2\n3,c\n4,"open\n5,e\n')
    run = go(etl_engine, simple_config(), path, chunk_rows=2, expect_error=True)
    assert isinstance(run.error, CsvFormatError)
    last = run.events[-1]
    assert (last.stage, last.status) == ("extract", "failed")
    assert counters_of_event(last) == {
        "extracted_count": 2,
        "loaded_count": 0,
        "rejected_count": 1,
        "duplicate_dropped_count": 0,
        "null_dropped_count": 0,
    }
    assert [r.row_number for r in run.error.rejected_sample] == [2]  # type: ignore[union-attr]
    assert tables(etl_engine, "datasets") == [] and tables(etl_engine, "staging") == []


@pytest.mark.parametrize(
    "text", ["", "id,name\n", 'id,name\n1,"open\n'], ids=["empty", "header-only", "unterminated"]
)
def test_file_level_faults_before_any_chunk(
    etl_engine: sa.Engine, tmp_path: Path, text: str
) -> None:
    run = go(etl_engine, simple_config(), write_csv(tmp_path, text), expect_error=True)
    assert isinstance(run.error, CsvFormatError)
    assert counters_of_event(run.events[-1])["extracted_count"] == 0


def test_missing_source_column(etl_engine: sa.Engine, tmp_path: Path) -> None:
    run = go(etl_engine, simple_config(), write_csv(tmp_path, "id,other\n1,a\n"), expect_error=True)
    assert isinstance(run.error, SourceMismatchError) and "'name'" in str(run.error)
    assert run.events[-1].stage == "extract"


def test_invalid_config_is_revalidated(etl_engine: sa.Engine, tmp_path: Path) -> None:
    bad = PipelineConfig(raw={"version": 2, "columns": [], "target": {}})
    run = go(etl_engine, bad, write_csv(tmp_path, "id\n1\n"), expect_error=True)
    assert isinstance(run.error, ConfigValidationError)
    assert run.events[-1].status == "failed"


# ---------------------------------------------------------------- the events


def test_event_sequence_and_totals(etl_engine: sa.Engine, tmp_path: Path) -> None:
    path = write_csv(tmp_path, "id,name\n" + "".join(f"{i},n{i}\n" for i in range(1, 6)))
    run = go(etl_engine, simple_config(), path, chunk_rows=2)
    assert run.result is not None
    seq = [(e.stage, e.status) for e in run.events]
    stages = ["extract", "transform", "validate", "load"]
    assert seq[:4] == [(s, "started") for s in stages]
    assert seq[4:16] == [(s, "progress") for _ in range(3) for s in stages]  # 3 chunks
    assert seq[16:] == [(s, "completed") for s in stages] + [
        ("publish", "started"),
        ("publish", "completed"),
    ]
    # at least one progress event per chunk; counters cumulative and never decreasing
    prev = [0] * 5
    for e in run.events:
        now = list(counters_of_event(e).values())
        assert all(a >= b for a, b in zip(now, prev, strict=True))
        prev = now
    assert counters_of_event(run.events[-1]) == counters_of(run.result)
    assert run.events[-1].counters.loaded_count == 5 and run.events[-3].counters.loaded_count == 0
    assert all(
        e.at.tzinfo is not None and e.at.utcoffset().total_seconds() == 0 for e in run.events
    )  # type: ignore[union-attr]


def test_chunk_events_carry_stage_rows(etl_engine: sa.Engine, tmp_path: Path) -> None:
    config = simple_config(validations=[{"rule": "range", "column": "id", "max": 3}])
    path = write_csv(tmp_path, "id,name\n1,a\nbad,b\n9,c\n3,d\n")
    run = go(etl_engine, config, path, chunk_rows=4)
    by_stage = {e.stage: e for e in run.progress}
    assert (by_stage["extract"].rows_in, by_stage["extract"].rows_out) == (None, 4)
    assert (by_stage["transform"].rows_in, by_stage["transform"].rows_out) == (4, 3)
    assert (by_stage["validate"].rows_in, by_stage["validate"].rows_out) == (3, 2)
    assert (by_stage["load"].rows_in, by_stage["load"].rows_out) == (2, 2)
    assert run.result is not None
    assert counters_of(run.result)["rejected_count"] == 2 and run.result.loaded_count == 2


def test_stage_durations_cover_every_stage(etl_engine: sa.Engine, tmp_path: Path) -> None:
    run = go(etl_engine, simple_config(), write_csv(tmp_path, "id,name\n1,a\n"))
    assert run.result is not None
    assert set(run.result.stage_durations_ms) == {
        "extract",
        "transform",
        "validate",
        "load",
        "publish",
    }
    assert all(isinstance(v, int) and v >= 0 for v in run.result.stage_durations_ms.values())


def test_on_event_is_optional_and_a_failing_callback_does_not_mask_errors(
    etl_engine: sa.Engine, tmp_path: Path
) -> None:
    res = run_pipeline(
        simple_config(),
        write_csv(tmp_path, "id,name\n1,a\n"),
        CsvOptions(),
        etl_engine,
        uuid.uuid4(),
    )
    assert res.loaded_count == 1

    def boom(_: StageEvent) -> None:
        raise RuntimeError("callback failed")

    with pytest.raises(RuntimeError, match="callback failed"):
        run_pipeline(
            simple_config(),
            tmp_path / "in.csv",
            CsvOptions(),
            etl_engine,
            uuid.uuid4(),
            on_event=boom,
        )
    assert tables(etl_engine, "staging") == []


# ------------------------------------------------------------ should_stop


class StopAt:
    """should_stop that turns true on its n-th call."""

    def __init__(self, n: int) -> None:
        self.n = n
        self.calls = 0

    def __call__(self) -> bool:
        self.calls += 1
        return self.calls >= self.n


def test_should_stop_at_every_boundary(etl_engine: sa.Engine, tmp_path: Path) -> None:
    path = write_csv(tmp_path, "id,name\n" + "".join(f"{i},n{i}\n" for i in range(1, 6)))
    first = go(etl_engine, simple_config(), path)  # publish an initial "t"
    assert first.result is not None and first.result.published.row_count == 5
    path.write_text("id,name\n100,x\n101,y\n")
    interrupted = 0
    for n in range(1, 40):
        run = go(
            etl_engine,
            simple_config(),
            path,
            chunk_rows=1,
            should_stop=StopAt(n),
            expect_error=run_will_stop(n),
        )
        if run.error is None:
            break
        interrupted += 1
        assert isinstance(run.error, RunInterrupted)
        last = run.events[-1]
        assert last.status == "failed" and last.message == "interrupted"
        assert last.counters.loaded_count == 0
        assert tables(etl_engine, "staging") == []
        assert table_ids(etl_engine, "t", "id") == [1, 2, 3, 4, 5]  # published table untouched
    assert interrupted >= 10
    assert run.result is not None and table_ids(etl_engine, "t", "id") == [100, 101]


def run_will_stop(n: int) -> bool:
    # 2 chunks: checks = (extract, transform, validate, load) x 2, final extract, validate, publish
    return n <= 11


def test_interrupt_never_reports_the_incomplete_chunk(
    etl_engine: sa.Engine, tmp_path: Path
) -> None:
    path = write_csv(tmp_path, "id,name\n1,a\n2,b\n3,c\n")
    # calls: chunk1 = 4 checks, chunk2 starts at call 5 (extract) .. stop at its load check (call 8)
    run = go(
        etl_engine, simple_config(), path, chunk_rows=1, should_stop=StopAt(8), expect_error=True
    )
    assert len(run.progress) == 4  # exactly one completed chunk
    assert counters_of_event(run.events[-1])["extracted_count"] == 1
    assert run.events[-1].stage == "load"


def test_interrupted_run_carries_rejected_sample_of_completed_chunks(
    etl_engine: sa.Engine, tmp_path: Path
) -> None:
    path = write_csv(tmp_path, "id,name\nbad,a\n2,b\nworse,c\n")
    run = go(
        etl_engine, simple_config(), path, chunk_rows=1, should_stop=StopAt(9), expect_error=True
    )
    assert isinstance(run.error, RunInterrupted)
    assert [r.row_number for r in run.error.rejected_sample] == [1]


# --------------------------------------------------------- accounting asserts


def test_chunk_invariant_violation_raises(
    etl_engine: sa.Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = Loader.load_chunk

    def short(self: Loader, frame: pd.DataFrame, numbers: Any) -> int:
        return real(self, frame, numbers) - 1

    monkeypatch.setattr(Loader, "load_chunk", short)
    run = go(
        etl_engine, simple_config(), write_csv(tmp_path, "id,name\n1,a\n2,b\n"), expect_error=True
    )
    assert isinstance(run.error, EtlError) and "row accounting mismatch" in str(run.error)
    assert run.events[-1].status == "failed" and not run.progress
    assert tables(etl_engine, "datasets") == [] and tables(etl_engine, "staging") == []


def test_reconciliation_is_asserted_before_publish(
    etl_engine: sa.Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    go(etl_engine, simple_config(), write_csv(tmp_path, "id,name\n7,old\n"))
    real = Loader.load_chunk

    def lie(self: Loader, frame: pd.DataFrame, numbers: Any) -> int:
        n = real(self, frame, numbers)
        self.staged_rows -= 1  # the chunk invariant (return value) still holds
        return n

    monkeypatch.setattr(Loader, "load_chunk", lie)
    run = go(
        etl_engine,
        simple_config(),
        write_csv(tmp_path, "id,name\n1,a\n2,b\n", "b.csv"),
        expect_error=True,
    )
    assert isinstance(run.error, EtlError) and "row accounting mismatch" in str(run.error)
    assert run.events[-1].stage == "publish" and run.events[-1].status == "failed"
    assert table_ids(etl_engine, "t", "id") == [7]  # untouched
    assert tables(etl_engine, "staging") == []


def test_succeeded_run_balances(etl_engine: sa.Engine, repo_root: Path, fx: Path) -> None:
    config = load_config(repo_root, "tests/fixtures/pipelines/orders_dirty_reject.json")
    run = go(etl_engine, config, fx / "csv" / "orders_dirty.csv", chunk_rows=7)
    assert run.result is not None
    assert_balanced(counters_of(run.result))
    assert run.result.loaded_count == run.result.published.row_count == 70


# --------------------------------------------------------- rejected sample cap


def test_rejected_sample_is_capped_at_1000_in_row_order(
    etl_engine: sa.Engine, tmp_path: Path
) -> None:
    body = "".join(f"bad{i},n\n" for i in range(1, 1501)) + "1,ok\n"
    run = go(etl_engine, simple_config(), write_csv(tmp_path, "id,name\n" + body), chunk_rows=400)
    assert run.result is not None
    assert run.result.rejected_count == 1500 and run.result.loaded_count == 1
    sample = run.result.rejected_sample
    assert len(sample) == 1000 and [r.row_number for r in sample] == list(range(1, 1001))


def test_error_rejected_sample_is_capped_and_from_completed_chunks(
    etl_engine: sa.Engine, tmp_path: Path
) -> None:
    body = "".join(f"bad{i},n\n" for i in range(1, 1501))
    config = simple_config(max_rejected_ratio=0.5)
    run = go(
        etl_engine,
        config,
        write_csv(tmp_path, "id,name\n" + body),
        chunk_rows=400,
        expect_error=True,
    )
    assert isinstance(run.error, RejectionLimitExceeded)
    assert len(run.error.rejected_sample) == 1000


def test_rejected_sample_orders_stages_within_a_row(etl_engine: sa.Engine, tmp_path: Path) -> None:
    config = simple_config(validations=[{"rule": "length", "column": "name", "max": 1}])
    run = go(etl_engine, config, write_csv(tmp_path, "id,name\nbad,x\n2,toolong\n3\n"))
    assert run.result is not None
    assert [(r.row_number, r.rule) for r in run.result.rejected_sample] == [
        (1, "type_cast"),
        (2, "length"),
        (3, "parse_error"),
    ]


# ------------------------------------------------------------------ isolation


def test_nothing_is_written_outside_staging_and_datasets(
    etl_engine: sa.Engine, repo_root: Path, fx: Path
) -> None:
    config = load_config(repo_root, "contracts/examples/pipeline/valid/orders_full.json")
    go(etl_engine, config, fx / "csv" / "orders_clean.csv")
    go(etl_engine, config, fx / "csv" / "orders_dirty.csv", expect_error=True)
    with etl_engine.connect() as conn:
        other = conn.execute(
            sa.text(
                "SELECT count(*) FROM pg_tables WHERE schemaname NOT IN "
                "('pg_catalog','information_schema','staging','datasets')"
            )
        ).scalar_one()
    assert other == 0


def test_published_table_has_run_metadata_columns(etl_engine: sa.Engine, tmp_path: Path) -> None:
    run = go(etl_engine, simple_config(), write_csv(tmp_path, "id,name\n1,a\n,\n3,c\n"))
    assert run.result is not None
    with etl_engine.connect() as conn:
        rows = conn.execute(
            sa.text("SELECT id, name, _localetl_row_number FROM datasets.t ORDER BY 3")
        ).all()
    assert [tuple(r) for r in rows] == [(1, "a", 1), (None, None, 2), (3, "c", 3)]
