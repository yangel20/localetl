"""BE-06: GET /metrics/summary."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import DataSource, Pipeline, Run, RunStatus

URL = "/api/v1/metrics/summary"


@pytest.fixture
def pipeline(api_session: Session) -> Pipeline:
    sid = uuid.uuid4()
    api_session.add(
        DataSource(
            id=sid, name="s", original_filename="s.csv", stored_path="x", size_bytes=1,
            sha256="0" * 64, csv_options={}, columns=[], row_count=0,
        )
    )  # fmt: skip
    api_session.flush()
    p = Pipeline(name="p", source_id=sid, config={})
    api_session.add(p)
    api_session.commit()
    return p


def add(
    session: Session,
    p: Pipeline,
    status: RunStatus,
    finished: datetime | None = None,
    started: datetime | None = None,
    loaded: int = 0,
) -> None:
    run = Run(
        pipeline_id=p.id, pipeline_name="p", config_snapshot={}, config_version=1, status=status,
        started_at=started, finished_at=finished, loaded_count=loaded,
        extracted_count=loaded if status == RunStatus.succeeded else 0,
    )  # fmt: skip
    session.add(run)
    session.commit()


def today() -> datetime:
    return datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)


def test_empty_database_is_zero_filled(api_client: TestClient) -> None:
    out = api_client.get(URL).json()
    assert out["total_runs"] == 0
    assert out["runs_by_status"] == {
        "queued": 0, "running": 0, "succeeded": 0, "failed": 0, "interrupted": 0,
    }  # fmt: skip
    assert (out["loaded_count_total"], out["avg_duration_ms"]) == (0, None)
    assert len(out["daily"]) == 30
    assert all(
        d["succeeded"] == d["failed"] == d["interrupted"] == d["loaded_count"] == 0
        for d in out["daily"]
    )


def test_daily_is_oldest_first_ending_today_utc(api_client: TestClient) -> None:
    daily = api_client.get(URL, params={"days": 7}).json()["daily"]
    dates = [d["date"] for d in daily]
    assert dates == sorted(dates) and len(set(dates)) == 7
    assert dates[-1] == datetime.now(UTC).date().isoformat()
    assert dates[0] == (datetime.now(UTC).date() - timedelta(days=6)).isoformat()


def test_counts_loaded_totals_and_durations(
    api_client: TestClient, api_session: Session, pipeline: Pipeline
) -> None:
    now = today()
    yesterday = now - timedelta(days=1)
    add(api_session, pipeline, RunStatus.succeeded, now, now - timedelta(seconds=2), loaded=10)
    add(api_session, pipeline, RunStatus.succeeded, yesterday, yesterday - timedelta(seconds=4), 5)
    add(api_session, pipeline, RunStatus.failed, yesterday, yesterday - timedelta(seconds=1))
    add(api_session, pipeline, RunStatus.interrupted, now, now - timedelta(seconds=1))
    add(api_session, pipeline, RunStatus.queued)
    other = Pipeline(name="p2", source_id=pipeline.source_id, config={})
    api_session.add(other)
    api_session.commit()
    add(api_session, other, RunStatus.running, started=now)

    out = api_client.get(URL, params={"days": 3}).json()
    assert out["total_runs"] == 6
    assert out["runs_by_status"] == {
        "queued": 1, "running": 1, "succeeded": 2, "failed": 1, "interrupted": 1,
    }  # fmt: skip
    assert out["loaded_count_total"] == 15
    assert out["avg_duration_ms"] == pytest.approx((2000 + 4000 + 1000 + 1000) / 4)
    daily = {d["date"]: d for d in out["daily"]}
    assert len(daily) == 3
    t, y = daily[now.date().isoformat()], daily[yesterday.date().isoformat()]
    assert (t["succeeded"], t["failed"], t["interrupted"], t["loaded_count"]) == (1, 0, 1, 10)
    assert (y["succeeded"], y["failed"], y["interrupted"], y["loaded_count"]) == (1, 1, 0, 5)
    two_days_ago = daily[(now - timedelta(days=2)).date().isoformat()]
    assert two_days_ago["succeeded"] == two_days_ago["loaded_count"] == 0


def test_runs_outside_window_count_in_totals_but_not_daily(
    api_client: TestClient, api_session: Session, pipeline: Pipeline
) -> None:
    old = today() - timedelta(days=40)
    add(api_session, pipeline, RunStatus.succeeded, old, old - timedelta(seconds=1), loaded=7)
    out = api_client.get(URL, params={"days": 30}).json()
    assert (out["total_runs"], out["loaded_count_total"]) == (1, 7)
    assert sum(d["succeeded"] for d in out["daily"]) == 0
    assert sum(d["loaded_count"] for d in out["daily"]) == 0


def test_loaded_counts_come_from_succeeded_runs_only(
    api_client: TestClient, api_session: Session, pipeline: Pipeline
) -> None:
    now = today()
    add(api_session, pipeline, RunStatus.failed, now, now - timedelta(seconds=1))
    out = api_client.get(URL).json()
    assert out["loaded_count_total"] == 0
    assert sum(d["loaded_count"] for d in out["daily"]) == 0


@pytest.mark.parametrize("days", ["0", "366", "abc", "-1"])
def test_days_validation(api_client: TestClient, days: str) -> None:
    resp = api_client.get(URL, params={"days": days})
    assert resp.status_code == 422
    body: dict[str, Any] = resp.json()["error"]
    assert (body["code"], body["details"][0]["path"]) == ("validation_error", "/days")


def test_days_bounds_are_accepted(api_client: TestClient) -> None:
    assert len(api_client.get(URL, params={"days": 1}).json()["daily"]) == 1
    assert len(api_client.get(URL, params={"days": 365}).json()["daily"]) == 365
