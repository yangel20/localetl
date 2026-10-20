"""ETL-05: validate stage on already-typed chunks."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from app.etl import PipelineConfig, RejectionLimitExceeded, validate_pipeline_config
from app.etl.validate import (
    MAX_REGEX_VALUE_LENGTH,
    Validator,
    _config_scalar,
    check_rejection_ratio,
)

SCHEMA = Path(__file__).resolve().parents[3] / "contracts" / "pipeline.schema.json"

COLUMNS = [
    {"source": "a", "name": "id", "type": "integer"},
    {"source": "b", "name": "name", "type": "string"},
    {"source": "c", "name": "score", "type": "float"},
    {"source": "d", "name": "day", "type": "date"},
    {"source": "e", "name": "at", "type": "datetime"},
    {"source": "f", "name": "flag", "type": "boolean"},
]


def make(validations: list[dict[str, Any]], **extra: Any) -> PipelineConfig:
    return validate_pipeline_config(
        {
            "version": 1,
            "columns": COLUMNS,
            "validations": validations,
            "target": {"table": "t", "mode": "replace"},
            **extra,
        }
    )


def frame(**cols: list[Any]) -> pd.DataFrame:
    return pd.DataFrame({k: pd.Series(v, dtype=object) for k, v in cols.items()})


def run(validations: list[dict[str, Any]], df: pd.DataFrame, **extra: Any):  # type: ignore[no-untyped-def]
    v = Validator(make(validations, **extra))
    return v.validate_chunk(df, list(range(1, len(df) + 1)))


def rules_of(result: Any) -> list[tuple[int, str, str | None]]:
    return [(r.row_number, r.rule, r.column) for r in result.rejections]


# ------------------------------------------------------------- completeness


def test_every_schema_rule_is_implemented() -> None:
    from app.etl import validate

    schema = json.loads(SCHEMA.read_text())
    enum = set(schema["$defs"]["Validation"]["properties"]["rule"]["enum"])
    assert enum == set(validate._COMPILERS)
    assert len(enum) == 6


# ------------------------------------------------------------------ not_null


def test_not_null() -> None:
    df = frame(name=["a", None, "c", float("nan")])
    res = run([{"rule": "not_null", "column": "name"}], df)
    assert rules_of(res) == [(2, "not_null", "name"), (4, "not_null", "name")]
    assert res.valid["name"].tolist() == ["a", "c"]
    assert res.rejections[0].value is None


def test_not_null_passes() -> None:
    res = run([{"rule": "not_null", "column": "id"}], frame(id=[1, 2]))
    assert res.rejections == [] and res.rejected_rows == 0 and len(res.valid) == 2


# -------------------------------------------------------------------- unique


def test_unique_first_wins_within_chunk() -> None:
    res = run([{"rule": "unique", "columns": ["id"]}], frame(id=[1, 2, 1, 3, 2]))
    assert rules_of(res) == [(3, "unique", "id"), (5, "unique", "id")]
    assert res.valid["id"].tolist() == [1, 2, 3]


def test_unique_across_chunks() -> None:
    v = Validator(make([{"rule": "unique", "columns": ["id"]}]))
    first = v.validate_chunk(frame(id=[1, 2]), [1, 2])
    second = v.validate_chunk(frame(id=[2, 3, 1]), [3, 4, 5])
    assert first.rejections == []
    assert rules_of(second) == [(3, "unique", "id"), (5, "unique", "id")]
    assert second.valid["id"].tolist() == [3]
    assert v.rejected_rows == 2


def test_unique_composite_key() -> None:
    df = frame(id=[1, 1, 1], name=["a", "b", "a"])
    res = run([{"rule": "unique", "columns": ["id", "name"]}], df)
    assert rules_of(res) == [(3, "unique", None)]
    assert res.rejections[0].value == "1, a"


def test_unique_ignores_nulls() -> None:
    res = run([{"rule": "unique", "columns": ["name"]}], frame(name=[None, None, "x"]))
    assert res.rejections == []


def test_unique_key_registered_by_row_failing_earlier_rule() -> None:
    # Row 1 fails `range` but still registers key 5, so row 2 is a duplicate.
    vals = [{"rule": "range", "column": "id", "max": 3}, {"rule": "unique", "columns": ["id"]}]
    res = run(vals, frame(id=[5, 5]))
    assert [(r.row_number, r.rule) for r in res.rejections] == [
        (1, "range"),
        (2, "range"),
        (2, "unique"),
    ]
    assert res.rejected_rows == 2


# --------------------------------------------------------------------- range


def test_range_integer_inclusive() -> None:
    res = run([{"rule": "range", "column": "id", "min": 1, "max": 3}], frame(id=[0, 1, 3, 4, None]))
    assert rules_of(res) == [(1, "range", "id"), (4, "range", "id")]


def test_range_float_one_sided() -> None:
    res = run([{"rule": "range", "column": "score", "min": 0.5}], frame(score=[0.4, 0.5, 9.0]))
    assert rules_of(res) == [(1, "range", "score")]
    res = run([{"rule": "range", "column": "score", "max": 1}], frame(score=[0.4, 1.0, 1.1]))
    assert rules_of(res) == [(3, "range", "score")]


def test_range_date() -> None:
    df = frame(day=[date(1999, 12, 31), date(2000, 1, 1), date(2100, 12, 31), date(2101, 1, 1)])
    res = run([{"rule": "range", "column": "day", "min": "2000-01-01", "max": "2100-12-31"}], df)
    assert rules_of(res) == [(1, "range", "day"), (4, "range", "day")]
    assert res.rejections[0].value == "1999-12-31"


def test_range_datetime() -> None:
    df = frame(
        at=[datetime(2024, 1, 1, 9), datetime(2024, 1, 1, 10), pd.Timestamp("2024-01-01 11:00:01")]
    )
    res = run(
        [
            {
                "rule": "range",
                "column": "at",
                "min": "2024-01-01T10:00:00",
                "max": "2024-01-01T11:00:00",
            }
        ],
        df,
    )
    assert rules_of(res) == [(1, "range", "at"), (3, "range", "at")]


def test_range_date_column_given_timestamps() -> None:
    df = frame(day=[pd.Timestamp("2000-01-01"), pd.Timestamp("1990-01-01")])
    res = run([{"rule": "range", "column": "day", "min": "1995-01-01"}], df)
    assert rules_of(res) == [(2, "range", "day")]


# ------------------------------------------------------------ allowed_values


def test_allowed_values_string_case_sensitive() -> None:
    res = run(
        [{"rule": "allowed_values", "column": "name", "values": ["open", "closed"]}],
        frame(name=["open", "Open", "closed", None, "x"]),
    )
    assert rules_of(res) == [(2, "allowed_values", "name"), (5, "allowed_values", "name")]


def test_allowed_values_typed() -> None:
    res = run([{"rule": "allowed_values", "column": "id", "values": [1, 2]}], frame(id=[1, 2, 3]))
    assert rules_of(res) == [(3, "allowed_values", "id")]
    res = run(
        [{"rule": "allowed_values", "column": "flag", "values": [True]}], frame(flag=[True, False])
    )
    assert rules_of(res) == [(2, "allowed_values", "flag")]
    res = run(
        [{"rule": "allowed_values", "column": "score", "values": [1, 2.5]}],
        frame(score=[1.0, 2.5, 3.0]),
    )
    assert rules_of(res) == [(3, "allowed_values", "score")]


# --------------------------------------------------------------------- regex


def test_regex_fullmatch() -> None:
    res = run(
        [{"rule": "regex", "column": "name", "pattern": r"[a-z]+\d"}],
        frame(name=["ab1", "ab1x", "Xab1", None]),
    )
    assert rules_of(res) == [(2, "regex", "name"), (3, "regex", "name")]


def test_regex_long_value_rejected_without_matching() -> None:
    long_value = "a" * (MAX_REGEX_VALUE_LENGTH + 1)
    ok_value = "a" * MAX_REGEX_VALUE_LENGTH
    res = run(
        [{"rule": "regex", "column": "name", "pattern": "a+"}], frame(name=[ok_value, long_value])
    )
    assert rules_of(res) == [(2, "regex", "name")]
    assert "not matched" in res.rejections[0].message
    assert len(res.rejections[0].value or "") == 500


def test_regex_catastrophic_pattern_long_value_is_not_evaluated() -> None:
    res = run(
        [{"rule": "regex", "column": "name", "pattern": "(a+)+$"}],
        frame(name=["a" * 20_000 + "!"]),
    )
    assert rules_of(res) == [(1, "regex", "name")]


# -------------------------------------------------------------------- length


def test_length_bounds() -> None:
    df = frame(name=["", "a", "ab", "abc", None])
    res = run([{"rule": "length", "column": "name", "min": 1, "max": 2}], df)
    assert rules_of(res) == [(1, "length", "name"), (4, "length", "name")]
    res = run([{"rule": "length", "column": "name", "min": 2}], df)
    assert rules_of(res) == [(1, "length", "name"), (2, "length", "name")]
    res = run([{"rule": "length", "column": "name", "max": 1}], df)
    assert rules_of(res) == [(3, "length", "name"), (4, "length", "name")]


def test_length_counts_characters() -> None:
    res = run([{"rule": "length", "column": "name", "max": 2}], frame(name=["éé", "ééé"]))
    assert rules_of(res) == [(2, "length", "name")]


# ----------------------------------------------------- row accounting (Q3)


def test_row_failing_several_rules_counts_once_with_one_entry_per_rule() -> None:
    vals = [
        {"rule": "length", "column": "name", "max": 1},
        {"rule": "regex", "column": "name", "pattern": "[a-z]"},
        {"rule": "allowed_values", "column": "name", "values": ["a"]},
    ]
    res = run(vals, frame(name=["a", "BB", "c"]))
    assert res.rejected_rows == 2
    assert [(r.row_number, r.rule) for r in res.rejections] == [
        (2, "length"),
        (2, "regex"),
        (2, "allowed_values"),
        (3, "allowed_values"),
    ]
    assert res.valid["name"].tolist() == ["a"]
    assert len(res.valid) + res.rejected_rows == 3


def test_rejection_order_is_row_then_rule() -> None:
    vals = [{"rule": "not_null", "column": "id"}, {"rule": "range", "column": "id", "min": 5}]
    res = run(vals, frame(id=[1, None, 2]))
    assert [(r.row_number, r.rule) for r in res.rejections] == [
        (1, "range"),
        (2, "not_null"),
        (3, "range"),
    ]


def test_row_numbers_are_reported_not_positions() -> None:
    v = Validator(make([{"rule": "not_null", "column": "id"}]))
    res = v.validate_chunk(frame(id=[1, None]), [101, 102])
    assert res.rejections[0].row_number == 102


def test_row_numbers_must_align() -> None:
    v = Validator(make([]))
    with pytest.raises(Exception, match="align"):
        v.validate_chunk(frame(id=[1, 2]), [1])


def test_no_validations_keeps_everything() -> None:
    res = run([], frame(id=[1, None]))
    assert len(res.valid) == 2 and res.rejections == []


def test_value_truncated_to_500() -> None:
    res = run([{"rule": "length", "column": "name", "max": 3}], frame(name=["x" * 900]))
    assert len(res.rejections[0].value or "") == 500


def test_valid_frame_keeps_original_index() -> None:
    df = frame(id=[1, None, 3])
    df.index = pd.Index([10, 11, 12])
    res = run([{"rule": "not_null", "column": "id"}], df)
    assert res.valid.index.tolist() == [10, 12]


# ------------------------------------------------------- fail_run and ratio


def test_fail_run_raises_on_first_rejection() -> None:
    v = Validator(make([{"rule": "not_null", "column": "id"}], on_validation_failure="fail_run"))
    v.validate_chunk(frame(id=[1, 2]), [1, 2])  # clean chunk is fine
    with pytest.raises(RejectionLimitExceeded, match="row 4"):
        v.validate_chunk(frame(id=[3, None]), [3, 4])


def test_reject_row_default_does_not_raise() -> None:
    res = run([{"rule": "not_null", "column": "id"}], frame(id=[None]))
    assert res.rejected_rows == 1


def test_ratio_not_exceeded() -> None:
    cfg = make([], max_rejected_ratio=0.25)
    check_rejection_ratio(cfg, 1, 4)  # equal is allowed
    check_rejection_ratio(cfg, 0, 10)


def test_ratio_exceeded() -> None:
    cfg = make([], max_rejected_ratio=0.25)
    with pytest.raises(RejectionLimitExceeded, match="max_rejected_ratio"):
        check_rejection_ratio(cfg, 2, 4)


def test_ratio_default_is_one() -> None:
    check_rejection_ratio(make([]), 10, 10)


def test_ratio_zero_limit() -> None:
    cfg = make([], max_rejected_ratio=0)
    check_rejection_ratio(cfg, 0, 5)
    with pytest.raises(RejectionLimitExceeded):
        check_rejection_ratio(cfg, 1, 5)


def test_dropped_rows_only_raise_denominator() -> None:
    cfg = make([], max_rejected_ratio=0.2)
    # 2 rejected of 10 extracted is 0.2 (ok); the other 8 may be loaded or dropped.
    check_rejection_ratio(cfg, 2, 10)
    # With 5 extracted of which 2 are rejected, the ratio is 0.4 and fails regardless of drops.
    with pytest.raises(RejectionLimitExceeded):
        check_rejection_ratio(cfg, 2, 5)


# ----------------------------------------------------------- casting hold


@pytest.mark.parametrize(
    ("value", "ctype", "expected"),
    [
        (5, "integer", 5),
        (2**63 - 1, "integer", 2**63 - 1),
        (-(2**63), "integer", -(2**63)),
        (1, "float", 1.0),
        (2.5, "float", 2.5),
        (True, "boolean", True),
        (False, "boolean", False),
        ("x", "string", "x"),
        ("2024-02-29", "date", date(2024, 2, 29)),
        ("2024-01-31T10:20:30", "datetime", datetime(2024, 1, 31, 10, 20, 30)),
    ],
)
def test_config_scalar_unambiguous(value: Any, ctype: str, expected: Any) -> None:
    result = _config_scalar(value, ctype)
    assert result == expected and type(result) is type(expected)


def test_held_cases_raise_not_implemented() -> None:
    held = [
        (True, "integer"), (1.0, "integer"), ("5", "integer"), (2**63, "integer"),
        (True, "float"), ("1.5", "float"), (float("inf"), "float"),
        (1, "boolean"), (0, "boolean"), ("true", "boolean"),
        (5, "string"), (True, "string"),
        ("20240131", "date"), ("2024-W05-3", "date"), ("2024-02-30", "date"),
        (" 2024-01-31", "date"), ("2024-01-31T00:00:00", "date"), (5, "date"),
        ("2024-01-31", "datetime"), ("2024-01-31 10:00:00", "datetime"),
        ("2024-01-31T10:00:00Z", "datetime"), ("2024-01-31T10:00:00+02:00", "datetime"),
        ("2024-01-31T10:00:00.5", "datetime"), ("2024-01-31T10:00", "datetime"),
        (" 2024-01-31T10:00:00", "datetime"),
    ]  # fmt: skip
    for value, ctype in held:
        with pytest.raises(NotImplementedError, match="Q6-3"):
            _config_scalar(value, ctype)


def test_hold_surfaces_at_validator_construction() -> None:
    raw = {
        "version": 1,
        "columns": COLUMNS,
        "validations": [{"rule": "allowed_values", "column": "id", "values": [1, 2]}],
        "target": {"table": "t", "mode": "replace"},
    }
    ok = PipelineConfig(raw=raw)
    Validator(ok)
    held = PipelineConfig(
        raw={**raw, "validations": [{"rule": "allowed_values", "column": "id", "values": ["1"]}]}
    )
    with pytest.raises(NotImplementedError, match="pending casting specification Q6-3"):
        Validator(held)
