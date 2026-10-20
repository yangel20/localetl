"""DB fixtures for ETL tests: a throwaway database with `staging` and `datasets` schemas.

Created on the TEST_DATABASE_URL server (never touching ``localetl_test`` itself) and
dropped WITH (FORCE) afterwards, like ``tests/models/conftest.py``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
import sqlalchemy as sa


@pytest.fixture(scope="module")
def etl_scratch_url(test_database_url: str) -> Iterator[str]:
    base = sa.engine.make_url(test_database_url)
    name = f"localetl_etl_{uuid.uuid4().hex[:12]}"
    admin = sa.create_engine(base, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    try:
        yield base.set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture(scope="module")
def etl_db(etl_scratch_url: str) -> Iterator[sa.Engine]:
    engine = sa.create_engine(etl_scratch_url)
    yield engine
    engine.dispose()


@pytest.fixture
def etl_engine(etl_db: sa.Engine) -> sa.Engine:
    """The scratch engine with freshly recreated, empty `staging` and `datasets` schemas."""
    with etl_db.begin() as conn:
        for schema in ("staging", "datasets"):
            conn.execute(sa.text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
            conn.execute(sa.text(f"CREATE SCHEMA {schema}"))
    return etl_db
