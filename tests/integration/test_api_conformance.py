"""API conformance (QA-05): live responses vs contracts/openapi.yaml, for every merged endpoint.

How coverage grows: each of the 22 contract operations has an entry in ``COVERAGE``.
* ``"covered"``: a test named ``test_op_<operationId>`` in this module exercises it through
  ``assert_conforms`` (success and declared error statuses).
* ``"pending: <ticket>"``: the endpoint is not merged yet.
``test_operation_coverage`` fails when a mounted route is not covered, when a pending route is now
mounted, or when a covered route is not mounted; it skips (naming the ticket) only for pending,
unmounted routes. A pending test never counts as a pass. Each BE merge flips its operationIds
and adds its cases here.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from referencing.exceptions import Unresolvable

if TYPE_CHECKING:  # fixtures and helpers live in conftest.py (no package: no relative import)
    from conftest import Conformance, Contract

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"

pytestmark = pytest.mark.db

COVERED = "covered"

COVERAGE: dict[str, str] = {
    "getHealth": COVERED,
    "createSource": COVERED,
    "listSources": COVERED,
    "getSource": COVERED,
    "deleteSource": COVERED,
    "previewSource": COVERED,
    "createPipeline": COVERED,
    "listPipelines": COVERED,
    "validatePipelineConfig": COVERED,
    "getPipeline": COVERED,
    "updatePipeline": COVERED,
    "deletePipeline": COVERED,
    "createRun": COVERED,
    "listRuns": COVERED,
    "getRun": COVERED,
    "listRunEvents": COVERED,
    "listRunRejections": COVERED,
    "listDatasets": COVERED,
    "getDataset": COVERED,
    "listDatasetRows": COVERED,
    "getDatasetProfile": COVERED,
    "getMetricsSummary": COVERED,
}


def _full(contract: Contract, template: str) -> str:
    return contract.prefix + template


def _mounted_operation_ids(
    app: FastAPI, contract: Contract, mounted_paths: Callable[[FastAPI], list[tuple[str, str]]]
) -> set[str]:
    """Operation ids of contract operations whose (method, path template) the app serves."""
    served = set(mounted_paths(app))
    return {
        op.operation_id
        for op in contract.operations.values()
        if (op.method, _full(contract, op.template)) in served
    }


# ------------------------------------------------------------------ the contract itself


def test_contract_has_22_operations(contract: Contract) -> None:
    assert len(contract.operations) == 22
    assert set(COVERAGE) == set(contract.operations), (
        "COVERAGE must list exactly the contract's operationIds; "
        f"missing={sorted(set(contract.operations) - set(COVERAGE))} "
        f"extra={sorted(set(COVERAGE) - set(contract.operations))}"
    )


def test_every_declared_response_schema_resolves(contract: Contract) -> None:
    """All $refs (incl. the external ones into pipeline.schema.json) resolve from the registry."""
    for op in contract.operations.values():
        checked = 0
        for status in (int(s) for s in op.responses if s.isdigit()):
            ref = contract.response_schema_ref(op, status)
            if ref is None:
                continue
            try:
                list(contract.validator(ref).iter_errors({}))
            except Unresolvable as exc:  # pragma: no cover - failure path
                pytest.fail(f"{op.operation_id} {status}: unresolvable {ref}: {exc}")
            checked += 1
        assert checked >= 1, f"{op.operation_id} declares no JSON body schema at all"


def test_referenced_error_responses_resolve_to_the_error_schema(contract: Contract) -> None:
    """Regression: a response that is itself a ``$ref`` (NotFound, Conflict...) must still be
    validated against ``Error``, not silently treated as having no body."""
    for op_id, status in [("getSource", 404), ("deleteSource", 409), ("createSource", 413)]:
        ref = contract.response_schema_ref(contract.operations[op_id], status)
        assert ref is not None and ref.endswith("#/components/schemas/Error"), (op_id, status, ref)


@pytest.mark.parametrize(
    ("name", "valid"),
    [(p.name, True) for p in sorted((CONTRACTS / "examples/pipeline/valid").glob("*.json"))]
    + [(p.name, False) for p in sorted((CONTRACTS / "examples/pipeline/invalid").glob("*.json"))],
)
def test_external_pipeline_schema_ref_is_enforced(
    contract: Contract, name: str, valid: bool
) -> None:
    """``PipelineConfig`` in openapi.yaml refs pipeline.schema.json: examples behave as labelled."""
    folder = "valid" if valid else "invalid"
    document = json.loads((CONTRACTS / "examples/pipeline" / folder / name).read_text("utf-8"))
    ref = "https://localetl.local/contracts/openapi.yaml#/components/schemas/PipelineConfig"
    errors = list(contract.validator(ref).iter_errors(document))
    assert (not errors) is valid, [e.message for e in errors][:3]


# ----------------------------------------------------- the checker catches non-conformance


def _fake(
    method: str, path: str, status: int, body: object | None, **headers: str
) -> httpx.Response:
    request = httpx.Request(method, f"http://testserver{path}")
    if body is None:
        return httpx.Response(status, request=request, headers=headers)
    return httpx.Response(status, json=body, request=request, headers=headers)


def test_checker_accepts_a_conforming_response(
    conformance: Conformance, contract: Contract
) -> None:
    ok = _fake("GET", f"{contract.prefix}/health", 200, {"status": "ok", "database": "ok"})
    assert conformance.assert_conforms(ok).operation_id == "getHealth"


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (200, {"status": "ok", "database": "maybe"}),  # enum violation
        (200, {"status": "ok"}),  # missing property
        (200, {"status": 1, "database": "ok"}),  # wrong type
        (201, {"status": "ok", "database": "ok"}),  # undeclared status
        (404, {"error": {"code": "not_found", "message": "x"}}),  # status not declared for health
    ],
)
def test_checker_rejects_non_conforming_responses(
    conformance: Conformance, contract: Contract, status: int, body: object
) -> None:
    with pytest.raises(AssertionError):
        conformance.assert_conforms(_fake("GET", f"{contract.prefix}/health", status, body))


@pytest.mark.parametrize(
    "body",
    [
        {"error": {"code": "teapot", "message": "x"}},  # code not in the enum
        {"error": {"message": "x"}},  # code missing
        {"message": "x"},  # no error envelope
    ],
)
def test_checker_rejects_malformed_error_bodies(conformance: Conformance, body: object) -> None:
    with pytest.raises(AssertionError):
        conformance.assert_error_body(_fake("GET", "/x", 404, body), 404)


# --------------------------------------------------------------------------- coverage table


@pytest.mark.parametrize("operation_id", sorted(COVERAGE))
def test_operation_coverage(
    operation_id: str,
    app_under_test: FastAPI,
    contract: Contract,
    mounted_paths: Callable[[FastAPI], list[tuple[str, str]]],
) -> None:
    mounted = operation_id in _mounted_operation_ids(app_under_test, contract, mounted_paths)
    entry = COVERAGE[operation_id]
    if entry == COVERED:
        assert mounted, f"{operation_id} is marked covered but the app does not serve it"
        assert f"test_op_{operation_id}" in globals(), f"missing test_op_{operation_id}"
    elif mounted:
        pytest.fail(
            f"{operation_id} is now mounted: add test_op_{operation_id} and mark it covered"
        )
    else:
        pytest.skip(f"{operation_id}: endpoint not merged yet ({entry})")


def test_every_mounted_api_route_is_in_the_contract(
    app_under_test: FastAPI,
    contract: Contract,
    mounted_paths: Callable[[FastAPI], list[tuple[str, str]]],
) -> None:
    """No route may exist outside the contract (no competing API)."""
    in_contract = {(op.method, _full(contract, op.template)) for op in contract.operations.values()}
    extra = sorted(
        r
        for r in mounted_paths(app_under_test)
        if r[1].startswith(contract.prefix) and r not in in_contract
    )
    assert not extra, f"routes not in contracts/openapi.yaml: {extra}"


# ------------------------------------------------------------------------------ operations


def test_op_getHealth(client: httpx.Client, conformance: Conformance, contract: Contract) -> None:
    response = client.get(f"{contract.prefix}/health")
    assert conformance.assert_conforms(response).operation_id == "getHealth"
    assert response.json() == {"status": "ok", "database": "ok"}


# ------------------------------------------------------------------------------ error probes


def test_unknown_path_is_a_contract_not_found(
    client: httpx.Client, conformance: Conformance, contract: Contract
) -> None:
    for path in (
        f"{contract.prefix}/nope",
        f"{contract.prefix}/health/extra",
        "/definitely-not-here",
    ):
        response = client.get(path)
        conformance.assert_error_body(response, 404, "not_found")


@pytest.mark.parametrize("method", ["DELETE", "POST", "PUT", "PATCH"])
def test_undefined_method_is_405_with_allow_header(
    client: httpx.Client, conformance: Conformance, contract: Contract, method: str
) -> None:
    response = client.request(method, f"{contract.prefix}/health")
    conformance.assert_error_body(response, 405, "method_not_allowed")
    allow = {m.strip() for m in response.headers["allow"].split(",")}
    assert "GET" in allow, response.headers


def test_unhandled_exception_is_a_contract_internal_error(
    app_under_test: FastAPI,
    conformance: Conformance,
    contract: Contract,
    api: Callable[[], httpx.Client],
) -> None:
    """A 500 must be the contract Error (code internal_error), never a stack trace or HTML."""
    from app.core.db import get_engine

    if "LOCALETL_API_URL" in __import__("os").environ:
        pytest.skip("needs the in-process app to inject a failure")

    def boom() -> None:
        raise RuntimeError("secret internal detail")

    previous = app_under_test.dependency_overrides[get_engine]
    app_under_test.dependency_overrides[get_engine] = boom
    try:
        with api() as c:
            response = c.get(f"{contract.prefix}/health")
    finally:
        app_under_test.dependency_overrides[get_engine] = previous
    conformance.assert_error_body(response, 500, "internal_error")
    assert "secret internal detail" not in response.text


def test_health_reports_database_unavailable_not_an_error(
    app_under_test: FastAPI, conformance: Conformance, contract: Contract, tmp_path: Path
) -> None:
    """Unreachable database: 200 with database=unavailable (declared), still conforming."""
    import sqlalchemy as sa
    from fastapi.testclient import TestClient

    from app.core.db import get_engine

    if "LOCALETL_API_URL" in __import__("os").environ:
        pytest.skip("needs the in-process app to inject a failure")

    dead = sa.create_engine(
        "postgresql+psycopg://nobody:nobody@127.0.0.1:1/none", connect_args={"connect_timeout": 1}
    )
    previous = app_under_test.dependency_overrides[get_engine]
    app_under_test.dependency_overrides[get_engine] = lambda: dead
    try:
        with TestClient(app_under_test, raise_server_exceptions=False) as c:
            response = c.get(f"{contract.prefix}/health")
    finally:
        app_under_test.dependency_overrides[get_engine] = previous
        dead.dispose()
    conformance.assert_conforms(response)
    assert response.json() == {"status": "ok", "database": "unavailable"}


# ----------------------------------------------------------------------------------------------
# BE-03: sources (createSource, listSources, getSource, deleteSource, previewSource)
# These arrange and inspect state directly (database rows, the data directory), so they run
# against the in-process app only.
# ----------------------------------------------------------------------------------------------

FIXTURE_CSV = Path(__file__).resolve().parents[1] / "fixtures" / "csv"
SOURCES = "/sources"


@pytest.fixture
def inprocess() -> None:
    if "LOCALETL_API_URL" in os.environ:
        pytest.skip("needs the in-process app (database rows and data directory are inspected)")


@pytest.fixture
def clean(inprocess: None, scratch_engine: sa.Engine, data_dir: Path) -> Iterator[sa.Engine]:
    """Empty `data_sources`/`pipelines` and the stored files before every sources test."""

    def wipe() -> None:
        with scratch_engine.begin() as conn:
            conn.execute(sa.text("TRUNCATE pipelines, data_sources CASCADE"))
            for (table,) in conn.execute(
                sa.text("SELECT tablename FROM pg_tables WHERE schemaname = 'datasets'")
            ).all():
                conn.execute(sa.text(f'DROP TABLE IF EXISTS datasets."{table}" CASCADE'))
        for sub in ("sources", "tmp"):
            folder = data_dir / sub
            if folder.is_dir():
                for f in folder.iterdir():
                    f.unlink()

    wipe()
    yield scratch_engine
    wipe()


def upload(
    client: httpx.Client,
    contract: Contract,
    content: bytes | str,
    filename: str = "data.csv",
    content_type: str | None = "text/csv",
    **fields: str,
) -> httpx.Response:
    data = content.encode() if isinstance(content, str) else content
    file_part = (filename, data, content_type) if content_type else (filename, data)
    return client.post(f"{contract.prefix}{SOURCES}", files={"file": file_part}, data=fields)


def fixture_bytes(name: str) -> bytes:
    return (FIXTURE_CSV / name).read_bytes()


def count(engine: sa.Engine, table: str) -> int:
    with engine.connect() as conn:
        return int(conn.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one())


def stored_files(data_dir: Path) -> list[str]:
    folder = data_dir / "sources"
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


def tmp_files(data_dir: Path) -> list[str]:
    folder = data_dir / "tmp"
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


def add_pipeline(engine: sa.Engine, source_id: str) -> str:
    pipeline_id = str(uuid.uuid4())
    config = {
        "version": 1,
        "columns": [{"source": "id", "name": "id", "type": "integer"}],
        "target": {"table": "t", "mode": "replace"},
    }
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO pipelines (id, name, source_id, config, config_version)"
                " VALUES (:id, :name, :source_id, CAST(:config AS jsonb), 1)"
            ),
            {
                "id": pipeline_id,
                "name": f"p-{pipeline_id[:8]}",
                "source_id": source_id,
                "config": json.dumps(config),
            },
        )
    return pipeline_id


def test_op_createSource(
    client: httpx.Client,
    conformance: Conformance,
    contract: Contract,
    clean: sa.Engine,
    data_dir: Path,
) -> None:
    r = upload(client, contract, fixture_bytes("orders_clean.csv"), "orders_clean.csv")
    assert conformance.assert_conforms(r).operation_id == "createSource"
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "orders_clean.csv" and body["original_filename"] == "orders_clean.csv"
    assert body["row_count"] == 200 and body["size_bytes"] == len(fixture_bytes("orders_clean.csv"))
    assert body["csv_options"] == {
        "encoding": "utf-8",
        "delimiter": ",",
        "has_header": True,
        "quote_char": '"',
    }
    assert [c["name"] for c in body["columns"]][:2] == ["Order ID", "Customer Email"]
    # server-generated storage path; nothing left in tmp
    assert stored_files(data_dir) == [f"{body['id']}.csv"] and tmp_files(data_dir) == []
    assert count(clean, "data_sources") == 1


def test_createSource_options_name_and_basename(
    client: httpx.Client, conformance: Conformance, contract: Contract, clean: sa.Engine
) -> None:
    r = upload(
        client,
        contract,
        fixture_bytes("semicolon.csv"),
        "C:\\Users\\someone\\..\\semi.csv",
        delimiter=";",
        name="My source",
    )
    conformance.assert_conforms(r)
    body = r.json()
    assert body["name"] == "My source" and body["original_filename"] == "semi.csv"  # basename only
    assert (
        body["csv_options"]["delimiter"] == ";"
        and body["row_count"] == 3
        and len(body["columns"]) == 4
    )
    r2 = upload(client, contract, fixture_bytes("no_header.csv"), has_header="false")
    conformance.assert_conforms(r2)
    assert [c["name"] for c in r2.json()["columns"]] == ["column_1", "column_2", "column_3"]
    assert r2.json()["row_count"] == 3
    r3 = upload(client, contract, fixture_bytes("latin1.csv"), encoding="latin-1")
    conformance.assert_conforms(r3)
    assert r3.json()["csv_options"]["encoding"] == "latin-1"
    r4 = upload(client, contract, "id,name\n1,a\n", "data.bin", content_type="text/csv")
    conformance.assert_conforms(r4)  # accepted on the content type alone
    assert r4.status_code == 201


def test_createSource_counts_malformed_records_but_preview_omits_them(
    client: httpx.Client, conformance: Conformance, contract: Contract, clean: sa.Engine
) -> None:
    """Q4-c: row_count includes malformed records; preview and null_count use well-formed ones."""
    r = upload(client, contract, fixture_bytes("ragged_rows.csv"), "ragged_rows.csv")
    conformance.assert_conforms(r)
    assert r.status_code == 201 and r.json()["row_count"] == 6
    p = client.get(f"{contract.prefix}{SOURCES}/{r.json()['id']}/preview")
    conformance.assert_conforms(p)
    assert p.json()["sampled_rows"] == 3 and len(p.json()["rows"]) == 3


@pytest.mark.parametrize(
    ("label", "content", "options", "expect_in_message"),
    [
        ("empty file", b"", {}, "empty"),
        ("header only", b"id,name\n", {}, "no data rows"),
        ("duplicate headers", fixture_bytes("duplicate_headers.csv"), {}, '"id" (columns 1, 5)'),
        ("empty header name", fixture_bytes("empty_header.csv"), {}, "header in column 2 is empty"),
        ("unterminated quote", fixture_bytes("unterminated_quote.csv"), {}, "quoted field"),
        ("501 columns", fixture_bytes("too_many_columns_501.csv"), {}, "too many columns"),
        ("not valid utf-8", fixture_bytes("invalid_utf8.csv"), {}, "not valid utf-8"),
        ("bad delimiter", b"id\n1\n", {"delimiter": "x"}, None),
        ("bad encoding", b"id\n1\n", {"encoding": "ebcdic"}, None),
        ("quote_char too long", b"id\n1\n", {"quote_char": "ab"}, None),
        ("bad has_header", b"id\n1\n", {"has_header": "maybe"}, None),
        ("empty name", b"id\n1\n", {"name": ""}, None),
        ("unknown field", b"id\n1\n", {"extra": "1"}, None),
    ],
)
def test_createSource_422_leaves_nothing_behind(
    client: httpx.Client,
    conformance: Conformance,
    contract: Contract,
    clean: sa.Engine,
    data_dir: Path,
    label: str,
    content: bytes,
    options: dict[str, str],
    expect_in_message: str | None,
) -> None:
    r = upload(client, contract, content, "bad.csv", **options)
    conformance.assert_conforms(r)
    assert r.status_code == 422, (label, r.text)
    error = r.json()["error"]
    assert error["code"] == "validation_error" and error["details"], label
    assert all(d["path"] and d["message"] for d in error["details"])
    if expect_in_message:
        assert expect_in_message in error["message"], (label, error["message"])
    assert (
        count(clean, "data_sources") == 0
        and stored_files(data_dir) == []
        and tmp_files(data_dir) == []
    ), label


def test_createSource_422_missing_file_part(
    client: httpx.Client, conformance: Conformance, contract: Contract, clean: sa.Engine
) -> None:
    r = client.post(
        f"{contract.prefix}{SOURCES}", files={"other": ("a.csv", b"id\n1\n", "text/csv")}
    )
    conformance.assert_conforms(r)
    assert r.status_code == 422
    r = client.post(f"{contract.prefix}{SOURCES}", data={"name": "x"}, files={"_": ("", b"")})
    assert r.status_code in (415, 422)
    conformance.assert_error_body(r, r.status_code)


def test_createSource_415_not_csv(
    client: httpx.Client,
    conformance: Conformance,
    contract: Contract,
    clean: sa.Engine,
    data_dir: Path,
) -> None:
    r = upload(client, contract, "id\n1\n", "notes.txt", content_type="text/plain")
    conformance.assert_conforms(r)
    assert r.status_code == 415 and r.json()["error"]["code"] == "unsupported_media_type"
    r = client.post(f"{contract.prefix}{SOURCES}", json={"file": "x"})  # not multipart at all
    conformance.assert_conforms(r)
    assert r.status_code == 415
    assert (
        count(clean, "data_sources") == 0
        and stored_files(data_dir) == []
        and tmp_files(data_dir) == []
    )


def test_createSource_413_streamed_and_declared(
    app_under_test: FastAPI,
    conformance: Conformance,
    contract: Contract,
    clean: sa.Engine,
    data_dir: Path,
    api: Callable[[], httpx.Client],
) -> None:
    """Limit 1 MB: a 1.5 MB body is cut off while streaming; a 3 MB body is refused up front."""
    from app.core.settings import Settings, get_settings

    app_under_test.dependency_overrides[get_settings] = lambda: Settings(
        localetl_max_upload_mb=1, localetl_data_dir=data_dir
    )
    try:
        with api() as client:
            row = b"1,abcdefghijklmnopqrstuvwxyz0123456789\n"
            for size in (1_500_000, 3_000_000):
                body = b"id,v\n" + row * (size // len(row))
                r = upload(client, contract, body, "big.csv")
                conformance.assert_conforms(r)
                assert r.status_code == 413 and r.json()["error"]["code"] == "payload_too_large", (
                    size
                )
            # a file exactly at the limit is accepted
            at_limit = b"id,v\n" + row * ((1024 * 1024 - 5) // len(row))
            at_limit += b"x" * (1024 * 1024 - len(at_limit))
            assert len(at_limit) == 1024 * 1024
            ok = upload(client, contract, at_limit, "limit.csv")
            assert ok.status_code in (201, 422), ok.text  # accepted by size; content may be ragged
            assert ok.status_code != 413
    finally:
        app_under_test.dependency_overrides.pop(get_settings, None)
    assert count(clean, "data_sources") <= 1 and tmp_files(data_dir) == []
    assert len(stored_files(data_dir)) == count(clean, "data_sources")


def test_op_listSources(
    client: httpx.Client, conformance: Conformance, contract: Contract, clean: sa.Engine
) -> None:
    empty = client.get(f"{contract.prefix}{SOURCES}")
    assert conformance.assert_conforms(empty).operation_id == "listSources"
    assert empty.json() == {"total": 0, "limit": 50, "offset": 0, "items": []}
    ids = []
    for i in range(3):
        r = upload(client, contract, f"id,v\n{i},x\n", f"s{i}.csv", name=f"source {i}")
        conformance.assert_conforms(r)
        ids.append(r.json()["id"])
    page = client.get(f"{contract.prefix}{SOURCES}")
    conformance.assert_conforms(page)
    assert (
        page.json()["total"] == 3 and [i["id"] for i in page.json()["items"]] == ids[::-1]
    )  # newest first
    p2 = client.get(f"{contract.prefix}{SOURCES}", params={"limit": 2, "offset": 2})
    conformance.assert_conforms(p2)
    assert (
        p2.json()["limit"] == 2
        and p2.json()["offset"] == 2
        and [i["id"] for i in p2.json()["items"]] == [ids[0]]
    )
    beyond = client.get(f"{contract.prefix}{SOURCES}", params={"offset": 10})
    conformance.assert_conforms(beyond)
    assert beyond.json()["items"] == [] and beyond.json()["total"] == 3
    for bad in ({"limit": 0}, {"limit": 201}, {"offset": -1}, {"limit": "x"}):
        r = client.get(f"{contract.prefix}{SOURCES}", params=bad)
        conformance.assert_conforms(r)
        assert r.status_code == 422, bad
    top = client.get(f"{contract.prefix}{SOURCES}", params={"limit": 200})
    conformance.assert_conforms(top)
    assert top.status_code == 200


def test_op_getSource(
    client: httpx.Client, conformance: Conformance, contract: Contract, clean: sa.Engine
) -> None:
    created = upload(client, contract, fixture_bytes("types_mixed.csv"), "types_mixed.csv")
    sid = created.json()["id"]
    r = client.get(f"{contract.prefix}{SOURCES}/{sid}")
    assert conformance.assert_conforms(r).operation_id == "getSource"
    assert r.json() == created.json()
    assert [(c["name"], c["inferred_type"]) for c in r.json()["columns"]] == [
        ("i", "integer"),
        ("f", "float"),
        ("b", "boolean"),
        ("d", "date"),
        ("dt", "datetime"),
        ("s", "string"),
    ]
    missing = client.get(f"{contract.prefix}{SOURCES}/{uuid.uuid4()}")
    conformance.assert_conforms(missing)
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"
    # The contract declares only 200/404 here; a malformed id is still a contract Error (422),
    # checked as a global error rather than as a declared response.
    bad = client.get(f"{contract.prefix}{SOURCES}/not-a-uuid")
    conformance.assert_error_body(bad, 422, "validation_error")


def test_op_deleteSource(
    client: httpx.Client,
    conformance: Conformance,
    contract: Contract,
    clean: sa.Engine,
    data_dir: Path,
) -> None:
    sid = upload(client, contract, "id\n1\n", "d.csv").json()["id"]
    assert stored_files(data_dir) == [f"{sid}.csv"]
    r = client.delete(f"{contract.prefix}{SOURCES}/{sid}")
    assert conformance.assert_conforms(r).operation_id == "deleteSource"
    assert r.status_code == 204 and r.content == b""
    assert count(clean, "data_sources") == 0 and stored_files(data_dir) == []
    again = client.delete(f"{contract.prefix}{SOURCES}/{sid}")
    conformance.assert_conforms(again)
    assert again.status_code == 404
    conformance.assert_error_body(
        client.delete(f"{contract.prefix}{SOURCES}/not-a-uuid"), 422, "validation_error"
    )


def test_deleteSource_409_when_a_pipeline_uses_it(
    client: httpx.Client,
    conformance: Conformance,
    contract: Contract,
    clean: sa.Engine,
    data_dir: Path,
) -> None:
    sid = upload(client, contract, "id\n1\n", "used.csv").json()["id"]
    pipeline_id = add_pipeline(clean, sid)
    r = client.delete(f"{contract.prefix}{SOURCES}/{sid}")
    conformance.assert_conforms(r)
    assert r.status_code == 409 and r.json()["error"]["code"] == "conflict"
    assert count(clean, "data_sources") == 1 and stored_files(data_dir) == [
        f"{sid}.csv"
    ]  # untouched
    assert client.get(f"{contract.prefix}{SOURCES}/{sid}").status_code == 200
    with clean.begin() as conn:
        conn.execute(sa.text("DELETE FROM pipelines WHERE id = :id"), {"id": pipeline_id})
    ok = client.delete(f"{contract.prefix}{SOURCES}/{sid}")
    conformance.assert_conforms(ok)
    assert ok.status_code == 204 and stored_files(data_dir) == []


def test_op_previewSource(
    client: httpx.Client, conformance: Conformance, contract: Contract, clean: sa.Engine
) -> None:
    sid = upload(client, contract, fixture_bytes("orders_clean.csv"), "orders.csv").json()["id"]
    r = client.get(f"{contract.prefix}{SOURCES}/{sid}/preview")
    assert conformance.assert_conforms(r).operation_id == "previewSource"
    body = r.json()
    assert body["source_id"] == sid and body["sampled_rows"] == 50 == len(
        body["rows"]
    )  # default limit
    assert all(set(row) == {c["name"] for c in body["columns"]} for row in body["rows"])
    assert all(v is None or isinstance(v, str) for row in body["rows"] for v in row.values())
    five = client.get(f"{contract.prefix}{SOURCES}/{sid}/preview", params={"limit": 5})
    conformance.assert_conforms(five)
    assert five.json()["sampled_rows"] == 5 and five.json()["rows"] == body["rows"][:5]
    big = client.get(f"{contract.prefix}{SOURCES}/{sid}/preview", params={"limit": 500})
    conformance.assert_conforms(big)
    assert big.json()["sampled_rows"] == 200  # the file has 200 rows
    for bad in ({"limit": 0}, {"limit": 501}, {"limit": "x"}):
        e = client.get(f"{contract.prefix}{SOURCES}/{sid}/preview", params=bad)
        conformance.assert_conforms(e)
        assert e.status_code == 422, bad
    missing = client.get(f"{contract.prefix}{SOURCES}/{uuid.uuid4()}/preview")
    conformance.assert_conforms(missing)
    assert missing.status_code == 404


def test_previewSource_text_and_nulls_are_raw_strings(
    client: httpx.Client, conformance: Conformance, contract: Contract, clean: sa.Engine
) -> None:
    sid = upload(client, contract, fixture_bytes("types_mixed.csv"), "types_mixed.csv").json()["id"]
    r = client.get(f"{contract.prefix}{SOURCES}/{sid}/preview")
    conformance.assert_conforms(r)
    assert r.json()["rows"][2] == {
        "i": "3",
        "f": None,
        "b": "yes",
        "d": None,
        "dt": None,
        "s": None,
    }
    cols = {c["name"]: c["null_count"] for c in r.json()["columns"]}
    assert cols["f"] == 1 and cols["i"] == 0


def test_previewSource_stored_file_missing_is_an_error_body(
    client: httpx.Client,
    conformance: Conformance,
    contract: Contract,
    clean: sa.Engine,
    data_dir: Path,
) -> None:
    sid = upload(client, contract, "id\n1\n", "gone.csv").json()["id"]
    (data_dir / "sources" / f"{sid}.csv").unlink()
    r = client.get(f"{contract.prefix}{SOURCES}/{sid}/preview")
    # 500 is not declared for previewSource; it must still be the contract Error, never a trace.
    conformance.assert_error_body(r, 500, "internal_error")
    assert str(data_dir) not in r.text


def test_sources_never_expose_server_paths(
    client: httpx.Client,
    conformance: Conformance,
    contract: Contract,
    clean: sa.Engine,
    data_dir: Path,
) -> None:
    r = upload(client, contract, "id\n1\n", "p.csv")
    assert "stored_path" not in r.json() and "sha256" not in r.json()
    assert str(data_dir) not in r.text


# ----------------------------------------------------------------------------------------------
# BE-04: pipelines (createPipeline, listPipelines, getPipeline, updatePipeline, deletePipeline,
# validatePipelineConfig). Error `path`s are JSON Pointers into the request, so config problems
# are reported under `/config/...` (contract: ErrorDetail.path).
# ----------------------------------------------------------------------------------------------

PIPELINES = "/pipelines"
EXAMPLES = Path(__file__).resolve().parents[2] / "contracts" / "examples" / "pipeline"


def orders_config() -> dict[str, object]:
    return json.loads((EXAMPLES / "valid" / "orders_full.json").read_text("utf-8"))


def make_source(client: httpx.Client, contract: Contract, name: str = "orders") -> str:
    r = upload(client, contract, fixture_bytes("orders_clean.csv"), "orders_clean.csv", name=name)
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def body(source_id: str, name: str = "orders cleanup", **over: object) -> dict[str, object]:
    return {
        "name": name,
        "description": "d",
        "source_id": source_id,
        "config": orders_config(),
        **over,
    }


def create_pipeline(
    client: httpx.Client, contract: Contract, source_id: str, name: str = "orders cleanup"
) -> httpx.Response:
    return client.post(f"{contract.prefix}{PIPELINES}", json=body(source_id, name))


def add_run(
    engine: sa.Engine, pipeline_id: str, status: str, queued_at: str = "2026-10-20T10:00:00Z"
) -> str:
    run_id = str(uuid.uuid4())
    finished = None if status in ("queued", "running") else queued_at
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO runs (id, pipeline_id, pipeline_name, config_snapshot, config_version,"
                " status, queued_at, finished_at) VALUES (:id, :pid, 'p', '{}', 1,"
                " CAST(:status AS run_status), :queued, :finished)"
            ),
            {
                "id": run_id,
                "pid": pipeline_id,
                "status": status,
                "queued": queued_at,
                "finished": finished,
            },
        )
    return run_id


def test_op_createPipeline(
    client: httpx.Client, conformance: Conformance, contract: Contract, clean: sa.Engine
) -> None:
    sid = make_source(client, contract)
    r = create_pipeline(client, contract, sid)
    assert (
        conformance.assert_conforms(r).operation_id == "createPipeline"
    )  # incl. config vs pipeline.schema.json
    assert r.status_code == 201
    p = r.json()
    assert p["name"] == "orders cleanup" and p["description"] == "d" and p["source_id"] == sid
    assert p["config_version"] == 1 and p["last_run"] is None and p["config"] == orders_config()
    assert count(clean, "pipelines") == 1
    minimal = client.post(
        f"{contract.prefix}{PIPELINES}",
        json={
            "name": "minimal",
            "source_id": sid,
            "config": {
                "version": 1,
                "columns": [{"source": "Order ID", "name": "id", "type": "integer"}],
                "target": {"table": "minimal", "mode": "replace"},
            },
        },
    )
    conformance.assert_conforms(minimal)
    assert minimal.status_code == 201 and minimal.json()["description"] is None


def test_createPipeline_409_duplicate_name(
    client: httpx.Client, conformance: Conformance, contract: Contract, clean: sa.Engine
) -> None:
    sid = make_source(client, contract)
    assert create_pipeline(client, contract, sid, "same").status_code == 201
    r = create_pipeline(client, contract, sid, "same")
    conformance.assert_conforms(r)
    assert r.status_code == 409 and r.json()["error"]["code"] == "conflict"
    assert count(clean, "pipelines") == 1


def test_createPipeline_404_unknown_source(
    client: httpx.Client, conformance: Conformance, contract: Contract, clean: sa.Engine
) -> None:
    r = client.post(f"{contract.prefix}{PIPELINES}", json=body(str(uuid.uuid4())))
    conformance.assert_conforms(r)
    assert r.status_code == 404 and count(clean, "pipelines") == 0


@pytest.mark.parametrize(
    ("label", "mutate", "path"),
    [
        (
            "bad column type",
            lambda c: c["columns"][0].__setitem__("type", "decimal"),
            "/config/columns/0/type",
        ),
        (
            "unknown property",
            lambda c: c["target"].__setitem__("schema", "public"),
            "/config/target",
        ),
        (
            "bad load mode",
            lambda c: c["target"].__setitem__("mode", "upsert"),
            "/config/target/mode",
        ),
        ("wrong version", lambda c: c.__setitem__("version", 2), "/config/version"),
        (
            "unknown column reference",
            lambda c: c["validations"][0].__setitem__("column", "nope"),
            "/config/validations/0/column",
        ),
        (
            "reserved table prefix",
            lambda c: c["target"].__setitem__("table", "run_x"),
            "/config/target/table",
        ),
        (
            "source column missing in the CSV",
            lambda c: c["columns"][0].__setitem__("source", "Not In File"),
            "/config/columns/0/source",
        ),
        (
            "format on a string column",
            lambda c: c["columns"][1].__setitem__("format", "%Y"),
            "/config/columns/1/format",
        ),
    ],
)
def test_createPipeline_422_config_errors_are_prefixed_with_config(
    client: httpx.Client,
    conformance: Conformance,
    contract: Contract,
    clean: sa.Engine,
    label: str,
    mutate: Callable[[dict[str, object]], None],
    path: str,
) -> None:
    sid = make_source(client, contract)
    config = orders_config()
    mutate(config)
    r = client.post(f"{contract.prefix}{PIPELINES}", json=body(sid, config=config))
    conformance.assert_conforms(r)
    assert r.status_code == 422, (label, r.text)
    paths = [d["path"] for d in r.json()["error"]["details"]]
    assert path in paths, (label, paths)
    assert all(p.startswith("/config") for p in paths), (label, paths)
    assert count(clean, "pipelines") == 0


def test_createPipeline_422_every_invalid_contract_example(
    client: httpx.Client, conformance: Conformance, contract: Contract, clean: sa.Engine
) -> None:
    sid = make_source(client, contract)
    files = sorted((EXAMPLES / "invalid").glob("*.json"))
    assert len(files) == 8
    for f in files:
        r = client.post(
            f"{contract.prefix}{PIPELINES}",
            json=body(sid, config=json.loads(f.read_text("utf-8"))),
        )
        conformance.assert_conforms(r)
        assert r.status_code == 422, f.name
        paths = [d["path"] for d in r.json()["error"]["details"]]
        assert paths and all(p == "/config" or p.startswith("/config/") for p in paths), (
            f.name,
            paths,
        )
    assert count(clean, "pipelines") == 0


@pytest.mark.parametrize(
    "bad",
    [
        {"name": ""},
        {"name": "x" * 201},
        {"description": "x" * 2001},
        {"extra": 1},
        {"source_id": "not-a-uuid"},
        {"config": "not an object"},
    ],
)
def test_createPipeline_422_request_shape(
    client: httpx.Client,
    conformance: Conformance,
    contract: Contract,
    clean: sa.Engine,
    bad: dict[str, object],
) -> None:
    sid = make_source(client, contract)
    r = client.post(f"{contract.prefix}{PIPELINES}", json={**body(sid), **bad})
    conformance.assert_conforms(r)
    assert r.status_code == 422 and r.json()["error"]["details"]


def test_op_listPipelines(
    client: httpx.Client, conformance: Conformance, contract: Contract, clean: sa.Engine
) -> None:
    empty = client.get(f"{contract.prefix}{PIPELINES}")
    assert conformance.assert_conforms(empty).operation_id == "listPipelines"
    assert empty.json() == {"total": 0, "limit": 50, "offset": 0, "items": []}
    sid = make_source(client, contract)
    ids = [create_pipeline(client, contract, sid, f"p{i}").json()["id"] for i in range(3)]
    page = client.get(f"{contract.prefix}{PIPELINES}")
    conformance.assert_conforms(page)
    assert (
        page.json()["total"] == 3 and [p["id"] for p in page.json()["items"]] == ids[::-1]
    )  # most recently updated first
    # updating the oldest moves it to the front
    upd = client.put(f"{contract.prefix}{PIPELINES}/{ids[0]}", json=body(sid, "p0"))
    assert upd.status_code == 200
    reordered = client.get(f"{contract.prefix}{PIPELINES}")
    assert reordered.json()["items"][0]["id"] == ids[0]
    p2 = client.get(f"{contract.prefix}{PIPELINES}", params={"limit": 1, "offset": 1})
    conformance.assert_conforms(p2)
    assert p2.json()["limit"] == 1 and p2.json()["offset"] == 1 and len(p2.json()["items"]) == 1
    for bad in ({"limit": 0}, {"limit": 201}, {"offset": -1}):
        r = client.get(f"{contract.prefix}{PIPELINES}", params=bad)
        conformance.assert_conforms(r)
        assert r.status_code == 422, bad


def test_pipelines_last_run_is_the_most_recent_run(
    client: httpx.Client, conformance: Conformance, contract: Contract, clean: sa.Engine
) -> None:
    sid = make_source(client, contract)
    pid = create_pipeline(client, contract, sid).json()["id"]
    add_run(clean, pid, "failed", "2026-10-20T09:00:00Z")
    newest = add_run(clean, pid, "succeeded", "2026-10-20T11:00:00Z")
    add_run(clean, pid, "interrupted", "2026-10-20T10:00:00Z")
    got = client.get(f"{contract.prefix}{PIPELINES}/{pid}")
    conformance.assert_conforms(got)
    assert (
        got.json()["last_run"]["id"] == newest and got.json()["last_run"]["status"] == "succeeded"
    )
    assert got.json()["last_run"]["finished_at"] is not None
    listed = client.get(f"{contract.prefix}{PIPELINES}")
    conformance.assert_conforms(listed)
    assert listed.json()["items"][0]["last_run"]["id"] == newest


def test_op_getPipeline(
    client: httpx.Client, conformance: Conformance, contract: Contract, clean: sa.Engine
) -> None:
    sid = make_source(client, contract)
    created = create_pipeline(client, contract, sid)
    r = client.get(f"{contract.prefix}{PIPELINES}/{created.json()['id']}")
    assert conformance.assert_conforms(r).operation_id == "getPipeline"
    assert r.json() == created.json()
    missing = client.get(f"{contract.prefix}{PIPELINES}/{uuid.uuid4()}")
    conformance.assert_conforms(missing)
    assert missing.status_code == 404
    conformance.assert_error_body(
        client.get(f"{contract.prefix}{PIPELINES}/not-a-uuid"), 422, "validation_error"
    )


def test_op_updatePipeline(
    client: httpx.Client, conformance: Conformance, contract: Contract, clean: sa.Engine
) -> None:
    sid = make_source(client, contract)
    pid = create_pipeline(client, contract, sid, "orig").json()["id"]
    url = f"{contract.prefix}{PIPELINES}/{pid}"
    changed = orders_config()
    changed["target"] = {"table": "orders_v2", "mode": "append"}  # type: ignore[index]
    r = client.put(url, json=body(sid, "renamed", config=changed, description=None))
    assert conformance.assert_conforms(r).operation_id == "updatePipeline"
    assert r.status_code == 200
    p = r.json()
    assert p["id"] == pid and p["name"] == "renamed" and p["description"] is None
    assert (
        p["config"]["target"] == {"table": "orders_v2", "mode": "append"}
        and p["config_version"] == 2
    )
    assert p["updated_at"] >= p["created_at"]
    again = client.put(url, json=body(sid, "renamed", config=changed))
    conformance.assert_conforms(again)
    assert again.json()["config_version"] == 3  # incremented on every PUT
    assert client.get(url).json()["config_version"] == 3
    # keeping its own name is not a conflict
    assert client.put(url, json=body(sid, "renamed")).status_code == 200


def test_updatePipeline_errors_do_not_change_anything(
    client: httpx.Client, conformance: Conformance, contract: Contract, clean: sa.Engine
) -> None:
    sid = make_source(client, contract)
    a = create_pipeline(client, contract, sid, "a").json()
    b = create_pipeline(client, contract, sid, "b").json()
    url = f"{contract.prefix}{PIPELINES}/{b['id']}"
    conflict = client.put(url, json=body(sid, "a"))
    conformance.assert_conforms(conflict)
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "conflict"
    unknown_source = client.put(url, json=body(str(uuid.uuid4()), "b"))
    conformance.assert_conforms(unknown_source)
    assert unknown_source.status_code == 404
    bad = orders_config()
    bad["columns"][0]["type"] = "decimal"  # type: ignore[index]
    invalid = client.put(url, json=body(sid, "b", config=bad))
    conformance.assert_conforms(invalid)
    assert invalid.status_code == 422
    assert "/config/columns/0/type" in [d["path"] for d in invalid.json()["error"]["details"]]
    missing = client.put(f"{contract.prefix}{PIPELINES}/{uuid.uuid4()}", json=body(sid, "x"))
    conformance.assert_conforms(missing)
    assert missing.status_code == 404
    after = client.get(url).json()
    assert after["config_version"] == 1 and after["name"] == "b" and after["config"] == b["config"]
    assert client.get(f"{contract.prefix}{PIPELINES}/{a['id']}").json()["name"] == "a"


def test_op_deletePipeline(
    client: httpx.Client, conformance: Conformance, contract: Contract, clean: sa.Engine
) -> None:
    sid = make_source(client, contract)
    pid = create_pipeline(client, contract, sid).json()["id"]
    done = add_run(clean, pid, "succeeded")
    r = client.delete(f"{contract.prefix}{PIPELINES}/{pid}")
    assert conformance.assert_conforms(r).operation_id == "deletePipeline"
    assert r.status_code == 204 and r.content == b""
    assert count(clean, "pipelines") == 0
    with clean.connect() as conn:  # history is kept, detached from the pipeline
        row = conn.execute(
            sa.text("SELECT pipeline_id FROM runs WHERE id = :id"), {"id": done}
        ).one()
    assert row[0] is None
    gone = client.delete(f"{contract.prefix}{PIPELINES}/{pid}")
    conformance.assert_conforms(gone)
    assert gone.status_code == 404
    conformance.assert_error_body(
        client.delete(f"{contract.prefix}{PIPELINES}/not-a-uuid"), 422, "validation_error"
    )


@pytest.mark.parametrize("status", ["queued", "running"])
def test_deletePipeline_409_with_an_active_run(
    client: httpx.Client,
    conformance: Conformance,
    contract: Contract,
    clean: sa.Engine,
    status: str,
) -> None:
    sid = make_source(client, contract)
    pid = create_pipeline(client, contract, sid).json()["id"]
    run_id = add_run(clean, pid, status)
    r = client.delete(f"{contract.prefix}{PIPELINES}/{pid}")
    conformance.assert_conforms(r)
    assert r.status_code == 409 and r.json()["error"]["code"] == "conflict"
    assert (
        count(clean, "pipelines") == 1
        and client.get(f"{contract.prefix}{PIPELINES}/{pid}").status_code == 200
    )
    with clean.begin() as conn:
        conn.execute(
            sa.text("UPDATE runs SET status = 'failed', finished_at = now() WHERE id = :id"),
            {"id": run_id},
        )
    ok = client.delete(f"{contract.prefix}{PIPELINES}/{pid}")
    conformance.assert_conforms(ok)
    assert ok.status_code == 204


def test_op_validatePipelineConfig(
    client: httpx.Client, conformance: Conformance, contract: Contract, clean: sa.Engine
) -> None:
    sid = make_source(client, contract)
    url = f"{contract.prefix}{PIPELINES}/validate"
    ok = client.post(url, json={"config": orders_config(), "source_id": sid})
    assert conformance.assert_conforms(ok).operation_id == "validatePipelineConfig"
    assert ok.status_code == 200 and ok.json() == {"valid": True, "errors": []}
    no_source = client.post(url, json={"config": orders_config()})
    conformance.assert_conforms(no_source)
    assert no_source.json() == {"valid": True, "errors": []}
    assert count(clean, "pipelines") == 0  # never persists
    bad = orders_config()
    bad["columns"][0]["type"] = "decimal"  # type: ignore[index]
    bad["validations"][0]["column"] = "nope"  # type: ignore[index]
    r = client.post(url, json={"config": bad, "source_id": sid})
    conformance.assert_conforms(r)
    assert r.status_code == 200 and r.json()["valid"] is False  # an invalid config is still a 200
    paths = [e["path"] for e in r.json()["errors"]]
    assert "/config/columns/0/type" in paths and all(p.startswith("/config") for p in paths)


def test_validatePipelineConfig_source_columns_and_errors(
    client: httpx.Client, conformance: Conformance, contract: Contract, clean: sa.Engine
) -> None:
    sid = make_source(client, contract)
    url = f"{contract.prefix}{PIPELINES}/validate"
    config = orders_config()
    config["columns"][0]["source"] = "Not In File"  # type: ignore[index]
    without = client.post(url, json={"config": config})
    conformance.assert_conforms(without)
    assert without.json()["valid"] is True  # source columns are only checked when a source is given
    with_source = client.post(url, json={"config": config, "source_id": sid})
    conformance.assert_conforms(with_source)
    assert with_source.json()["valid"] is False
    assert "/config/columns/0/source" in [e["path"] for e in with_source.json()["errors"]]
    unknown = client.post(url, json={"config": orders_config(), "source_id": str(uuid.uuid4())})
    conformance.assert_conforms(unknown)
    assert unknown.status_code == 404
    for bad_body in (
        {},
        {"config": "x"},
        {"config": {}, "source_id": "nope"},
        {"config": {}, "extra": 1},
    ):
        r = client.post(url, json=bad_body)
        conformance.assert_conforms(r)
        assert r.status_code == 422, bad_body
    # every contract example behaves as labelled, with /config-prefixed paths
    for f in sorted((EXAMPLES / "valid").glob("*.json")):
        r = client.post(url, json={"config": json.loads(f.read_text("utf-8"))})
        conformance.assert_conforms(r)
        assert r.json()["valid"] is True, f.name
    for f in sorted((EXAMPLES / "invalid").glob("*.json")):
        r = client.post(url, json={"config": json.loads(f.read_text("utf-8"))})
        conformance.assert_conforms(r)
        errors = r.json()["errors"]
        assert r.json()["valid"] is False and errors, f.name
        assert all(e["path"] == "/config" or e["path"].startswith("/config/") for e in errors), (
            f.name
        )


# ----------------------------------------------------------------------------------------------
# BE-05: runs (createRun, listRuns, getRun, listRunEvents, listRunRejections).
# The API only queues runs; every later status change belongs to the worker, so tests that need
# runs in other states, events or rejections arrange those rows directly.
# ----------------------------------------------------------------------------------------------

RUNS = "/runs"
COUNTERS = (
    "extracted_count",
    "loaded_count",
    "rejected_count",
    "duplicate_dropped_count",
    "null_dropped_count",
)


def queue_run(client: httpx.Client, contract: Contract, pipeline_id: str) -> httpx.Response:
    return client.post(f"{contract.prefix}{PIPELINES}/{pipeline_id}/runs")


def pipeline_with_source(
    client: httpx.Client, contract: Contract, name: str = "p"
) -> tuple[str, str]:
    sid = make_source(client, contract, name=f"src-{name}")
    return sid, str(create_pipeline(client, contract, sid, name).json()["id"])


def add_finished_run(
    engine: sa.Engine,
    pipeline_id: str,
    *,
    status: str = "succeeded",
    queued_at: str = "2026-10-20T10:00:00Z",
    started_at: str | None = "2026-10-20T10:00:01Z",
    finished_at: str | None = "2026-10-20T10:00:03.500Z",
    counters: tuple[int, int, int, int, int] = (10, 6, 2, 1, 1),
    error_message: str | None = None,
) -> str:
    run_id = str(uuid.uuid4())
    values = dict(zip(COUNTERS, counters, strict=True))
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO runs (id, pipeline_id, pipeline_name, config_snapshot, config_version,"
                " status, queued_at, started_at, finished_at, error_message, extracted_count,"
                " loaded_count, rejected_count, duplicate_dropped_count, null_dropped_count)"
                " VALUES (:id, :pid, 'p', '{}', 1, CAST(:status AS run_status), :queued, :started,"
                " :finished, :err, :extracted_count, :loaded_count, :rejected_count,"
                " :duplicate_dropped_count, :null_dropped_count)"
            ),
            {
                "id": run_id,
                "pid": pipeline_id,
                "status": status,
                "queued": queued_at,
                "started": started_at,
                "finished": finished_at,
                "err": error_message,
                **values,
            },
        )
    return run_id


def add_events(
    engine: sa.Engine, run_id: str, events: list[tuple[str, str, int | None, int | None]]
) -> None:
    with engine.begin() as conn:
        for stage, status, rows_in, rows_out in events:
            conn.execute(
                sa.text(
                    "INSERT INTO run_events (run_id, stage, status, rows_in, rows_out, message)"
                    " VALUES (:r, :stage, :status, :rin, :rout, :msg)"
                ),
                {
                    "r": run_id,
                    "stage": stage,
                    "status": status,
                    "rin": rows_in,
                    "rout": rows_out,
                    "msg": "note" if status == "failed" else None,
                },
            )


def add_rejections(
    engine: sa.Engine, run_id: str, rows: list[tuple[int, str | None, str, str, str | None]]
) -> None:
    with engine.begin() as conn:
        for row_number, column, rule, message, value in rows:
            conn.execute(
                sa.text(
                    "INSERT INTO run_rejections"
                    " (run_id, row_number, column_name, rule, message, value)"
                    " VALUES (:r, :n, :c, :rule, :m, :v)"
                ),
                {"r": run_id, "n": row_number, "c": column, "rule": rule, "m": message, "v": value},
            )


def run_row(engine: sa.Engine, run_id: str) -> sa.Row[tuple[object, ...]]:
    with engine.connect() as conn:
        return conn.execute(sa.text("SELECT * FROM runs WHERE id = :id"), {"id": run_id}).one()


def test_op_createRun(
    client: httpx.Client, conformance: Conformance, contract: Contract, clean: sa.Engine
) -> None:
    _, pid = pipeline_with_source(client, contract)
    pipeline = client.get(f"{contract.prefix}{PIPELINES}/{pid}").json()
    r = queue_run(client, contract, pid)
    assert conformance.assert_conforms(r).operation_id == "createRun"
    assert r.status_code == 202
    run = r.json()
    assert run["status"] == "queued" and run["pipeline_id"] == pid and run["pipeline_name"] == "p"
    assert (
        run["source_id"] == pipeline["source_id"]
        and run["config_version"] == pipeline["config_version"]
    )
    assert [run[c] for c in COUNTERS] == [0, 0, 0, 0, 0]
    for field in (
        "current_stage",
        "started_at",
        "finished_at",
        "duration_ms",
        "dataset_id",
        "error_message",
    ):
        assert run[field] is None, field
    row = run_row(clean, run["id"])
    assert (
        row.config_snapshot == pipeline["config"]
    )  # the snapshot is a copy of the pipeline config
    assert row.worker_id is None and row.heartbeat_at is None


def test_createRun_never_executes_and_nothing_changes_status(
    client: httpx.Client, conformance: Conformance, contract: Contract, clean: sa.Engine
) -> None:
    _, pid = pipeline_with_source(client, contract)
    run_id = queue_run(client, contract, pid).json()["id"]
    time.sleep(1.0)
    for _ in range(3):
        got = client.get(f"{contract.prefix}{RUNS}/{run_id}")
        conformance.assert_conforms(got)
        assert got.json()["status"] == "queued" and got.json()["started_at"] is None
    with clean.connect() as conn:
        tables = conn.execute(
            sa.text("SELECT count(*) FROM pg_tables WHERE schemaname IN ('datasets', 'staging')")
        ).scalar_one()
    assert tables == 0 and count(clean, "run_events") == 0 and count(clean, "run_rejections") == 0
    # there is no API to change a run: other methods are 405 with an Allow header
    for method in ("PUT", "PATCH", "DELETE"):
        r = client.request(method, f"{contract.prefix}{RUNS}/{run_id}")
        conformance.assert_error_body(r, 405, "method_not_allowed")
        assert "GET" in r.headers["allow"]
    conformance.assert_error_body(
        client.post(f"{contract.prefix}{RUNS}/{run_id}/cancel"), 404, "not_found"
    )
    assert run_row(clean, run_id).status == "queued"


def test_createRun_snapshot_is_frozen(
    client: httpx.Client, conformance: Conformance, contract: Contract, clean: sa.Engine
) -> None:
    sid, pid = pipeline_with_source(client, contract)
    first = queue_run(client, contract, pid).json()
    changed = orders_config()
    changed["target"] = {"table": "later", "mode": "append"}  # type: ignore[index]
    assert (
        client.put(
            f"{contract.prefix}{PIPELINES}/{pid}", json=body(sid, "p", config=changed)
        ).status_code
        == 200
    )
    assert run_row(clean, first["id"]).config_snapshot == orders_config()
    assert client.get(f"{contract.prefix}{RUNS}/{first['id']}").json()["config_version"] == 1
    with clean.begin() as conn:
        conn.execute(
            sa.text("UPDATE runs SET status = 'failed', finished_at = now() WHERE id = :id"),
            {"id": first["id"]},
        )
    second = queue_run(client, contract, pid)
    conformance.assert_conforms(second)
    assert second.status_code == 202 and second.json()["config_version"] == 2
    assert run_row(clean, second.json()["id"]).config_snapshot["target"] == {
        "table": "later",
        "mode": "append",
    }


@pytest.mark.parametrize("state", ["queued", "running"])
def test_createRun_409_when_the_pipeline_has_an_active_run(
    client: httpx.Client, conformance: Conformance, contract: Contract, clean: sa.Engine, state: str
) -> None:
    sid, pid = pipeline_with_source(client, contract)
    first = queue_run(client, contract, pid).json()["id"]
    if state == "running":
        with clean.begin() as conn:
            conn.execute(
                sa.text("UPDATE runs SET status = 'running', started_at = now() WHERE id = :id"),
                {"id": first},
            )
    r = queue_run(client, contract, pid)
    conformance.assert_conforms(r)
    assert r.status_code == 409 and r.json()["error"]["code"] == "conflict"
    assert count(clean, "runs") == 1
    # another pipeline is independent
    other = create_pipeline(client, contract, sid, "other").json()["id"]
    ok = queue_run(client, contract, other)
    conformance.assert_conforms(ok)
    assert ok.status_code == 202
    # after the first run ends, the pipeline can be queued again
    with clean.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE runs SET status = 'succeeded', loaded_count = 0, extracted_count = 0,"
                " finished_at = now() WHERE id = :id"
            ),
            {"id": first},
        )
    again = queue_run(client, contract, pid)
    conformance.assert_conforms(again)
    assert again.status_code == 202


def test_createRun_concurrent_requests_queue_exactly_one(
    app_under_test: FastAPI,
    conformance: Conformance,
    contract: Contract,
    clean: sa.Engine,
    api: Callable[[], httpx.Client],
) -> None:
    with api() as client:
        _, pid = pipeline_with_source(client, contract)
    codes: list[int] = []

    def go() -> None:
        with api() as c:
            codes.append(queue_run(c, contract, pid).status_code)

    threads = [threading.Thread(target=go) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(codes) == [202] + [409] * 7, codes
    assert count(clean, "runs") == 1


def test_createRun_404_and_malformed_id(
    client: httpx.Client, conformance: Conformance, contract: Contract, clean: sa.Engine
) -> None:
    r = queue_run(client, contract, str(uuid.uuid4()))
    conformance.assert_conforms(r)
    assert r.status_code == 404 and count(clean, "runs") == 0
    conformance.assert_error_body(
        queue_run(client, contract, "not-a-uuid"), 422, "validation_error"
    )


def test_op_listRuns(
    client: httpx.Client, conformance: Conformance, contract: Contract, clean: sa.Engine
) -> None:
    empty = client.get(f"{contract.prefix}{RUNS}")
    assert conformance.assert_conforms(empty).operation_id == "listRuns"
    assert empty.json() == {"total": 0, "limit": 50, "offset": 0, "items": []}
    sid, pid = pipeline_with_source(client, contract, "a")
    other = create_pipeline(client, contract, sid, "b").json()["id"]
    r1 = add_finished_run(
        clean, pid, status="failed", queued_at="2026-10-20T09:00:00Z", counters=(5, 0, 5, 0, 0)
    )
    r2 = add_finished_run(clean, pid, status="succeeded", queued_at="2026-10-20T10:00:00Z")
    r3 = add_finished_run(
        clean,
        other,
        status="interrupted",
        queued_at="2026-10-20T11:00:00Z",
        counters=(3, 0, 1, 0, 0),
    )
    running = add_run(clean, pid, "running", "2026-10-20T12:00:00Z")
    page = client.get(f"{contract.prefix}{RUNS}")
    conformance.assert_conforms(page)
    assert page.json()["total"] == 4 and [i["id"] for i in page.json()["items"]] == [
        running,
        r3,
        r2,
        r1,
    ]  # newest first
    for item in page.json()["items"]:
        assert set(COUNTERS) <= set(item)
    by_pipeline = client.get(f"{contract.prefix}{RUNS}", params={"pipeline_id": pid})
    conformance.assert_conforms(by_pipeline)
    assert [i["id"] for i in by_pipeline.json()["items"]] == [
        running,
        r2,
        r1,
    ] and by_pipeline.json()["total"] == 3
    by_status = client.get(f"{contract.prefix}{RUNS}", params={"status": "succeeded"})
    conformance.assert_conforms(by_status)
    assert [i["id"] for i in by_status.json()["items"]] == [r2]
    both = client.get(f"{contract.prefix}{RUNS}", params={"pipeline_id": pid, "status": "failed"})
    conformance.assert_conforms(both)
    assert [i["id"] for i in both.json()["items"]] == [r1]
    nobody = client.get(f"{contract.prefix}{RUNS}", params={"pipeline_id": str(uuid.uuid4())})
    conformance.assert_conforms(nobody)
    assert nobody.json()["items"] == [] and nobody.json()["total"] == 0
    p2 = client.get(f"{contract.prefix}{RUNS}", params={"limit": 2, "offset": 1})
    conformance.assert_conforms(p2)
    assert [i["id"] for i in p2.json()["items"]] == [r3, r2] and p2.json()["total"] == 4
    for bad in (
        {"status": "paused"},
        {"pipeline_id": "x"},
        {"limit": 0},
        {"limit": 201},
        {"offset": -1},
    ):
        e = client.get(f"{contract.prefix}{RUNS}", params=bad)
        conformance.assert_conforms(e)
        assert e.status_code == 422, bad


def test_op_getRun(
    client: httpx.Client, conformance: Conformance, contract: Contract, clean: sa.Engine
) -> None:
    _, pid = pipeline_with_source(client, contract)
    done = add_finished_run(clean, pid)  # succeeded; counters 10 = 6 + 2 + 1 + 1
    r = client.get(f"{contract.prefix}{RUNS}/{done}")
    assert conformance.assert_conforms(r).operation_id == "getRun"
    run = r.json()
    assert (
        run["extracted_count"],
        run["loaded_count"],
        run["rejected_count"],
        run["duplicate_dropped_count"],
        run["null_dropped_count"],
    ) == (10, 6, 2, 1, 1)
    assert (
        run["extracted_count"]
        == run["loaded_count"]
        + run["rejected_count"]
        + run["duplicate_dropped_count"]
        + run["null_dropped_count"]
    )
    assert run["duration_ms"] == 2500 and run["pipeline_id"] == pid and run["error_message"] is None
    failed = add_finished_run(
        clean,
        pid,
        status="failed",
        queued_at="2026-10-20T11:00:00Z",
        counters=(4, 0, 1, 0, 0),
        error_message="boom",
    )
    f = client.get(f"{contract.prefix}{RUNS}/{failed}")
    conformance.assert_conforms(f)
    assert (
        f.json()["error_message"] == "boom"
        and f.json()["loaded_count"] == 0
        and f.json()["status"] == "failed"
    )
    live = add_run(clean, pid, "running", "2026-10-20T12:00:00Z")
    with clean.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE runs SET started_at = now(), current_stage = 'transform',"
                " extracted_count = 50, rejected_count = 3 WHERE id = :id"
            ),
            {"id": live},
        )
    lr = client.get(f"{contract.prefix}{RUNS}/{live}")
    conformance.assert_conforms(lr)
    assert (
        lr.json()["duration_ms"] is None
        and lr.json()["current_stage"] == "transform"
        and lr.json()["extracted_count"] == 50
    )
    missing = client.get(f"{contract.prefix}{RUNS}/{uuid.uuid4()}")
    conformance.assert_conforms(missing)
    assert missing.status_code == 404
    conformance.assert_error_body(
        client.get(f"{contract.prefix}{RUNS}/not-a-uuid"), 422, "validation_error"
    )


def test_op_listRunEvents(
    client: httpx.Client, conformance: Conformance, contract: Contract, clean: sa.Engine
) -> None:
    _, pid = pipeline_with_source(client, contract)
    queued = queue_run(client, contract, pid).json()["id"]
    none = client.get(f"{contract.prefix}{RUNS}/{queued}/events")
    assert conformance.assert_conforms(none).operation_id == "listRunEvents"
    assert none.status_code == 200 and none.json() == []
    done = add_finished_run(clean, pid, queued_at="2026-10-21T10:00:00Z")
    plan = [
        ("extract", "started", None, None),
        ("extract", "progress", None, 10),
        ("transform", "started", None, None),
        ("transform", "completed", 10, 8),
        ("load", "failed", 8, None),
        ("publish", "completed", 8, 8),
    ]
    add_events(clean, done, plan)
    r = client.get(f"{contract.prefix}{RUNS}/{done}/events")
    conformance.assert_conforms(r)
    events = r.json()
    assert [
        (e["stage"], e["status"], e["rows_in"], e["rows_out"]) for e in events
    ] == plan  # in insertion order
    assert [e["id"] for e in events] == sorted(e["id"] for e in events) and all(
        e["run_id"] == done for e in events
    )
    assert events[4]["message"] == "note" and events[0]["message"] is None
    missing = client.get(f"{contract.prefix}{RUNS}/{uuid.uuid4()}/events")
    conformance.assert_conforms(missing)
    assert missing.status_code == 404
    conformance.assert_error_body(
        client.get(f"{contract.prefix}{RUNS}/not-a-uuid/events"), 422, "validation_error"
    )


def test_op_listRunRejections(
    client: httpx.Client, conformance: Conformance, contract: Contract, clean: sa.Engine
) -> None:
    _, pid = pipeline_with_source(client, contract)
    done = add_finished_run(clean, pid)
    empty = client.get(f"{contract.prefix}{RUNS}/{done}/rejections")
    assert conformance.assert_conforms(empty).operation_id == "listRunRejections"
    assert empty.json() == {"total": 0, "limit": 50, "offset": 0, "items": []}
    rows = [
        (7, "amount", "type_cast", "cannot cast", "abc"),
        (3, None, "parse_error", "expected 3 fields, found 2", "3,x"),
        (7, "email", "regex", "does not match", "no-at"),
        (12, "id", "not_null", "must not be null", None),
    ] + [(20 + i, "n", "range", "out of range", str(i)) for i in range(6)]
    add_rejections(clean, done, rows)
    page = client.get(f"{contract.prefix}{RUNS}/{done}/rejections")
    conformance.assert_conforms(page)
    items = page.json()["items"]
    assert page.json()["total"] == 10
    assert [i["row_number"] for i in items] == sorted(i["row_number"] for i in items)  # row order
    seven = [i for i in items if i["row_number"] == 7]
    assert [i["rule"] for i in seven] == [
        "type_cast",
        "regex",
    ]  # several entries for one row, kept in insertion order
    first = items[0]
    assert (first["row_number"], first["column"], first["rule"]) == (3, None, "parse_error")
    nullval = next(i for i in items if i["rule"] == "not_null")
    assert nullval["value"] is None
    p2 = client.get(f"{contract.prefix}{RUNS}/{done}/rejections", params={"limit": 4, "offset": 4})
    conformance.assert_conforms(p2)
    assert p2.json()["limit"] == 4 and p2.json()["offset"] == 4 and p2.json()["total"] == 10
    assert [i["row_number"] for i in p2.json()["items"]] == [i["row_number"] for i in items[4:8]]
    beyond = client.get(f"{contract.prefix}{RUNS}/{done}/rejections", params={"offset": 50})
    conformance.assert_conforms(beyond)
    assert beyond.json()["items"] == [] and beyond.json()["total"] == 10
    for bad in ({"limit": 0}, {"limit": 201}, {"offset": -1}):
        e = client.get(f"{contract.prefix}{RUNS}/{done}/rejections", params=bad)
        conformance.assert_conforms(e)
        assert e.status_code == 422, bad
    missing = client.get(f"{contract.prefix}{RUNS}/{uuid.uuid4()}/rejections")
    conformance.assert_conforms(missing)
    assert missing.status_code == 404
    conformance.assert_error_body(
        client.get(f"{contract.prefix}{RUNS}/not-a-uuid/rejections"), 422, "validation_error"
    )


# ----------------------------------------------------------------------------------------------
# BE-06: datasets and metrics (listDatasets, getDataset, listDatasetRows, getDatasetProfile,
# getMetricsSummary). Datasets are published by the real engine (`run_pipeline`) and registered the
# way the worker will (a succeeded run plus a `datasets` row); crafted tables cover edge cases.
# ----------------------------------------------------------------------------------------------

DATASETS = "/datasets"
HIDDEN = ("_localetl_run_id", "_localetl_row_number")


def register_dataset(
    engine: sa.Engine,
    table: str,
    columns: list[tuple[str, str]],
    row_count: int,
    pipeline_id: str | None = None,
    published_at: str = "2026-10-20T12:00:00Z",
) -> str:
    """Insert the registry row (and the succeeded run it points to) for an existing table."""
    run_id, dataset_id = str(uuid.uuid4()), str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO runs (id, pipeline_id, pipeline_name, config_snapshot, config_version,"
                " status, finished_at, extracted_count, loaded_count)"
                " VALUES (:id, :pid, 'p', '{}', 1, 'succeeded', now(), :n, :n)"
            ),
            {"id": run_id, "pid": pipeline_id, "n": row_count},
        )
        conn.execute(
            sa.text(
                "INSERT INTO datasets (id, table_name, pipeline_id, last_run_id, row_count,"
                " columns,"
                " published_at) VALUES (:id, :t, :pid, :run, :n, CAST(:cols AS jsonb), :at)"
            ),
            {
                "id": dataset_id,
                "t": table,
                "pid": pipeline_id,
                "run": run_id,
                "n": row_count,
                "cols": json.dumps([{"name": n, "type": t} for n, t in columns]),
                "at": published_at,
            },
        )
    return dataset_id


def publish_orders(
    engine: sa.Engine, table: str = "orders_clean", published_at: str = "2026-10-20T12:00:00Z"
) -> str:
    """Run the real engine on the clean orders file and register what it published."""
    from app.etl import CsvOptions, run_pipeline, validate_pipeline_config

    config = orders_config()
    config["target"] = {"table": table, "mode": "replace"}  # type: ignore[index]
    result = run_pipeline(
        validate_pipeline_config(config),
        FIXTURE_CSV / "orders_clean.csv",
        CsvOptions(),
        engine,
        uuid.uuid4(),
    )
    assert result.loaded_count == 200
    return register_dataset(
        engine,
        table,
        list(result.published.columns),
        result.published.row_count,
        None,
        published_at,
    )


def craft_table(
    engine: sa.Engine, table: str, ddl_columns: str, rows: list[dict[str, object]]
) -> None:
    """A published-shaped table: the given columns plus the two run-metadata columns."""
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                f'CREATE TABLE datasets."{table}" ({ddl_columns}, _localetl_run_id uuid NOT NULL,'
                " _localetl_row_number bigint NOT NULL)"
            )
        )
        for i, row in enumerate(rows, start=1):
            names = ", ".join(f'"{k}"' for k in row)
            marks = ", ".join(f":{k}" for k in row)
            conn.execute(
                sa.text(
                    f'INSERT INTO datasets."{table}" ({names}, _localetl_run_id,'
                    f" _localetl_row_number) VALUES ({marks}, :rid, :rn)"
                ),
                {**row, "rid": str(uuid.uuid4()), "rn": i},
            )


def test_op_listDatasets(
    client: httpx.Client, conformance: Conformance, contract: Contract, clean: sa.Engine
) -> None:
    empty = client.get(f"{contract.prefix}{DATASETS}")
    assert conformance.assert_conforms(empty).operation_id == "listDatasets"
    assert empty.json() == {"total": 0, "limit": 50, "offset": 0, "items": []}
    a = publish_orders(clean, "orders_a", "2026-10-20T10:00:00Z")
    b = publish_orders(clean, "orders_b", "2026-10-20T11:00:00Z")
    page = client.get(f"{contract.prefix}{DATASETS}")
    conformance.assert_conforms(page)
    assert page.json()["total"] == 2 and [d["id"] for d in page.json()["items"]] == [
        b,
        a,
    ]  # newest first
    first = page.json()["items"][0]
    assert first["table_name"] == "orders_b" and first["row_count"] == 200
    assert [c["name"] for c in first["columns"]] == [
        "order_id",
        "customer_email",
        "country",
        "status",
        "amount",
        "order_date",
        "is_gift",
    ]
    assert not any(c["name"] in HIDDEN for c in first["columns"])
    p2 = client.get(f"{contract.prefix}{DATASETS}", params={"limit": 1, "offset": 1})
    conformance.assert_conforms(p2)
    assert [d["id"] for d in p2.json()["items"]] == [a] and p2.json()["total"] == 2
    for bad in ({"limit": 0}, {"limit": 201}, {"offset": -1}):
        e = client.get(f"{contract.prefix}{DATASETS}", params=bad)
        conformance.assert_conforms(e)
        assert e.status_code == 422, bad


def test_op_getDataset(
    client: httpx.Client, conformance: Conformance, contract: Contract, clean: sa.Engine
) -> None:
    did = publish_orders(clean)
    r = client.get(f"{contract.prefix}{DATASETS}/{did}")
    assert conformance.assert_conforms(r).operation_id == "getDataset"
    body_ = r.json()
    assert (
        body_["id"] == did and body_["table_name"] == "orders_clean" and body_["row_count"] == 200
    )
    assert {c["name"]: c["type"] for c in body_["columns"]}["amount"] == "float"
    assert body_["pipeline_id"] is None
    missing = client.get(f"{contract.prefix}{DATASETS}/{uuid.uuid4()}")
    conformance.assert_conforms(missing)
    assert missing.status_code == 404
    conformance.assert_error_body(
        client.get(f"{contract.prefix}{DATASETS}/not-a-uuid"), 422, "validation_error"
    )


def test_op_listDatasetRows(
    client: httpx.Client, conformance: Conformance, contract: Contract, clean: sa.Engine
) -> None:
    did = publish_orders(clean)
    url = f"{contract.prefix}{DATASETS}/{did}/rows"
    r = client.get(url)
    assert conformance.assert_conforms(r).operation_id == "listDatasetRows"
    page = r.json()
    assert (
        page["total"] == 200
        and page["limit"] == 50
        and page["offset"] == 0
        and len(page["items"]) == 50
    )
    names = [c["name"] for c in page["columns"]]
    assert all(list(item) == names for item in page["items"])  # registry columns only, in order
    assert not any(k in item for item in page["items"] for k in HIDDEN)
    ids = [item["order_id"] for item in page["items"]]
    assert ids == sorted(ids) and ids[0] == 1  # default: file (row) order
    first = page["items"][0]
    assert isinstance(first["order_id"], int) and isinstance(first["amount"], float)
    assert isinstance(first["order_date"], str) and len(first["order_date"]) == 10  # ISO date
    p2 = client.get(url, params={"limit": 5, "offset": 10})
    conformance.assert_conforms(p2)
    assert [i["order_id"] for i in p2.json()["items"]] == ids_range(11, 15)
    assert p2.json()["offset"] == 10 and len(p2.json()["items"]) == 5
    desc = client.get(url, params={"sort": "order_id", "order": "desc", "limit": 3})
    conformance.assert_conforms(desc)
    assert [i["order_id"] for i in desc.json()["items"]] == [200, 199, 198]
    asc = client.get(url, params={"sort": "amount", "limit": 200})
    conformance.assert_conforms(asc)
    amounts = [i["amount"] for i in asc.json()["items"]]
    assert amounts == sorted(amounts)
    beyond = client.get(url, params={"offset": 500})
    conformance.assert_conforms(beyond)
    assert beyond.json()["items"] == [] and beyond.json()["total"] == 200


def ids_range(a: int, b: int) -> list[int]:
    return list(range(a, b + 1))


@pytest.mark.parametrize(
    "bad",
    [
        {"sort": "nope"},
        {"sort": "_localetl_row_number"},
        {"sort": "_localetl_run_id"},
        {"sort": "order_id; DROP TABLE runs;--"},
        {"sort": 'order_id" DESC, (SELECT 1)--'},
        {"order": "sideways"},
        {"limit": 0},
        {"limit": 201},
        {"offset": -1},
    ],
)
def test_listDatasetRows_422_and_nothing_executed(
    client: httpx.Client,
    conformance: Conformance,
    contract: Contract,
    clean: sa.Engine,
    bad: dict[str, object],
) -> None:
    did = publish_orders(clean)
    r = client.get(f"{contract.prefix}{DATASETS}/{did}/rows", params=bad)
    conformance.assert_conforms(r)
    assert r.status_code == 422, bad
    if "sort" in bad:
        assert [d["path"] for d in r.json()["error"]["details"]] == ["/sort"]
    assert count(clean, "runs") == 1  # the injection attempt did not touch other tables


def test_listDatasetRows_nulls_types_and_hostile_names(
    client: httpx.Client, conformance: Conformance, contract: Contract, clean: sa.Engine
) -> None:
    """Reserved words as table and column names work because identifiers are quoted."""
    craft_table(
        clean,
        "order",
        '"group" bigint, "select" text, "user" boolean, "when" date, "ts" timestamp,'
        ' "x" double precision',
        [
            {
                "group": 2,
                "select": "b",
                "user": True,
                "when": dt.date(2026, 1, 2),
                "ts": dt.datetime(2026, 1, 2, 3, 4, 5),
                "x": 1.5,
            },
            {"group": 1, "select": None, "user": False, "when": None, "ts": None, "x": None},
        ],
    )
    did = register_dataset(
        clean,
        "order",
        [
            ("group", "integer"),
            ("select", "string"),
            ("user", "boolean"),
            ("when", "date"),
            ("ts", "datetime"),
            ("x", "float"),
        ],
        2,
    )
    r = client.get(f"{contract.prefix}{DATASETS}/{did}/rows")
    conformance.assert_conforms(r)
    items = r.json()["items"]
    assert items[0] == {
        "group": 2,
        "select": "b",
        "user": True,
        "when": "2026-01-02",
        "ts": "2026-01-02T03:04:05",
        "x": 1.5,
    }
    assert items[1] == {
        "group": 1,
        "select": None,
        "user": False,
        "when": None,
        "ts": None,
        "x": None,
    }
    by_group = client.get(f"{contract.prefix}{DATASETS}/{did}/rows", params={"sort": "group"})
    conformance.assert_conforms(by_group)
    assert [i["group"] for i in by_group.json()["items"]] == [1, 2]
    by_select = client.get(
        f"{contract.prefix}{DATASETS}/{did}/rows", params={"sort": "select", "order": "desc"}
    )
    conformance.assert_conforms(by_select)
    assert len(by_select.json()["items"]) == 2


def test_dataset_registry_problems_are_contract_errors(
    client: httpx.Client, conformance: Conformance, contract: Contract, clean: sa.Engine
) -> None:
    missing_table = register_dataset(clean, "never_created", [("a", "integer")], 0)
    for suffix in ("rows", "profile"):
        r = client.get(f"{contract.prefix}{DATASETS}/{missing_table}/{suffix}")
        conformance.assert_error_body(r, 500, "internal_error")
    bad_name = register_dataset(clean, "Bad Name; DROP TABLE runs", [("a", "integer")], 0)
    r = client.get(f"{contract.prefix}{DATASETS}/{bad_name}/rows")
    conformance.assert_error_body(r, 500, "internal_error")
    assert count(clean, "runs") == 2  # nothing was executed
    # the metadata endpoints still work for those rows
    conformance.assert_conforms(client.get(f"{contract.prefix}{DATASETS}/{bad_name}"))


def test_op_getDatasetProfile(
    client: httpx.Client, conformance: Conformance, contract: Contract, clean: sa.Engine
) -> None:
    rows = [
        {
            "id": i,
            "name": f"n{i % 12:02d}" if i % 5 else None,
            "score": float(i) / 2,
            "flag": i % 2 == 0,
            "d": dt.date(2026, 1, 1) + dt.timedelta(days=i),
            "ts": dt.datetime(2026, 1, 1, 0, 0, 0) + dt.timedelta(hours=i),
            "empty": None,
        }
        for i in range(1, 31)
    ]
    craft_table(
        clean,
        "prof",
        "id bigint, name text, score double precision, flag boolean, d date, ts timestamp,"
        " empty text",
        rows,
    )
    did = register_dataset(
        clean,
        "prof",
        [
            ("id", "integer"),
            ("name", "string"),
            ("score", "float"),
            ("flag", "boolean"),
            ("d", "date"),
            ("ts", "datetime"),
            ("empty", "string"),
        ],
        30,
    )
    r = client.get(f"{contract.prefix}{DATASETS}/{did}/profile")
    assert conformance.assert_conforms(r).operation_id == "getDatasetProfile"
    prof = r.json()
    assert prof["dataset_id"] == did and prof["row_count"] == 30
    cols = {c["name"]: c for c in prof["columns"]}
    assert list(cols) == [
        "id",
        "name",
        "score",
        "flag",
        "d",
        "ts",
        "empty",
    ]  # registry order, no _localetl_*
    assert (
        cols["id"]["null_count"],
        cols["id"]["distinct_count"],
        cols["id"]["min"],
        cols["id"]["max"],
    ) == (0, 30, 1, 30)
    assert cols["score"]["min"] == 0.5 and cols["score"]["max"] == 15.0
    assert (
        cols["name"]["null_count"] == 6
        and cols["name"]["min"] is None
        and cols["name"]["max"] is None
    )
    assert cols["name"]["distinct_count"] == 12
    assert cols["flag"]["min"] is None and cols["flag"]["distinct_count"] == 2
    assert cols["d"]["min"] == "2026-01-02" and cols["d"]["max"] == "2026-01-31"
    assert cols["ts"]["min"] == "2026-01-01T01:00:00" and cols["ts"]["max"] == "2026-01-02T06:00:00"
    assert (
        cols["empty"]["null_count"],
        cols["empty"]["distinct_count"],
        cols["empty"]["top_values"],
    ) == (30, 0, [])
    top = cols["id"]["top_values"]
    assert len(top) == 10  # at most 10
    name_top = cols["name"]["top_values"]
    assert len(name_top) == 10 and [t["count"] for t in name_top] == sorted(
        (t["count"] for t in name_top), reverse=True
    )
    assert sum(t["count"] for t in cols["flag"]["top_values"]) == 30
    missing = client.get(f"{contract.prefix}{DATASETS}/{uuid.uuid4()}/profile")
    conformance.assert_conforms(missing)
    assert missing.status_code == 404
    conformance.assert_error_body(
        client.get(f"{contract.prefix}{DATASETS}/not-a-uuid/profile"), 422, "validation_error"
    )


def utc_day(offset: int) -> dt.date:
    return dt.datetime.now(dt.UTC).date() - dt.timedelta(days=offset)


def add_metric_run(
    engine: sa.Engine,
    status: str,
    finished: dt.datetime | None,
    duration_s: float | None,
    loaded: int = 0,
    extracted: int | None = None,
) -> None:
    started = (
        finished - dt.timedelta(seconds=duration_s) if finished and duration_s is not None else None
    )
    if extracted is None:
        extracted = loaded if status == "succeeded" else 0
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO runs (pipeline_name, config_snapshot, config_version, status,"
                " started_at,"
                " finished_at, extracted_count, loaded_count) VALUES ('p', '{}', 1,"
                " CAST(:s AS run_status), :st, :fi, :ex, :lo)"
            ),
            {"s": status, "st": started, "fi": finished, "ex": extracted, "lo": loaded},
        )


def at(day: dt.date, hour: int, minute: int = 0) -> dt.datetime:
    return dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=dt.UTC)


def test_op_getMetricsSummary(
    client: httpx.Client, conformance: Conformance, contract: Contract, clean: sa.Engine
) -> None:
    url = f"{contract.prefix}/metrics/summary"
    empty = client.get(url)
    assert conformance.assert_conforms(empty).operation_id == "getMetricsSummary"
    e = empty.json()
    assert e["total_runs"] == 0 and e["loaded_count_total"] == 0 and e["avg_duration_ms"] is None
    assert e["runs_by_status"] == {
        "queued": 0,
        "running": 0,
        "succeeded": 0,
        "failed": 0,
        "interrupted": 0,
    }
    assert len(e["daily"]) == 30
    expected_days = [str(utc_day(29 - i)) for i in range(30)]
    assert [
        d["date"] for d in e["daily"]
    ] == expected_days  # ascending, ending today (UTC), zero-filled
    assert all(
        d == {"date": d["date"], "succeeded": 0, "failed": 0, "interrupted": 0, "loaded_count": 0}
        for d in e["daily"]
    )
    today, yday = utc_day(0), utc_day(1)
    add_metric_run(clean, "succeeded", at(today, 1, 0), 2.0, loaded=5)
    add_metric_run(clean, "succeeded", at(yday, 23, 30), 4.0, loaded=7)
    add_metric_run(clean, "failed", at(yday, 10), 1.0, extracted=3)
    add_metric_run(clean, "interrupted", at(utc_day(3), 12), None)
    with clean.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO runs (pipeline_name, config_snapshot, config_version, status)"
                " VALUES ('q', '{}', 1, 'queued')"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO runs (pipeline_name, config_snapshot, config_version, status,"
                " started_at) VALUES ('r', '{}', 1, 'running', now())"
            )
        )
    r = client.get(url)
    conformance.assert_conforms(r)
    m = r.json()
    assert m["total_runs"] == 6
    assert m["runs_by_status"] == {
        "queued": 1,
        "running": 1,
        "succeeded": 2,
        "failed": 1,
        "interrupted": 1,
    }
    assert m["loaded_count_total"] == 12  # succeeded runs only
    assert m["avg_duration_ms"] == pytest.approx((2000 + 4000 + 1000) / 3)
    daily = {d["date"]: d for d in m["daily"]}
    assert daily[str(today)] == {
        "date": str(today),
        "succeeded": 1,
        "failed": 0,
        "interrupted": 0,
        "loaded_count": 5,
    }
    assert daily[str(yday)] == {
        "date": str(yday),
        "succeeded": 1,
        "failed": 1,
        "interrupted": 0,
        "loaded_count": 7,
    }  # 23:30 UTC stays on its UTC day
    assert (
        daily[str(utc_day(3))]["interrupted"] == 1 and daily[str(utc_day(3))]["loaded_count"] == 0
    )
    assert (
        sum(d["succeeded"] + d["failed"] + d["interrupted"] for d in m["daily"]) == 4
    )  # queued/running are not bucketed
    assert sum(d["loaded_count"] for d in m["daily"]) == 12


def test_getMetricsSummary_days_window(
    client: httpx.Client, conformance: Conformance, contract: Contract, clean: sa.Engine
) -> None:
    url = f"{contract.prefix}/metrics/summary"
    add_metric_run(clean, "succeeded", at(utc_day(0), 1), 1.0, loaded=1)
    add_metric_run(clean, "succeeded", at(utc_day(20), 1), 1.0, loaded=10)
    seven = client.get(url, params={"days": 7})
    conformance.assert_conforms(seven)
    assert len(seven.json()["daily"]) == 7 and seven.json()["daily"][-1]["date"] == str(utc_day(0))
    assert seven.json()["loaded_count_total"] == 11  # totals are not limited to the window
    assert sum(d["loaded_count"] for d in seven.json()["daily"]) == 1
    one = client.get(url, params={"days": 1})
    conformance.assert_conforms(one)
    assert [d["date"] for d in one.json()["daily"]] == [str(utc_day(0))]
    year = client.get(url, params={"days": 365})
    conformance.assert_conforms(year)
    assert len(year.json()["daily"]) == 365
    for bad in ({"days": 0}, {"days": 366}, {"days": "x"}):
        e = client.get(url, params=bad)
        conformance.assert_conforms(e)
        assert e.status_code == 422, bad
