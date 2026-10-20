"""BE-05: run endpoints. The API only queues runs; the worker owns every later transition."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import DataSource, Pipeline, Run, RunEvent, RunRejection, RunStatus

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
CONFIG: dict[str, Any] = {
    "version": 1,
    "columns": [{"source": "id", "name": "id", "type": "integer"}],
    "target": {"table": "t", "mode": "replace"},
}


@pytest.fixture
def pipeline(api_session: Session) -> Pipeline:
    sid = uuid.uuid4()
    api_session.add(
        DataSource(
            id=sid,
            name="s",
            original_filename="s.csv",
            stored_path=f"sources/{sid}.csv",
            size_bytes=1,
            sha256="0" * 64,
            csv_options={},
            columns=[],
            row_count=0,
        )
    )
    api_session.commit()
    p = Pipeline(name="orders", source_id=sid, config=CONFIG, config_version=3)
    api_session.add(p)
    api_session.commit()
    return p


def mk_run(session: Session, p: Pipeline, status: RunStatus, minutes: int = 0, **kw: Any) -> Run:
    run = Run(
        pipeline_id=p.id,
        pipeline_name=p.name,
        source_id=p.source_id,
        config_snapshot={},
        config_version=1,
        status=status,
        queued_at=T0 + timedelta(minutes=minutes),
        **kw,
    )
    session.add(run)
    session.commit()
    return run


def error(resp: Any, status: int, code: str) -> dict[str, Any]:
    assert resp.status_code == status, resp.text
    err: dict[str, Any] = resp.json()["error"]
    assert err["code"] == code
    return err


def test_create_run_queues_with_snapshot_and_never_executes(
    api_client: TestClient, api_session: Session, pipeline: Pipeline
) -> None:
    resp = api_client.post(f"/api/v1/pipelines/{pipeline.id}/runs")
    assert resp.status_code == 202, resp.text
    run = resp.json()
    assert set(run) == {
        "id",
        "pipeline_id",
        "pipeline_name",
        "source_id",
        "status",
        "current_stage",
        "config_version",
        "queued_at",
        "started_at",
        "finished_at",
        "duration_ms",
        "extracted_count",
        "loaded_count",
        "rejected_count",
        "duplicate_dropped_count",
        "null_dropped_count",
        "dataset_id",
        "error_message",
    }
    assert run["status"] == "queued"
    assert run["pipeline_id"] == str(pipeline.id)
    assert run["pipeline_name"] == "orders"
    assert run["source_id"] == str(pipeline.source_id)
    assert run["config_version"] == 3
    assert (run["current_stage"], run["started_at"], run["finished_at"]) == (None, None, None)
    assert (run["duration_ms"], run["dataset_id"], run["error_message"]) == (None, None, None)
    counters = ("extracted", "loaded", "rejected", "duplicate_dropped", "null_dropped")
    assert [run[f"{c}_count"] for c in counters] == [0] * 5
    assert run["queued_at"].endswith("Z")

    api_session.expire_all()
    stored = api_session.get(Run, uuid.UUID(run["id"]))
    assert stored is not None
    assert stored.config_snapshot == CONFIG
    assert stored.status == RunStatus.queued and stored.started_at is None
    assert api_client.get(f"/api/v1/runs/{run['id']}").json() == run


def test_snapshot_is_unaffected_by_later_pipeline_edits(
    api_client: TestClient, api_session: Session, pipeline: Pipeline
) -> None:
    run_id = api_client.post(f"/api/v1/pipelines/{pipeline.id}/runs").json()["id"]
    api_session.expire_all()
    pipeline.config = {**CONFIG, "target": {"table": "other", "mode": "replace"}}
    api_session.commit()
    stored = api_session.get(Run, uuid.UUID(run_id))
    assert stored is not None and stored.config_snapshot == CONFIG


@pytest.mark.parametrize("status", [RunStatus.queued, RunStatus.running])
def test_second_active_run_is_409(
    api_client: TestClient, api_session: Session, pipeline: Pipeline, status: RunStatus
) -> None:
    mk_run(api_session, pipeline, status)
    error(api_client.post(f"/api/v1/pipelines/{pipeline.id}/runs"), 409, "conflict")
    count = api_session.scalar(sa.select(sa.func.count()).select_from(Run))
    assert count == 1


def test_run_allowed_after_previous_run_finished(
    api_client: TestClient, api_session: Session, pipeline: Pipeline
) -> None:
    mk_run(api_session, pipeline, RunStatus.failed)
    assert api_client.post(f"/api/v1/pipelines/{pipeline.id}/runs").status_code == 202


def test_create_run_unknown_pipeline_is_404(api_client: TestClient) -> None:
    error(api_client.post(f"/api/v1/pipelines/{uuid.uuid4()}/runs"), 404, "not_found")
    err = error(api_client.post("/api/v1/pipelines/nope/runs"), 422, "validation_error")
    assert err["details"][0]["path"] == "/pipeline_id"


def test_list_runs_newest_first_with_filters_and_pagination(
    api_client: TestClient, api_session: Session, pipeline: Pipeline
) -> None:
    other = Pipeline(name="other", source_id=pipeline.source_id, config=CONFIG)
    api_session.add(other)
    api_session.commit()
    a = mk_run(api_session, pipeline, RunStatus.succeeded, 1)
    b = mk_run(api_session, pipeline, RunStatus.failed, 2)
    c = mk_run(api_session, other, RunStatus.succeeded, 3)
    d = mk_run(api_session, pipeline, RunStatus.queued, 4)

    page = api_client.get("/api/v1/runs").json()
    assert (page["total"], page["limit"], page["offset"]) == (4, 50, 0)
    assert [i["id"] for i in page["items"]] == [str(x.id) for x in (d, c, b, a)]

    by_pipeline = api_client.get("/api/v1/runs", params={"pipeline_id": str(pipeline.id)}).json()
    assert [i["id"] for i in by_pipeline["items"]] == [str(x.id) for x in (d, b, a)]
    assert by_pipeline["total"] == 3

    by_status = api_client.get("/api/v1/runs", params={"status": "succeeded"}).json()
    assert [i["id"] for i in by_status["items"]] == [str(c.id), str(a.id)]

    both = api_client.get(
        "/api/v1/runs", params={"status": "succeeded", "pipeline_id": str(pipeline.id)}
    ).json()
    assert [i["id"] for i in both["items"]] == [str(a.id)]

    paged = api_client.get("/api/v1/runs", params={"limit": 2, "offset": 1}).json()
    assert (paged["total"], [i["id"] for i in paged["items"]]) == (4, [str(c.id), str(b.id)])


@pytest.mark.parametrize(
    ("params", "path"),
    [
        ({"status": "bogus"}, "/status"),
        ({"pipeline_id": "x"}, "/pipeline_id"),
        ({"limit": 0}, "/limit"),
        ({"limit": 201}, "/limit"),
        ({"offset": -1}, "/offset"),
    ],
)
def test_list_runs_rejects_bad_params(
    api_client: TestClient, params: dict[str, Any], path: str
) -> None:
    err = error(api_client.get("/api/v1/runs", params=params), 422, "validation_error")
    assert err["details"][0]["path"] == path


def test_run_counters_duration_and_dataset_fields(
    api_client: TestClient, api_session: Session, pipeline: Pipeline
) -> None:
    run = mk_run(
        api_session,
        pipeline,
        RunStatus.succeeded,
        started_at=T0,
        finished_at=T0 + timedelta(seconds=2, milliseconds=500),
        current_stage="publish",
        extracted_count=10,
        loaded_count=6,
        rejected_count=2,
        duplicate_dropped_count=1,
        null_dropped_count=1,
    )
    out = api_client.get(f"/api/v1/runs/{run.id}").json()
    assert out["duration_ms"] == 2500
    assert out["current_stage"] == "publish"
    assert [
        out[k]
        for k in (
            "extracted_count",
            "loaded_count",
            "rejected_count",
            "duplicate_dropped_count",
            "null_dropped_count",
        )
    ] == [10, 6, 2, 1, 1]
    assert out["started_at"] == "2026-01-01T12:00:00Z"


def test_running_run_has_no_duration(
    api_client: TestClient, api_session: Session, pipeline: Pipeline
) -> None:
    run = mk_run(api_session, pipeline, RunStatus.running, started_at=T0, current_stage="load")
    out = api_client.get(f"/api/v1/runs/{run.id}").json()
    assert (out["duration_ms"], out["finished_at"]) == (None, None)


def test_run_of_deleted_pipeline_has_null_pipeline_id(
    api_client: TestClient, api_session: Session, pipeline: Pipeline
) -> None:
    run = mk_run(api_session, pipeline, RunStatus.succeeded)
    api_client.delete(f"/api/v1/pipelines/{pipeline.id}")
    out = api_client.get(f"/api/v1/runs/{run.id}").json()
    assert (out["pipeline_id"], out["pipeline_name"]) == (None, "orders")


def test_unknown_run_is_404_everywhere(api_client: TestClient) -> None:
    rid = uuid.uuid4()
    for suffix in ("", "/events", "/rejections"):
        error(api_client.get(f"/api/v1/runs/{rid}{suffix}"), 404, "not_found")


def test_events_in_chronological_order(
    api_client: TestClient, api_session: Session, pipeline: Pipeline
) -> None:
    run = mk_run(api_session, pipeline, RunStatus.running)
    other = mk_run(api_session, pipeline, RunStatus.succeeded, 1)
    for stage, status, rin, rout in [
        ("extract", "started", None, None),
        ("extract", "completed", 5, 5),
        ("transform", "failed", 5, None),
    ]:
        api_session.add(
            RunEvent(
                run_id=run.id,
                stage=stage,
                status=status,
                rows_in=rin,
                rows_out=rout,
                message="m" if status == "failed" else None,
            )
        )
    api_session.add(RunEvent(run_id=other.id, stage="extract", status="started"))
    api_session.commit()
    events = api_client.get(f"/api/v1/runs/{run.id}/events").json()
    assert [(e["stage"], e["status"]) for e in events] == [
        ("extract", "started"),
        ("extract", "completed"),
        ("transform", "failed"),
    ]
    assert set(events[0]) == {
        "id",
        "run_id",
        "stage",
        "status",
        "rows_in",
        "rows_out",
        "message",
        "created_at",
    }
    assert events[1]["rows_in"] == 5 and events[0]["rows_in"] is None
    assert events[2]["message"] == "m"
    assert all(e["run_id"] == str(run.id) for e in events)
    assert api_client.get(f"/api/v1/runs/{other.id}/events").json()[0]["stage"] == "extract"


def test_events_empty(api_client: TestClient, api_session: Session, pipeline: Pipeline) -> None:
    run = mk_run(api_session, pipeline, RunStatus.queued)
    assert api_client.get(f"/api/v1/runs/{run.id}/events").json() == []


def test_rejections_page_entries_by_row_number(
    api_client: TestClient, api_session: Session, pipeline: Pipeline
) -> None:
    run = mk_run(api_session, pipeline, RunStatus.succeeded)
    other = mk_run(api_session, pipeline, RunStatus.succeeded, 1)
    for n, col, rule in [
        (5, "a", "range"),
        (2, "a", "not_null"),
        (5, "b", "regex"),
        (9, None, "parse_error"),
    ]:
        api_session.add(
            RunRejection(
                run_id=run.id,
                row_number=n,
                column_name=col,
                rule=rule,
                message=f"{rule} failed",
                value=None if col is None else "v",
            )
        )
    api_session.add(RunRejection(run_id=other.id, row_number=1, rule="unique", message="dup"))
    api_session.commit()

    page = api_client.get(f"/api/v1/runs/{run.id}/rejections").json()
    assert (page["total"], page["limit"], page["offset"]) == (4, 50, 0)
    assert [(i["row_number"], i["rule"]) for i in page["items"]] == [
        (2, "not_null"),
        (5, "range"),
        (5, "regex"),
        (9, "parse_error"),
    ]
    assert page["items"][0] == {
        "row_number": 2,
        "column": "a",
        "rule": "not_null",
        "message": "not_null failed",
        "value": "v",
    }
    assert page["items"][3]["column"] is None and page["items"][3]["value"] is None

    second = api_client.get(
        f"/api/v1/runs/{run.id}/rejections", params={"limit": 2, "offset": 2}
    ).json()
    assert [i["rule"] for i in second["items"]] == ["regex", "parse_error"]
    assert second["total"] == 4


@pytest.mark.parametrize(
    ("params", "path"),
    [({"limit": 0}, "/limit"), ({"limit": 201}, "/limit"), ({"offset": -1}, "/offset")],
)
def test_rejections_reject_bad_params(
    api_client: TestClient,
    api_session: Session,
    pipeline: Pipeline,
    params: dict[str, Any],
    path: str,
) -> None:
    run = mk_run(api_session, pipeline, RunStatus.queued)
    err = error(
        api_client.get(f"/api/v1/runs/{run.id}/rejections", params=params), 422, "validation_error"
    )
    assert err["details"][0]["path"] == path


def test_served_openapi_has_run_operations(api_client: TestClient) -> None:
    spec = api_client.get("/openapi.json").json()
    ops = {
        op["operationId"]
        for path, item in spec["paths"].items()
        if path.startswith(("/api/v1/runs", "/api/v1/pipelines/{pipeline_id}/runs"))
        for op in item.values()
    }
    assert ops == {"createRun", "listRuns", "getRun", "listRunEvents", "listRunRejections"}
