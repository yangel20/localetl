"""Throwaway migrated database per test module (own DB; never touches localetl_test tables)."""

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

BACKEND_DIR = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def engine(test_database_url: str) -> Iterator[sa.Engine]:
    base = sa.engine.make_url(test_database_url)
    name = f"localetl_wk_{uuid.uuid4().hex[:12]}"
    admin = sa.create_engine(base, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    url = base.set(database=name).render_as_string(hide_password=False)
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(cfg, "head")
    eng = sa.create_engine(url, pool_size=10)
    try:
        yield eng
    finally:
        eng.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def clean_runs(engine: sa.Engine) -> Iterator[None]:
    with engine.begin() as conn:
        conn.execute(sa.text("DELETE FROM datasets"))
        conn.execute(sa.text("DELETE FROM runs"))
        conn.execute(sa.text("DELETE FROM data_sources"))
    yield


def insert_run(
    engine: sa.Engine, status: str = "queued", heartbeat_age_s: float | None = None
) -> uuid.UUID:
    rid = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                """INSERT INTO runs (id, pipeline_name, config_snapshot, config_version, status,
                       queued_at, heartbeat_at)
                   VALUES (:id, 'p', '{}'::jsonb, 1, :st, now() - make_interval(secs => :q),
                       CASE WHEN CAST(:age AS float) IS NULL THEN NULL
                            ELSE now() - make_interval(secs => CAST(:age AS float)) END)"""
            ),
            {"id": rid, "st": status, "age": heartbeat_age_s, "q": 0},
        )
    return rid


def get_run(engine: sa.Engine, rid: uuid.UUID) -> sa.Row[tuple[object, ...]]:
    with engine.connect() as conn:
        row = conn.execute(sa.text("SELECT * FROM runs WHERE id=:id"), {"id": rid}).one()
    return row
