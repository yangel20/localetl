"""ETL-03b: shared casting (architecture section 5, "Value casting", Q6-3)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pytest

from app.etl.casting import (
    CastError,
    cast_cell,
    cast_config_value,
    format_error,
    infer_type,
)


def ok(raw: str | None, ctype: str, fmt: str | None = None) -> Any:
    return cast_cell(raw, ctype, fmt)


def bad(raw: str, ctype: str, fmt: str | None = None) -> None:
    with pytest.raises(CastError):
        cast_cell(raw, ctype, fmt)


# ------------------------------------------------------ general rules 1-5


def test_rule1_non_string_values_are_stripped() -> None:
    assert ok("  42 \t", "integer") == 42
    assert ok("\n1.5\n", "float") == 1.5
    assert ok(" yes ", "boolean") is True
    assert ok(" 2024-01-31 ", "date") == date(2024, 1, 31)
    assert ok("  2024-01-31T10:00:00 ", "datetime") == datetime(2024, 1, 31, 10)


def test_rule1_whitespace_only_is_null_c_a() -> None:
    for t in ("integer", "float", "boolean", "date", "datetime"):
        assert ok("   ", t) is None
        assert ok("\t\n", t) is None
        assert ok("", t) is None


def test_rule1_strings_are_never_stripped() -> None:
    assert ok("  a b  ", "string") == "  a b  "
    assert ok("   ", "string") == "   "


def test_rule2_nulls_are_never_cast() -> None:
    for t in ("integer", "float", "boolean", "date", "datetime", "string"):
        assert ok(None, t) is None


@pytest.mark.parametrize(
    ("ctype", "text"),
    [
        ("integer", "١٢"),
        ("integer", "1_000"),
        ("integer", "1,000"),
        ("float", "1,5"),
        ("float", "1_0.5"),
        ("float", "١.٥"),
        ("date", "٢٠٢٤-٠١-٣١"),
        ("datetime", "٢٠٢٤-٠١-٣١T١٠:٠٠:٠٠"),
        ("boolean", "١"),
    ],
)
def test_rule3_ascii_digits_only(ctype: str, text: str) -> None:
    bad(text, ctype)


def test_rule3_formatted_dates_reject_non_ascii_digits() -> None:
    bad("٣١/٠١/٢٠٢٤", "date", "%d/%m/%Y")
    bad("2024-01-31 ١٠:٠٠", "datetime", "%Y-%m-%d %H:%M")


def test_rule4_failure_is_a_cast_error_with_reason() -> None:
    with pytest.raises(CastError, match="integer"):
        cast_cell("x", "integer")


def test_rule5_deterministic() -> None:
    for _ in range(3):
        assert cast_cell(" 007 ", "integer") == 7
        assert cast_cell("2024-02-29", "date") == date(2024, 2, 29)


def test_unknown_type() -> None:
    with pytest.raises(CastError):
        cast_cell("1", "decimal")


# ----------------------------------------------------------- (A) table rows


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0", 0),
        ("+5", 5),
        ("-5", -5),
        ("007", 7),
        ("9223372036854775807", 2**63 - 1),
        ("-9223372036854775808", -(2**63)),
    ],
)
def test_integer_accepted(text: str, expected: int) -> None:
    result = ok(text, "integer")
    assert result == expected and type(result) is int


@pytest.mark.parametrize(
    "text",
    [
        "1.0",
        "1e3",
        "9223372036854775808",
        "-9223372036854775809",
        "abc",
        "1 2",
        "+",
        "-",
        "--1",
        "0x10",
        "1" * 5000,
    ],
)
def test_integer_rejected(text: str) -> None:
    bad(text, "integer")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1", 1.0),
        ("-1.5", -1.5),
        ("+.5", 0.5),
        ("5.", 5.0),
        ("1e3", 1000.0),
        ("1.5E-2", 0.015),
        ("007.50", 7.5),
        ("0", 0.0),
    ],
)
def test_float_accepted(text: str, expected: float) -> None:
    result = ok(text, "float")
    assert result == expected and type(result) is float


@pytest.mark.parametrize(
    "text",
    [
        "nan",
        "inf",
        "-inf",
        "Infinity",
        "1e400",
        "-1e400",
        "1,5",
        "1_0.5",
        ".",
        "e5",
        "1e",
        "1.5.5",
        "abc",
    ],
)
def test_float_rejected(text: str) -> None:
    bad(text, "float")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("true", True),
        ("TRUE", True),
        ("False", False),
        ("yes", True),
        ("No", False),
        ("1", True),
        ("0", False),
    ],
)
def test_boolean_accepted(text: str, expected: bool) -> None:
    assert ok(text, "boolean") is expected


@pytest.mark.parametrize("text", ["t", "y", "on", "off", "2", "-1", "truee", "01", "10"])
def test_boolean_rejected(text: str) -> None:
    bad(text, "boolean")


def test_date_with_format() -> None:
    assert ok("31/01/2024", "date", "%d/%m/%Y") == date(2024, 1, 31)
    assert type(ok("31/01/2024", "date", "%d/%m/%Y")) is date
    assert ok("Jan 5 2024", "date", "%b %d %Y") == date(2024, 1, 5)
    bad("2024-01-31", "date", "%d/%m/%Y")
    bad("31/01/2024 extra", "date", "%d/%m/%Y")
    bad("31/02/2024", "date", "%d/%m/%Y")


def test_date_format_pivot_for_two_digit_years() -> None:
    assert ok("01/02/69", "date", "%d/%m/%y") == date(1969, 2, 1)
    assert ok("01/02/68", "date", "%d/%m/%y") == date(2068, 2, 1)


@pytest.mark.parametrize(
    "fmt",
    ["%Y-%m-%d %H", "%Y %I", "%Y %M", "%Y %S", "%Y %f", "%Y %p", "%X", "%c", "%Y %z", "%Y %Z"],
)
def test_date_format_with_forbidden_directive_is_rejected(fmt: str) -> None:
    bad("2024", "date", fmt)


def test_date_without_format() -> None:
    assert ok("2026-10-20", "date") == date(2026, 10, 20)
    assert ok("2024-02-29", "date") == date(2024, 2, 29)
    for text in [
        "20261020",
        "2026-W43-2",
        "2026-10-20T00:00",
        "2026-02-30",
        "2026-2-3",
        "0000-01-01",
        "2026-10-2x",
    ]:
        bad(text, "date")


def test_datetime_with_format() -> None:
    result = ok("31/01/2024 10:30", "datetime", "%d/%m/%Y %H:%M")
    assert result == datetime(2024, 1, 31, 10, 30) and result.tzinfo is None
    assert ok("2024-01-31 10:30 PM", "datetime", "%Y-%m-%d %I:%M %p") == datetime(
        2024, 1, 31, 22, 30
    )
    assert ok("2024-01-31", "datetime", "%Y-%m-%d") == datetime(2024, 1, 31)
    bad("2024-01-31", "datetime", "%Y-%m-%d %H:%M")
    bad("2024-01-31 10:30 +0200", "datetime", "%Y-%m-%d %H:%M %z")
    bad("2024-01-31 10:30 UTC", "datetime", "%Y-%m-%d %H:%M %Z")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-10-20T10:00", datetime(2026, 10, 20, 10, 0)),
        ("2026-10-20T10:00:05", datetime(2026, 10, 20, 10, 0, 5)),
        ("2026-10-20 10:00:05", datetime(2026, 10, 20, 10, 0, 5)),
        ("2026-10-20T10:00:05.5", datetime(2026, 10, 20, 10, 0, 5, 500000)),
        ("2026-10-20T10:00:05.123456", datetime(2026, 10, 20, 10, 0, 5, 123456)),
        ("2026-10-20T23:59:59", datetime(2026, 10, 20, 23, 59, 59)),
    ],
)
def test_datetime_without_format_accepted(text: str, expected: datetime) -> None:
    result = ok(text, "datetime")
    assert result == expected and result.tzinfo is None


@pytest.mark.parametrize(
    "text",
    [
        "2026-10-20T10:00Z",
        "2026-10-20T10:00+02:00",
        "2026-10-20T10:00:00-0500",
        "20261020T1000",
        "2026-10-20",
        "2026-10-20  10:00",
        "2026-10-20T10",
        "2026-10-20T24:00",
        "2026-10-20T10:60",
        "2026-10-20T10:00:60",
        "2026-10-20T10:00:05.1234567",
        "2026-10-20T10:00.5",
        "2026-02-30T10:00",
    ],
)
def test_datetime_without_format_rejected(text: str) -> None:
    bad(text, "datetime")


def test_string_anything() -> None:
    for text in ["", "x", " y ", "١٢", "NaN", "1,5"]:
        assert ok(text, "string") == text


# ------------------------------------------------------------------ format_error


def test_format_error_c_e() -> None:
    assert format_error("date", "%Y-%m-%d") is None
    assert format_error("datetime", "%Y-%m-%d %H:%M:%S.%f") is None
    assert format_error("date", "%%H") is None  # literal percent followed by H
    assert format_error("date", "%Y %H") is not None
    assert format_error("datetime", "%Y %z") is not None
    assert format_error("date", "100%") is None  # lone trailing percent: not a directive


# ------------------------------------------------------ (B) config scalars


@pytest.mark.parametrize(
    ("value", "ctype", "expected"),
    [
        (5, "integer", 5),
        (1.0, "integer", 1),
        (-3.0, "integer", -3),
        ("5", "integer", 5),
        (" 7 ", "integer", 7),
        (2**63 - 1, "integer", 2**63 - 1),
        (1, "float", 1.0),
        (2.5, "float", 2.5),
        ("1e3", "float", 1000.0),
        (True, "boolean", True),
        (0, "boolean", False),
        (1, "boolean", True),
        (1.0, "boolean", True),
        ("yes", "boolean", True),
        ("0", "boolean", False),
        ("2024-01-31", "date", date(2024, 1, 31)),
        ("2024-01-31T10:00:00", "datetime", datetime(2024, 1, 31, 10)),
        ("2024-01-31 10:00", "datetime", datetime(2024, 1, 31, 10)),
        ("x", "string", "x"),
        ("", "string", ""),
        (" x ", "string", " x "),
    ],
)
def test_config_scalar_accepted(value: Any, ctype: str, expected: Any) -> None:
    result = cast_config_value(value, ctype)
    assert result == expected and type(result) is type(expected)


@pytest.mark.parametrize(
    ("value", "ctype"),
    [
        (True, "integer"),
        (1.5, "integer"),
        (float("inf"), "integer"),
        (2**63, "integer"),
        (1e30, "integer"),
        ("1.0", "integer"),
        ("", "integer"),
        ("  ", "float"),
        ("1_000", "integer"),
        (True, "float"),
        (float("nan"), "float"),
        (10**400, "float"),
        ("nan", "float"),
        (2, "boolean"),
        (0.5, "boolean"),
        ("maybe", "boolean"),
        (5, "date"),
        (True, "date"),
        ("20240131", "date"),
        ("2024-02-30", "date"),
        ("31/01/2024", "date"),
        (" 2024-01-31", "date"),
        ("2024-01-31", "datetime"),
        ("2024-01-31T10:00:00Z", "datetime"),
        ("2024-01-31T10:00:00+02:00", "datetime"),
        (5, "string"),
        (True, "string"),
        (2.5, "string"),
        (None, "string"),
        (None, "integer"),
    ],
)
def test_config_scalar_rejected(value: Any, ctype: str) -> None:
    with pytest.raises(CastError):
        cast_config_value(value, ctype)


def test_config_scalar_unknown_type() -> None:
    with pytest.raises(CastError):
        cast_config_value("x", "decimal")


# ---------------------------------------------------------------- inference


@pytest.mark.parametrize(
    ("cells", "expected"),
    [
        (["1", "2", None, " 3 "], "integer"),
        (["0", "1"], "integer"),  # 0/1 columns infer integer
        (["1", "2.5"], "float"),
        (["yes", "no", "YES"], "boolean"),
        (["true", "false"], "boolean"),
        (["1", "yes"], "boolean"),
        (["2024-01-31", "2024-02-01"], "date"),
        (["2024-01-31", "2024-02-01T10:00"], "string"),  # no single type fits both
        (["2024-01-31T10:00:00"], "datetime"),
        (["2024-01-31T10:00:00Z"], "string"),
        (["1", "x"], "string"),
        (["1,5"], "string"),
        ([None, None], "string"),
        ([], "string"),
        (["  ", ""], "string"),
        (["abc"], "string"),
        (["١٢"], "string"),
        (["9223372036854775808"], "float"),
        (["1e3"], "float"),
    ],
)
def test_infer_type(cells: list[str | None], expected: str) -> None:
    assert infer_type(cells) == expected


def test_infer_type_agrees_with_cast_cell() -> None:
    for cells in (["1", "2"], ["1.5"], ["yes"], ["2024-01-31"], ["2024-01-31 10:00"]):
        t = infer_type(cells)
        assert all(cast_cell(c, t) is not None for c in cells)
