"""Application metadata tables in schema `public` (architecture section 7.1)."""

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import RUN_STATUS_VALUES, RunStatus

_UUID_DEFAULT = sa.text("gen_random_uuid()")
_NOW = sa.text("now()")

run_status_enum = pg.ENUM(*RUN_STATUS_VALUES, name="run_status", create_type=False)


class DataSource(Base):
    __tablename__ = "data_sources"

    id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=_UUID_DEFAULT
    )
    name: Mapped[str] = mapped_column(sa.Text)
    original_filename: Mapped[str] = mapped_column(sa.Text)
    stored_path: Mapped[str] = mapped_column(sa.Text)
    size_bytes: Mapped[int] = mapped_column(sa.BigInteger)
    sha256: Mapped[str] = mapped_column(sa.CHAR(64))
    csv_options: Mapped[dict[str, Any]] = mapped_column(pg.JSONB)
    columns: Mapped[list[dict[str, Any]]] = mapped_column(pg.JSONB)
    row_count: Mapped[int] = mapped_column(sa.BigInteger)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=_NOW)


class Pipeline(Base):
    __tablename__ = "pipelines"

    id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=_UUID_DEFAULT
    )
    name: Mapped[str] = mapped_column(sa.Text, unique=True)
    description: Mapped[str | None] = mapped_column(sa.Text)
    source_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), sa.ForeignKey("data_sources.id", ondelete="RESTRICT")
    )
    config: Mapped[dict[str, Any]] = mapped_column(pg.JSONB)
    config_version: Mapped[int] = mapped_column(sa.Integer, server_default=sa.text("1"))
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=_NOW)
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=_NOW)


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        sa.Index(
            "one_running_run",
            sa.text("(true)"),
            unique=True,
            postgresql_where=sa.text("status = 'running'"),
        ),
        sa.Index(
            "one_active_run_per_pipeline",
            "pipeline_id",
            unique=True,
            postgresql_where=sa.text("status IN ('queued', 'running')"),
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

    id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=_UUID_DEFAULT
    )
    pipeline_id: Mapped[uuid.UUID | None] = mapped_column(
        pg.UUID(as_uuid=True), sa.ForeignKey("pipelines.id", ondelete="SET NULL")
    )
    pipeline_name: Mapped[str] = mapped_column(sa.Text)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        pg.UUID(as_uuid=True), sa.ForeignKey("data_sources.id", ondelete="SET NULL")
    )
    config_snapshot: Mapped[dict[str, Any]] = mapped_column(pg.JSONB)
    config_version: Mapped[int] = mapped_column(sa.Integer)
    status: Mapped[RunStatus] = mapped_column(run_status_enum, server_default=sa.text("'queued'"))
    current_stage: Mapped[str | None] = mapped_column(sa.Text)
    queued_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=_NOW)
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    worker_id: Mapped[str | None] = mapped_column(sa.Text)
    extracted_count: Mapped[int] = mapped_column(sa.BigInteger, server_default=sa.text("0"))
    loaded_count: Mapped[int] = mapped_column(sa.BigInteger, server_default=sa.text("0"))
    rejected_count: Mapped[int] = mapped_column(sa.BigInteger, server_default=sa.text("0"))
    duplicate_dropped_count: Mapped[int] = mapped_column(sa.BigInteger, server_default=sa.text("0"))
    null_dropped_count: Mapped[int] = mapped_column(sa.BigInteger, server_default=sa.text("0"))
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        pg.UUID(as_uuid=True),
        sa.ForeignKey("datasets.id", ondelete="SET NULL", use_alter=True),
    )
    error_message: Mapped[str | None] = mapped_column(sa.Text)


class RunEvent(Base):
    __tablename__ = "run_events"
    __table_args__ = (sa.Index("ix_run_events_run_id_id", "run_id", "id"),)

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), sa.ForeignKey("runs.id", ondelete="CASCADE")
    )
    stage: Mapped[str] = mapped_column(sa.Text)
    status: Mapped[str] = mapped_column(sa.Text)
    rows_in: Mapped[int | None] = mapped_column(sa.BigInteger)
    rows_out: Mapped[int | None] = mapped_column(sa.BigInteger)
    message: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=_NOW)


class RunRejection(Base):
    __tablename__ = "run_rejections"
    __table_args__ = (sa.Index("ix_run_rejections_run_id_row_number", "run_id", "row_number"),)

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), sa.ForeignKey("runs.id", ondelete="CASCADE")
    )
    row_number: Mapped[int] = mapped_column(sa.BigInteger)
    column_name: Mapped[str | None] = mapped_column(sa.Text)
    rule: Mapped[str] = mapped_column(sa.Text)
    message: Mapped[str] = mapped_column(sa.Text)
    value: Mapped[str | None] = mapped_column(sa.Text)


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=_UUID_DEFAULT
    )
    table_name: Mapped[str] = mapped_column(sa.Text, unique=True)
    pipeline_id: Mapped[uuid.UUID | None] = mapped_column(
        pg.UUID(as_uuid=True), sa.ForeignKey("pipelines.id", ondelete="SET NULL")
    )
    last_run_id: Mapped[uuid.UUID] = mapped_column(pg.UUID(as_uuid=True), sa.ForeignKey("runs.id"))
    row_count: Mapped[int] = mapped_column(sa.BigInteger)
    columns: Mapped[list[dict[str, Any]]] = mapped_column(pg.JSONB)
    published_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=_NOW)
