"""BE-04: /pipelines endpoints. Config problems are reported as JSON Pointers into the request
(`/config/...`): the engine's config-relative paths are prefixed with `/config`."""

import copy
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import DataSource, Pipeline, Run, RunStatus

BASE = "/api/v1/pipelines"
EXAMPLES = Path(__file__).resolve().parents[3] / "contracts" / "examples" / "pipeline"
MINIMAL: dict[str, Any] = json.loads((EXAMPLES / "valid" / "minimal.json").read_text())


@pytest.fixture
def source_id(api_session: Session) -> uuid.UUID:
    return add_source(api_session, ["id", "name", "amount"])


def add_source(session: Session, names: list[str]) -> uuid.UUID:
    sid = uuid.uuid4()
    session.add(
        DataSource(
            id=sid,
            name="s",
            original_filename="s.csv",
            stored_path=f"sources/{sid}.csv",
            size_bytes=1,
            sha256="0" * 64,
            csv_options={},
            columns=[{"name": n, "inferred_type": "string", "null_count": 0} for n in names],
            row_count=1,
        )
    )
    session.commit()
    return sid


def body(sid: uuid.UUID, name: str = "p1", **extra: Any) -> dict[str, Any]:
    return {"name": name, "source_id": str(sid), "config": copy.deepcopy(MINIMAL), **extra}


def error(resp: Any, status: int, code: str) -> dict[str, Any]:
    assert resp.status_code == status, resp.text
    err: dict[str, Any] = resp.json()["error"]
    assert err["code"] == code
    return err


def add_run(session: Session, pid: uuid.UUID, status: RunStatus, queued: datetime) -> uuid.UUID:
    run = Run(
        pipeline_id=pid,
        pipeline_name="p1",
        config_snapshot={},
        config_version=1,
        status=status,
        queued_at=queued,
        finished_at=queued if status in (RunStatus.succeeded, RunStatus.failed) else None,
    )
    session.add(run)
    session.commit()
    return run.id


def bad_config(sid: uuid.UUID, **override: Any) -> dict[str, Any]:
    payload = body(sid)
    payload["config"]["columns"] = [
        {"source": "id", "name": "id", "type": "integer"},
        {"source": "name", "name": "name", "type": "string"},
    ]
    payload["config"]["transformations"] = [
        {"op": "trim_whitespace", "columns": ["name"]},
        {"op": "trim_whitespace", "columns": ["id"]},  # id is an integer column
    ]
    payload.update(override)
    return payload


# --- create ---------------------------------------------------------------------------------


def test_create_returns_pipeline(api_client: TestClient, source_id: uuid.UUID) -> None:
    resp = api_client.post(BASE, json=body(source_id, description="d"))
    assert resp.status_code == 201, resp.text
    out = resp.json()
    assert set(out) == {
        "id", "name", "description", "source_id", "config", "config_version", "created_at",
        "updated_at", "last_run",
    }  # fmt: skip
    assert (out["name"], out["description"], out["config_version"]) == ("p1", "d", 1)
    assert out["source_id"] == str(source_id)
    assert out["config"] == MINIMAL
    assert out["last_run"] is None
    assert out["created_at"].endswith("Z")
    assert api_client.get(f"{BASE}/{out['id']}").json() == out


def test_create_description_defaults_to_null(api_client: TestClient, source_id: uuid.UUID) -> None:
    assert api_client.post(BASE, json=body(source_id)).json()["description"] is None


def test_every_valid_example_config_is_accepted(
    api_client: TestClient, api_session: Session
) -> None:
    for i, path in enumerate(sorted((EXAMPLES / "valid").glob("*.json"))):
        config = json.loads(path.read_text())
        sid = add_source(api_session, [c["source"] for c in config["columns"]])
        resp = api_client.post(
            BASE, json={"name": f"ex{i}", "source_id": str(sid), "config": config}
        )
        assert resp.status_code == 201, (path.name, resp.text)
        assert resp.json()["config"] == config


def test_unknown_source_is_404(api_client: TestClient) -> None:
    error(api_client.post(BASE, json=body(uuid.uuid4())), 404, "not_found")


def test_duplicate_name_is_409(api_client: TestClient, source_id: uuid.UUID) -> None:
    assert api_client.post(BASE, json=body(source_id)).status_code == 201
    err = error(api_client.post(BASE, json=body(source_id)), 409, "conflict")
    assert err["details"][0]["path"] == "/name"


@pytest.mark.parametrize(
    ("patch", "path"),
    [
        ({"name": ""}, "/name"),
        ({"name": "n" * 201}, "/name"),
        ({"description": "d" * 2001}, "/description"),
        ({"source_id": "nope"}, "/source_id"),
        ({"config": "x"}, "/config"),
        ({"extra": 1}, "/extra"),
    ],
)
def test_create_request_shape_errors(
    api_client: TestClient, source_id: uuid.UUID, patch: dict[str, Any], path: str
) -> None:
    err = error(api_client.post(BASE, json=body(source_id, **patch)), 422, "validation_error")
    assert path in [d["path"] for d in err["details"]]


@pytest.mark.parametrize("missing", ["name", "source_id", "config"])
def test_create_requires_fields(api_client: TestClient, source_id: uuid.UUID, missing: str) -> None:
    payload = body(source_id)
    del payload[missing]
    err = error(api_client.post(BASE, json=payload), 422, "validation_error")
    assert err["details"][0]["path"] == f"/{missing}"


def test_invalid_config_paths_are_prefixed_with_config(
    api_client: TestClient, api_session: Session, source_id: uuid.UUID
) -> None:
    err = error(api_client.post(BASE, json=bad_config(source_id)), 422, "validation_error")
    paths = [d["path"] for d in err["details"]]
    assert "/config/transformations/1/columns" in paths or any(
        p.startswith("/config/transformations/1") for p in paths
    ), paths
    assert all(p.startswith("/config") for p in paths)
    assert api_session.scalar(sa.select(sa.func.count()).select_from(Pipeline)) == 0


@pytest.mark.parametrize("name", sorted(p.name for p in (EXAMPLES / "invalid").glob("*.json")))
def test_invalid_examples_are_rejected_with_config_paths(
    api_client: TestClient, source_id: uuid.UUID, name: str
) -> None:
    config = json.loads((EXAMPLES / "invalid" / name).read_text())
    payload = {"name": "x", "source_id": str(source_id), "config": config}
    err = error(api_client.post(BASE, json=payload), 422, "validation_error")
    assert err["details"]
    assert all(d["path"].startswith("/config") for d in err["details"])


def test_config_referencing_missing_source_column_is_422(
    api_client: TestClient, source_id: uuid.UUID
) -> None:
    payload = body(source_id)
    payload["config"]["columns"][0]["source"] = "no_such_column"
    err = error(api_client.post(BASE, json=payload), 422, "validation_error")
    assert err["details"][0]["path"] == "/config/columns/0/source"


# --- validate ---------------------------------------------------------------------------------


def test_validate_valid_config(api_client: TestClient, source_id: uuid.UUID) -> None:
    resp = api_client.post(
        f"{BASE}/validate", json={"config": MINIMAL, "source_id": str(source_id)}
    )
    assert resp.status_code == 200
    assert resp.json() == {"valid": True, "errors": []}


def test_validate_without_source_skips_column_check(api_client: TestClient) -> None:
    resp = api_client.post(f"{BASE}/validate", json={"config": MINIMAL})
    assert resp.json() == {"valid": True, "errors": []}


def test_validate_invalid_config_is_200_with_prefixed_paths(
    api_client: TestClient, source_id: uuid.UUID
) -> None:
    cfg = bad_config(source_id)["config"]
    resp = api_client.post(f"{BASE}/validate", json={"config": cfg, "source_id": str(source_id)})
    assert resp.status_code == 200
    out = resp.json()
    assert out["valid"] is False
    assert out["errors"]
    assert all(e["path"].startswith("/config/") and e["message"] for e in out["errors"])
    assert any(e["path"].startswith("/config/transformations/1") for e in out["errors"])


def test_validate_reports_source_column_mismatch(
    api_client: TestClient, api_session: Session
) -> None:
    sid = add_source(api_session, ["other"])
    out = api_client.post(
        f"{BASE}/validate", json={"config": MINIMAL, "source_id": str(sid)}
    ).json()
    assert out["valid"] is False
    assert out["errors"][0]["path"] == "/config/columns/0/source"


def test_validate_schema_error_at_config_root_uses_config_pointer(
    api_client: TestClient,
) -> None:
    out = api_client.post(f"{BASE}/validate", json={"config": {}}).json()
    assert out["valid"] is False
    assert all(e["path"].startswith("/config") for e in out["errors"])


def test_validate_unknown_source_is_404(api_client: TestClient) -> None:
    error(
        api_client.post(
            f"{BASE}/validate", json={"config": MINIMAL, "source_id": str(uuid.uuid4())}
        ),
        404,
        "not_found",
    )


def test_validate_non_object_config_is_422(api_client: TestClient) -> None:
    err = error(api_client.post(f"{BASE}/validate", json={"config": []}), 422, "validation_error")
    assert err["details"][0]["path"] == "/config"


def test_validate_saves_nothing(
    api_client: TestClient, api_session: Session, source_id: uuid.UUID
) -> None:
    api_client.post(f"{BASE}/validate", json={"config": MINIMAL, "source_id": str(source_id)})
    assert api_session.scalar(sa.select(sa.func.count()).select_from(Pipeline)) == 0


# --- get / list ---------------------------------------------------------------------------------


def test_get_unknown_and_bad_uuid(api_client: TestClient) -> None:
    error(api_client.get(f"{BASE}/{uuid.uuid4()}"), 404, "not_found")
    err = error(api_client.get(f"{BASE}/nope"), 422, "validation_error")
    assert err["details"][0]["path"] == "/pipeline_id"


def test_list_orders_by_updated_desc_and_paginates(
    api_client: TestClient, source_id: uuid.UUID
) -> None:
    ids = [api_client.post(BASE, json=body(source_id, f"p{i}")).json()["id"] for i in range(4)]
    # touching the oldest moves it to the front
    api_client.put(f"{BASE}/{ids[0]}", json=body(source_id, "p0", description="touched"))
    page = api_client.get(BASE, params={"limit": 2, "offset": 0}).json()
    assert (page["total"], page["limit"], page["offset"]) == (4, 2, 0)
    assert [i["id"] for i in page["items"]] == [ids[0], ids[3]]
    rest = api_client.get(BASE, params={"limit": 2, "offset": 2}).json()
    assert [i["id"] for i in rest["items"]] == [ids[2], ids[1]]


def test_list_defaults_and_bad_params(api_client: TestClient) -> None:
    assert api_client.get(BASE).json() == {"total": 0, "limit": 50, "offset": 0, "items": []}
    for params, path in [({"limit": 0}, "/limit"), ({"limit": 201}, "/limit"),
                         ({"offset": -1}, "/offset")]:  # fmt: skip
        err = error(api_client.get(BASE, params=params), 422, "validation_error")
        assert err["details"][0]["path"] == path


def test_last_run_is_the_most_recently_queued(
    api_client: TestClient, api_session: Session, source_id: uuid.UUID
) -> None:
    pid = api_client.post(BASE, json=body(source_id)).json()["id"]
    other = api_client.post(BASE, json=body(source_id, "p2")).json()["id"]
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    old = add_run(api_session, uuid.UUID(pid), RunStatus.succeeded, t0)
    new = add_run(api_session, uuid.UUID(pid), RunStatus.failed, t0.replace(day=2))
    expected = {
        "id": str(new),
        "status": "failed",
        "queued_at": "2026-01-02T00:00:00Z",
        "finished_at": "2026-01-02T00:00:00Z",
    }
    assert str(old) != str(new)
    assert api_client.get(f"{BASE}/{pid}").json()["last_run"] == expected
    items = {i["id"]: i for i in api_client.get(BASE).json()["items"]}
    assert items[pid]["last_run"] == expected
    assert items[other]["last_run"] is None


def test_last_run_of_unfinished_run_has_null_finished_at(
    api_client: TestClient, api_session: Session, source_id: uuid.UUID
) -> None:
    pid = api_client.post(BASE, json=body(source_id)).json()["id"]
    add_run(api_session, uuid.UUID(pid), RunStatus.queued, datetime(2026, 1, 1, tzinfo=UTC))
    last = api_client.get(f"{BASE}/{pid}").json()["last_run"]
    assert (last["status"], last["finished_at"]) == ("queued", None)


# --- update -------------------------------------------------------------------------------------


def test_put_replaces_fields_and_increments_config_version(
    api_client: TestClient, api_session: Session, source_id: uuid.UUID
) -> None:
    created = api_client.post(BASE, json=body(source_id)).json()
    other_source = add_source(api_session, ["a"])
    payload = body(other_source, "renamed", description="new")
    payload["config"]["columns"][0].update(source="a", name="a")
    resp = api_client.put(f"{BASE}/{created['id']}", json=payload)
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert (out["name"], out["description"], out["config_version"]) == ("renamed", "new", 2)
    assert out["source_id"] == str(other_source)
    assert out["config"]["columns"][0]["name"] == "a"
    assert out["created_at"] == created["created_at"]
    assert out["updated_at"] >= created["updated_at"]
    again = api_client.put(f"{BASE}/{created['id']}", json=payload).json()
    assert again["config_version"] == 3


def test_put_allows_keeping_own_name(api_client: TestClient, source_id: uuid.UUID) -> None:
    pid = api_client.post(BASE, json=body(source_id)).json()["id"]
    assert api_client.put(f"{BASE}/{pid}", json=body(source_id)).status_code == 200


def test_put_duplicate_name_is_409(api_client: TestClient, source_id: uuid.UUID) -> None:
    api_client.post(BASE, json=body(source_id, "a"))
    pid = api_client.post(BASE, json=body(source_id, "b")).json()["id"]
    error(api_client.put(f"{BASE}/{pid}", json=body(source_id, "a")), 409, "conflict")


def test_put_unknown_pipeline_and_source_are_404(
    api_client: TestClient, source_id: uuid.UUID
) -> None:
    error(api_client.put(f"{BASE}/{uuid.uuid4()}", json=body(source_id)), 404, "not_found")
    pid = api_client.post(BASE, json=body(source_id)).json()["id"]
    error(api_client.put(f"{BASE}/{pid}", json=body(uuid.uuid4())), 404, "not_found")


def test_put_invalid_config_is_422_with_prefix_and_changes_nothing(
    api_client: TestClient, source_id: uuid.UUID
) -> None:
    created = api_client.post(BASE, json=body(source_id)).json()
    err = error(
        api_client.put(f"{BASE}/{created['id']}", json=bad_config(source_id)),
        422,
        "validation_error",
    )
    assert all(d["path"].startswith("/config/") for d in err["details"])
    assert api_client.get(f"{BASE}/{created['id']}").json() == created


# --- delete -------------------------------------------------------------------------------------


def test_delete_keeps_run_history(
    api_client: TestClient, api_session: Session, source_id: uuid.UUID
) -> None:
    pid = uuid.UUID(api_client.post(BASE, json=body(source_id)).json()["id"])
    rid = add_run(api_session, pid, RunStatus.succeeded, datetime(2026, 1, 1, tzinfo=UTC))
    resp = api_client.delete(f"{BASE}/{pid}")
    assert resp.status_code == 204 and resp.content == b""
    error(api_client.get(f"{BASE}/{pid}"), 404, "not_found")
    api_session.expire_all()
    run = api_session.get(Run, rid)
    assert run is not None and run.pipeline_id is None and run.pipeline_name == "p1"
    error(api_client.delete(f"{BASE}/{pid}"), 404, "not_found")


@pytest.mark.parametrize("status", [RunStatus.queued, RunStatus.running])
def test_delete_with_active_run_is_409(
    api_client: TestClient, api_session: Session, source_id: uuid.UUID, status: RunStatus
) -> None:
    pid = uuid.UUID(api_client.post(BASE, json=body(source_id)).json()["id"])
    add_run(api_session, pid, status, datetime(2026, 1, 1, tzinfo=UTC))
    error(api_client.delete(f"{BASE}/{pid}"), 409, "conflict")
    assert api_client.get(f"{BASE}/{pid}").status_code == 200


def test_source_with_pipeline_cannot_be_deleted_until_pipeline_is(
    api_client: TestClient, source_id: uuid.UUID
) -> None:
    pid = api_client.post(BASE, json=body(source_id)).json()["id"]
    error(api_client.delete(f"/api/v1/sources/{source_id}"), 409, "conflict")
    api_client.delete(f"{BASE}/{pid}")
    assert api_client.delete(f"/api/v1/sources/{source_id}").status_code == 204


def test_served_openapi_has_pipeline_operations(api_client: TestClient) -> None:
    spec = api_client.get("/openapi.json").json()
    ops = {
        op["operationId"]
        for path, item in spec["paths"].items()
        if path.startswith("/api/v1/pipelines") and not path.endswith("/runs")
        for op in item.values()
    }
    assert ops == {
        "createPipeline", "listPipelines", "validatePipelineConfig", "getPipeline",
        "updatePipeline", "deletePipeline",
    }  # fmt: skip
