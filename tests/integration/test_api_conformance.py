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

import json
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest
from fastapi import FastAPI
from referencing.exceptions import Unresolvable

if TYPE_CHECKING:  # fixtures and helpers live in conftest.py (no package: no relative import)
    from conftest import Conformance, Contract

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"

pytestmark = pytest.mark.db

COVERED = "covered"

COVERAGE: dict[str, str] = {
    "getHealth": COVERED,
    "createSource": "pending: BE-03",
    "listSources": "pending: BE-03",
    "getSource": "pending: BE-03",
    "deleteSource": "pending: BE-03",
    "previewSource": "pending: BE-03",
    "createPipeline": "pending: BE-04",
    "listPipelines": "pending: BE-04",
    "validatePipelineConfig": "pending: BE-04",
    "getPipeline": "pending: BE-04",
    "updatePipeline": "pending: BE-04",
    "deletePipeline": "pending: BE-04",
    "createRun": "pending: BE-05",
    "listRuns": "pending: BE-05",
    "getRun": "pending: BE-05",
    "listRunEvents": "pending: BE-05",
    "listRunRejections": "pending: BE-05",
    "listDatasets": "pending: BE-06",
    "getDataset": "pending: BE-06",
    "listDatasetRows": "pending: BE-06",
    "getDatasetProfile": "pending: BE-06",
    "getMetricsSummary": "pending: BE-06",
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
    from app.core.db import get_engine
    from fastapi.testclient import TestClient

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
