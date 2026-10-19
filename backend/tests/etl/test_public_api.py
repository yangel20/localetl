"""ETL-01: the public interface matches docs/architecture.md section 5."""

from __future__ import annotations

import ast
import dataclasses
import inspect
from pathlib import Path
from typing import get_args

import pytest

import app.etl as etl

EXPECTED_EXPORTS = {
    "ColumnInfo", "ColumnType", "ConfigErrorItem", "ConfigValidationError",
    "CsvFormatError", "CsvOptions", "CsvPreview", "CsvProfile", "EtlError",
    "EventStatus", "LoadError", "PipelineConfig", "PublishedTable",
    "RejectedRow", "RejectionLimitExceeded", "RejectionRule", "RunInterrupted",
    "RunResult", "SourceMismatchError", "Stage", "StageEvent", "inspect_csv",
    "preview_csv", "run_pipeline", "validate_pipeline_config",
}  # fmt: skip

DATACLASSES = [
    etl.CsvOptions, etl.ColumnInfo, etl.CsvProfile, etl.CsvPreview,
    etl.ConfigErrorItem, etl.PipelineConfig, etl.StageEvent, etl.RejectedRow,
    etl.PublishedTable, etl.RunResult,
]  # fmt: skip

ETL_DIR = Path(etl.__file__).resolve().parent


def test_export_list_is_exact() -> None:
    assert set(etl.__all__) == EXPECTED_EXPORTS
    assert len(etl.__all__) == len(set(etl.__all__))
    for name in etl.__all__:
        assert hasattr(etl, name)


def test_literal_values() -> None:
    assert get_args(etl.ColumnType) == ("integer", "float", "boolean", "date", "datetime", "string")
    assert get_args(etl.Stage) == ("extract", "transform", "validate", "load", "publish")
    assert get_args(etl.EventStatus) == ("started", "progress", "completed", "failed")
    assert get_args(etl.RejectionRule) == (
        "not_null", "unique", "range", "allowed_values", "regex", "length",
        "type_cast", "parse_error",
    )  # fmt: skip


@pytest.mark.parametrize("cls", DATACLASSES)
def test_dataclasses_are_frozen(cls: type) -> None:
    assert dataclasses.is_dataclass(cls)
    assert cls.__dataclass_params__.frozen  # type: ignore[attr-defined]


def test_dataclass_fields() -> None:
    def names(cls: type) -> list[str]:
        return [f.name for f in dataclasses.fields(cls)]

    assert names(etl.CsvOptions) == ["encoding", "delimiter", "has_header", "quote_char"]
    assert names(etl.ColumnInfo) == ["name", "inferred_type", "null_count"]
    assert names(etl.CsvProfile) == ["columns", "row_count"]
    assert names(etl.CsvPreview) == ["columns", "rows", "sampled_rows"]
    assert names(etl.ConfigErrorItem) == ["path", "message"]
    assert names(etl.PipelineConfig)[0] == "raw"
    assert names(etl.StageEvent) == ["stage", "status", "rows_in", "rows_out", "message", "at"]
    assert names(etl.RejectedRow) == ["row_number", "column", "rule", "message", "value"]
    assert names(etl.PublishedTable) == ["schema", "table", "columns", "row_count"]
    assert names(etl.RunResult) == [
        "rows_read", "rows_rejected", "rows_loaded", "rejected_sample", "published",
        "stage_durations_ms",
    ]  # fmt: skip


def test_csv_options_defaults() -> None:
    o = etl.CsvOptions()
    assert (o.encoding, o.delimiter, o.has_header, o.quote_char) == ("utf-8", ",", True, '"')


def test_error_hierarchy() -> None:
    for exc in (
        etl.CsvFormatError, etl.ConfigValidationError, etl.SourceMismatchError,
        etl.RejectionLimitExceeded, etl.LoadError, etl.RunInterrupted,
    ):  # fmt: skip
        assert issubclass(exc, etl.EtlError)
    items = [etl.ConfigErrorItem("/columns", "bad")]
    err = etl.ConfigValidationError(items)
    assert err.errors == items


def _params(fn: object) -> list[tuple[str, str, bool]]:
    sig = inspect.signature(fn)  # type: ignore[arg-type]
    return [(p.name, p.kind.name, p.default is not inspect.Parameter.empty) for p in sig.parameters.values()]


def test_function_signatures() -> None:
    assert _params(etl.inspect_csv) == [
        ("path", "POSITIONAL_OR_KEYWORD", False),
        ("options", "POSITIONAL_OR_KEYWORD", False),
        ("sample_rows", "KEYWORD_ONLY", True),
    ]
    assert _params(etl.preview_csv) == [
        ("path", "POSITIONAL_OR_KEYWORD", False),
        ("options", "POSITIONAL_OR_KEYWORD", False),
        ("limit", "KEYWORD_ONLY", True),
    ]
    assert _params(etl.validate_pipeline_config) == [
        ("config", "POSITIONAL_OR_KEYWORD", False),
        ("source_columns", "KEYWORD_ONLY", True),
    ]
    assert _params(etl.run_pipeline) == [
        ("config", "POSITIONAL_OR_KEYWORD", False),
        ("source_path", "POSITIONAL_OR_KEYWORD", False),
        ("csv_options", "POSITIONAL_OR_KEYWORD", False),
        ("engine", "POSITIONAL_OR_KEYWORD", False),
        ("run_id", "POSITIONAL_OR_KEYWORD", False),
        ("chunk_rows", "KEYWORD_ONLY", True),
        ("on_event", "KEYWORD_ONLY", True),
        ("should_stop", "KEYWORD_ONLY", True),
    ]
    assert inspect.signature(etl.inspect_csv).parameters["sample_rows"].default == 1000
    assert inspect.signature(etl.preview_csv).parameters["limit"].default == 50
    assert inspect.signature(etl.run_pipeline).parameters["chunk_rows"].default == 50_000


FORBIDDEN = {"fastapi", "starlette", "pydantic", "app"}
ALLOWED_APP_PREFIX = "app.etl"


def _imports(tree: ast.AST) -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(a.name, 0) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            found.append((node.module or "", node.level))
    return found


def test_import_rules() -> None:
    files = sorted(ETL_DIR.rglob("*.py"))
    assert files
    for f in files:
        for module, level in _imports(ast.parse(f.read_text())):
            if level:  # relative imports stay inside app.etl
                continue
            top = module.split(".")[0]
            if module == ALLOWED_APP_PREFIX or module.startswith(ALLOWED_APP_PREFIX + "."):
                continue
            assert top not in FORBIDDEN, f"{f.name} imports forbidden module {module}"
