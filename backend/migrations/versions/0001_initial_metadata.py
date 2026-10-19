"""Initial metadata schema (architecture section 7.1) incl. Q3 row counters.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0001"
down_revision: str | None = None
branch_labels = None
depends_on = None

UUID_DEFAULT = sa.text("gen_random_uuid()")
NOW = sa.text("now()")
ZERO = sa.text("0")
RUN_STATUSES = ("queued", "running", "succeeded", "failed", "interrupted")
run_status = pg.ENUM(*RUN_STATUSES, name="run_status", create_type=False)


def _counter(name: str) -> sa.Column[int]:
    return sa.Column(name, sa.BigInteger(), server_default=ZERO, nullable=False)


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS staging")
    op.execute("CREATE SCHEMA IF NOT EXISTS datasets")
    pg.ENUM(*RUN_STATUSES, name="run_status").create(op.get_bind(), checkfirst=False)

    op.create_table(
        "data_sources",
        sa.Column("id", pg.UUID(as_uuid=True), server_default=UUID_DEFAULT, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("stored_path", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.CHAR(64), nullable=False),
        sa.Column("csv_options", pg.JSONB(), nullable=False),
        sa.Column("columns", pg.JSONB(), nullable=False),
        sa.Column("row_count", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_data_sources"),
    )

    op.create_table(
        "pipelines",
        sa.Column("id", pg.UUID(as_uuid=True), server_default=UUID_DEFAULT, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("config", pg.JSONB(), nullable=False),
        sa.Column("config_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_pipelines"),
        sa.UniqueConstraint("name", name="uq_pipelines_name"),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_sources.id"],
            name="fk_pipelines_source_id_data_sources",
            ondelete="RESTRICT",
        ),
    )

    # runs.dataset_id -> datasets.id is added after `datasets` exists (circular reference).
    op.create_table(
        "runs",
        sa.Column("id", pg.UUID(as_uuid=True), server_default=UUID_DEFAULT, nullable=False),
        sa.Column("pipeline_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("pipeline_name", sa.Text(), nullable=False),
        sa.Column("source_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("config_snapshot", pg.JSONB(), nullable=False),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column("status", run_status, server_default=sa.text("'queued'"), nullable=False),
        sa.Column("current_stage", sa.Text(), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_id", sa.Text(), nullable=True),
        _counter("extracted_count"),
        _counter("loaded_count"),
        _counter("rejected_count"),
        _counter("duplicate_dropped_count"),
        _counter("null_dropped_count"),
        sa.Column("dataset_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_runs"),
        sa.ForeignKeyConstraint(
            ["pipeline_id"],
            ["pipelines.id"],
            name="fk_runs_pipeline_id_pipelines",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_sources.id"],
            name="fk_runs_source_id_data_sources",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "status <> 'succeeded' OR extracted_count = loaded_count + rejected_count"
            " + duplicate_dropped_count + null_dropped_count",
            name="runs_succeeded_counts_reconcile",
        ),
        sa.CheckConstraint(
            "status = 'succeeded' OR loaded_count = 0",
            name="runs_unsuccessful_loaded_zero",
        ),
    )
    op.create_index(
        "one_running_run",
        "runs",
        [sa.text("(true)")],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )
    op.create_index(
        "one_active_run_per_pipeline",
        "runs",
        ["pipeline_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )

    op.create_table(
        "run_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("rows_in", sa.BigInteger(), nullable=True),
        sa.Column("rows_out", sa.BigInteger(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_run_events"),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name="fk_run_events_run_id_runs", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_run_events_run_id_id", "run_events", ["run_id", "id"])

    op.create_table(
        "run_rejections",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("row_number", sa.BigInteger(), nullable=False),
        sa.Column("column_name", sa.Text(), nullable=True),
        sa.Column("rule", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_run_rejections"),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name="fk_run_rejections_run_id_runs", ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_run_rejections_run_id_row_number", "run_rejections", ["run_id", "row_number"]
    )

    op.create_table(
        "datasets",
        sa.Column("id", pg.UUID(as_uuid=True), server_default=UUID_DEFAULT, nullable=False),
        sa.Column("table_name", sa.Text(), nullable=False),
        sa.Column("pipeline_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("last_run_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("row_count", sa.BigInteger(), nullable=False),
        sa.Column("columns", pg.JSONB(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_datasets"),
        sa.UniqueConstraint("table_name", name="uq_datasets_table_name"),
        sa.ForeignKeyConstraint(
            ["pipeline_id"],
            ["pipelines.id"],
            name="fk_datasets_pipeline_id_pipelines",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["last_run_id"], ["runs.id"], name="fk_datasets_last_run_id_runs"),
    )

    op.create_foreign_key(
        "fk_runs_dataset_id_datasets",
        "runs",
        "datasets",
        ["dataset_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_runs_dataset_id_datasets", "runs", type_="foreignkey")
    op.drop_table("datasets")
    op.drop_table("run_rejections")
    op.drop_table("run_events")
    op.drop_table("runs")
    op.drop_table("pipelines")
    op.drop_table("data_sources")
    pg.ENUM(name="run_status").drop(op.get_bind(), checkfirst=False)
    # RESTRICT (no CASCADE): never destroys ETL-owned tables; fails if they still exist.
    op.execute("DROP SCHEMA IF EXISTS datasets RESTRICT")
    op.execute("DROP SCHEMA IF EXISTS staging RESTRICT")
