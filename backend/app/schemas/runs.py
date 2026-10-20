"""Run schemas (openapi.yaml: Run, RunPage, RunEvent, RejectedRow, RejectedRowPage)."""

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.schemas.pipelines import NonNegInt, RunStatusName, UtcDatetime

StageName = Literal["extract", "transform", "validate", "load", "publish"]
EventStatusName = Literal["started", "progress", "completed", "failed"]
RuleName = Literal[
    "not_null", "unique", "range", "allowed_values", "regex", "length", "type_cast", "parse_error"
]


class RunOut(BaseModel):
    id: uuid.UUID
    pipeline_id: uuid.UUID | None
    pipeline_name: str
    source_id: uuid.UUID | None
    status: RunStatusName
    current_stage: StageName | None
    config_version: Annotated[int, Field(ge=1)]
    queued_at: UtcDatetime
    started_at: UtcDatetime | None
    finished_at: UtcDatetime | None
    duration_ms: NonNegInt | None
    extracted_count: NonNegInt
    loaded_count: NonNegInt
    rejected_count: NonNegInt
    duplicate_dropped_count: NonNegInt
    null_dropped_count: NonNegInt
    dataset_id: uuid.UUID | None
    error_message: str | None


class RunPage(BaseModel):
    total: NonNegInt
    limit: Annotated[int, Field(ge=1)]
    offset: NonNegInt
    items: list[RunOut]


class RunEventOut(BaseModel):
    id: int
    run_id: uuid.UUID
    stage: StageName
    status: EventStatusName
    rows_in: NonNegInt | None
    rows_out: NonNegInt | None
    message: str | None
    created_at: UtcDatetime


class RejectedRowOut(BaseModel):
    row_number: Annotated[int, Field(ge=1)]
    column: str | None
    rule: RuleName
    message: str
    value: str | None


class RejectedRowPage(BaseModel):
    total: NonNegInt
    limit: Annotated[int, Field(ge=1)]
    offset: NonNegInt
    items: list[RejectedRowOut]
