import re
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Base, Dataset, DataSource, Pipeline, Run, RunEvent, RunStatus

from .conftest import alembic_config

pytestmark = pytest.mark.db

TABLES = {"data_sources", "pipelines", "runs", "run_events", "run_rejections", "datasets"}
COUNTERS = [
    "extracted_count",
    "loaded_count",
    "rejected_count",
    "duplicate_dropped_count",
    "null_dropped_count",
]


# ---------- helpers ----------
def make_source(session: Session) -> DataSource:
    src = DataSource(
        name="s",
        original_filename="s.csv",
        stored_path="sources/x.csv",
        size_bytes=1,
        sha256="0" * 64,
        csv_options={},
        columns=[],
        row_count=0,
    )
    session.add(src)
    session.flush()
    return src


def make_pipeline(session: Session, name: str = "p") -> Pipeline:
    src = make_source(session)
    pipe = Pipeline(name=name, source_id=src.id, config={}, config_version=1)
    session.add(pipe)
    session.flush()
    return pipe


def make_run(session: Session, pipeline: Pipeline | None, status: RunStatus, **counts: int) -> Run:
    run = Run(
        pipeline_id=pipeline.id if pipeline else None,
        pipeline_name="p",
        config_snapshot={},
        config_version=1,
        status=status,
        **counts,
    )
    session.add(run)
    session.flush()
    return run


# ---------- schema shape ----------
def test_tables_schemas_and_enum(migrated_engine: sa.Engine) -> None:
    insp = sa.inspect(migrated_engine)
    assert TABLES <= set(insp.get_table_names())
    assert {"staging", "datasets"} <= set(insp.get_schema_names())
    with migrated_engine.connect() as conn:
        labels = (
            conn.execute(
                sa.text(
                    "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid"
                    " WHERE t.typname = 'run_status' ORDER BY e.enumsortorder"
                )
            )
            .scalars()
            .all()
        )
    assert labels == ["queued", "running", "succeeded", "failed", "interrupted"]


def test_enum_matches_openapi_run_status() -> None:
    text = (Path(__file__).resolve().parents[3] / "contracts" / "openapi.yaml").read_text()
    block = re.search(r"\n    RunStatus:\n(.*?)\n    \w", text, re.S)
    assert block is not None
    declared = re.search(r"enum:\s*\[([^\]]*)\]", block.group(1))
    assert declared is not None
    assert [v.strip() for v in declared.group(1).split(",")] == [s.value for s in RunStatus]


def test_counter_columns_are_bigint_not_null_default_zero(migrated_engine: sa.Engine) -> None:
    cols = {c["name"]: c for c in sa.inspect(migrated_engine).get_columns("runs")}
    legacy = {"rows_read", "rows_rejected", "rows_loaded"}
    assert legacy.isdisjoint(cols)
    for name in COUNTERS:
        col = cols[name]
        assert isinstance(col["type"], sa.BigInteger), name
        assert col["nullable"] is False, name
        assert str(col["default"]).strip("()") == "0", name


def test_models_match_migration(migrated_engine: sa.Engine) -> None:
    with migrated_engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_upgrade_downgrade_roundtrip(scratch_url: str) -> None:
    cfg = alembic_config(scratch_url)
    engine = sa.create_engine(scratch_url)
    try:
        command.downgrade(cfg, "base")
        insp = sa.inspect(engine)
        assert TABLES.isdisjoint(insp.get_table_names())
        assert {"staging", "datasets"}.isdisjoint(insp.get_schema_names())
        with engine.connect() as conn:
            assert conn.execute(sa.text("SELECT to_regtype('run_status')")).scalar() is None
        command.upgrade(cfg, "head")
        assert TABLES <= set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()


# ---------- partial unique indexes ----------
def test_second_running_run_rejected(session: Session) -> None:
    make_run(session, make_pipeline(session, "a"), RunStatus.running)
    with pytest.raises(IntegrityError, match="one_running_run"):
        make_run(session, make_pipeline(session, "b"), RunStatus.running)


def test_running_index_ignores_other_statuses(session: Session) -> None:
    make_run(session, make_pipeline(session, "a"), RunStatus.running)
    make_run(session, make_pipeline(session, "b"), RunStatus.queued)
    make_run(session, make_pipeline(session, "c"), RunStatus.failed)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (RunStatus.queued, RunStatus.queued),
        (RunStatus.queued, RunStatus.running),
        (RunStatus.running, RunStatus.queued),
    ],
)
def test_second_active_run_per_pipeline_rejected(
    session: Session, first: RunStatus, second: RunStatus
) -> None:
    pipe = make_pipeline(session)
    make_run(session, pipe, first)
    with pytest.raises(IntegrityError, match="one_active_run_per_pipeline"):
        make_run(session, pipe, second)


def test_active_index_allows_terminal_history_and_other_pipelines(session: Session) -> None:
    pipe = make_pipeline(session, "a")
    for status in (RunStatus.succeeded, RunStatus.failed, RunStatus.interrupted):
        make_run(session, pipe, status)
    make_run(session, pipe, RunStatus.queued)
    make_run(session, make_pipeline(session, "b"), RunStatus.queued)


# ---------- Q3 CHECK constraints ----------
def test_counters_default_to_zero(session: Session) -> None:
    run = make_run(session, None, RunStatus.queued)
    session.refresh(run)
    assert [getattr(run, c) for c in COUNTERS] == [0] * 5


def test_succeeded_run_that_reconciles_is_accepted(session: Session) -> None:
    make_run(
        session,
        None,
        RunStatus.succeeded,
        extracted_count=10,
        loaded_count=6,
        rejected_count=2,
        duplicate_dropped_count=1,
        null_dropped_count=1,
    )
    make_run(session, None, RunStatus.succeeded)  # 0 = 0 + 0 + 0 + 0


@pytest.mark.parametrize("counter", COUNTERS)
def test_succeeded_run_that_does_not_reconcile_is_rejected(session: Session, counter: str) -> None:
    counts = {
        "extracted_count": 10,
        "loaded_count": 6,
        "rejected_count": 2,
        "duplicate_dropped_count": 1,
        "null_dropped_count": 1,
    }
    counts[counter] += 1
    with pytest.raises(IntegrityError, match="runs_succeeded_counts_reconcile"):
        make_run(session, None, RunStatus.succeeded, **counts)


@pytest.mark.parametrize(
    "status", [RunStatus.queued, RunStatus.running, RunStatus.failed, RunStatus.interrupted]
)
def test_unsuccessful_run_with_loaded_rows_is_rejected(session: Session, status: RunStatus) -> None:
    with pytest.raises(IntegrityError, match="runs_unsuccessful_loaded_zero"):
        make_run(session, None, status, extracted_count=5, loaded_count=1)


@pytest.mark.parametrize("status", [RunStatus.failed, RunStatus.interrupted])
def test_unsuccessful_run_keeps_partial_counters_without_identity(
    session: Session, status: RunStatus
) -> None:
    make_run(session, None, status, extracted_count=100, rejected_count=3)


def test_update_to_succeeded_is_checked(session: Session) -> None:
    run = make_run(session, None, RunStatus.running, extracted_count=4, rejected_count=1)
    run.status = RunStatus.succeeded
    with pytest.raises(IntegrityError, match="runs_succeeded_counts_reconcile"):
        session.flush()


# ---------- foreign keys ----------
def test_source_delete_restricted_by_pipeline(session: Session) -> None:
    pipe = make_pipeline(session)
    with pytest.raises(IntegrityError, match="fk_pipelines_source_id_data_sources"):
        session.execute(sa.delete(DataSource).where(DataSource.id == pipe.source_id))


def test_pipeline_delete_nulls_run_and_circular_dataset_refs(session: Session) -> None:
    pipe = make_pipeline(session)
    run = make_run(session, pipe, RunStatus.succeeded)
    ds = Dataset(table_name="t", pipeline_id=pipe.id, last_run_id=run.id, row_count=0, columns=[])
    session.add(ds)
    session.flush()
    run.dataset_id = ds.id
    session.flush()
    session.execute(sa.delete(Pipeline).where(Pipeline.id == pipe.id))
    session.refresh(run)
    session.refresh(ds)
    assert run.pipeline_id is None
    assert ds.pipeline_id is None
    assert run.dataset_id == ds.id


def test_run_delete_cascades_events(session: Session) -> None:
    run = make_run(session, None, RunStatus.queued)
    session.add(RunEvent(run_id=run.id, stage="extract", status="started"))
    session.flush()
    session.execute(sa.delete(Run).where(Run.id == run.id))
    assert session.scalar(sa.select(sa.func.count()).select_from(RunEvent)) == 0


def test_pipeline_name_unique(session: Session) -> None:
    pipe = make_pipeline(session, "dup")
    session.add(Pipeline(name="dup", source_id=pipe.source_id, config={}, config_version=1))
    with pytest.raises(IntegrityError, match="uq_pipelines_name"):
        session.flush()
