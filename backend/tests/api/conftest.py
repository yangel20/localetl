"""Fixtures for API tests that need their own migrated throwaway database and data dir."""

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.core.settings import Settings, get_settings
from app.main import create_app

BACKEND_DIR = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="package")
def api_db_engine(test_database_url: str) -> Iterator[sa.Engine]:
    """A migrated scratch database, so API tests never share `localetl_test` state."""
    base = sa.engine.make_url(test_database_url)
    name = f"localetl_api_{uuid.uuid4().hex[:12]}"
    admin = sa.create_engine(base, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    url = base.set(database=name).render_as_string(hide_password=False)
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(cfg, "head")
    engine = sa.create_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    path = tmp_path / "data"
    path.mkdir()
    return path


@pytest.fixture
def settings(data_dir: Path) -> Settings:
    return Settings(localetl_data_dir=data_dir, localetl_max_upload_mb=1)


@pytest.fixture
def api_session(api_db_engine: sa.Engine) -> Iterator[Session]:
    """Session for arranging/inspecting rows; tables are emptied before each test."""
    with api_db_engine.begin() as conn:
        conn.execute(sa.text("TRUNCATE pipelines, data_sources CASCADE"))
    with Session(api_db_engine) as sess:
        yield sess


@pytest.fixture
def api_client(
    api_db_engine: sa.Engine, api_session: Session, settings: Settings
) -> Iterator[TestClient]:
    def _session() -> Iterator[Session]:
        with Session(api_db_engine) as sess:
            yield sess

    app = create_app()
    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
