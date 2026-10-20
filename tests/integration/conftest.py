"""API conformance harness (QA-05): responses are validated against contracts/openapi.yaml.

Design (docs/qa, QA-05 proposal):
* The app runs in-process (``TestClient``). Set ``LOCALETL_API_URL`` to run the same tests against
  a live server instead (it must already point at a migrated database).
* ``assert_conforms`` resolves the operation from method + path, requires the status to be one the
  contract declares, validates the body with JSON Schema 2020-12 (OpenAPI 3.1 schemas are plain
  JSON Schema) and checks the ``Error`` shape for every non-2xx response.
* The contract's external ``$ref`` into ``pipeline.schema.json`` is resolved through a
  ``referencing`` registry; nothing is fetched from the network.
* Each test module gets a throwaway database on the ``TEST_DATABASE_URL`` server, migrated with
  ``alembic upgrade head`` and dropped afterwards. No other database is touched.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
import pytest
import sqlalchemy as sa
import yaml
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
CONTRACTS = REPO_ROOT / "contracts"
OPENAPI_URI = "https://localetl.local/contracts/openapi.yaml"
HTTP_METHODS = ("get", "post", "put", "patch", "delete")

DEFAULT_TEST_DATABASE_URL = "postgresql+psycopg://localetl:localetl@127.0.0.1:5432/localetl_test"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "db: tests that need PostgreSQL at TEST_DATABASE_URL")


# ----------------------------------------------------------------------------- contract model


@dataclass(frozen=True)
class Operation:
    operation_id: str
    method: str  # upper case
    template: str  # as written in the contract, e.g. /sources/{source_id}
    pattern: re.Pattern[str]  # matches the path below the server prefix
    responses: dict[str, Any]


def _template_regex(template: str) -> re.Pattern[str]:
    """``/sources/{source_id}`` -> a regex matching one path segment per parameter."""
    parts = re.split(r"\{[^/}]+\}", template)
    return re.compile("^" + "[^/]+".join(re.escape(p) for p in parts) + "$")


class Contract:
    """Loads openapi.yaml and answers "which operation, which response schema"."""

    def __init__(self) -> None:
        self.doc: dict[str, Any] = yaml.safe_load((CONTRACTS / "openapi.yaml").read_text("utf-8"))
        pipeline_schema = json.loads((CONTRACTS / "pipeline.schema.json").read_text("utf-8"))
        self.registry: Registry[Any] = Registry().with_resources(
            [
                (OPENAPI_URI, Resource.from_contents(self.doc, default_specification=DRAFT202012)),
                (
                    pipeline_schema["$id"],
                    Resource.from_contents(pipeline_schema, default_specification=DRAFT202012),
                ),
            ]
        )
        self.prefix = urlsplit(self.doc["servers"][0]["url"]).path.rstrip("/")
        self.operations: dict[str, Operation] = {}
        for template, item in self.doc["paths"].items():
            for method in HTTP_METHODS:
                if method in item:
                    op = item[method]
                    self.operations[op["operationId"]] = Operation(
                        operation_id=op["operationId"],
                        method=method.upper(),
                        template=template,
                        pattern=_template_regex(template),
                        responses=op["responses"],
                    )
        self.error_schema_ref = f"{OPENAPI_URI}#/components/schemas/Error"

    # -- lookup
    def operation_for(self, method: str, path: str) -> Operation | None:
        below = path[len(self.prefix) :] if path.startswith(self.prefix) else None
        if below is None:
            return None
        for op in self.operations.values():
            if op.method == method.upper() and op.pattern.match(below):
                return op
        return None

    def path_exists(self, path: str) -> bool:
        below = path[len(self.prefix) :] if path.startswith(self.prefix) else ""
        return any(op.pattern.match(below) for op in self.operations.values())

    # -- schema resolution
    def _jump(self, node: Any, done: list[str]) -> tuple[Any, list[str]]:
        """If ``node`` is a local ``$ref``, move to its target (repeatedly)."""
        while isinstance(node, dict) and str(node.get("$ref", "")).startswith("#/"):
            done = [p.replace("~1", "/").replace("~0", "~") for p in node["$ref"][2:].split("/")]
            node = self.doc
            for part in done:
                node = node[part]
        return node, done

    def _walk(self, pointer: list[str]) -> list[str]:
        """Follow ``pointer`` through the document, jumping over local ``$ref`` nodes on the way
        (including one that is the final node), and return the resolved pointer."""
        node: Any = self.doc
        done: list[str] = []
        for part in pointer:
            node, done = self._jump(node, done)
            node = node[part]
            done = [*done, part]
        _, done = self._jump(node, done)
        return done

    def response_schema_ref(self, op: Operation, status: int) -> str | None:
        """``$ref`` URI of the JSON body schema for ``op``/``status``, or None for "no body"."""
        resolved = self._walk(["paths", op.template, op.method.lower(), "responses", str(status)])
        probe: Any = self.doc
        for part in resolved:
            probe = probe[part]
        if "content" not in probe:
            return None
        pointer = self._walk([*resolved, "content", "application/json", "schema"])
        return (
            OPENAPI_URI
            + "#/"
            + "/".join(quote(p.replace("~", "~0").replace("/", "~1"), safe="~") for p in pointer)
        )

    def validator(self, ref: str) -> Draft202012Validator:
        return Draft202012Validator(
            {"$ref": ref}, registry=self.registry, format_checker=FormatChecker()
        )


@pytest.fixture(scope="session")
def contract() -> Contract:
    return Contract()


# -------------------------------------------------------------------------------- the checker


class Conformance:
    def __init__(self, contract: Contract) -> None:
        self.contract = contract

    def assert_error_body(
        self, response: httpx.Response, status: int, code: str | None = None
    ) -> None:
        """The body is a contract ``Error`` (for statuses that are global, not per operation)."""
        assert response.status_code == status, (response.status_code, response.text)
        assert response.headers.get("content-type", "").startswith("application/json"), (
            response.headers
        )
        body = response.json()
        errors = sorted(
            self.contract.validator(self.contract.error_schema_ref).iter_errors(body),
            key=lambda e: list(e.absolute_path),
        )
        assert not errors, [f"{list(e.absolute_path)}: {e.message}" for e in errors]
        if code is not None:
            assert body["error"]["code"] == code, body

    def assert_conforms(self, response: httpx.Response) -> Operation:
        """Status is declared for the operation; the body matches the declared schema."""
        request = response.request
        op = self.contract.operation_for(request.method, request.url.path)
        assert op is not None, f"no contract operation for {request.method} {request.url.path}"
        status = response.status_code
        declared = [int(s) for s in op.responses if s.isdigit()]
        assert status in declared, (
            f"{op.operation_id}: status {status} not declared in the contract {sorted(declared)}; "
            f"body={response.text[:300]}"
        )
        ref = self.contract.response_schema_ref(op, status)
        if ref is None:
            assert response.content == b"", f"{op.operation_id}: {status} must have no body"
        else:
            assert response.headers.get("content-type", "").startswith("application/json"), (
                op.operation_id,
                response.headers.get("content-type"),
            )
            errors = sorted(
                self.contract.validator(ref).iter_errors(response.json()),
                key=lambda e: list(e.absolute_path),
            )
            assert not errors, [
                f"{op.operation_id} {list(e.absolute_path)}: {e.message}" for e in errors
            ]
        if status >= 400:
            self.assert_error_body(response, status)
        return op


@pytest.fixture(scope="session")
def conformance(contract: Contract) -> Conformance:
    return Conformance(contract)


# ------------------------------------------------------------------------------- app + database


def _server_url() -> sa.URL:
    return sa.engine.make_url(os.environ.get("TEST_DATABASE_URL") or DEFAULT_TEST_DATABASE_URL)


@pytest.fixture(scope="module")
def scratch_url() -> Iterator[str]:
    """A throwaway, migrated database on the TEST_DATABASE_URL server (dropped WITH FORCE)."""
    base = _server_url()
    name = f"localetl_api_{uuid.uuid4().hex[:12]}"
    admin = sa.create_engine(base, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    url = base.set(database=name).render_as_string(hide_password=False)
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    try:
        command.upgrade(cfg, "head")
        yield url
    finally:
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("localetl-data")


@pytest.fixture(scope="module")
def app_under_test(scratch_url: str, data_dir: Path) -> Iterator[FastAPI]:
    from app.core.db import get_engine, make_engine
    from app.core.settings import get_settings
    from app.main import create_app

    patch = pytest.MonkeyPatch()
    patch.setenv("DATABASE_URL", scratch_url)
    patch.setenv("LOCALETL_DATA_DIR", str(data_dir))
    get_settings.cache_clear()
    engine = make_engine(scratch_url)
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: engine
    try:
        yield app
    finally:
        engine.dispose()
        patch.undo()
        get_settings.cache_clear()


@pytest.fixture(scope="module")
def api(app_under_test: FastAPI, contract: Contract) -> Iterator[Callable[[], httpx.Client]]:
    """Factory for an HTTP client rooted at the contract's server prefix.

    ``LOCALETL_API_URL`` (e.g. ``http://127.0.0.1:8000``) switches to a live server.
    """
    live = os.environ.get("LOCALETL_API_URL")

    def make() -> httpx.Client:
        if live:
            return httpx.Client(base_url=live.rstrip("/"), timeout=30)
        return TestClient(app_under_test, raise_server_exceptions=False)

    yield make


@pytest.fixture
def client(api: Callable[[], httpx.Client]) -> Iterator[httpx.Client]:
    with api() as c:
        yield c


@pytest.fixture(scope="session")
def mounted_paths() -> Callable[[FastAPI], list[tuple[str, str]]]:
    """(METHOD, path template) for every operation the app serves, including the server prefix.

    Read from the app's own generated OpenAPI document, not from ``app.routes``: FastAPI's
    internal router classes change between releases, the public schema does not. (A route hidden
    with ``include_in_schema=False`` would not be listed; BE-06's drift test covers that.)
    """

    def collect(app: FastAPI) -> list[tuple[str, str]]:
        served: list[tuple[str, str]] = []
        for path, item in app.openapi().get("paths", {}).items():
            for method in item:
                if method in HTTP_METHODS:
                    served.append((method.upper(), path))
        return served

    return collect
