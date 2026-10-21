# ruff: noqa: E501
"""WK-02: execute_run persists events, counters, datasets and rejections (architecture 7.2)."""

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa

from app.services.runs import claim_next_run, execute_run
from app.services.runs import executor as ex
from app.services.runs.executor import resolve_source_path
from tests.worker.conftest import get_run

pytestmark = pytest.mark.usefixtures("clean_runs")

CSV = "id,name,score\n1,a,10\n2,b,20\n3,,30\n3,d,40\nx,e,50\n"
COLS = [
    {"source": "id", "name": "id", "type": "integer"},
    {"source": "name", "name": "name", "type": "string"},
    {"source": "score", "name": "score", "type": "integer"},
]


def config(table: str, **extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "version": 1,
        "columns": COLS,
        "target": {"table": table, "mode": "replace"},
        "on_validation_failure": "reject_row",
    }
    base.update(extra)
    return base


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    (tmp_path / "sources").mkdir()
    (tmp_path / "sources" / "s.csv").write_text(CSV)
    return tmp_path


def make_run(
    engine: sa.Engine, cfg: dict[str, Any], stored: str | None = "sources/s.csv"
) -> uuid.UUID:
    sid, rid = uuid.uuid4(), uuid.uuid4()
    with engine.begin() as conn:
        if stored is not None:
            conn.execute(
                sa.text(
                    """INSERT INTO data_sources (id, name, original_filename, stored_path, size_bytes,
                        sha256, csv_options, columns, row_count)
                       VALUES (:id,'s','s.csv',:sp,1,repeat('0',64),CAST(:o AS jsonb),CAST(:c AS jsonb),5)"""
                ),
                {
                    "id": sid,
                    "sp": stored,
                    "o": json.dumps(
                        {
                            "encoding": "utf-8",
                            "delimiter": ",",
                            "has_header": True,
                            "quote_char": '"',
                        }
                    ),
                    "c": json.dumps(
                        [
                            {"name": n, "inferred_type": "string", "null_count": 0}
                            for n in ("id", "name", "score")
                        ]
                    ),
                },
            )
        conn.execute(
            sa.text(
                """INSERT INTO runs (id, pipeline_name, source_id, config_snapshot, config_version)
                   VALUES (:id,'p',:sid,CAST(:cfg AS jsonb),1)"""
            ),
            {"id": rid, "sid": sid if stored is not None else None, "cfg": json.dumps(cfg)},
        )
    return rid


def run_it(engine: sa.Engine, data_dir: Path, rid: uuid.UUID, **kw: Any) -> None:
    assert claim_next_run(engine, "w1") == rid
    execute_run(engine, rid, "w1", data_dir=data_dir, chunk_rows=2, **kw)


def q(engine: sa.Engine, sql: str, **p: Any) -> list[Any]:
    with engine.connect() as conn:
        return list(conn.execute(sa.text(sql), p).all())


def test_success_persists_everything(engine: sa.Engine, data_dir: Path) -> None:
    rid = make_run(engine, config("wk02_ok", validations=[{"rule": "not_null", "column": "name"}]))
    run_it(engine, data_dir, rid)
    r = get_run(engine, rid)
    assert r.status == "succeeded" and r.finished_at and r.error_message is None, r.error_message
    assert r.extracted_count == 5
    assert (
        r.extracted_count
        == r.loaded_count + r.rejected_count + r.duplicate_dropped_count + r.null_dropped_count
    )
    assert r.loaded_count == 3 and r.rejected_count == 2
    ds = q(engine, "SELECT * FROM datasets WHERE table_name='wk02_ok'")[0]
    assert r.dataset_id == ds.id and ds.last_run_id == rid and ds.row_count == 3
    assert [c["name"] for c in ds.columns] == ["id", "name", "score"]
    assert {x.rule for x in q(engine, "SELECT rule FROM run_rejections WHERE run_id=:i", i=rid)}
    events = q(engine, "SELECT stage,status FROM run_events WHERE run_id=:i ORDER BY id", i=rid)
    assert events[0] == ("extract", "started") and events[-1].stage == "publish"
    assert r.current_stage == "publish"


def test_second_run_updates_registry_row(engine: sa.Engine, data_dir: Path) -> None:
    first = make_run(engine, config("wk02_up"))
    run_it(engine, data_dir, first)
    second = make_run(engine, config("wk02_up"))
    run_it(engine, data_dir, second)
    rows = q(engine, "SELECT id,last_run_id FROM datasets WHERE table_name='wk02_up'")
    assert len(rows) == 1 and rows[0].last_run_id == second
    assert get_run(engine, second).dataset_id == rows[0].id


def test_validation_failure_fails_run_with_rejections(engine: sa.Engine, data_dir: Path) -> None:
    cfg = config(
        "wk02_fail",
        on_validation_failure="fail_run",
        validations=[{"rule": "not_null", "column": "name"}],
    )
    rid = make_run(engine, cfg)
    run_it(engine, data_dir, rid)
    r = get_run(engine, rid)
    assert r.status == "failed" and r.error_message and r.finished_at
    assert r.loaded_count == 0 and r.dataset_id is None
    assert q(engine, "SELECT 1 FROM datasets WHERE table_name='wk02_fail'") == []
    assert any(
        e.status == "failed"
        for e in q(engine, "SELECT status FROM run_events WHERE run_id=:i", i=rid)
    )


def test_should_stop_marks_interrupted(engine: sa.Engine, data_dir: Path) -> None:
    rid = make_run(engine, config("wk02_int"))
    run_it(engine, data_dir, rid, should_stop=lambda: True)
    r = get_run(engine, rid)
    assert r.status == "interrupted" and r.loaded_count == 0 and r.finished_at


def test_invalid_config_fails(engine: sa.Engine, data_dir: Path) -> None:
    rid = make_run(engine, {"version": 99})
    run_it(engine, data_dir, rid)
    r = get_run(engine, rid)
    assert r.status == "failed" and r.error_message


def test_missing_source_row_fails(engine: sa.Engine, data_dir: Path) -> None:
    rid = make_run(engine, config("wk02_nosrc"), stored=None)
    run_it(engine, data_dir, rid)
    r = get_run(engine, rid)
    assert r.status == "failed" and "source" in r.error_message


def test_missing_file_fails(engine: sa.Engine, data_dir: Path) -> None:
    rid = make_run(engine, config("wk02_nofile"), stored="sources/none.csv")
    run_it(engine, data_dir, rid)
    assert get_run(engine, rid).status == "failed"


def test_path_escape_fails(engine: sa.Engine, data_dir: Path) -> None:
    rid = make_run(engine, config("wk02_esc"), stored="../outside.csv")
    run_it(engine, data_dir, rid)
    r = get_run(engine, rid)
    assert r.status == "failed" and "outside" in r.error_message


def test_resolve_source_path(tmp_path: Path) -> None:
    assert (
        resolve_source_path(tmp_path, "sources/a.csv") == tmp_path.resolve() / "sources" / "a.csv"
    )
    with pytest.raises(ValueError):
        resolve_source_path(tmp_path, "/etc/passwd")
    with pytest.raises(ValueError):
        resolve_source_path(tmp_path, "../x")


def test_unexpected_exception_fails_run(
    engine: sa.Engine, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*a: Any, **k: Any) -> None:
        raise ZeroDivisionError("bang")

    monkeypatch.setattr(ex, "run_pipeline", boom)
    rid = make_run(engine, config("wk02_boom"))
    run_it(engine, data_dir, rid)
    r = get_run(engine, rid)
    assert r.status == "failed" and "ZeroDivisionError" in r.error_message


def test_progress_is_atomic_and_keeps_counters_on_failure(
    engine: sa.Engine, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = ex.run_pipeline

    def crash_after_progress(*a: Any, **k: Any) -> Any:
        on_event = k["on_event"]

        def wrapped(ev: Any) -> None:
            on_event(ev)
            if ev.status == "progress" and ev.stage == "load":
                raise RuntimeError("die after first chunk")

        k["on_event"] = wrapped
        return real(*a, **k)

    monkeypatch.setattr(ex, "run_pipeline", crash_after_progress)
    rid = make_run(engine, config("wk02_prog"))
    run_it(engine, data_dir, rid)
    r = get_run(engine, rid)
    assert r.status == "failed" and r.extracted_count > 0 and r.loaded_count == 0
    n = q(engine, "SELECT count(*) AS n FROM run_events WHERE run_id=:i", i=rid)[0].n
    assert n >= 4


def test_lost_run_is_not_overwritten(engine: sa.Engine, data_dir: Path) -> None:
    rid = make_run(engine, config("wk02_lost"))
    assert claim_next_run(engine, "w1") == rid
    with engine.begin() as conn:  # recovered as stale by another worker meanwhile
        conn.execute(
            sa.text("UPDATE runs SET status='interrupted', finished_at=now() WHERE id=:i"),
            {"i": rid},
        )
    execute_run(engine, rid, "w1", data_dir=data_dir, chunk_rows=2)
    assert get_run(engine, rid).status == "interrupted"
    assert q(engine, "SELECT 1 FROM datasets WHERE table_name='wk02_lost'") == []
