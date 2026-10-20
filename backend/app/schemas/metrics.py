"""Metrics schemas (openapi.yaml: MetricsSummary)."""

import datetime as dt
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

NonNegInt = Annotated[int, Field(ge=0)]


class RunsByStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    queued: NonNegInt
    running: NonNegInt
    succeeded: NonNegInt
    failed: NonNegInt
    interrupted: NonNegInt


class DailyMetrics(BaseModel):
    date: dt.date
    succeeded: NonNegInt
    failed: NonNegInt
    interrupted: NonNegInt
    loaded_count: NonNegInt


class MetricsSummary(BaseModel):
    total_runs: NonNegInt
    runs_by_status: RunsByStatus
    loaded_count_total: NonNegInt
    avg_duration_ms: Annotated[float, Field(ge=0)] | None
    daily: list[DailyMetrics]
