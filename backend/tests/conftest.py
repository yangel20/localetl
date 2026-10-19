import os
from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.core.db import get_engine, make_engine
from app.core.settings import get_settings
from app.main import create_app


@pytest.fixture(scope="session")
def test_database_url() -> str:
    return os.environ.get("TEST_DATABASE_URL") or get_settings().test_database_url


@pytest.fixture(scope="session")
def db_engine(test_database_url: str) -> Iterator[sa.Engine]:
    """Engine on TEST_DATABASE_URL (never DATABASE_URL). Skips nothing silently: fails if down."""
    engine = make_engine(test_database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def client(db_engine: sa.Engine) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: db_engine
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
