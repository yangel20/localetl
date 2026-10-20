"""Pipeline config validation (implemented in ETL-03)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .types import PipelineConfig


def validate_pipeline_config(
    config: Mapping[str, Any], *, source_columns: list[str] | None = None
) -> PipelineConfig:
    raise NotImplementedError("ETL-03")
