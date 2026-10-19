"""Public data types of the ETL engine (docs/architecture.md section 5)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

ColumnType = Literal["integer", "float", "boolean", "date", "datetime", "string"]
Stage = Literal["extract", "transform", "validate", "load", "publish"]
EventStatus = Literal["started", "progress", "completed", "failed"]
RejectionRule = Literal[
    "not_null",
    "unique",
    "range",
    "allowed_values",
    "regex",
    "length",
    "type_cast",
    "parse_error",
]


@dataclass(frozen=True)
class CsvOptions:
    encoding: Literal["utf-8", "utf-8-sig", "latin-1", "cp1252"] = "utf-8"
    delimiter: Literal[",", ";", "\t", "|"] = ","
    has_header: bool = True
    quote_char: str = '"'


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    inferred_type: ColumnType
    null_count: int


@dataclass(frozen=True)
class CsvProfile:
    """Returned by ``inspect_csv``; stored on the data source."""

    columns: list[ColumnInfo]
    row_count: int


@dataclass(frozen=True)
class CsvPreview:
    columns: list[ColumnInfo]
    rows: list[dict[str, str | None]]
    sampled_rows: int


@dataclass(frozen=True)
class ConfigErrorItem:
    path: str  # JSON Pointer into the config, e.g. "/transformations/2/columns"
    message: str


@dataclass(frozen=True)
class PipelineConfig:
    """Parsed, validated form of pipeline.schema.json.

    ``raw`` is the original JSON document. Typed accessors are added by
    ETL-03 without changing the public constructor contract.
    """

    raw: Mapping[str, Any]


@dataclass(frozen=True)
class RunCounters:
    """Cumulative row counters; same five fields, same order, as ``RunResult``."""

    extracted_count: int
    loaded_count: int  # 0 until the publish transaction commits
    rejected_count: int
    duplicate_dropped_count: int
    null_dropped_count: int


@dataclass(frozen=True)
class StageEvent:
    stage: Stage
    status: EventStatus
    rows_in: int | None
    rows_out: int | None
    message: str | None
    at: datetime  # UTC
    counters: RunCounters  # cumulative for the whole run after this event


@dataclass(frozen=True)
class RejectedRow:
    row_number: int  # 1-based data row (header excluded)
    column: str | None
    rule: RejectionRule
    message: str
    value: str | None  # truncated to 500 chars


@dataclass(frozen=True)
class PublishedTable:
    schema: Literal["datasets"]
    table: str
    columns: list[tuple[str, ColumnType]]
    row_count: int  # rows in the published table after publish


@dataclass(frozen=True)
class RunResult:
    extracted_count: int  # data rows read from the source file (header excluded)
    loaded_count: int  # rows committed to the published table by this run's publish
    rejected_count: int  # rows failing parsing, casting or a validation rule (once per row)
    duplicate_dropped_count: int  # rows removed by `deduplicate`
    null_dropped_count: int  # rows removed by `drop_null_rows`
    rejected_sample: list[RejectedRow]  # first 1,000 rejections, row order
    published: PublishedTable
    stage_durations_ms: dict[Stage, int]
