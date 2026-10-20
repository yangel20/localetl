"""Transform stage (docs/architecture.md section 5, "Stage semantics" 2).

Per chunk, in this order (Q3 "first removal wins"):

a. select ``columns[].source`` and rename to ``columns[].name``;
b. cast every cell with :mod:`app.etl.casting` (A) -> ``type_cast`` rejections
   (one entry per bad cell, decision C-d); null cells of ``nullable: false``
   columns -> ``not_null`` rejections;
c. apply ``transformations`` in array order. ``deduplicate`` and
   ``drop_null_rows`` remove rows without rejecting them.

Output cells are Python ``int``/``float``/``bool``/``date``/naive ``datetime``/
``str`` or ``None`` in ``object`` columns, so an integer column with nulls never
becomes float. Under ``on_validation_failure: fail_run`` the whole chunk is cast
and checked before ``RejectionLimitExceeded`` is raised (Q7-3).

Usage (ETL-07)::

    transformer = Transformer(config)
    result = transformer.transform_chunk(chunk.frame, chunk.row_numbers)
    # result.frame / result.row_numbers -> validate stage
    # result.rejections, result.rejected_rows, result.duplicate_dropped, result.null_dropped
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import pandas as pd

from .casting import CastError, cast_cell, cast_config_value
from .errors import EtlError, RejectionLimitExceeded, SourceMismatchError
from .types import PipelineConfig, RejectedRow

MAX_REJECTED_VALUE_LENGTH = 500


@dataclass(frozen=True)
class TransformResult:
    frame: pd.DataFrame  # typed rows that continue to the validate stage; columns = target names
    row_numbers: list[int]  # aligned with ``frame`` rows
    rejections: list[RejectedRow]  # type_cast / not_null, in row then column order
    rejected_rows: int  # distinct rows with at least one rejection
    duplicate_dropped: int  # rows removed by ``deduplicate`` in this chunk
    null_dropped: int  # rows removed by ``drop_null_rows`` in this chunk
    rows_in: int  # well-formed rows received
    rows_out: int  # rows in ``frame``


@dataclass
class _Work:
    """Mutable column store for one chunk; every list has one entry per live row."""

    cols: dict[str, list[Any]]
    numbers: list[int]
    duplicate_dropped: int = 0
    null_dropped: int = 0

    def __len__(self) -> int:
        return len(self.numbers)

    def keep(self, mask: Sequence[bool]) -> int:
        """Keep rows where ``mask`` is true; returns how many were removed."""
        removed = len(mask) - sum(mask)
        if removed:
            for name, values in self.cols.items():
                self.cols[name] = [v for v, m in zip(values, mask, strict=True) if m]
            self.numbers = [n for n, m in zip(self.numbers, mask, strict=True) if m]
        return removed


_Step = Callable[[_Work], None]


def _render(value: Any) -> str:
    """A typed value as the string ``replace_values`` keys are compared with."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _clip(text: str) -> str:
    return text[:MAX_REJECTED_VALUE_LENGTH]


class Transformer:
    """Stateful transform stage for one run (``deduplicate`` keys span chunks)."""

    def __init__(self, config: PipelineConfig) -> None:
        raw = config.raw
        self._columns: list[dict[str, Any]] = list(raw["columns"])
        self._types = {c["name"]: c["type"] for c in self._columns}
        self._fail_run = raw.get("on_validation_failure", "reject_row") == "fail_run"
        self._steps: list[_Step] = [self._compile(t) for t in raw.get("transformations", [])]

    # ------------------------------------------------------------------ public

    def transform_chunk(self, frame: pd.DataFrame, row_numbers: Sequence[int]) -> TransformResult:
        """Run stage 2 on one chunk of source strings; ``row_numbers[i]`` is row ``i``'s number."""
        if len(row_numbers) != len(frame):
            raise EtlError("transform: row_numbers must align with the chunk rows")
        rows_in = len(frame)
        cols, rejections, bad = self._cast(frame, row_numbers)
        if rejections and self._fail_run:
            first = rejections[0]
            raise RejectionLimitExceeded(
                f"on_validation_failure=fail_run: row {first.row_number} failed "
                f"{first.rule}: {first.message}"
            )
        work = _Work(
            cols={n: [v for v, b in zip(c, bad, strict=True) if not b] for n, c in cols.items()},
            numbers=[n for n, b in zip(row_numbers, bad, strict=True) if not b],
        )
        for step in self._steps:
            step(work)
        out = pd.DataFrame(
            {name: pd.Series(work.cols[name], dtype=object) for name in self._types},
            columns=list(self._types),
        )
        return TransformResult(
            frame=out,
            row_numbers=list(work.numbers),
            rejections=rejections,
            rejected_rows=sum(bad),
            duplicate_dropped=work.duplicate_dropped,
            null_dropped=work.null_dropped,
            rows_in=rows_in,
            rows_out=len(work),
        )

    # -------------------------------------------------------------- (a) and (b)

    def _cast(
        self, frame: pd.DataFrame, row_numbers: Sequence[int]
    ) -> tuple[dict[str, list[Any]], list[RejectedRow], list[bool]]:
        sources: list[list[Any]] = []
        for col in self._columns:
            if col["source"] not in frame.columns:
                raise SourceMismatchError(
                    f"source column '{col['source']}' is missing from the CSV"
                )
            sources.append(frame[col["source"]].tolist())
        count = len(frame)
        cols: dict[str, list[Any]] = {c["name"]: [None] * count for c in self._columns}
        bad = [False] * count
        rejections: list[RejectedRow] = []
        for i in range(count):
            for col, source in zip(self._columns, sources, strict=True):
                name, ctype, fmt = col["name"], col["type"], col.get("format")
                raw = source[i]
                if raw is not None and not isinstance(raw, str):
                    if pd.isna(raw):
                        raw = None
                    else:
                        raise EtlError(f"transform: column '{col['source']}' must hold strings")
                try:
                    value = cast_cell(raw, ctype, fmt)
                except CastError:
                    bad[i] = True
                    suffix = f" with format {fmt}" if fmt else ""
                    shown = _clip(raw or "")
                    rejections.append(
                        RejectedRow(
                            row_number=row_numbers[i],
                            column=name,
                            rule="type_cast",
                            message=f'cannot cast "{shown}" to {ctype}{suffix}',
                            value=shown,
                        )
                    )
                    continue
                if value is None and not col.get("nullable", True):
                    bad[i] = True
                    rejections.append(
                        RejectedRow(
                            row_number=row_numbers[i],
                            column=name,
                            rule="not_null",
                            message=f"'{name}' must not be null",
                            value=None,
                        )
                    )
                cols[name][i] = value
        return cols, rejections, bad

    # -------------------------------------------------------- (c) transformations

    def _compile(self, op: dict[str, Any]) -> _Step:
        handler = _OPS.get(op["op"])
        if handler is None:  # schema-validated config; guards future enum growth
            raise EtlError(f"transform: unsupported operation '{op['op']}'")
        return handler(self, op)

    def _require_type(self, op: dict[str, Any], names: Sequence[str], ctype: str) -> None:
        for name in names:
            if self._types.get(name) != ctype:
                raise EtlError(
                    f"transform: {op['op']} applies only to {ctype} columns; "
                    f"'{name}' is {self._types.get(name)}"
                )

    def _trim_whitespace(self, op: dict[str, Any]) -> _Step:
        names: list[str] = op["columns"]
        self._require_type(op, names, "string")

        def step(work: _Work) -> None:
            for name in names:
                work.cols[name] = [None if v is None else v.strip() for v in work.cols[name]]

        return step

    def _change_case(self, op: dict[str, Any]) -> _Step:
        names: list[str] = op["columns"]
        self._require_type(op, names, "string")
        convert: Callable[[str], str] = {
            "lower": str.lower,
            "upper": str.upper,
            "title": str.title,
        }[op["case"]]

        def step(work: _Work) -> None:
            for name in names:
                work.cols[name] = [None if v is None else convert(v) for v in work.cols[name]]

        return step

    def _replace_values(self, op: dict[str, Any]) -> _Step:
        name: str = op["column"]
        ctype = self._types[name]
        mapping: dict[str, Any] = {}
        for key, replacement in op["mapping"].items():
            if replacement is None:
                mapping[key] = None
                continue
            try:
                mapping[key] = cast_config_value(replacement, ctype)
            except CastError as exc:
                raise EtlError(
                    f"transform: replace_values on '{name}': {replacement!r} is not a valid "
                    f"{ctype} value ({exc})"
                ) from exc

        def step(work: _Work) -> None:
            work.cols[name] = [
                v if v is None or _render(v) not in mapping else mapping[_render(v)]
                for v in work.cols[name]
            ]

        return step

    def _fill_null(self, op: dict[str, Any]) -> _Step:
        name: str = op["column"]
        try:
            fill = cast_config_value(op["value"], self._types[name])
        except CastError as exc:
            raise EtlError(f"transform: fill_null on '{name}': {exc}") from exc

        def step(work: _Work) -> None:
            work.cols[name] = [fill if v is None else v for v in work.cols[name]]

        return step

    def _drop_null_rows(self, op: dict[str, Any]) -> _Step:
        names: list[str] = op["columns"]
        how = op.get("how", "any")

        def step(work: _Work) -> None:
            nulls = [[v is None for v in work.cols[n]] for n in names]
            drop = [
                (any if how == "any" else all)(col[i] for col in nulls) for i in range(len(work))
            ]
            work.null_dropped += work.keep([not d for d in drop])

        return step

    def _deduplicate(self, op: dict[str, Any]) -> _Step:
        names: list[str] = op.get("columns") or list(self._types)
        seen: set[tuple[Any, ...]] = set()

        def step(work: _Work) -> None:
            mask: list[bool] = []
            columns = [work.cols[n] for n in names]
            for i in range(len(work)):
                key = tuple(col[i] for col in columns)  # nulls compare equal, like SQL DISTINCT
                if key in seen:
                    mask.append(False)
                else:
                    seen.add(key)
                    mask.append(True)
            work.duplicate_dropped += work.keep(mask)

        return step

    def _round_number(self, op: dict[str, Any]) -> _Step:
        name: str = op["column"]
        self._require_type(op, [name], "float")
        decimals: int = op["decimals"]

        def step(work: _Work) -> None:
            work.cols[name] = [None if v is None else round(v, decimals) for v in work.cols[name]]

        return step


_OPS: dict[str, Callable[[Transformer, dict[str, Any]], _Step]] = {
    "trim_whitespace": Transformer._trim_whitespace,
    "change_case": Transformer._change_case,
    "replace_values": Transformer._replace_values,
    "fill_null": Transformer._fill_null,
    "drop_null_rows": Transformer._drop_null_rows,
    "deduplicate": Transformer._deduplicate,
    "round_number": Transformer._round_number,
}
