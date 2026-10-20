"""Load and publish stages (docs/architecture.md section 5 stages 4-5, section 7.3).

The engine writes only to the ``staging`` and ``datasets`` schemas. Input is
*already typed* (Python ``int``, ``float``, ``bool``, ``date``, naive
``datetime``, ``str`` or null); nothing here casts.

Per run (used by ``run_pipeline``, ETL-07)::

    loader = Loader(engine, run_id, columns)      # columns: [(name, ColumnType), ...]
    loader.create()                               # staging.run_<hex>
    try:
        for typed_chunk, row_numbers in chunks:
            loader.load_chunk(typed_chunk, row_numbers)   # returns rows written
        outcome = loader.publish(table="orders", mode="replace")
    finally:
        loader.drop()                             # idempotent; no-op after a publish

``publish`` runs in one transaction. On any failure the published table is
unchanged and the staging table is dropped. Identifiers are validated against
``^[a-z_][a-z0-9_]{0,62}$`` and always quoted; values are always bound.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

import pandas as pd
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import DOUBLE_PRECISION

from .errors import LoadError
from .types import ColumnType, PublishedTable

STAGING_SCHEMA = "staging"
DATASETS_SCHEMA = "datasets"
RUN_ID_COLUMN = "_localetl_run_id"
ROW_NUMBER_COLUMN = "_localetl_row_number"
RESERVED_PREFIX = "_localetl_"

_IDENTIFIER_RE = re.compile(r"[a-z_][a-z0-9_]{0,62}")

_SQL_TYPES: dict[str, Any] = {
    "integer": sa.BigInteger(),
    "float": DOUBLE_PRECISION(),
    "boolean": sa.Boolean(),
    "date": sa.Date(),
    "datetime": sa.DateTime(timezone=False),
    "string": sa.Text(),
}


@dataclass(frozen=True)
class PublishOutcome:
    published: PublishedTable
    loaded_rows: int  # rows this run's publish transaction added (append: not the table total)


def staging_table_name(run_id: UUID) -> str:
    return f"run_{run_id.hex}"


def _check_identifier(name: str, what: str) -> str:
    if not isinstance(name, str) or not _IDENTIFIER_RE.fullmatch(name):
        raise LoadError(f"invalid {what} identifier: {name!r}")
    return name


def _normalise(value: Any, column: str, ctype: str) -> Any:
    """Typed cell -> value to bind: nulls to None, numpy/pandas scalars to Python."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    elif hasattr(value, "item") and not isinstance(value, (str, bytes, date)):
        value = value.item()
    if isinstance(value, datetime) and value.tzinfo is not None:
        # Binding an aware datetime to a naive `timestamp` column converts it
        # silently using the session time zone. Whether to reject, convert or
        # strip is a casting decision (Q6-3), so refuse rather than guess.
        raise LoadError(
            f"column '{column}': timezone-aware datetime is not supported (pending casting spec)"
        )
    return value


class Loader:
    """Writes one run's typed chunks to ``staging.run_<hex>`` and publishes them."""

    def __init__(
        self, engine: sa.Engine, run_id: UUID, columns: Sequence[tuple[str, ColumnType]]
    ) -> None:
        if not columns:
            raise LoadError("at least one column is required")
        seen: set[str] = set()
        for name, ctype in columns:
            _check_identifier(name, "column")
            if name.startswith(RESERVED_PREFIX):
                raise LoadError(
                    f"column name '{name}' uses the reserved prefix '{RESERVED_PREFIX}'"
                )
            if name in seen:
                raise LoadError(f"duplicate column name '{name}'")
            if ctype not in _SQL_TYPES:
                raise LoadError(f"unsupported column type {ctype!r}")
            seen.add(name)
        self._engine = engine
        self._run_id = run_id
        self._columns = [(n, t) for n, t in columns]
        self._staging = staging_table_name(run_id)
        self._table = self._build_table(self._staging, STAGING_SCHEMA)
        self.staged_rows = 0

    # ------------------------------------------------------------------ helpers

    def _build_table(self, name: str, schema: str) -> sa.Table:
        cols: list[sa.Column[Any]] = [sa.Column(n, _SQL_TYPES[t]) for n, t in self._columns]
        cols.append(sa.Column(RUN_ID_COLUMN, sa.Uuid(), nullable=False))
        cols.append(sa.Column(ROW_NUMBER_COLUMN, sa.BigInteger(), nullable=False))
        return sa.Table(name, sa.MetaData(), *cols, schema=schema)

    def _q(self, schema: str, name: str) -> str:
        prep = self._engine.dialect.identifier_preparer
        return f"{prep.quote_identifier(schema)}.{prep.quote_identifier(name)}"

    # ------------------------------------------------------------------- stages

    def create(self) -> None:
        """Create the (empty) staging table."""
        try:
            with self._engine.begin() as conn:
                conn.execute(
                    sa.text(f"DROP TABLE IF EXISTS {self._q(STAGING_SCHEMA, self._staging)}")
                )
                self._table.create(conn)
        except sa.exc.SQLAlchemyError as exc:
            raise LoadError(f"cannot create staging table: {_short(exc)}") from exc

    def load_chunk(self, frame: pd.DataFrame, row_numbers: Sequence[int]) -> int:
        """Append typed rows; ``row_numbers[i]`` is the 1-based data row of row ``i``."""
        if len(row_numbers) != len(frame):
            raise LoadError("row_numbers must align with the chunk rows")
        if len(frame) == 0:
            return 0
        try:
            lists = []
            for name, ctype in self._columns:
                if name not in frame.columns:
                    raise LoadError(f"column '{name}' missing from the chunk")
                lists.append([_normalise(v, name, ctype) for v in frame[name].tolist()])
            rows = [
                {
                    **{name: lists[c][i] for c, (name, _) in enumerate(self._columns)},
                    RUN_ID_COLUMN: self._run_id,
                    ROW_NUMBER_COLUMN: int(row_numbers[i]),
                }
                for i in range(len(frame))
            ]
            with self._engine.begin() as conn:
                conn.execute(sa.insert(self._table), rows)
        except LoadError:
            self.drop()
            raise
        except sa.exc.SQLAlchemyError as exc:
            self.drop()
            raise LoadError(f"cannot load chunk: {_short(exc)}") from exc
        self.staged_rows += len(rows)
        return len(rows)

    def publish(self, table: str, mode: Literal["replace", "append"]) -> PublishOutcome:
        """Publish staging as ``datasets.<table>`` in one transaction."""
        try:
            _check_identifier(table, "table")
            if table.startswith("run_"):
                raise LoadError("table names starting with 'run_' are reserved for staging")
            if mode not in ("replace", "append"):
                raise LoadError(f"unknown publish mode {mode!r}")
            with self._engine.begin() as conn:
                if mode == "replace":
                    loaded = self._publish_replace(conn, table)
                else:
                    loaded = self._publish_append(conn, table)
                count: int = conn.execute(
                    sa.text(f"SELECT count(*) FROM {self._q(DATASETS_SCHEMA, table)}")
                ).scalar_one()
        except LoadError:
            self.drop()
            raise
        except sa.exc.SQLAlchemyError as exc:
            self.drop()
            raise LoadError(f"publish failed: {_short(exc)}") from exc
        published = PublishedTable(
            schema="datasets", table=table, columns=list(self._columns), row_count=int(count)
        )
        return PublishOutcome(published=published, loaded_rows=loaded)

    def drop(self) -> None:
        """Drop the staging table if it exists. Safe to call repeatedly."""
        try:
            with self._engine.begin() as conn:
                conn.execute(
                    sa.text(f"DROP TABLE IF EXISTS {self._q(STAGING_SCHEMA, self._staging)}")
                )
        except sa.exc.SQLAlchemyError as exc:
            raise LoadError(f"cannot drop staging table: {_short(exc)}") from exc

    # ---------------------------------------------------------------- publishing

    def _publish_replace(self, conn: sa.Connection, table: str) -> int:
        staging = self._q(STAGING_SCHEMA, self._staging)
        target = self._q(DATASETS_SCHEMA, table)
        prep = self._engine.dialect.identifier_preparer
        conn.execute(sa.text(f"DROP TABLE IF EXISTS {target}"))
        conn.execute(
            sa.text(f"ALTER TABLE {staging} SET SCHEMA {prep.quote_identifier(DATASETS_SCHEMA)}")
        )
        conn.execute(
            sa.text(
                f"ALTER TABLE {self._q(DATASETS_SCHEMA, self._staging)} "
                f"RENAME TO {prep.quote_identifier(table)}"
            )
        )
        return self.staged_rows

    def _publish_append(self, conn: sa.Connection, table: str) -> int:
        staging = self._q(STAGING_SCHEMA, self._staging)
        target = self._q(DATASETS_SCHEMA, table)
        if conn.execute(sa.text("SELECT to_regclass(:name)"), {"name": target}).scalar() is None:
            conn.execute(sa.text(f"CREATE TABLE {target} (LIKE {staging})"))
        else:
            existing = _column_signature(conn, target)
            expected = _column_signature(conn, staging)
            if existing != expected:
                raise LoadError(
                    f"append schema mismatch for datasets.{table}: "
                    f"existing {existing} != incoming {expected}"
                )
        prep = self._engine.dialect.identifier_preparer
        names = ", ".join(
            prep.quote_identifier(n)
            for n in [*(n for n, _ in self._columns), RUN_ID_COLUMN, ROW_NUMBER_COLUMN]
        )
        result = conn.execute(
            sa.text(f"INSERT INTO {target} ({names}) SELECT {names} FROM {staging}")
        )
        conn.execute(sa.text(f"DROP TABLE {staging}"))
        return int(result.rowcount)


def _column_signature(conn: sa.Connection, qualified: str) -> list[tuple[str, str]]:
    rows = conn.execute(
        sa.text(
            "SELECT a.attname, format_type(a.atttypid, a.atttypmod) "
            "FROM pg_attribute a WHERE a.attrelid = to_regclass(:name) "
            "AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum"
        ),
        {"name": qualified},
    )
    return [(str(r[0]), str(r[1])) for r in rows]


def _short(exc: sa.exc.SQLAlchemyError) -> str:
    orig = getattr(exc, "orig", None)
    text = str(orig if orig is not None else exc).splitlines()[0]
    return text[:300]
