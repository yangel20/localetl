"""Validate stage (docs/architecture.md section 5, "Stage semantics" 3).

The validate stage receives *already typed* chunks (Python ``int``, ``float``,
``bool``, ``date``, naive ``datetime``, ``str`` or null) whose columns are the
target names (``columns[].name``). It never parses CSV text.

Usage (by the runner, ETL-07)::

    validator = Validator(config)
    for chunk, row_numbers in typed_chunks:
        result = validator.validate_chunk(chunk, row_numbers)   # may raise
        # result.valid -> rows to load; result.rejections -> RejectedRow entries
    check_rejection_ratio(config, total_rejected_count, extracted_count)

Row accounting (Q3): a row failing several rules is counted once in
``ChunkResult.rejected_rows`` and yields one :class:`RejectedRow` per failing
rule. ``unique`` keeps the first occurrence across chunks; a key is registered
by the first row that reaches the step, even if that row fails another rule.
Nulls are ignored by every rule except ``not_null`` (they never fail ``unique``,
``range``, ``allowed_values``, ``regex`` or ``length``).

Casting hold (Q6-3 is not approved): config values (``range`` bounds,
``allowed_values.values``) are converted by :func:`_config_scalar`, which only
handles the unambiguous cases and raises ``NotImplementedError`` otherwise.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import pandas as pd

from .errors import EtlError, RejectionLimitExceeded
from .types import PipelineConfig, RejectedRow, RejectionRule

MAX_REGEX_VALUE_LENGTH = 10_000
MAX_REJECTED_VALUE_LENGTH = 500
_BIGINT_MIN = -(2**63)
_BIGINT_MAX = 2**63 - 1
_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_DATETIME_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}")
_HOLD = "pending casting specification Q6-3"


@dataclass(frozen=True)
class ChunkResult:
    valid: pd.DataFrame  # input rows that passed every rule, original order and index
    rejections: list[RejectedRow]  # one entry per (row, failing rule), row order then rule order
    rejected_rows: int  # distinct rows with at least one entry


# ----------------------------------------------------------------- config values


def _config_scalar(value: Any, column_type: str) -> Any:
    """Convert a JSON config scalar to the column's Python type.

    Only the cases that behave identically before and after the casting
    specification (Q6-3) are implemented. Everything else is held.
    """
    if column_type == "integer":
        if type(value) is int and _BIGINT_MIN <= value <= _BIGINT_MAX:
            return value
    elif column_type == "float":
        if type(value) in (int, float):
            try:
                result = float(value)
            except OverflowError:
                result = math.inf
            if math.isfinite(result):
                return result
    elif column_type == "boolean":
        if type(value) is bool:
            return value
    elif column_type == "string":
        if type(value) is str:
            return value
    elif column_type == "date":
        if type(value) is str and _DATE_RE.fullmatch(value):
            try:
                return date.fromisoformat(value)
            except ValueError:
                pass
    elif column_type == "datetime":
        if type(value) is str and _DATETIME_RE.fullmatch(value):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                pass
    raise NotImplementedError(_HOLD)


# ------------------------------------------------------------------ cell helpers


def _typed_values(frame: pd.DataFrame, name: str, column_type: str) -> list[Any]:
    """Column as a list of Python values with ``None`` for nulls."""
    if name not in frame.columns:
        raise EtlError(f"validate: column '{name}' missing from the chunk")
    out: list[Any] = []
    for value in frame[name].tolist():
        if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
            out.append(None)
        elif isinstance(value, pd.Timestamp):
            py = value.to_pydatetime()
            out.append(py.date() if column_type == "date" else py)
        elif column_type == "date" and isinstance(value, datetime):
            out.append(value.date())
        else:
            out.append(value)
    return out


def _render(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _clip(text: str) -> str:
    return text[:MAX_REJECTED_VALUE_LENGTH]


# -------------------------------------------------------------------- the rules

# A compiled rule maps (frame, names->types) to a list of (position, entry fields).
_Failure = tuple[int, RejectedRow]
_Compiled = Callable[[pd.DataFrame, Sequence[int]], list[_Failure]]


class Validator:
    """Stateful validator for one run (keeps ``unique`` keys across chunks)."""

    def __init__(self, config: PipelineConfig) -> None:
        raw = config.raw
        self._types: dict[str, str] = {c["name"]: c["type"] for c in raw["columns"]}
        self._fail_run = raw.get("on_validation_failure", "reject_row") == "fail_run"
        self._rules: list[_Compiled] = [self._compile(v) for v in raw.get("validations", [])]
        self.rejected_rows = 0  # cumulative distinct rejected rows across chunks

    # ------------------------------------------------------------------ public

    def validate_chunk(self, frame: pd.DataFrame, row_numbers: Sequence[int]) -> ChunkResult:
        """Apply every rule; ``row_numbers[i]`` is the 1-based data row of row ``i``."""
        if len(row_numbers) != len(frame):
            raise EtlError("validate: row_numbers must align with the chunk rows")
        failures: list[tuple[int, int, RejectedRow]] = []
        for rule_index, rule in enumerate(self._rules):
            for position, entry in rule(frame, row_numbers):
                failures.append((position, rule_index, entry))
        failures.sort(key=lambda f: (f[0], f[1]))
        if failures and self._fail_run:
            first = failures[0][2]
            raise RejectionLimitExceeded(
                f"on_validation_failure=fail_run: row {first.row_number} failed "
                f"{first.rule}: {first.message}"
            )
        bad_positions = {f[0] for f in failures}
        self.rejected_rows += len(bad_positions)
        keep = [i not in bad_positions for i in range(len(frame))]
        return ChunkResult(
            valid=frame[keep],
            rejections=[f[2] for f in failures],
            rejected_rows=len(bad_positions),
        )

    # ---------------------------------------------------------------- compilers

    def _compile(self, rule: dict[str, Any]) -> _Compiled:
        compiler = _COMPILERS.get(rule["rule"])
        if compiler is None:  # config is schema-validated; this guards future enum growth
            raise EtlError(f"validate: unsupported rule '{rule['rule']}'")
        return compiler(self, rule)

    def _entry(
        self, number: int, column: str | None, rule: RejectionRule, message: str, value: Any
    ) -> RejectedRow:
        rendered = None if value is None else _clip(_render(value))
        return RejectedRow(
            row_number=number,
            column=column,
            rule=rule,
            message=message,
            value=rendered,
        )

    def _not_null(self, rule: dict[str, Any]) -> _Compiled:
        name = rule["column"]
        ctype = self._types[name]

        def run(frame: pd.DataFrame, numbers: Sequence[int]) -> list[_Failure]:
            values = _typed_values(frame, name, ctype)
            return [
                (i, self._entry(numbers[i], name, "not_null", f"'{name}' must not be null", None))
                for i, v in enumerate(values)
                if v is None
            ]

        return run

    def _unique(self, rule: dict[str, Any]) -> _Compiled:
        names: list[str] = rule["columns"]
        seen: set[tuple[Any, ...]] = set()

        def run(frame: pd.DataFrame, numbers: Sequence[int]) -> list[_Failure]:
            columns = [_typed_values(frame, n, self._types[n]) for n in names]
            out: list[_Failure] = []
            for i in range(len(frame)):
                key = tuple(col[i] for col in columns)
                if any(k is None for k in key):
                    continue  # nulls are distinct; not_null covers them
                if key in seen:
                    label = names[0] if len(names) == 1 else None
                    shown = ", ".join(_render(k) for k in key)
                    out.append(
                        (
                            i,
                            self._entry(
                                numbers[i],
                                label,
                                "unique",
                                f"duplicate value for unique key ({', '.join(names)})",
                                shown,
                            ),
                        )
                    )
                else:
                    seen.add(key)
            return out

        return run

    def _range(self, rule: dict[str, Any]) -> _Compiled:
        name = rule["column"]
        ctype = self._types[name]
        low = _config_scalar(rule["min"], ctype) if "min" in rule else None
        high = _config_scalar(rule["max"], ctype) if "max" in rule else None

        def run(frame: pd.DataFrame, numbers: Sequence[int]) -> list[_Failure]:
            out: list[_Failure] = []
            for i, v in enumerate(_typed_values(frame, name, ctype)):
                if v is None:
                    continue
                if (low is not None and v < low) or (high is not None and v > high):
                    bounds = " and ".join(
                        p
                        for p in (
                            f">= {_render(low)}" if low is not None else "",
                            f"<= {_render(high)}" if high is not None else "",
                        )
                        if p
                    )
                    out.append(
                        (
                            i,
                            self._entry(numbers[i], name, "range", f"'{name}' must be {bounds}", v),
                        )
                    )
            return out

        return run

    def _allowed_values(self, rule: dict[str, Any]) -> _Compiled:
        name = rule["column"]
        ctype = self._types[name]
        allowed = {_config_scalar(v, ctype) for v in rule["values"]}

        def run(frame: pd.DataFrame, numbers: Sequence[int]) -> list[_Failure]:
            return [
                (
                    i,
                    self._entry(
                        numbers[i], name, "allowed_values", f"'{name}' is not an allowed value", v
                    ),
                )
                for i, v in enumerate(_typed_values(frame, name, ctype))
                if v is not None and v not in allowed
            ]

        return run

    def _regex(self, rule: dict[str, Any]) -> _Compiled:
        name = rule["column"]
        ctype = self._types[name]
        pattern = re.compile(rule["pattern"])

        def run(frame: pd.DataFrame, numbers: Sequence[int]) -> list[_Failure]:
            out: list[_Failure] = []
            for i, v in enumerate(_typed_values(frame, name, ctype)):
                if v is None:
                    continue
                text = str(v)
                if len(text) > MAX_REGEX_VALUE_LENGTH:
                    message = (
                        f"'{name}' is longer than {MAX_REGEX_VALUE_LENGTH} characters; not matched"
                    )
                elif pattern.fullmatch(text):
                    continue
                else:
                    message = f"'{name}' does not match pattern {rule['pattern']!r}"
                out.append((i, self._entry(numbers[i], name, "regex", message, text)))
            return out

        return run

    def _length(self, rule: dict[str, Any]) -> _Compiled:
        name = rule["column"]
        ctype = self._types[name]
        low: int | None = rule.get("min")
        high: int | None = rule.get("max")

        def run(frame: pd.DataFrame, numbers: Sequence[int]) -> list[_Failure]:
            out: list[_Failure] = []
            for i, v in enumerate(_typed_values(frame, name, ctype)):
                if v is None:
                    continue
                text = str(v)
                if (low is not None and len(text) < low) or (high is not None and len(text) > high):
                    bounds = " and ".join(
                        p
                        for p in (
                            f">= {low}" if low is not None else "",
                            f"<= {high}" if high is not None else "",
                        )
                        if p
                    )
                    out.append(
                        (
                            i,
                            self._entry(
                                numbers[i],
                                name,
                                "length",
                                f"'{name}' length must be {bounds}",
                                text,
                            ),
                        )
                    )
            return out

        return run


_COMPILERS: dict[str, Callable[[Validator, dict[str, Any]], _Compiled]] = {
    "not_null": Validator._not_null,
    "unique": Validator._unique,
    "range": Validator._range,
    "allowed_values": Validator._allowed_values,
    "regex": Validator._regex,
    "length": Validator._length,
}


def check_rejection_ratio(
    config: PipelineConfig, rejected_count: int, extracted_count: int
) -> None:
    """Raise ``RejectionLimitExceeded`` if ``rejected_count / extracted_count`` exceeds the limit.

    ``rejected_count`` is the run's total (parse, cast, not-null and validation
    rejections). Rows dropped by ``deduplicate``/``drop_null_rows`` count in the
    denominator only.
    """
    if extracted_count <= 0:
        return
    limit = float(config.raw.get("max_rejected_ratio", 1))
    ratio = rejected_count / extracted_count
    if ratio > limit:
        raise RejectionLimitExceeded(
            f"rejected ratio {ratio:.4f} ({rejected_count}/{extracted_count}) "
            f"exceeds max_rejected_ratio {limit}"
        )
