from collections.abc import Iterator

import pytest
from fastapi import APIRouter, FastAPI, Query
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.errors import ApiError, json_pointer
from app.main import create_app


class Body(BaseModel):
    name: str
    items: list[int]


@pytest.fixture
def client() -> Iterator[TestClient]:
    app: FastAPI = create_app()
    r = APIRouter(prefix="/api/v1")

    @r.post("/_t/body")
    def body(b: Body) -> None: ...

    @r.get("/_t/q")
    def q(limit: int = Query(1, ge=1, le=10)) -> None: ...

    @r.get("/_t/conflict")
    def conflict() -> None:
        raise ApiError(409, "conflict", "already exists", [{"path": "/name", "message": "dup"}])

    @r.get("/_t/boom")
    def boom() -> None:
        raise RuntimeError("secret detail")

    app.include_router(r)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_unknown_route_is_contract_404(client: TestClient) -> None:
    resp = client.get("/api/v1/nope")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_body_validation_uses_json_pointer(client: TestClient) -> None:
    resp = client.post("/api/v1/_t/body", json={"name": "x", "items": [1, "a"]})
    assert resp.status_code == 422
    err = resp.json()["error"]
    assert err["code"] == "validation_error"
    assert {"path": "/items/1", "message": err["details"][0]["message"]} in err["details"]
    assert "detail" not in resp.json()


def test_query_validation(client: TestClient) -> None:
    resp = client.get("/api/v1/_t/q", params={"limit": 0})
    assert resp.status_code == 422
    assert resp.json()["error"]["details"][0]["path"] == "/limit"


def test_api_error(client: TestClient) -> None:
    resp = client.get("/api/v1/_t/conflict")
    assert resp.status_code == 409
    assert resp.json() == {
        "error": {
            "code": "conflict",
            "message": "already exists",
            "details": [{"path": "/name", "message": "dup"}],
        }
    }


def test_unhandled_is_internal_error_without_leak(client: TestClient) -> None:
    resp = client.get("/api/v1/_t/boom")
    assert resp.status_code == 500
    assert resp.json() == {"error": {"code": "internal_error", "message": "Internal server error"}}


def test_json_pointer_escaping() -> None:
    assert json_pointer(("body", "a/b", "c~d", 0)) == "/a~1b/c~0d/0"
    assert json_pointer(("body",)) == "/body"


def test_method_not_allowed_keeps_allow_header() -> None:
    resp = TestClient(create_app()).delete("/api/v1/health")
    assert resp.status_code == 405
    body = resp.json()["error"]
    assert body["code"] == "method_not_allowed"
    assert "GET" in resp.headers["allow"]
