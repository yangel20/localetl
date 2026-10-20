"""Shared value casting (docs/architecture.md section 5, "Value casting", decision Q6-3).

One set of pure functions used by the transform stage (CSV cells, "A"), type
inference in ``inspect_csv`` (A), and config validation (config scalars, "B"), so
the three can never drift. Everything here is a pure function of the value, the
type and the format; digits are ASCII only.

* :func:`cast_cell`          (A) CSV text -> typed value; ``None`` is null.
* :func:`cast_config_value`  (B) JSON scalar -> typed value.
* :func:`infer_type`         type inference over sampled cells (A, no ``format``).
* :func:`format_error`       decision C-e directive check for ``columns[].format``.

Failures raise :class:`CastError`.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any

from .types import ColumnType

BIGINT_MIN = -(2**63)
BIGINT_MAX = 2**63 - 1

_INT_RE = re.compile(r"[+-]?[0-9]+")
_FLOAT_RE = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_DATE_RE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
_DATETIME_RE = re.compile(
    r"([0-9]{4})-([0-9]{2})-([0-9]{2})[T ]([0-9]{2}):([0-9]{2})(?::([0-9]{2})(?:\.([0-9]{1,6}))?)?"
)
_BOOLEANS = {"true": True, "false": False, "yes": True, "no": False, "1": True, "0": False}

# Decision C-e: directives that carry a time or a zone.
_TIME_DIRECTIVES = frozenset("HIMSfpXc")
_ZONE_DIRECTIVES = frozenset("zZ")

INFERENCE_ORDER: tuple[ColumnType, ...] = ("integer", "float", "boolean", "date", "datetime")


class CastError(ValueError):
    """A value cannot be cast to the requested type."""


# --------------------------------------------------------------------- scalars


def _parse_int(text: str) -> int:
    if not _INT_RE.fullmatch(text):
        raise CastError("not an integer")
    try:
        value = int(text)
    except ValueError as exc:  # Python's digit-count limit
        raise CastError("integer too large") from exc
    if not BIGINT_MIN <= value <= BIGINT_MAX:
        raise CastError("integer out of bigint range")
    return value


def _parse_float(text: str) -> float:
    if not _FLOAT_RE.fullmatch(text):
        raise CastError("not a float")
    try:
        value = float(text)
    except (ValueError, OverflowError) as exc:
        raise CastError("not a float") from exc
    if not math.isfinite(value):
        raise CastError("float is not finite")
    return value


def _parse_bool(text: str) -> bool:
    try:
        return _BOOLEANS[text.lower()]
    except KeyError:
        raise CastError("not a boolean") from None


def parse_iso_date(text: str) -> date:
    """``YYYY-MM-DD`` (a valid calendar date) and nothing else."""
    if not _DATE_RE.fullmatch(text):
        raise CastError("not an ISO date (YYYY-MM-DD)")
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise CastError("not a valid calendar date") from exc


def parse_iso_datetime(text: str) -> datetime:
    """``YYYY-MM-DD`` + ``T`` or one space + ``HH:MM[:SS[.f{1,6}]]``; no offset, no ``Z``."""
    m = _DATETIME_RE.fullmatch(text)
    if m is None:
        raise CastError("not an ISO datetime without offset")
    year, month, day, hour, minute, second, fraction = m.groups()
    try:
        return datetime(
            int(year),
            int(month),
            int(day),
            int(hour),
            int(minute),
            int(second or 0),
            int((fraction or "").ljust(6, "0")),
        )
    except ValueError as exc:
        raise CastError("not a valid date and time") from exc


def _strptime(text: str, fmt: str) -> datetime:
    # strptime's `\d` accepts non-ASCII decimal digits; digits are ASCII only.
    if any(ch.isdecimal() and not ch.isascii() for ch in text):
        raise CastError("non-ASCII digits")
    try:
        return datetime.strptime(text, fmt)
    except ValueError as exc:
        raise CastError("does not match the format") from exc


def _directives(fmt: str) -> set[str]:
    found: set[str] = set()
    i = 0
    while i < len(fmt):
        if fmt[i] == "%" and i + 1 < len(fmt):
            if fmt[i + 1] != "%":
                found.add(fmt[i + 1])
            i += 2
        else:
            i += 1
    return found


def format_error(column_type: str, fmt: str) -> str | None:
    """Decision C-e: why ``fmt`` is not allowed for ``column_type`` (``None`` if allowed)."""
    used = _directives(fmt)
    if used & _ZONE_DIRECTIVES:
        return "format must not contain a zone directive (%z, %Z)"
    if column_type == "date" and used & _TIME_DIRECTIVES:
        return "a date format must not contain a time directive (%H, %I, %M, %S, %f, %p, %X, %c)"
    return None


# ------------------------------------------------------------------- (A) cells


def cast_cell(raw: str | None, column_type: str, fmt: str | None = None) -> Any:
    """Cast one CSV cell. Returns ``None`` for null; raises :class:`CastError` on failure.

    Non-string values are stripped first, and a whitespace-only value is null
    (C-a). ``string`` values are returned unchanged.
    """
    if raw is None:
        return None
    if column_type == "string":
        return raw
    text = raw.strip()
    if text == "":
        return None
    if column_type == "integer":
        return _parse_int(text)
    if column_type == "float":
        return _parse_float(text)
    if column_type == "boolean":
        return _parse_bool(text)
    if column_type in ("date", "datetime"):
        if fmt is None:
            return parse_iso_date(text) if column_type == "date" else parse_iso_datetime(text)
        problem = format_error(column_type, fmt)
        if problem is not None:
            raise CastError(problem)
        parsed = _strptime(text, fmt)
        return parsed.date() if column_type == "date" else parsed
    raise CastError(f"unknown column type {column_type!r}")


def infer_type(cells: Iterable[str | None]) -> ColumnType:
    """First of integer, float, boolean, date, datetime that every non-null cell casts to.

    All-null (or empty) input is ``string``; so is anything that fits none.
    """
    values = [c for c in cells if c is not None and c.strip() != ""]
    if not values:
        return "string"
    for candidate in INFERENCE_ORDER:
        try:
            for v in values:
                cast_cell(v, candidate)
        except CastError:
            continue
        return candidate
    return "string"


# --------------------------------------------------------------- (B) config scalars


def cast_config_value(value: Any, column_type: str) -> Any:
    """Cast a JSON scalar from a config (``fill_null``, ``allowed_values``, ``range``).

    The column ``format`` never applies here (C-b). Raises :class:`CastError`.
    """
    if value is None:
        raise CastError("null is not a value")
    if column_type == "integer":
        if isinstance(value, bool):
            raise CastError("boolean is not an integer")
        if isinstance(value, int):
            if not BIGINT_MIN <= value <= BIGINT_MAX:
                raise CastError("integer out of bigint range")
            return value
        if isinstance(value, float):
            if not math.isfinite(value) or not value.is_integer():
                raise CastError("not an integral number")
            return _parse_int(str(int(value)))
        if isinstance(value, str):
            return _config_text(value, column_type)
    elif column_type == "float":
        if isinstance(value, bool):
            raise CastError("boolean is not a float")
        if isinstance(value, (int, float)):
            try:
                result = float(value)
            except OverflowError as exc:
                raise CastError("number out of range") from exc
            if not math.isfinite(result):
                raise CastError("float is not finite")
            return result
        if isinstance(value, str):
            return _config_text(value, column_type)
    elif column_type == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            if value == 0 or value == 1:
                return bool(value)
            raise CastError("only 0 and 1 are booleans")
        if isinstance(value, str):
            return _config_text(value, column_type)
    elif column_type == "date":
        if isinstance(value, str):
            return parse_iso_date(value)
    elif column_type == "datetime":
        if isinstance(value, str):
            return parse_iso_datetime(value)
    elif column_type == "string":
        if isinstance(value, str):
            return value
    else:
        raise CastError(f"unknown column type {column_type!r}")
    raise CastError(f"{type(value).__name__} is not a valid {column_type} value")


def _config_text(value: str, column_type: str) -> Any:
    """A string config value "per the CSV rule"; empty (null) is not a value."""
    result = cast_cell(value, column_type)
    if result is None:
        raise CastError("an empty value is not a value")
    return result
