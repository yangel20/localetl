"""Pipeline schemas (openapi.yaml: PipelineCreate, Pipeline, PipelinePage, RunSummary,
PipelineValidateRequest, PipelineValidationResult). ``config`` is typed loosely on purpose: the
real validation is ``app.etl.validate_pipeline_config`` so every problem is reported with a path."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field


def _to_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


UtcDatetime = Annotated[AwareDatetime, AfterValidator(_to_utc)]
NonNegInt = Annotated[int, Field(ge=0)]
RunStatusName = Literal["queued", "running", "succeeded", "failed", "interrupted"]


class PipelineCreate(BaseModel):
    """Body of POST /pipelines and PUT /pipelines/{id}."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=200)]
    description: Annotated[str, Field(max_length=2000)] | None = None
    source_id: uuid.UUID
    config: dict[str, Any]


class PipelineValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: dict[str, Any]
    source_id: uuid.UUID | None = None


class ErrorDetailOut(BaseModel):
    path: str
    message: str


class PipelineValidationResult(BaseModel):
    valid: bool
    errors: list[ErrorDetailOut]


class RunSummaryOut(BaseModel):
    id: uuid.UUID
    status: RunStatusName
    queued_at: UtcDatetime
    finished_at: UtcDatetime | None


class PipelineOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    source_id: uuid.UUID
    config: dict[str, Any]
    config_version: Annotated[int, Field(ge=1)]
    created_at: UtcDatetime
    updated_at: UtcDatetime
    last_run: RunSummaryOut | None


class PipelinePage(BaseModel):
    total: NonNegInt
    limit: Annotated[int, Field(ge=1)]
    offset: NonNegInt
    items: list[PipelineOut]
