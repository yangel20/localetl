"""Fixtures: a throwaway database on the TEST_DATABASE_URL server, migrated to head.

The server (not the `localetl_test` database itself) is used so that migration tests can run
`downgrade base` without touching tables other suites keep in `localetl_test`.
"""

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session

BACKEND_DIR = Path(__file__).resolve().parents[2]


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


@pytest.fixture(scope="module")
def scratch_url(test_database_url: str) -> Iterator[str]:
    base = sa.engine.make_url(test_database_url)
    name = f"localetl_mig_{uuid.uuid4().hex[:12]}"
    admin = sa.create_engine(base, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    url = base.set(database=name).render_as_string(hide_password=False)
    try:
        yield url
    finally:
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture(scope="module")
def migrated_engine(scratch_url: str) -> Iterator[sa.Engine]:
    command.upgrade(alembic_config(scratch_url), "head")
    engine = sa.create_engine(scratch_url)
    yield engine
    engine.dispose()


@pytest.fixture
def session(migrated_engine: sa.Engine) -> Iterator[Session]:
    """Session whose work is always rolled back, so tests stay independent."""
    with migrated_engine.connect() as conn:
        outer = conn.begin()
        sess = Session(bind=conn, join_transaction_mode="create_savepoint")
        try:
            yield sess
        finally:
            sess.close()
            outer.rollback()
