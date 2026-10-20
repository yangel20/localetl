"""CSV inspection, preview and chunked extraction (ETL-02).

Tokenizing uses the stdlib ``csv.reader(strict=True)`` over a strictly decoded
text stream opened with ``newline=""`` (docs/architecture.md section 5, "CSV
structure and malformed input", decision Q4). pandas is not used for parsing: its
readers pad short rows, rename duplicate headers and shift columns.

* File-level faults raise :class:`CsvFormatError` (empty file, header only, bytes
  undecodable in the chosen encoding, more than 500 columns, empty or duplicate
  header names, an unterminated quoted field, a field over 131,072 characters).
* Row-level faults (wrong field count, a recoverable quoting fault) become
  ``parse_error`` :class:`RejectedRow` entries with ``column=None``.
* Blank lines are skipped and are not records. Row numbers are 1-based ordinals
  of *records* (header and blank lines excluded), global across chunks.

For the runner (ETL-07)::

    for chunk in iter_csv_chunks(path, options, chunk_rows=50_000):
        chunk.frame         # DataFrame of str/None, columns = header (or column_N)
        chunk.row_numbers   # record ordinal of each frame row
        chunk.rejected      # parse_error RejectedRow entries found in this chunk
        chunk.records       # records in the chunk, well-formed or not (counts to extracted_count)
"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import IO

import pandas as pd

from .casting import cast_cell, infer_type
from .errors import CsvFormatError
from .types import ColumnInfo, CsvOptions, CsvPreview, CsvProfile, RejectedRow

MAX_COLUMNS = 500
MAX_FIELD_CHARS = 131_072
MAX_REJECTED_VALUE_LENGTH = 500
QUOTING_FAULT_MESSAGE = "quoting fault"

_STRUCTURAL_MARKERS = ("unexpected end of data", "field larger than field limit")


@dataclass(frozen=True)
class CsvChunk:
    frame: pd.DataFrame  # well-formed records; str or None (empty string -> None)
    row_numbers: list[int]  # 1-based record ordinal for each frame row
    rejected: list[RejectedRow]  # parse_error entries for malformed records in this chunk
    records: int  # all records in the chunk (well-formed + malformed)


@dataclass(frozen=True)
class _Record:
    number: int
    fields: list[str] | None  # None for a quoting fault (the reader yields no fields)
    fault: str | None  # parse_error message, None when well-formed
    value: str | None  # parse_error value


def _fault_value(error: csv.Error) -> str | None:
    """``RejectedRow.value`` for a quoting fault.

    OPEN (board Q8-5): ``csv.reader`` raises instead of returning the fields, so
    the "fields joined with the delimiter" rule cannot apply. Today this is
    ``None``. This is the only place to change when the ruling arrives.
    """
    return None


def _width_fault_value(fields: list[str], delimiter: str) -> str:
    return delimiter.join(fields)[:MAX_REJECTED_VALUE_LENGTH]


# ---------------------------------------------------------------- tokenizing


class _Source:
    """One open CSV file: validated header, then records."""

    def __init__(self, path: Path, options: CsvOptions) -> None:
        self._options = options
        self._fh: IO[str] | None = None
        try:
            self._fh = open(path, encoding=options.encoding, errors="strict", newline="")  # noqa: SIM115
        except OSError as exc:
            raise CsvFormatError(f"cannot open file: {exc.strerror or exc}") from exc
        csv.field_size_limit(MAX_FIELD_CHARS)
        self._reader = csv.reader(
            self._fh, delimiter=options.delimiter, quotechar=options.quote_char, strict=True
        )
        self._first: _Record | None = None
        try:
            self.columns: list[str] = self._read_header()
        except BaseException:
            self.close()
            raise
        self.width = len(self.columns)

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def __enter__(self) -> _Source:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- low level

    def _tokens(self) -> Iterator[list[str] | csv.Error]:
        """Non-blank records as field lists; recoverable quoting faults as the error object."""
        while True:
            try:
                fields = next(self._reader)
            except StopIteration:
                return
            except UnicodeDecodeError as exc:
                raise CsvFormatError(
                    f"file is not valid {self._options.encoding}: "
                    f"byte {exc.start} cannot be decoded"
                ) from exc
            except csv.Error as exc:
                text = str(exc)
                if any(marker in text for marker in _STRUCTURAL_MARKERS):
                    if "field larger" in text:
                        raise CsvFormatError(
                            f"a field is longer than {MAX_FIELD_CHARS} characters"
                        ) from exc
                    raise CsvFormatError(
                        "a quoted field is still open at the end of the file"
                    ) from exc
                yield exc
                continue
            if not fields:  # blank line
                continue
            yield fields

    def _read_header(self) -> list[str]:
        tokens = self._tokens()
        first = next(tokens, None)
        if first is None:
            raise CsvFormatError("file is empty")
        if isinstance(first, csv.Error):
            raise CsvFormatError(f"the first row cannot be parsed: {first}")
        if len(first) > MAX_COLUMNS:
            raise CsvFormatError(f"too many columns: {len(first)} (maximum {MAX_COLUMNS})")
        self._tokens_iter = tokens
        if not self._options.has_header:
            self._first = _Record(1, first, None, None)
            return [f"column_{i}" for i in range(1, len(first) + 1)]
        for position, name in enumerate(first, start=1):
            if name == "":
                raise CsvFormatError(f"header in column {position} is empty")
        positions: dict[str, list[int]] = {}
        for position, name in enumerate(first, start=1):
            positions.setdefault(name, []).append(position)
        duplicated = {n: p for n, p in positions.items() if len(p) > 1}
        if duplicated:
            listed = ", ".join(
                f'"{n}" (columns {", ".join(str(i) for i in p)})' for n, p in duplicated.items()
            )
            raise CsvFormatError(f"duplicate header names: {listed}")
        return list(first)

    # -- records

    def records(self) -> Iterator[_Record]:
        """All data records; ``CsvFormatError`` for file-level faults, incl. a header-only file."""
        number = 0
        delimiter = self._options.delimiter
        if self._first is not None:
            number = 1
            yield self._first
        for item in self._tokens_iter:
            number += 1
            if isinstance(item, csv.Error):
                yield _Record(number, None, QUOTING_FAULT_MESSAGE, _fault_value(item))
            elif len(item) != self.width:
                yield _Record(
                    number,
                    item,
                    f"expected {self.width} fields, found {len(item)}",
                    _width_fault_value(item, delimiter),
                )
            else:
                yield _Record(number, item, None, None)
        if number == 0:
            raise CsvFormatError("file has a header but no data rows")


def _cell(value: str) -> str | None:
    return None if value == "" else value


def _to_rejected(record: _Record) -> RejectedRow:
    assert record.fault is not None
    return RejectedRow(
        row_number=record.number,
        column=None,
        rule="parse_error",
        message=record.fault,
        value=record.value,
    )


# ------------------------------------------------------------------- public


def iter_csv_chunks(
    path: Path, options: CsvOptions, *, chunk_rows: int = 50_000
) -> Iterator[CsvChunk]:
    """Yield chunks of ``chunk_rows`` *records* (malformed ones included).

    The header is validated before the first chunk. A file-level fault found
    later raises ``CsvFormatError`` after the earlier chunks were yielded.
    """
    if chunk_rows < 1:
        raise ValueError("chunk_rows must be at least 1")
    with _Source(path, options) as source:
        rows: list[list[str | None]] = []
        numbers: list[int] = []
        rejected: list[RejectedRow] = []
        records = 0

        def build() -> CsvChunk:
            frame = pd.DataFrame(rows, columns=source.columns, dtype=object)
            return CsvChunk(frame, list(numbers), list(rejected), records)

        for record in source.records():
            records += 1
            if record.fault is not None:
                rejected.append(_to_rejected(record))
            else:
                assert record.fields is not None
                rows.append([_cell(v) for v in record.fields])
                numbers.append(record.number)
            if records == chunk_rows:
                yield build()
                rows, numbers, rejected, records = [], [], [], 0
        if records:
            yield build()


def _profile(columns: list[str], sample: list[list[str]]) -> list[ColumnInfo]:
    infos: list[ColumnInfo] = []
    for index, name in enumerate(columns):
        cells: list[str | None] = [_cell(row[index]) for row in sample]
        inferred = infer_type(cells)
        nulls = sum(1 for c in cells if cast_cell(c, inferred) is None)
        infos.append(ColumnInfo(name=name, inferred_type=inferred, null_count=nulls))
    return infos


def inspect_csv(path: Path, options: CsvOptions, *, sample_rows: int = 1000) -> CsvProfile:
    """Full streaming pass: validates the file and counts every data record."""
    if sample_rows < 1:
        raise ValueError("sample_rows must be at least 1")
    sample: list[list[str]] = []
    row_count = 0
    with _Source(path, options) as source:
        for record in source.records():
            row_count += 1
            if record.fault is None and len(sample) < sample_rows:
                assert record.fields is not None
                sample.append(record.fields)
        return CsvProfile(columns=_profile(source.columns, sample), row_count=row_count)


def preview_csv(path: Path, options: CsvOptions, *, limit: int = 50) -> CsvPreview:
    """The first ``limit`` well-formed records; reads only as far as needed."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    sample: list[list[str]] = []
    with _Source(path, options) as source:
        for record in source.records():
            if record.fault is None:
                assert record.fields is not None
                sample.append(record.fields)
                if len(sample) == limit:
                    break
        rows = [
            {name: _cell(value) for name, value in zip(source.columns, fields, strict=True)}
            for fields in sample
        ]
        return CsvPreview(
            columns=_profile(source.columns, sample), rows=rows, sampled_rows=len(sample)
        )
