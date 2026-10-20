"""Pipeline config validation (docs/architecture.md sections 5 and 6).

Two phases, each collecting every problem it finds:

1. JSON Schema validation against ``contracts/pipeline.schema.json``.
2. The semantic rules of section 6, run only when phase 1 found nothing
   (the rules assume a structurally valid document).

All problems end up in one :class:`ConfigValidationError`.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Iterator, Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from .casting import CastError, cast_config_value, format_error
from .errors import ConfigValidationError
from .types import ConfigErrorItem, PipelineConfig

_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "contracts" / "pipeline.schema.json"

_STRING_ONLY_TRANSFORMS = frozenset({"trim_whitespace", "change_case"})
_STRING_ONLY_VALIDATIONS = frozenset({"regex", "length"})

_Path = tuple[str | int, ...]


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    import json

    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _pointer(path: _Path) -> str:
    """RFC 6901 JSON Pointer; the root document is the empty string."""
    return "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in path)


def validate_pipeline_config(
    config: Mapping[str, Any], *, source_columns: list[str] | None = None
) -> PipelineConfig:
    """Validate ``config`` and return the parsed form, or raise ``ConfigValidationError``."""
    errors = _schema_errors(config)
    if not errors:
        errors = _semantic_errors(config, source_columns)
    if errors:
        raise ConfigValidationError(errors)
    return PipelineConfig(raw=copy.deepcopy(dict(config)))


# --------------------------------------------------------------------------- schema


def _sort_key(path: _Path) -> list[tuple[int, int, str]]:
    return [(0, p, "") if isinstance(p, int) else (1, 0, p) for p in path]


def _schema_errors(config: Mapping[str, Any]) -> list[ConfigErrorItem]:
    found: dict[tuple[_Path, str], None] = {}
    for err in _validator().iter_errors(config):
        for path, message in _flatten(err):
            found[(path, message)] = None
    ordered = sorted(found, key=lambda pm: (_sort_key(pm[0]), pm[1]))
    return [ConfigErrorItem(path=_pointer(p), message=m) for p, m in ordered]


def _flatten(err: ValidationError) -> Iterator[tuple[_Path, str]]:
    """Turn a jsonschema error into (path, message) pairs.

    ``oneOf`` over transformations/validations is replaced by the errors of the
    branch selected by ``op``/``rule``. When the discriminator is missing or
    unknown, the sibling ``required``/``enum`` error already says so.
    """
    path = tuple(err.absolute_path)
    if err.validator == "oneOf" and isinstance(err.instance, dict):
        branch = _selected_branch(err)
        if branch is not None:
            for sub in err.context or ():
                if sub.relative_schema_path[0] == branch:
                    yield from _flatten(sub)
        return
    if err.validator == "anyOf" and _is_required_alternatives(err.validator_value):
        names = ", ".join(repr(r) for alt in err.validator_value for r in alt["required"])
        yield path, f"at least one of {names} is required"
        return
    yield path, err.message


def _selected_branch(err: ValidationError) -> int | None:
    schema: Any = err.schema
    branches = schema.get("oneOf", [])
    root = _validator().schema
    for key in ("op", "rule"):
        value = err.instance.get(key)
        if value is None:
            continue
        for index, branch in enumerate(branches):
            name = branch["$ref"].rsplit("/", 1)[-1]
            const = root["$defs"][name]["properties"].get(key, {}).get("const")
            if const == value:
                return index
    return None


def _is_required_alternatives(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(a, dict) and set(a) == {"required"} for a in value)
    )


# ------------------------------------------------------------------------ semantics


def _semantic_errors(
    config: Mapping[str, Any], source_columns: list[str] | None
) -> list[ConfigErrorItem]:
    out: list[ConfigErrorItem] = []

    def add(path: _Path, message: str) -> None:
        out.append(ConfigErrorItem(path=_pointer(path), message=message))

    columns: list[dict[str, Any]] = config["columns"]
    transformations: list[dict[str, Any]] = config.get("transformations", [])
    validations: list[dict[str, Any]] = config.get("validations", [])

    # Rule 1: unique names and sources.
    types: dict[str, str] = {}
    seen_sources: set[str] = set()
    for i, col in enumerate(columns):
        if col["name"] in types:
            add(("columns", i, "name"), f"duplicate column name '{col['name']}'")
        else:
            types[col["name"]] = col["type"]
        if col["source"] in seen_sources:
            add(("columns", i, "source"), f"duplicate source column '{col['source']}'")
        seen_sources.add(col["source"])

    # Rule 7: format only on date/datetime columns, without time/zone directives (C-e).
    for i, col in enumerate(columns):
        if "format" not in col:
            continue
        if col["type"] not in ("date", "datetime"):
            add(
                ("columns", i, "format"),
                f"format is allowed only on date/datetime columns, not {col['type']}",
            )
        else:
            problem = format_error(col["type"], col["format"])
            if problem is not None:
                add(("columns", i, "format"), problem)

    # Rule 2: references, collected as (path, name, owner kind, owner item).
    refs: list[tuple[_Path, str]] = []
    for group, items in (("transformations", transformations), ("validations", validations)):
        for i, item in enumerate(items):
            if "column" in item:
                refs.append(((group, i, "column"), item["column"]))
            for j, name in enumerate(item.get("columns", [])):
                refs.append(((group, i, "columns", j), name))
    for path, name in refs:
        if name not in types:
            add(path, f"unknown column '{name}'; must be a columns[].name")

    def type_of(name: str) -> str | None:
        return types.get(name)

    # Rules 3, 4 (type applicability), 5 and 6, per item in array order.
    for i, item in enumerate(transformations):
        op = item["op"]
        if op in _STRING_ONLY_TRANSFORMS:
            for j, name in enumerate(item["columns"]):
                t = type_of(name)
                if t is not None and t != "string":
                    add(
                        ("transformations", i, "columns", j),
                        f"{op} applies only to string columns; '{name}' is {t}",
                    )
        elif op == "round_number":
            t = type_of(item["column"])
            if t is not None and t != "float":
                add(
                    ("transformations", i, "column"),
                    f"round_number applies only to float columns; '{item['column']}' is {t}",
                )
        elif op == "fill_null":
            name = item["column"]
            t = type_of(name)
            if t is not None and not _castable(item["value"], t):
                add(
                    ("transformations", i, "value"),
                    f"value {item['value']!r} cannot be cast to {t} column '{name}'",
                )

    for i, item in enumerate(validations):
        rule = item["rule"]
        name = item.get("column")
        t = type_of(name) if name is not None else None
        if rule in _STRING_ONLY_VALIDATIONS and t is not None and t != "string":
            add(
                ("validations", i, "column"),
                f"{rule} applies only to string columns; '{name}' is {t}",
            )
        if rule == "regex":
            try:
                re.compile(item["pattern"])
            except (re.error, RecursionError, OverflowError) as exc:
                add(("validations", i, "pattern"), f"pattern does not compile: {exc}")
        elif rule == "allowed_values" and t is not None and name is not None:
            for j, value in enumerate(item["values"]):
                if not _castable(value, t):
                    add(
                        ("validations", i, "values", j),
                        f"value {value!r} cannot be cast to {t} column '{name}'",
                    )
        elif rule == "range" and t is not None:
            _check_range(item, i, t, add)

    # Rule 8: source columns present in the CSV.
    if source_columns is not None:
        available = set(source_columns)
        for i, col in enumerate(columns):
            if col["source"] not in available:
                add(
                    ("columns", i, "source"),
                    f"source column '{col['source']}' not found in the CSV",
                )

    # Rule 9: reserved staging prefix.
    if config["target"]["table"].startswith("run_"):
        add(("target", "table"), "table names starting with 'run_' are reserved for staging")

    return out


def _check_range(item: dict[str, Any], i: int, t: str, add: Any) -> None:
    name = item["column"]
    if t not in ("integer", "float", "date", "datetime"):
        add(
            ("validations", i, "column"),
            f"range applies only to integer, float, date and datetime columns; '{name}' is {t}",
        )
        return
    numeric = t in ("integer", "float")
    parsed: dict[str, Any] = {}
    for bound in ("min", "max"):
        if bound not in item:
            continue
        value = item[bound]
        # Numbers for number columns, ISO strings for date columns (section 6 rule 4).
        if numeric == isinstance(value, str):
            kind = "a number" if numeric else "an ISO 8601 string"
            add(("validations", i, bound), f"{bound} must be {kind} for {t} column '{name}'")
            continue
        try:
            parsed[bound] = cast_config_value(value, t)
        except CastError as exc:
            add(
                ("validations", i, bound),
                f"{bound} {value!r} is not valid for {t} column '{name}': {exc}",
            )
    if len(parsed) == 2 and parsed["min"] > parsed["max"]:
        add(("validations", i), "min must be less than or equal to max")


def _castable(value: Any, t: str) -> bool:
    """Whether a JSON scalar is a valid config value for a column of type ``t`` (section 5, B)."""
    try:
        cast_config_value(value, t)
    except CastError:
        return False
    return True
