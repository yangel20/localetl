"""ETL-03: validate_pipeline_config (schema + architecture section 6 rules)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from app.etl import ConfigValidationError, PipelineConfig, validate_pipeline_config

EXAMPLES = Path(__file__).resolve().parents[3] / "contracts" / "examples" / "pipeline"
FIXTURE_PIPELINES = sorted(
    (EXAMPLES.parents[2] / "tests" / "fixtures" / "pipelines").glob("*.json")
)
VALID = sorted((EXAMPLES / "valid").glob("*.json"))
INVALID = sorted((EXAMPLES / "invalid").glob("*.json"))


def base(**extra: Any) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "version": 1,
        "columns": [
            {"source": "Name", "name": "name", "type": "string"},
            {"source": "Qty", "name": "qty", "type": "integer"},
            {"source": "Price", "name": "price", "type": "float"},
            {"source": "Day", "name": "day", "type": "date", "format": "%Y-%m-%d"},
            {"source": "At", "name": "at", "type": "datetime"},
            {"source": "Ok", "name": "ok", "type": "boolean"},
        ],
        "target": {"table": "t", "mode": "replace"},
    }
    cfg.update(extra)
    return cfg


def errors_of(cfg: dict[str, Any], **kw: Any) -> list[tuple[str, str]]:
    with pytest.raises(ConfigValidationError) as info:
        validate_pipeline_config(cfg, **kw)
    return [(e.path, e.message) for e in info.value.errors]


def paths_of(cfg: dict[str, Any], **kw: Any) -> list[str]:
    return [p for p, _ in errors_of(cfg, **kw)]


# ---------------------------------------------------------------- examples


def test_examples_exist() -> None:
    assert len(VALID) >= 3 and len(INVALID) >= 8


@pytest.mark.parametrize("path", VALID, ids=lambda p: p.name)
def test_valid_examples_pass(path: Path) -> None:
    raw = json.loads(path.read_text())
    result = validate_pipeline_config(raw)
    assert isinstance(result, PipelineConfig)
    assert result.raw == raw


@pytest.mark.parametrize("path", FIXTURE_PIPELINES, ids=lambda p: p.name)
def test_fixture_pipelines_validate(path: Path) -> None:
    assert FIXTURE_PIPELINES
    validate_pipeline_config(json.loads(path.read_text()))


@pytest.mark.parametrize("path", INVALID, ids=lambda p: p.name)
def test_invalid_examples_fail(path: Path) -> None:
    errs = errors_of(json.loads(path.read_text()))
    assert errs and all(isinstance(p, str) and m for p, m in errs)


def test_invalid_example_paths() -> None:
    def load(name: str) -> dict[str, Any]:
        return json.loads((EXAMPLES / "invalid" / name).read_text())

    assert paths_of(load("range_without_bounds.json")) == ["/validations/0"]
    assert paths_of(load("bad_target_identifier.json")) == ["/target/table"]
    assert paths_of(load("bad_load_mode.json")) == ["/target/mode"]
    assert paths_of(load("bad_column_type.json"))[0].startswith("/columns/")
    assert paths_of(load("wrong_version.json")) == ["/version"]
    assert paths_of(load("extra_property.json")) == ["/target"]
    assert paths_of(load("missing_columns.json")) == [""]
    assert paths_of(load("unknown_transformation.json")) == ["/transformations/0/op"]


# ---------------------------------------------------------------- behaviour


def test_result_is_a_copy() -> None:
    cfg = base()
    result = validate_pipeline_config(cfg)
    cfg["columns"].clear()
    assert len(result.raw["columns"]) == 6


def test_input_not_mutated() -> None:
    cfg = base(transformations=[{"op": "trim_whitespace", "columns": ["name"]}])
    before = copy.deepcopy(cfg)
    validate_pipeline_config(cfg)
    assert cfg == before


def test_non_object_root() -> None:
    with pytest.raises(ConfigValidationError) as info:
        validate_pipeline_config([])  # type: ignore[arg-type]
    assert info.value.errors[0].path == ""


def test_schema_errors_are_collected() -> None:
    cfg = base(on_validation_failure="nope", max_rejected_ratio=2)
    cfg["columns"][0]["type"] = "text"
    cfg["target"]["mode"] = "merge"
    assert sorted(paths_of(cfg)) == [
        "/columns/0/type",
        "/max_rejected_ratio",
        "/on_validation_failure",
        "/target/mode",
    ]


def test_selected_branch_errors_not_generic_oneof() -> None:
    cfg = base(transformations=[{"op": "change_case", "columns": ["name"], "case": "snake"}])
    errs = errors_of(cfg)
    assert [p for p, _ in errs] == ["/transformations/0/case"]
    assert "oneOf" not in errs[0][1] and "valid under" not in errs[0][1]


def test_unknown_rule_and_missing_op() -> None:
    cfg = base(validations=[{"rule": "magic"}], transformations=[{"columns": ["name"]}])
    assert sorted(paths_of(cfg)) == ["/transformations/0", "/validations/0/rule"]


def test_semantic_rules_skipped_until_schema_valid() -> None:
    cfg = base(transformations=[{"op": "trim_whitespace", "columns": ["qty"]}])
    cfg["target"]["mode"] = "bad"
    assert paths_of(cfg) == ["/target/mode"]


def test_errors_collected_across_semantic_rules() -> None:
    cfg = base(
        transformations=[
            {"op": "trim_whitespace", "columns": ["qty", "ghost"]},
            {"op": "round_number", "column": "qty", "decimals": 1},
        ],
        validations=[{"rule": "regex", "column": "name", "pattern": "("}],
    )
    cfg["target"]["table"] = "run_x"
    # Semantic errors come out in section 6 rule order (rule 2, 3, 4, 6, 9).
    assert paths_of(cfg) == [
        "/transformations/0/columns/1",
        "/transformations/0/columns/0",
        "/transformations/1/column",
        "/validations/0/pattern",
        "/target/table",
    ]


def test_error_message_summarises_count() -> None:
    cfg = base()
    cfg["columns"][0]["type"] = "x"
    with pytest.raises(ConfigValidationError, match=r"1 error"):
        validate_pipeline_config(cfg)


def test_schema_errors_deterministic_order() -> None:
    cfg = base()
    cfg["columns"][5]["type"] = "x"
    cfg["columns"][1]["type"] = "x"
    cfg["target"]["mode"] = "x"
    assert paths_of(cfg) == ["/columns/1/type", "/columns/5/type", "/target/mode"]


# ------------------------------------------------------- JSON Pointer escaping


def test_pointer_escapes_tilde_and_slash() -> None:
    cfg = base(
        transformations=[
            {
                "op": "replace_values",
                "column": "name",
                "mapping": {"a/b": {"x": 1}, "c~d": [1], "ok": "fine"},
            }
        ]
    )
    paths = paths_of(cfg)
    assert "/transformations/0/mapping/a~1b" in paths
    assert "/transformations/0/mapping/c~0d" in paths
    assert len(paths) == 2


def test_pointer_escape_order_tilde_one() -> None:
    # "~1" in a key must become "~01", not "~1" (which would decode to "/").
    cfg = base(
        transformations=[{"op": "replace_values", "column": "name", "mapping": {"~1": {"x": 1}}}]
    )
    assert paths_of(cfg) == ["/transformations/0/mapping/~01"]


# ------------------------------------------------------------ section 6 rules


def test_rule1_ok_and_duplicates() -> None:
    validate_pipeline_config(base())
    cfg = base()
    cfg["columns"].append({"source": "Name", "name": "name", "type": "string"})
    assert sorted(paths_of(cfg)) == ["/columns/6/name", "/columns/6/source"]


def test_rule2_ok_and_unknown_reference() -> None:
    validate_pipeline_config(
        base(transformations=[{"op": "fill_null", "column": "name", "value": "x"}])
    )
    cfg = base(
        transformations=[
            {"op": "deduplicate", "columns": ["name", "nope"]},
            {"op": "drop_null_rows", "columns": ["zzz"]},
            {"op": "replace_values", "column": "missing", "mapping": {"a": "b"}},
        ],
        validations=[
            {"rule": "not_null", "column": "q"},
            {"rule": "unique", "columns": ["w"]},
        ],
    )
    assert paths_of(cfg) == [
        "/transformations/0/columns/1",
        "/transformations/1/columns/0",
        "/transformations/2/column",
        "/validations/0/column",
        "/validations/1/columns/0",
    ]


def test_rule3_string_only() -> None:
    ok = base(
        transformations=[
            {"op": "trim_whitespace", "columns": ["name"]},
            {"op": "change_case", "columns": ["name"], "case": "upper"},
        ],
        validations=[
            {"rule": "regex", "column": "name", "pattern": "a+"},
            {"rule": "length", "column": "name", "max": 5},
        ],
    )
    validate_pipeline_config(ok)
    bad = base(
        transformations=[
            {"op": "trim_whitespace", "columns": ["name", "qty"]},
            {"op": "change_case", "columns": ["price"], "case": "upper"},
        ],
        validations=[
            {"rule": "regex", "column": "day", "pattern": "a+"},
            {"rule": "length", "column": "ok", "max": 5},
        ],
    )
    assert paths_of(bad) == [
        "/transformations/0/columns/1",
        "/transformations/1/columns/0",
        "/validations/0/column",
        "/validations/1/column",
    ]


def test_rule4_round_number_float_only() -> None:
    validate_pipeline_config(
        base(transformations=[{"op": "round_number", "column": "price", "decimals": 2}])
    )
    cfg = base(transformations=[{"op": "round_number", "column": "qty", "decimals": 2}])
    assert paths_of(cfg) == ["/transformations/0/column"]


def test_rule4_range_types_and_bounds() -> None:
    ok = base(
        validations=[
            {"rule": "range", "column": "qty", "min": 0, "max": 10},
            {"rule": "range", "column": "price", "min": 0.5},
            {"rule": "range", "column": "day", "min": "2000-01-01", "max": "2000-01-01"},
            {"rule": "range", "column": "at", "max": "2024-05-01T10:00:00"},
        ]
    )
    validate_pipeline_config(ok)
    bad = base(
        validations=[
            {"rule": "range", "column": "name", "min": 1},
            {"rule": "range", "column": "ok", "max": 1},
            {"rule": "range", "column": "qty", "min": "1"},
            {"rule": "range", "column": "day", "min": 20},
            {"rule": "range", "column": "day", "min": "not a date"},
            {"rule": "range", "column": "at", "min": "2024-13-45"},
            {"rule": "range", "column": "day", "min": "2024-01-02T00:00:00"},
        ]
    )
    assert paths_of(bad) == [
        "/validations/0/column",
        "/validations/1/column",
        "/validations/2/min",
        "/validations/3/min",
        "/validations/4/min",
        "/validations/5/min",
        "/validations/6/min",
    ]


@pytest.mark.parametrize(
    ("col", "lo", "hi"),
    [
        ("qty", 5, 4),
        ("price", 1.5, 1.4),
        ("day", "2024-02-01", "2024-01-01"),
        ("at", "2024-01-01T10:00:00", "2024-01-01T09:00:00"),
    ],
)
def test_rule4_min_not_above_max(col: str, lo: Any, hi: Any) -> None:
    assert paths_of(base(validations=[{"rule": "range", "column": col, "min": lo, "max": hi}])) == [
        "/validations/0"
    ]


@pytest.mark.parametrize("bound", ["2024-01-01T00:00:00+00:00", "2024-01-01T00:00:00Z"])
def test_rule4_datetime_bounds_reject_offsets(bound: str) -> None:
    v = {"rule": "range", "column": "at", "min": bound}
    assert paths_of(base(validations=[v])) == ["/validations/0/min"]


def test_rule4_datetime_bound_without_seconds_is_valid() -> None:
    v = {"rule": "range", "column": "at", "min": "2024-01-01T00:00"}
    validate_pipeline_config(base(validations=[v]))


def test_rule4_integer_bounds_must_be_integral() -> None:
    ok = base(validations=[{"rule": "range", "column": "qty", "min": 1.0, "max": 10}])
    validate_pipeline_config(ok)
    bad = base(validations=[{"rule": "range", "column": "qty", "min": 0.5, "max": 2}])
    assert paths_of(bad) == ["/validations/0/min"]
    big = base(validations=[{"rule": "range", "column": "qty", "max": 2**63}])
    assert paths_of(big) == ["/validations/0/max"]


def test_rule4_compact_and_week_dates_rejected() -> None:
    for bound in ("20240101", "2024-W01-1", "2024-01-01T00:00:00"):
        assert paths_of(base(validations=[{"rule": "range", "column": "day", "min": bound}])) == [
            "/validations/0/min"
        ]


@pytest.mark.parametrize(
    ("col", "good", "bad"),
    [
        (
            "qty",
            [3, "4", 5.0, " 7 ", "+8", "007"],
            [1.5, "x", True, "1.5", "1_000", "١٢", 2**63, "1e3"],
        ),
        (
            "price",
            [1, 2.5, "3.25", ".5", "1e3", "5."],
            ["abc", True, "nan", "inf", "1,5", "1_0.5", "1e400"],
        ),
        ("ok", [True, 0, 1, "Yes", "NO", "true"], ["maybe", 2, "2"]),
        ("day", ["2024-01-31"], ["2024-02-30", "31/01/2024", 5, "20240131", "2024-W05-3"]),
        (
            "at",
            ["2024-01-31T10:00:00", "2024-01-31 10:00", "2024-01-31T10:00:00.25"],
            ["yesterday", 3, "2024-01-31", "2024-01-31T10:00:00Z"],
        ),
        ("name", ["a", ""], [1, True, 2.5]),
    ],
)
def test_rule5_castable_fill_null_and_allowed_values(
    col: str, good: list[Any], bad: list[Any]
) -> None:
    for v in good:
        validate_pipeline_config(
            base(transformations=[{"op": "fill_null", "column": col, "value": v}])
        )
    validate_pipeline_config(
        base(validations=[{"rule": "allowed_values", "column": col, "values": good}])
    )
    for v in bad:
        assert paths_of(base(transformations=[{"op": "fill_null", "column": col, "value": v}])) == [
            "/transformations/0/value"
        ]
    if bad:
        cfg = base(
            validations=[{"rule": "allowed_values", "column": col, "values": [*good[:1], *bad]}]
        )
        assert paths_of(cfg) == [f"/validations/0/values/{i}" for i in range(1, len(bad) + 1)]


def test_rule5_ignores_column_format_config_dates_are_iso() -> None:
    cfg = base()
    cfg["columns"][3]["format"] = "%d/%m/%Y"
    cfg["transformations"] = [{"op": "fill_null", "column": "day", "value": "2024-01-31"}]
    validate_pipeline_config(cfg)
    cfg["transformations"] = [{"op": "fill_null", "column": "day", "value": "31/01/2024"}]
    assert paths_of(cfg) == ["/transformations/0/value"]


def test_rule6_regex_compiles() -> None:
    validate_pipeline_config(
        base(validations=[{"rule": "regex", "column": "name", "pattern": r"^[a-z]+\d*$"}])
    )
    errs = errors_of(
        base(validations=[{"rule": "regex", "column": "name", "pattern": "(unclosed"}])
    )
    assert [p for p, _ in errs] == ["/validations/0/pattern"]
    assert "compile" in errs[0][1]


def test_rule7_format_only_on_date_types() -> None:
    validate_pipeline_config(base())  # date has format, datetime has none
    cfg = base()
    cfg["columns"][1]["format"] = "%Y"
    cfg["columns"][0]["format"] = "%Y"
    assert paths_of(cfg) == ["/columns/0/format", "/columns/1/format"]


def test_rule8_source_columns() -> None:
    sources = ["Name", "Qty", "Price", "Day", "At", "Ok", "Extra"]
    validate_pipeline_config(base(), source_columns=sources)
    validate_pipeline_config(base())  # None: no check
    assert paths_of(base(), source_columns=["Name", "Qty", "Price", "At", "Ok"]) == [
        "/columns/3/source"
    ]
    assert paths_of(base(), source_columns=[]) == [f"/columns/{i}/source" for i in range(6)]
    # case-sensitive exact match
    assert "/columns/0/source" in paths_of(
        base(), source_columns=["name", "Qty", "Price", "Day", "At", "Ok"]
    )


def test_rule9_reserved_run_prefix() -> None:
    cfg = base()
    cfg["target"]["table"] = "runs"
    validate_pipeline_config(cfg)
    cfg["target"]["table"] = "run_abc"
    assert paths_of(cfg) == ["/target/table"]


@pytest.mark.parametrize("fmt", ["%Y-%m-%d", "%d/%m/%Y", "%d %B %Y", "%y%%%m%d", "%%H"])
def test_rule7_date_format_ok(fmt: str) -> None:
    cfg = base()
    cfg["columns"][3]["format"] = fmt
    validate_pipeline_config(cfg)


@pytest.mark.parametrize("directive", list("HIMSfpXcz") + ["Z"])
def test_rule7_date_format_rejects_time_and_zone_directives(directive: str) -> None:
    cfg = base()
    cfg["columns"][3]["format"] = f"%Y-%m-%d %{directive}"
    assert paths_of(cfg) == ["/columns/3/format"]


@pytest.mark.parametrize("fmt", ["%Y-%m-%d %H:%M:%S", "%d/%m/%Y %I:%M %p", "%Y%m%dT%H%M%S.%f"])
def test_rule7_datetime_format_allows_time_directives(fmt: str) -> None:
    cfg = base()
    cfg["columns"][4]["format"] = fmt
    validate_pipeline_config(cfg)


@pytest.mark.parametrize("directive", ["z", "Z"])
def test_rule7_datetime_format_rejects_zone_directives(directive: str) -> None:
    cfg = base()
    cfg["columns"][4]["format"] = f"%Y-%m-%d %H:%M:%S %{directive}"
    assert paths_of(cfg) == ["/columns/4/format"]
