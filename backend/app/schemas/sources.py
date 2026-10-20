"""Data source schemas (openapi.yaml: DataSource, DataSourcePage, CsvPreview, ColumnInfo)."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

ColumnType = Literal["integer", "float", "boolean", "date", "datetime", "string"]
Encoding = Literal["utf-8", "utf-8-sig", "latin-1", "cp1252"]
Delimiter = Literal[",", ";", "\t", "|"]
NonNegInt = Annotated[int, Field(ge=0)]


class CsvOptionsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    encoding: Encoding = "utf-8"
    delimiter: Delimiter = ","
    has_header: bool = True
    quote_char: Annotated[str, Field(min_length=1, max_length=1)] = '"'


class ColumnInfoOut(BaseModel):
    name: str
    inferred_type: ColumnType
    null_count: NonNegInt


class DataSourceOut(BaseModel):
    id: uuid.UUID
    name: str
    original_filename: str
    size_bytes: NonNegInt
    csv_options: CsvOptionsOut
    columns: list[ColumnInfoOut]
    row_count: NonNegInt
    created_at: AwareDatetime

    @field_validator("created_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class DataSourcePage(BaseModel):
    total: NonNegInt
    limit: Annotated[int, Field(ge=1)]
    offset: NonNegInt
    items: list[DataSourceOut]


class CsvPreviewOut(BaseModel):
    source_id: uuid.UUID
    columns: list[ColumnInfoOut]
    rows: list[dict[str, str | None]]
    sampled_rows: NonNegInt
