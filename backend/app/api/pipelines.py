"""Pipeline endpoints: /pipelines, /pipelines/validate, /pipelines/{pipeline_id}.

Config validation goes only through ``app.etl.validate_pipeline_config`` with the source's column
names. The engine reports paths relative to the config (``/transformations/2/columns``); this module
prefixes ``/config`` so every ``ErrorDetail.path`` is a JSON Pointer into the request body.
"""

import uuid
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.core.errors import ApiError
from app.etl import ConfigValidationError, validate_pipeline_config
from app.models import DataSource, Pipeline, Run
from app.models.enums import RunStatus
from app.schemas.pipelines import (
    ErrorDetailOut,
    PipelineCreate,
    PipelineOut,
    PipelinePage,
    PipelineValidateRequest,
    PipelineValidationResult,
    RunSummaryOut,
)

router = APIRouter(prefix="/pipelines", tags=["pipelines"])

_ACTIVE = (RunStatus.queued, RunStatus.running)


def _config_errors(
    config: dict[str, object], source_columns: list[str] | None
) -> list[ErrorDetailOut]:
    """Run the engine validator; paths are prefixed with ``/config``."""
    try:
        validate_pipeline_config(config, source_columns=source_columns)
    except ConfigValidationError as exc:
        return [ErrorDetailOut(path=f"/config{e.path}", message=e.message) for e in exc.errors]
    return []


def _source_or_404(session: Session, source_id: uuid.UUID) -> DataSource:
    source = session.get(DataSource, source_id)
    if source is None:
        raise ApiError(404, "not_found", "Data source not found")
    return source


def _pipeline_or_404(session: Session, pipeline_id: uuid.UUID, *, lock: bool = False) -> Pipeline:
    stmt = sa.select(Pipeline).where(Pipeline.id == pipeline_id)
    if lock:
        stmt = stmt.with_for_update()
    row = session.scalars(stmt).one_or_none()
    if row is None:
        raise ApiError(404, "not_found", "Pipeline not found")
    return row


def _validated(session: Session, body: PipelineCreate) -> None:
    """404 for an unknown source, 422 (details under /config) for an invalid config."""
    source = _source_or_404(session, body.source_id)
    errors = _config_errors(body.config, [c["name"] for c in source.columns])
    if errors:
        raise ApiError(
            422,
            "validation_error",
            "Pipeline config is invalid",
            [e.model_dump() for e in errors],
        )


def _name_taken(session: Session, name: str, *, exclude: uuid.UUID | None = None) -> bool:
    stmt = sa.select(sa.func.count()).select_from(Pipeline).where(Pipeline.name == name)
    if exclude is not None:
        stmt = stmt.where(Pipeline.id != exclude)
    return bool(session.scalar(stmt))


def _duplicate_name() -> ApiError:
    return ApiError(
        409,
        "conflict",
        "A pipeline with this name already exists",
        [{"path": "/name", "message": "name must be unique"}],
    )


def _last_runs(session: Session, pipeline_ids: list[uuid.UUID]) -> dict[uuid.UUID, RunSummaryOut]:
    if not pipeline_ids:
        return {}
    rows = session.execute(
        select(Run.pipeline_id, Run.id, Run.status, Run.queued_at, Run.finished_at)
        .ext(distinct_on(Run.pipeline_id))
        .where(Run.pipeline_id.in_(pipeline_ids))
        .order_by(Run.pipeline_id, Run.queued_at.desc(), Run.id.desc())
    ).all()
    return {
        r.pipeline_id: RunSummaryOut(
            id=r.id, status=str(r.status), queued_at=r.queued_at, finished_at=r.finished_at
        )
        for r in rows
    }


def _to_out(row: Pipeline, last_run: RunSummaryOut | None) -> PipelineOut:
    return PipelineOut(
        id=row.id,
        name=row.name,
        description=row.description,
        source_id=row.source_id,
        config=row.config,
        config_version=row.config_version,
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_run=last_run,
    )


def _out(session: Session, row: Pipeline) -> PipelineOut:
    return _to_out(row, _last_runs(session, [row.id]).get(row.id))


def _commit_or_conflict(session: Session, body: PipelineCreate, row_id: uuid.UUID | None) -> None:
    try:
        session.commit()
    except sa.exc.IntegrityError:  # lost a race on the unique name or the source FK
        session.rollback()
        if _name_taken(session, body.name, exclude=row_id):
            raise _duplicate_name() from None
        if session.get(DataSource, body.source_id) is None:
            raise ApiError(404, "not_found", "Data source not found") from None
        raise


@router.post("", operation_id="createPipeline", status_code=201, response_model=PipelineOut)
def create_pipeline(
    body: PipelineCreate, session: Annotated[Session, Depends(get_session)]
) -> PipelineOut:
    _validated(session, body)
    if _name_taken(session, body.name):
        raise _duplicate_name()
    row = Pipeline(
        name=body.name, description=body.description, source_id=body.source_id, config=body.config
    )
    session.add(row)
    _commit_or_conflict(session, body, None)
    session.refresh(row)
    return _to_out(row, None)


@router.get("", operation_id="listPipelines", response_model=PipelinePage)
def list_pipelines(
    session: Annotated[Session, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PipelinePage:
    total = session.scalar(sa.select(sa.func.count()).select_from(Pipeline)) or 0
    rows = session.scalars(
        sa.select(Pipeline)
        .order_by(Pipeline.updated_at.desc(), Pipeline.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    last = _last_runs(session, [r.id for r in rows])
    return PipelinePage(
        total=total, limit=limit, offset=offset, items=[_to_out(r, last.get(r.id)) for r in rows]
    )


@router.post(
    "/validate", operation_id="validatePipelineConfig", response_model=PipelineValidationResult
)
def validate_config(
    body: PipelineValidateRequest, session: Annotated[Session, Depends(get_session)]
) -> PipelineValidationResult:
    columns: list[str] | None = None
    if body.source_id is not None:
        columns = [c["name"] for c in _source_or_404(session, body.source_id).columns]
    errors = _config_errors(body.config, columns)
    return PipelineValidationResult(valid=not errors, errors=errors)


@router.get("/{pipeline_id}", operation_id="getPipeline", response_model=PipelineOut)
def get_pipeline(
    pipeline_id: uuid.UUID, session: Annotated[Session, Depends(get_session)]
) -> PipelineOut:
    return _out(session, _pipeline_or_404(session, pipeline_id))


@router.put("/{pipeline_id}", operation_id="updatePipeline", response_model=PipelineOut)
def update_pipeline(
    pipeline_id: uuid.UUID,
    body: PipelineCreate,
    session: Annotated[Session, Depends(get_session)],
) -> PipelineOut:
    row = _pipeline_or_404(session, pipeline_id, lock=True)
    _validated(session, body)
    if _name_taken(session, body.name, exclude=pipeline_id):
        raise _duplicate_name()
    row.name = body.name
    row.description = body.description
    row.source_id = body.source_id
    row.config = body.config
    row.config_version = Pipeline.config_version + 1
    row.updated_at = sa.func.now()
    _commit_or_conflict(session, body, pipeline_id)
    session.refresh(row)
    return _out(session, row)


@router.delete("/{pipeline_id}", operation_id="deletePipeline", status_code=204)
def delete_pipeline(
    pipeline_id: uuid.UUID, session: Annotated[Session, Depends(get_session)]
) -> Response:
    row = _pipeline_or_404(session, pipeline_id, lock=True)
    active = session.scalar(
        sa.select(sa.func.count())
        .select_from(Run)
        .where(Run.pipeline_id == pipeline_id, Run.status.in_(_ACTIVE))
    )
    if active:
        session.rollback()
        raise ApiError(
            409, "conflict", "Pipeline has a queued or running run and cannot be deleted"
        )
    session.delete(row)  # runs keep their history: runs.pipeline_id is ON DELETE SET NULL
    session.commit()
    return Response(status_code=204)
