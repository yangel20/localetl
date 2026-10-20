"""BE-06: the served OpenAPI must not drift from contracts/openapi.yaml.

Compared per operation: path + method, operationId, parameters (name, location, required, type,
bounds, enum, default), request body media types, success status code, and the *shape* of the
success response (property names and required sets, recursively). Documented error responses are
checked separately by tests/integration and by the per-endpoint API tests.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

CONTRACT_PATH = Path(__file__).resolve().parents[3] / "contracts" / "openapi.yaml"
PREFIX = "/api/v1"
METHODS = ("get", "post", "put", "delete", "patch")


def _resolve(doc: dict[str, Any], node: Any) -> Any:
    """Follow local $refs; external-file refs are opaque (None)."""
    while isinstance(node, dict) and "$ref" in node:
        ref = node["$ref"]
        if not ref.startswith("#/"):
            return None
        target: Any = doc
        for part in ref[2:].split("/"):
            target = target[part]
        node = target
    return node


def _shape(doc: dict[str, Any], node: Any) -> Any:
    """Recursive property-name/required shape; free-form or opaque nodes collapse to None."""
    node = _resolve(doc, node)
    if not isinstance(node, dict):
        return None
    if "allOf" in node:
        merged: dict[str, Any] = {"properties": {}, "required": []}
        for part in node["allOf"]:
            sub = _resolve(doc, part)
            if sub is None:
                return None
            merged["properties"].update(sub.get("properties", {}))
            merged["required"] += sub.get("required", [])
        node = merged
    if "oneOf" in node or "anyOf" in node:
        return None
    if node.get("type") == "array" or "items" in node:
        return {"items": _shape(doc, node.get("items", {}))}
    props = node.get("properties")
    if not props:
        return None
    return {
        "properties": {k: _shape(doc, v) for k, v in sorted(props.items())},
        "required": sorted(set(node.get("required", []))),
    }


def _compatible(contract: Any, served: Any, where: str) -> list[str]:
    if contract is None or served is None:
        return []  # free-form / opaque on either side: nothing to compare
    problems: list[str] = []
    if ("items" in contract) != ("items" in served):
        return [f"{where}: array vs object"]
    if "items" in contract:
        return _compatible(contract["items"], served["items"], f"{where}[]")
    if set(contract["properties"]) != set(served["properties"]):
        problems.append(
            f"{where}: properties differ: contract={sorted(contract['properties'])} "
            f"served={sorted(served['properties'])}"
        )
    if contract["required"] != served["required"]:
        problems.append(
            f"{where}: required differs: contract={contract['required']} "
            f"served={served['required']}"
        )
    for name in set(contract["properties"]) & set(served["properties"]):
        problems += _compatible(
            contract["properties"][name], served["properties"][name], f"{where}.{name}"
        )
    return problems


def _non_null(doc: dict[str, Any], node: Any) -> Any:
    """`X | None` renders as anyOf [X, null]; compare X."""
    node = _resolve(doc, node)
    if isinstance(node, dict) and "anyOf" in node:
        rest = [n for n in node["anyOf"] if n.get("type") != "null"]
        if len(rest) == 1:
            return rest[0]
    return node


def _params(doc: dict[str, Any], path_item: dict[str, Any], op: dict[str, Any]) -> dict[Any, Any]:
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in [*path_item.get("parameters", []), *op.get("parameters", [])]:
        p = _resolve(doc, raw)
        schema = _resolve(doc, _non_null(doc, p.get("schema", {})))
        opaque = schema is None  # external ref (pipeline.schema.json): compare presence only
        schema = schema or {}
        found[(p["in"], p["name"])] = {
            "required": bool(p.get("required", False)),
            "opaque": opaque,
            "type": schema.get("type"),
            "format": schema.get("format"),
            "minimum": schema.get("minimum"),
            "maximum": schema.get("maximum"),
            "default": schema.get("default"),
            "enum": schema.get("enum"),
        }
    return found


def _success(op: dict[str, Any]) -> list[str]:
    return sorted(code for code in op["responses"] if str(code).startswith("2"))


def _operations(doc: dict[str, Any], prefix: str) -> dict[str, tuple[str, str, dict[str, Any]]]:
    out: dict[str, tuple[str, str, dict[str, Any]]] = {}
    for path, item in doc["paths"].items():
        for method in METHODS:
            if method in item:
                out[item[method]["operationId"]] = (prefix + path, method, item)
    return out


@pytest.fixture(scope="module")
def contract() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(CONTRACT_PATH.read_text())
    return loaded


@pytest.fixture
def served(api_client: TestClient) -> dict[str, Any]:
    spec: dict[str, Any] = api_client.get("/openapi.json").json()
    return spec


def test_all_22_operations_are_served_with_the_contract_path_and_method(
    contract: dict[str, Any], served: dict[str, Any]
) -> None:
    want = _operations(contract, PREFIX)
    have = _operations(served, "")
    assert len(want) == 22
    assert {k: v[:2] for k, v in want.items()} == {k: v[:2] for k, v in have.items()}


def _op_ids(contract: dict[str, Any]) -> list[str]:
    return sorted(_operations(contract, PREFIX))


def test_parameters_match_the_contract(contract: dict[str, Any], served: dict[str, Any]) -> None:
    want, have = _operations(contract, PREFIX), _operations(served, "")
    problems: list[str] = []
    for op_id, (_, method, item) in want.items():
        expected = _params(contract, item, item[method])
        s_item = have[op_id][2]
        actual = _params(served, s_item, s_item[method])
        for key, spec in expected.items():
            if key not in actual:
                problems.append(f"{op_id}: missing parameter {key}")
            elif spec["opaque"] and actual[key]["required"] == spec["required"]:
                continue
            elif actual[key] != spec:
                problems.append(f"{op_id}: parameter {key} differs: {spec} vs {actual[key]}")
        for key in set(actual) - set(expected):
            problems.append(f"{op_id}: unexpected parameter {key}")
    assert not problems, "\n".join(problems)


def test_request_bodies_match_the_contract(
    contract: dict[str, Any], served: dict[str, Any]
) -> None:
    want, have = _operations(contract, PREFIX), _operations(served, "")
    problems: list[str] = []
    for op_id, (_, method, item) in want.items():
        c_body = item[method].get("requestBody")
        s_item = have[op_id][2]
        s_body = s_item[method].get("requestBody")
        if (c_body is None) != (s_body is None):
            problems.append(f"{op_id}: requestBody presence differs")
            continue
        if c_body is None:
            continue
        if sorted(c_body["content"]) != sorted(s_body["content"]):
            problems.append(f"{op_id}: media types differ")
            continue
        for media, c_media in c_body["content"].items():
            problems += _compatible(
                _shape(contract, c_media["schema"]),
                _shape(served, s_body["content"][media]["schema"]),
                f"{op_id} request",
            )
    assert not problems, "\n".join(problems)


def test_success_status_and_response_shape_match_the_contract(
    contract: dict[str, Any], served: dict[str, Any]
) -> None:
    want, have = _operations(contract, PREFIX), _operations(served, "")
    problems: list[str] = []
    for op_id, (_, method, item) in want.items():
        c_op = item[method]
        s_op = have[op_id][2][method]
        if _success(c_op) != _success(s_op):
            problems.append(f"{op_id}: success codes {_success(c_op)} vs {_success(s_op)}")
            continue
        for code in _success(c_op):
            c_content = c_op["responses"][code].get("content")
            s_content = s_op["responses"][code].get("content")
            if (c_content is None) != (s_content is None):
                problems.append(f"{op_id} {code}: response body presence differs")
                continue
            if c_content is None:
                continue
            c_schema = c_content["application/json"]["schema"]
            s_schema = s_content["application/json"]["schema"]
            problems += _compatible(
                _shape(contract, c_schema), _shape(served, s_schema), f"{op_id} {code}"
            )
    assert not problems, "\n".join(problems)


def test_drift_checker_detects_a_changed_response(
    contract: dict[str, Any], served: dict[str, Any]
) -> None:
    """The comparison is not vacuous: removing a property from a served schema is reported."""
    ok = _compatible(
        _shape(contract, {"$ref": "#/components/schemas/Run"}),
        _shape(served, {"$ref": "#/components/schemas/RunOut"}),
        "Run",
    )
    assert ok == []
    broken = _shape(served, {"$ref": "#/components/schemas/RunOut"})
    del broken["properties"]["duration_ms"]
    assert _compatible(_shape(contract, {"$ref": "#/components/schemas/Run"}), broken, "Run")
