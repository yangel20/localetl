"""Run endpoints: POST /pipelines/{id}/runs, GET /runs, /runs/{id}, /events, /rejections.

This module only inserts `queued` runs and reads. Every later status change belongs to the
worker (architecture section 7.2); nothing here executes a pipeline.
"""

import uuid
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.core.errors import ApiError
from app.models import Pipeline, Run, RunEvent, RunRejection
from app.models.enums import RunStatus
from app.schemas.runs import (
    RejectedRowOut,
    RejectedRowPage,
    RunEventOut,
    RunOut,
    RunPage,
)

router = APIRouter(tags=["runs"])
_ACTIVE = (RunStatus.queued, RunStatus.running)


def _run_out(run: Run) -> RunOut:
    duration = None
    if run.started_at is not None and run.finished_at is not None:
        duration = max(0, int((run.finished_at - run.started_at).total_seconds() * 1000))
    return RunOut(
        id=run.id,
        pipeline_id=run.pipeline_id,
        pipeline_name=run.pipeline_name,
        source_id=run.source_id,
        status=str(run.status),
        current_stage=run.current_stage,
        config_version=run.config_version,
        queued_at=run.queued_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        duration_ms=duration,
        extracted_count=run.extracted_count,
        loaded_count=run.loaded_count,
        rejected_count=run.rejected_count,
        duplicate_dropped_count=run.duplicate_dropped_count,
        null_dropped_count=run.null_dropped_count,
        dataset_id=run.dataset_id,
        error_message=run.error_message,
    )


def _run_or_404(session: Session, run_id: uuid.UUID) -> Run:
    run = session.get(Run, run_id)
    if run is None:
        raise ApiError(404, "not_found", "Run not found")
    return run


def _already_active() -> ApiError:
    return ApiError(409, "conflict", "This pipeline already has a queued or running run")


@router.post(
    "/pipelines/{pipeline_id}/runs",
    operation_id="createRun",
    status_code=202,
    response_model=RunOut,
)
def create_run(pipeline_id: uuid.UUID, session: Annotated[Session, Depends(get_session)]) -> RunOut:
    # Lock the pipeline row so a concurrent PUT/DELETE cannot slip between snapshot and insert.
    pipeline = session.scalars(
        sa.select(Pipeline).where(Pipeline.id == pipeline_id).with_for_update()
    ).one_or_none()
    if pipeline is None:
        raise ApiError(404, "not_found", "Pipeline not found")
    active = session.scalar(
        sa.select(sa.func.count())
        .select_from(Run)
        .where(
            Run.pipeline_id == pipeline_id, Run.status.in_((RunStatus.queued, RunStatus.running))
        )
    )
    if active:
        session.rollback()
        raise _already_active()
    run = Run(
        pipeline_id=pipeline.id,
        pipeline_name=pipeline.name,
        source_id=pipeline.source_id,
        config_snapshot=pipeline.config,
        config_version=pipeline.config_version,
        status=RunStatus.queued,
    )
    session.add(run)
    try:
        session.commit()
    except sa.exc.IntegrityError:  # one_active_run_per_pipeline lost a race
        session.rollback()
        raise _already_active() from None
    session.refresh(run)
    return _run_out(run)


@router.get("/runs", operation_id="listRuns", response_model=RunPage)
def list_runs(
    session: Annotated[Session, Depends(get_session)],
    pipeline_id: uuid.UUID | None = None,
    status: RunStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RunPage:
    filters: list[sa.ColumnElement[bool]] = []
    if pipeline_id is not None:
        filters.append(Run.pipeline_id == pipeline_id)
    if status is not None:
        filters.append(Run.status == status)
    total = session.scalar(sa.select(sa.func.count()).select_from(Run).where(*filters)) or 0
    rows = session.scalars(
        sa.select(Run)
        .where(*filters)
        .order_by(Run.queued_at.desc(), Run.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return RunPage(total=total, limit=limit, offset=offset, items=[_run_out(r) for r in rows])


@router.get("/runs/{run_id}", operation_id="getRun", response_model=RunOut)
def get_run(run_id: uuid.UUID, session: Annotated[Session, Depends(get_session)]) -> RunOut:
    return _run_out(_run_or_404(session, run_id))


@router.get("/runs/{run_id}/events", operation_id="listRunEvents", response_model=list[RunEventOut])
def list_run_events(
    run_id: uuid.UUID, session: Annotated[Session, Depends(get_session)]
) -> list[RunEventOut]:
    _run_or_404(session, run_id)
    events = session.scalars(
        sa.select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.id)
    ).all()
    return [
        RunEventOut.model_validate(
            {
                "id": e.id,
                "run_id": e.run_id,
                "stage": e.stage,
                "status": e.status,
                "rows_in": e.rows_in,
                "rows_out": e.rows_out,
                "message": e.message,
                "created_at": e.created_at,
            }
        )
        for e in events
    ]


@router.get(
    "/runs/{run_id}/rejections", operation_id="listRunRejections", response_model=RejectedRowPage
)
def list_run_rejections(
    run_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RejectedRowPage:
    _run_or_404(session, run_id)
    total = (
        session.scalar(
            sa.select(sa.func.count())
            .select_from(RunRejection)
            .where(RunRejection.run_id == run_id)
        )
        or 0
    )
    rows = session.scalars(
        sa.select(RunRejection)
        .where(RunRejection.run_id == run_id)
        .order_by(RunRejection.row_number, RunRejection.id)
        .limit(limit)
        .offset(offset)
    ).all()
    items = [
        RejectedRowOut.model_validate(
            {
                "row_number": r.row_number,
                "column": r.column_name,
                "rule": r.rule,
                "message": r.message,
                "value": r.value,
            }
        )
        for r in rows
    ]
    return RejectedRowPage(total=total, limit=limit, offset=offset, items=items)
