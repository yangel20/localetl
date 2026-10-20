"""Pipeline execution (implemented in ETL-07)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from uuid import UUID

import sqlalchemy as sa

from .types import CsvOptions, PipelineConfig, RunResult, StageEvent


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
    raise NotImplementedError("ETL-07")
