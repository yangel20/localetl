"""ETL-06: staging load and publish against a throwaway PostgreSQL database."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd
import pytest
import sqlalchemy as sa

from app.etl import LoadError
from app.etl.load import Loader, staging_table_name
from app.etl.types import ColumnType

pytestmark = pytest.mark.db

COLUMNS: list[tuple[str, ColumnType]] = [
    ("id", "integer"),
    ("score", "float"),
    ("flag", "boolean"),
    ("day", "date"),
    ("at", "datetime"),
    ("name", "string"),
]


def chunk(n: int = 3, start: int = 1) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id": pd.Series([start + i for i in range(n)], dtype=object),
            "score": pd.Series([0.5 * i for i in range(n)], dtype=object),
            "flag": pd.Series([i % 2 == 0 for i in range(n)], dtype=object),
            "day": pd.Series([date(2024, 1, 1 + i) for i in range(n)], dtype=object),
            "at": pd.Series([datetime(2024, 1, 1, 10, i) for i in range(n)], dtype=object),
            "name": pd.Series([f"n{i}" for i in range(n)], dtype=object),
        }
    )


def loaded(engine: sa.Engine, run_id: uuid.UUID, df: pd.DataFrame, start: int = 1) -> Loader:
    ld = Loader(engine, run_id, COLUMNS)
    ld.create()
    ld.load_chunk(df, list(range(start, start + len(df))))
    return ld


def tables(engine: sa.Engine, schema: str) -> list[str]:
    return sorted(sa.inspect(engine).get_table_names(schema=schema))


def rows(engine: sa.Engine, table: str, cols: str = "id") -> list[Any]:
    with engine.connect() as conn:
        return [
            tuple(r)
            for r in conn.execute(sa.text(f'SELECT {cols} FROM datasets."{table}" ORDER BY 1'))
        ]


NON_ETL_TABLES = (
    "SELECT count(*) FROM pg_tables WHERE schemaname NOT IN "
    "('pg_catalog','information_schema','staging','datasets')"
)

# ------------------------------------------------------------------- staging


def test_staging_table_name_and_types(etl_engine: sa.Engine) -> None:
    run_id = uuid.uuid4()
    ld = Loader(etl_engine, run_id, COLUMNS)
    ld.create()
    assert tables(etl_engine, "staging") == [f"run_{run_id.hex}"] == [staging_table_name(run_id)]
    with etl_engine.connect() as conn:
        got = conn.execute(
            sa.text(
                "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
                "WHERE table_schema='staging' ORDER BY ordinal_position"
            )
        ).all()
    assert [tuple(r) for r in got] == [
        ("id", "bigint", "YES"),
        ("score", "double precision", "YES"),
        ("flag", "boolean", "YES"),
        ("day", "date", "YES"),
        ("at", "timestamp without time zone", "YES"),
        ("name", "text", "YES"),
        ("_localetl_run_id", "uuid", "NO"),
        ("_localetl_row_number", "bigint", "NO"),
    ]


def test_load_chunks_accumulate_with_run_metadata(etl_engine: sa.Engine) -> None:
    run_id = uuid.uuid4()
    ld = loaded(etl_engine, run_id, chunk(3))
    assert ld.load_chunk(chunk(2, start=10), [101, 102]) == 2
    assert ld.staged_rows == 5
    with etl_engine.connect() as conn:
        got = conn.execute(
            sa.text(
                "SELECT id, _localetl_row_number, _localetl_run_id "
                f'FROM staging."{staging_table_name(run_id)}" ORDER BY 2'
            )
        ).all()
    assert [(r[0], r[1]) for r in got] == [(1, 1), (2, 2), (3, 3), (10, 101), (11, 102)]
    assert {r[2] for r in got} == {run_id}


def test_values_roundtrip_and_nulls(etl_engine: sa.Engine) -> None:
    run_id = uuid.uuid4()
    df = chunk(2)
    df.loc[1, ["id", "score", "flag", "day", "at", "name"]] = [
        None,
        float("nan"),
        None,
        pd.NaT,
        pd.NaT,
        pd.NA,
    ]
    ld = loaded(etl_engine, run_id, df)
    with etl_engine.connect() as conn:
        got = conn.execute(
            sa.text(
                "SELECT id, score, flag, day, at, name "
                f'FROM staging."{staging_table_name(run_id)}" ORDER BY _localetl_row_number'
            )
        ).all()
    assert tuple(got[0]) == (1, 0.0, True, date(2024, 1, 1), datetime(2024, 1, 1, 10, 0), "n0")
    assert tuple(got[1]) == (None,) * 6
    assert ld.staged_rows == 2


def test_numpy_and_timestamp_values_are_accepted(etl_engine: sa.Engine) -> None:
    import numpy as np

    df = pd.DataFrame(
        {
            "id": np.array([1, 2], dtype="int64"),
            "score": np.array([1.5, 2.5]),
            "flag": np.array([True, False]),
            "day": pd.Series([date(2024, 1, 1)] * 2, dtype=object),
            "at": pd.to_datetime(["2024-01-01 10:00:00", "2024-01-02 11:00:00"]),
            "name": ["a", "b"],
        }
    )
    ld = loaded(etl_engine, uuid.uuid4(), df)
    assert ld.staged_rows == 2


def test_sql_special_values_are_bound_not_interpolated(etl_engine: sa.Engine) -> None:
    run_id = uuid.uuid4()
    evil = "x'); DROP SCHEMA datasets CASCADE; --"
    df = chunk(1)
    df.loc[0, "name"] = evil
    loaded(etl_engine, run_id, df)
    with etl_engine.connect() as conn:
        assert (
            conn.execute(
                sa.text(f'SELECT name FROM staging."{staging_table_name(run_id)}"')
            ).scalar_one()
            == evil
        )
    assert "datasets" in {
        r[0]
        for r in etl_engine.connect().execute(
            sa.text("SELECT schema_name FROM information_schema.schemata")
        )
    }


def test_empty_chunk_is_a_noop(etl_engine: sa.Engine) -> None:
    ld = loaded(etl_engine, uuid.uuid4(), chunk(1))
    assert ld.load_chunk(chunk(0), []) == 0 and ld.staged_rows == 1


def test_tz_aware_datetime_refused_and_staging_dropped(etl_engine: sa.Engine) -> None:
    df = chunk(1)
    df.loc[0, "at"] = datetime(2024, 1, 1, tzinfo=timezone(timedelta(hours=2)))
    ld = Loader(etl_engine, uuid.uuid4(), COLUMNS)
    ld.create()
    with pytest.raises(LoadError, match="timezone-aware"):
        ld.load_chunk(df, [1])
    assert tables(etl_engine, "staging") == []


def test_wrong_value_type_is_load_error_and_drops_staging(etl_engine: sa.Engine) -> None:
    df = chunk(1)
    df.loc[0, "id"] = "not a number"
    ld = Loader(etl_engine, uuid.uuid4(), COLUMNS)
    ld.create()
    with pytest.raises(LoadError, match="cannot load chunk"):
        ld.load_chunk(df, [1])
    assert tables(etl_engine, "staging") == []


def test_missing_column_and_misaligned_row_numbers(etl_engine: sa.Engine) -> None:
    ld = Loader(etl_engine, uuid.uuid4(), COLUMNS)
    ld.create()
    with pytest.raises(LoadError, match="align"):
        ld.load_chunk(chunk(2), [1])
    with pytest.raises(LoadError, match="missing"):
        ld.load_chunk(chunk(2).drop(columns=["name"]), [1, 2])
    assert tables(etl_engine, "staging") == []


def test_drop_is_idempotent(etl_engine: sa.Engine) -> None:
    ld = loaded(etl_engine, uuid.uuid4(), chunk(1))
    ld.drop()
    ld.drop()
    assert tables(etl_engine, "staging") == []


def test_create_replaces_leftover_staging_of_same_run(etl_engine: sa.Engine) -> None:
    run_id = uuid.uuid4()
    loaded(etl_engine, run_id, chunk(2))
    ld = Loader(etl_engine, run_id, COLUMNS)
    ld.create()
    ld.publish("t", "replace")
    assert rows(etl_engine, "t") == []


# ------------------------------------------------------------------- replace


def test_replace_creates_table(etl_engine: sa.Engine) -> None:
    run_id = uuid.uuid4()
    ld = loaded(etl_engine, run_id, chunk(3))
    out = ld.publish("orders", "replace")
    assert out.loaded_rows == 3
    assert out.published.schema == "datasets" and out.published.table == "orders"
    assert out.published.row_count == 3 and out.published.columns == COLUMNS
    assert tables(etl_engine, "staging") == []
    assert tables(etl_engine, "datasets") == ["orders"]
    assert rows(etl_engine, "orders", "id, _localetl_row_number") == [(1, 1), (2, 2), (3, 3)]


def test_replace_overwrites_previous_table_and_schema(etl_engine: sa.Engine) -> None:
    loaded(etl_engine, uuid.uuid4(), chunk(5)).publish("orders", "replace")
    new_cols: list[tuple[str, ColumnType]] = [("other", "string")]
    ld = Loader(etl_engine, uuid.uuid4(), new_cols)
    ld.create()
    ld.load_chunk(pd.DataFrame({"other": ["x"]}), [1])
    out = ld.publish("orders", "replace")
    assert out.published.row_count == 1 and out.published.columns == new_cols
    assert rows(etl_engine, "orders", "other") == [("x",)]


def test_replace_failure_leaves_published_table_unchanged(etl_engine: sa.Engine) -> None:
    loaded(etl_engine, uuid.uuid4(), chunk(2)).publish("orders", "replace")
    with etl_engine.begin() as conn:  # a dependent view makes DROP TABLE fail
        conn.execute(sa.text("CREATE VIEW datasets.v AS SELECT id FROM datasets.orders"))
    ld = loaded(etl_engine, uuid.uuid4(), chunk(7, start=100))
    with pytest.raises(LoadError, match="publish failed"):
        ld.publish("orders", "replace")
    assert rows(etl_engine, "orders") == [(1,), (2,)]
    assert tables(etl_engine, "staging") == []
    assert tables(etl_engine, "datasets") == ["orders"]


def test_replace_is_atomic_for_concurrent_readers(etl_engine: sa.Engine) -> None:
    loaded(etl_engine, uuid.uuid4(), chunk(2)).publish("orders", "replace")
    reader = etl_engine.connect()
    reader.execute(sa.text("BEGIN"))
    assert reader.execute(sa.text("SELECT count(*) FROM datasets.orders")).scalar_one() == 2
    reader.rollback()
    reader.close()


# -------------------------------------------------------------------- append


def test_append_creates_table_when_absent(etl_engine: sa.Engine) -> None:
    out = loaded(etl_engine, uuid.uuid4(), chunk(3)).publish("log", "append")
    assert out.loaded_rows == 3 and out.published.row_count == 3
    assert tables(etl_engine, "staging") == [] and tables(etl_engine, "datasets") == ["log"]


def test_append_adds_rows_and_reports_run_rows_vs_total(etl_engine: sa.Engine) -> None:
    first = uuid.uuid4()
    loaded(etl_engine, first, chunk(3)).publish("log", "append")
    second = uuid.uuid4()
    out = loaded(etl_engine, second, chunk(2, start=10)).publish("log", "append")
    assert out.loaded_rows == 2 and out.published.row_count == 5
    assert rows(etl_engine, "log") == [(1,), (2,), (3,), (10,), (11,)]
    with etl_engine.connect() as conn:
        by_run = dict(
            conn.execute(
                sa.text("SELECT _localetl_run_id, count(*) FROM datasets.log GROUP BY 1")
            ).all()
        )
    assert by_run == {first: 3, second: 2}
    assert tables(etl_engine, "staging") == []


@pytest.mark.parametrize(
    "other",
    [
        [("id", "integer")],  # fewer columns
        [*COLUMNS[:5], ("name", "integer")],  # type differs
        [*COLUMNS[:5], ("title", "string")],  # name differs
        [COLUMNS[1], COLUMNS[0], *COLUMNS[2:]],  # order differs
    ],
)
def test_append_mismatch_raises_and_leaves_table_unchanged(
    etl_engine: sa.Engine, other: list[tuple[str, ColumnType]]
) -> None:
    loaded(etl_engine, uuid.uuid4(), chunk(2)).publish("log", "append")
    ld = Loader(etl_engine, uuid.uuid4(), other)
    ld.create()
    with pytest.raises(LoadError, match="append schema mismatch"):
        ld.publish("log", "append")
    assert rows(etl_engine, "log") == [(1,), (2,)]
    assert tables(etl_engine, "staging") == []


# --------------------------------------------------------------- identifiers

HOSTILE = [
    "Orders",
    "a-b",
    'a"b',
    "a;drop table x",
    "a b",
    "1abc",
    "",
    "x" * 64,
    "public.x",
    "datasets.x",
    "é",
    "a\x00b",
    "a'b",
]


@pytest.mark.parametrize("name", HOSTILE)
def test_hostile_table_names_rejected_before_any_sql_effect(
    etl_engine: sa.Engine, name: str
) -> None:
    ld = loaded(etl_engine, uuid.uuid4(), chunk(1))
    for mode in ("replace", "append"):
        ld2 = loaded(etl_engine, uuid.uuid4(), chunk(1))
        with pytest.raises(LoadError, match="invalid table identifier"):
            ld2.publish(name, mode)  # type: ignore[arg-type]
        assert tables(etl_engine, "staging") == [staging_table_name(ld._run_id)]
    assert tables(etl_engine, "datasets") == []


@pytest.mark.parametrize("name", HOSTILE)
def test_hostile_column_names_rejected(etl_engine: sa.Engine, name: str) -> None:
    with pytest.raises(LoadError, match="invalid column identifier"):
        Loader(etl_engine, uuid.uuid4(), [(name, "string")])
    assert tables(etl_engine, "staging") == []


def test_reserved_names(etl_engine: sa.Engine) -> None:
    with pytest.raises(LoadError, match="reserved"):
        Loader(etl_engine, uuid.uuid4(), [("_localetl_run_id", "string")])
    with pytest.raises(LoadError, match="duplicate"):
        Loader(etl_engine, uuid.uuid4(), [("a", "string"), ("a", "integer")])
    with pytest.raises(LoadError, match="at least one"):
        Loader(etl_engine, uuid.uuid4(), [])
    with pytest.raises(LoadError, match="unsupported column type"):
        Loader(etl_engine, uuid.uuid4(), [("a", "decimal")])  # type: ignore[list-item]
    ld = loaded(etl_engine, uuid.uuid4(), chunk(1))
    with pytest.raises(LoadError, match="reserved for staging"):
        ld.publish("run_abc", "replace")
    with pytest.raises(LoadError, match="unknown publish mode"):
        ld.publish("ok", "merge")  # type: ignore[arg-type]
    assert tables(etl_engine, "staging") == []


@pytest.mark.parametrize("word", ["user", "select", "order", "table", "group", "_x"])
def test_sql_reserved_words_work_as_names_because_they_are_quoted(
    etl_engine: sa.Engine, word: str
) -> None:
    ld = Loader(etl_engine, uuid.uuid4(), [(word, "integer")])
    ld.create()
    ld.load_chunk(pd.DataFrame({word: [1, 2]}), [1, 2])
    out = ld.publish(word, "replace")
    assert out.published.row_count == 2
    ld = Loader(etl_engine, uuid.uuid4(), [(word, "integer")])
    ld.create()
    ld.load_chunk(pd.DataFrame({word: [3]}), [1])
    assert ld.publish(word, "append").published.row_count == 3


# ---------------------------------------------------------------- isolation


def test_only_staging_and_datasets_are_written(etl_engine: sa.Engine) -> None:
    with etl_engine.connect() as conn:
        before = conn.execute(sa.text(NON_ETL_TABLES)).scalar_one()
    loaded(etl_engine, uuid.uuid4(), chunk(2)).publish("a", "replace")
    loaded(etl_engine, uuid.uuid4(), chunk(2)).publish("b", "append")
    with etl_engine.connect() as conn:
        after = conn.execute(sa.text(NON_ETL_TABLES)).scalar_one()
    assert before == after == 0
    assert tables(etl_engine, "datasets") == ["a", "b"]


def test_load_module_has_no_public_schema_reference() -> None:
    from pathlib import Path

    import app.etl.load as load

    src = Path(load.__file__).read_text()
    assert "public." not in src and '"public"' not in src
