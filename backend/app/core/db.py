"""SQLAlchemy engine and session access (lazy: importing never connects)."""

from collections.abc import Iterator
from functools import lru_cache

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.settings import get_settings


def make_engine(url: str) -> sa.Engine:
    return sa.create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 3})


@lru_cache
def get_engine() -> sa.Engine:
    return make_engine(get_settings().database_url)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    with Session(get_engine()) as session:
        yield session
