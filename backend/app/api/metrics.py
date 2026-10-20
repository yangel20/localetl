"""GET /metrics/summary: aggregate run metrics (all times UTC).

Totals cover all runs. ``daily`` covers the last ``days`` UTC days ending today (zero-filled) and
buckets terminal runs by ``finished_at`` (falling back to ``started_at``, then ``queued_at``).
``loaded_count`` figures sum succeeded runs only (failed/interrupted runs always load 0 rows).
"""

import datetime as dt
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.models import Run
from app.models.enums import RunStatus
from app.schemas.metrics import DailyMetrics, MetricsSummary, RunsByStatus

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/summary", operation_id="getMetricsSummary", response_model=MetricsSummary)
def get_metrics_summary(
    session: Annotated[Session, Depends(get_session)],
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> MetricsSummary:
    by_status = {s.value: 0 for s in RunStatus}
    for status, n in session.execute(sa.select(Run.status, sa.func.count()).group_by(Run.status)):
        by_status[str(status)] = n

    loaded_total = session.scalar(
        sa.select(sa.func.coalesce(sa.func.sum(Run.loaded_count), 0)).where(
            Run.status == RunStatus.succeeded
        )
    )
    avg_ms = session.scalar(
        sa.select(
            sa.func.avg(sa.func.extract("epoch", Run.finished_at - Run.started_at) * 1000)
        ).where(Run.started_at.is_not(None), Run.finished_at.is_not(None))
    )

    today = dt.datetime.now(dt.UTC).date()
    first = today - dt.timedelta(days=days - 1)
    stamp = sa.func.coalesce(Run.finished_at, Run.started_at, Run.queued_at)
    day = sa.cast(sa.func.timezone("UTC", stamp), sa.Date)
    daily = {
        first + dt.timedelta(days=i): DailyMetrics(
            date=first + dt.timedelta(days=i), succeeded=0, failed=0, interrupted=0, loaded_count=0
        )
        for i in range(days)
    }
    rows = session.execute(
        sa.select(
            day.label("d"),
            Run.status,
            sa.func.count(),
            sa.func.coalesce(sa.func.sum(Run.loaded_count), 0),
        )
        .where(
            Run.status.in_((RunStatus.succeeded, RunStatus.failed, RunStatus.interrupted)),
            day >= first,
            day <= today,
        )
        .group_by(day, Run.status)
    )
    for d, status, n, loaded in rows:
        entry = daily[d]
        setattr(entry, str(status), n)
        if status == RunStatus.succeeded:
            entry.loaded_count = int(loaded)

    return MetricsSummary(
        total_runs=sum(by_status.values()),
        runs_by_status=RunsByStatus(**by_status),
        loaded_count_total=int(loaded_total or 0),
        avg_duration_ms=float(avg_ms) if avg_ms is not None else None,
        daily=list(daily.values()),
    )
