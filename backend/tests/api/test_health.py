import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.core.db import get_engine, make_engine
from app.main import create_app


@pytest.mark.db
def test_health_ok(client: TestClient) -> None:
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "database": "ok"}


def test_health_database_unavailable() -> None:
    dead: sa.Engine = make_engine("postgresql+psycopg://x:x@127.0.0.1:1/none")
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: dead
    resp = TestClient(app).get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "database": "unavailable"}
