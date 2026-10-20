"""BE-06: /datasets endpoints. Physical tables live in the scratch DB's `datasets` schema."""

import math
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Dataset, DataSource, Pipeline, Run, RunStatus

BASE = "/api/v1/datasets"
COLUMNS = [
    {"name": "id", "type": "integer"},
    {"name": "name", "type": "string"},
    {"name": "amount", "type": "float"},
    {"name": "day", "type": "date"},
    {"name": "ts", "type": "datetime"},
    {"name": "flag", "type": "boolean"},
]
ROWS = [
    (1, "b", 2.5, "2026-01-03", "2026-01-03 10:00:00", True),
    (2, "a", None, "2026-01-01", "2026-01-01 08:30:00", False),
    (3, "b", 7.0, None, None, True),
    (4, None, float("nan"), "2026-01-02", "2026-01-02 00:00:01", None),
    (5, "c", 2.5, "2026-01-01", "2026-01-01 08:30:00", True),
]


@pytest.fixture
def tables(api_db_engine: sa.Engine) -> Iterator[list[str]]:
    created: list[str] = []
    yield created
    with api_db_engine.begin() as conn:
        for name in created:
            conn.execute(sa.text(f'DROP TABLE IF EXISTS datasets."{name}"'))


def make_dataset(
    session: Session,
    engine: sa.Engine,
    tables: list[str],
    rows: list[tuple[Any, ...]] = ROWS,
    columns: list[dict[str, str]] = COLUMNS,
    published_at: datetime | None = None,
) -> Dataset:
    name = f"ds_{uuid.uuid4().hex[:10]}"
    tables.append(name)
    run_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                f'CREATE TABLE datasets."{name}" (id bigint, name text, amount double precision,'
                " day date, ts timestamp, flag boolean, _localetl_run_id uuid not null,"
                " _localetl_row_number bigint not null)"
            )
        )
        for n, r in enumerate(rows, start=1):
            conn.execute(
                sa.text(f'INSERT INTO datasets."{name}" VALUES (:a,:b,:c,:d,:e,:f,:run,:n)'),
                {
                    "a": r[0],
                    "b": r[1],
                    "c": r[2],
                    "d": r[3],
                    "e": r[4],
                    "f": r[5],
                    "run": run_id,
                    "n": n,
                },
            )
    sid = uuid.uuid4()
    session.add(
        DataSource(
            id=sid,
            name="s",
            original_filename="s.csv",
            stored_path="x",
            size_bytes=1,
            sha256="0" * 64,
            csv_options={},
            columns=[],
            row_count=0,
        )
    )
    session.flush()
    pipeline = Pipeline(name=f"p_{name}", source_id=sid, config={})
    session.add(pipeline)
    session.flush()
    session.add(
        Run(
            id=run_id,
            pipeline_id=pipeline.id,
            pipeline_name=pipeline.name,
            config_snapshot={},
            config_version=1,
            status=RunStatus.succeeded,
        )
    )
    session.flush()
    ds = Dataset(
        table_name=name,
        pipeline_id=pipeline.id,
        last_run_id=run_id,
        row_count=len(rows),
        columns=columns,
        published_at=published_at or datetime.now(UTC),
    )
    session.add(ds)
    session.commit()
    return ds


@pytest.fixture
def ds(api_session: Session, api_db_engine: sa.Engine, tables: list[str]) -> Dataset:
    return make_dataset(api_session, api_db_engine, tables)


def error(resp: Any, status: int, code: str) -> dict[str, Any]:
    assert resp.status_code == status, resp.text
    err: dict[str, Any] = resp.json()["error"]
    assert err["code"] == code
    return err


def test_get_dataset(api_client: TestClient, ds: Dataset) -> None:
    out = api_client.get(f"{BASE}/{ds.id}").json()
    assert set(out) == {
        "id",
        "table_name",
        "pipeline_id",
        "last_run_id",
        "row_count",
        "columns",
        "published_at",
    }
    assert out["table_name"] == ds.table_name
    assert out["row_count"] == 5
    assert out["columns"] == COLUMNS
    assert out["last_run_id"] == str(ds.last_run_id)
    assert out["published_at"].endswith("Z")


def test_unknown_dataset_is_404_everywhere(api_client: TestClient) -> None:
    for suffix in ("", "/rows", "/profile"):
        error(api_client.get(f"{BASE}/{uuid.uuid4()}{suffix}"), 404, "not_found")
    err = error(api_client.get(f"{BASE}/nope"), 422, "validation_error")
    assert err["details"][0]["path"] == "/dataset_id"


def test_list_newest_first_and_paginated(
    api_client: TestClient, api_session: Session, api_db_engine: sa.Engine, tables: list[str]
) -> None:
    t = datetime(2026, 1, 1, tzinfo=UTC)
    made = [
        make_dataset(api_session, api_db_engine, tables, [], published_at=t + timedelta(days=i))
        for i in range(3)
    ]
    page = api_client.get(BASE, params={"limit": 2}).json()
    assert (page["total"], page["limit"], page["offset"]) == (3, 2, 0)
    assert [i["id"] for i in page["items"]] == [str(made[2].id), str(made[1].id)]
    rest = api_client.get(BASE, params={"limit": 2, "offset": 2}).json()
    assert [i["id"] for i in rest["items"]] == [str(made[0].id)]


@pytest.mark.parametrize(
    ("params", "path"),
    [({"limit": 0}, "/limit"), ({"limit": 201}, "/limit"), ({"offset": -1}, "/offset")],
)
def test_list_rejects_bad_params(api_client: TestClient, params: dict[str, Any], path: str) -> None:
    err = error(api_client.get(BASE, params=params), 422, "validation_error")
    assert err["details"][0]["path"] == path


def test_rows_default_order_hides_internal_columns(api_client: TestClient, ds: Dataset) -> None:
    page = api_client.get(f"{BASE}/{ds.id}/rows").json()
    assert (page["total"], page["limit"], page["offset"]) == (5, 50, 0)
    assert page["columns"] == COLUMNS
    assert [r["id"] for r in page["items"]] == [1, 2, 3, 4, 5]
    assert all(set(r) == {c["name"] for c in COLUMNS} for r in page["items"])
    assert "_localetl_run_id" not in str(page) and "_localetl_row_number" not in str(page)
    assert page["items"][0] == {
        "id": 1,
        "name": "b",
        "amount": 2.5,
        "day": "2026-01-03",
        "ts": "2026-01-03T10:00:00",
        "flag": True,
    }
    assert page["items"][1]["amount"] is None
    assert math.isfinite(1) and page["items"][3]["amount"] is None  # NaN becomes null


def test_rows_sort_order_and_stable_ties(api_client: TestClient, ds: Dataset) -> None:
    asc = api_client.get(f"{BASE}/{ds.id}/rows", params={"sort": "name"}).json()["items"]
    assert [r["id"] for r in asc] == [2, 1, 3, 5, 4]  # a, b, b (row order), c, NULL last
    desc = api_client.get(f"{BASE}/{ds.id}/rows", params={"sort": "name", "order": "desc"})
    assert [r["id"] for r in desc.json()["items"]] == [4, 5, 1, 3, 2]
    rev = api_client.get(f"{BASE}/{ds.id}/rows", params={"order": "desc"}).json()["items"]
    assert [r["id"] for r in rev] == [5, 4, 3, 2, 1]


def test_rows_pagination(api_client: TestClient, ds: Dataset) -> None:
    page = api_client.get(f"{BASE}/{ds.id}/rows", params={"limit": 2, "offset": 3}).json()
    assert (page["total"], page["limit"], page["offset"]) == (5, 2, 3)
    assert [r["id"] for r in page["items"]] == [4, 5]


@pytest.mark.parametrize(
    "sort",
    ["nope", "_localetl_row_number", "_localetl_run_id", 'id"; DROP TABLE x; --', "ID", ""],
)
def test_rows_sort_must_be_a_registry_column(
    api_client: TestClient, ds: Dataset, sort: str
) -> None:
    err = error(
        api_client.get(f"{BASE}/{ds.id}/rows", params={"sort": sort}), 422, "validation_error"
    )
    assert err["details"][0]["path"] == "/sort"


def test_rows_bad_params(api_client: TestClient, ds: Dataset) -> None:
    for params, path in [
        ({"order": "up"}, "/order"),
        ({"limit": 0}, "/limit"),
        ({"offset": -1}, "/offset"),
    ]:
        err = error(api_client.get(f"{BASE}/{ds.id}/rows", params=params), 422, "validation_error")
        assert err["details"][0]["path"] == path


def test_rows_empty_dataset(
    api_client: TestClient, api_session: Session, api_db_engine: sa.Engine, tables: list[str]
) -> None:
    empty = make_dataset(api_session, api_db_engine, tables, [])
    page = api_client.get(f"{BASE}/{empty.id}/rows").json()
    assert (page["total"], page["items"]) == (0, [])


def test_missing_physical_table_is_500_not_a_leak(
    api_client: TestClient, ds: Dataset, api_db_engine: sa.Engine
) -> None:
    with api_db_engine.begin() as conn:
        conn.execute(sa.text(f'DROP TABLE datasets."{ds.table_name}"'))
    for suffix in ("/rows", "/profile"):
        error(api_client.get(f"{BASE}/{ds.id}{suffix}"), 500, "internal_error")


def test_registry_with_hostile_identifier_is_refused(
    api_client: TestClient, api_session: Session, ds: Dataset
) -> None:
    ds.columns = [{"name": 'id" FROM x; --', "type": "integer"}]
    api_session.commit()
    error(api_client.get(f"{BASE}/{ds.id}/rows"), 500, "internal_error")


def test_profile(api_client: TestClient, ds: Dataset) -> None:
    prof = api_client.get(f"{BASE}/{ds.id}/profile").json()
    assert set(prof) == {"dataset_id", "row_count", "columns"}
    assert (prof["dataset_id"], prof["row_count"]) == (str(ds.id), 5)
    cols = {c["name"]: c for c in prof["columns"]}
    assert list(cols) == [c["name"] for c in COLUMNS]
    assert set(cols["id"]) == {
        "name",
        "type",
        "null_count",
        "distinct_count",
        "min",
        "max",
        "top_values",
    }

    assert (cols["id"]["min"], cols["id"]["max"], cols["id"]["distinct_count"]) == (1, 5, 5)
    assert (cols["name"]["null_count"], cols["name"]["distinct_count"]) == (1, 3)
    assert (cols["name"]["min"], cols["name"]["max"]) == (None, None)
    assert cols["name"]["top_values"] == [
        {"value": "b", "count": 2},
        {"value": "a", "count": 1},
        {"value": "c", "count": 1},
    ]
    assert cols["amount"]["null_count"] == 1
    assert cols["amount"]["min"] == 2.5
    assert cols["day"]["min"] == "2026-01-01" and cols["day"]["max"] == "2026-01-03"
    assert cols["day"]["top_values"][0] == {"value": "2026-01-01", "count": 2}
    assert cols["ts"]["max"] == "2026-01-03T10:00:00"
    assert (cols["flag"]["min"], cols["flag"]["max"]) == (None, None)
    assert cols["flag"]["top_values"] == [{"value": True, "count": 3}, {"value": False, "count": 1}]


def test_profile_top_values_capped_at_ten(
    api_client: TestClient, api_session: Session, api_db_engine: sa.Engine, tables: list[str]
) -> None:
    rows = [(i, f"v{i:02}", None, None, None, None) for i in range(15)]
    many = make_dataset(api_session, api_db_engine, tables, rows)
    cols = {c["name"]: c for c in api_client.get(f"{BASE}/{many.id}/profile").json()["columns"]}
    assert len(cols["name"]["top_values"]) == 10
    assert cols["name"]["distinct_count"] == 15
    assert cols["name"]["top_values"][0] == {"value": "v00", "count": 1}


def test_profile_of_empty_dataset(
    api_client: TestClient, api_session: Session, api_db_engine: sa.Engine, tables: list[str]
) -> None:
    empty = make_dataset(api_session, api_db_engine, tables, [])
    prof = api_client.get(f"{BASE}/{empty.id}/profile").json()
    assert prof["row_count"] == 0
    first = prof["columns"][0]
    assert (first["null_count"], first["distinct_count"], first["min"], first["top_values"]) == (
        0,
        0,
        None,
        [],
    )
