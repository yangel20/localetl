"""Dataset schemas (openapi.yaml: Dataset, DatasetPage, DatasetRowPage, DatasetProfile)."""

import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from app.schemas.pipelines import NonNegInt, UtcDatetime

ColumnTypeName = Literal["integer", "float", "boolean", "date", "datetime", "string"]
CellValue = str | int | float | bool | None


class DatasetColumnOut(BaseModel):
    name: str
    type: ColumnTypeName


class DatasetOut(BaseModel):
    id: uuid.UUID
    table_name: str
    pipeline_id: uuid.UUID | None
    last_run_id: uuid.UUID
    row_count: NonNegInt
    columns: list[DatasetColumnOut]
    published_at: UtcDatetime


class DatasetPage(BaseModel):
    total: NonNegInt
    limit: Annotated[int, Field(ge=1)]
    offset: NonNegInt
    items: list[DatasetOut]


class DatasetRowPage(BaseModel):
    total: NonNegInt
    limit: Annotated[int, Field(ge=1)]
    offset: NonNegInt
    columns: list[DatasetColumnOut]
    items: list[dict[str, CellValue]]


class TopValue(BaseModel):
    value: CellValue
    count: Annotated[int, Field(ge=1)]


class ColumnProfileOut(BaseModel):
    name: str
    type: ColumnTypeName
    null_count: NonNegInt
    distinct_count: NonNegInt
    min: int | float | str | None
    max: int | float | str | None
    top_values: Annotated[list[TopValue], Field(max_length=10)]


class DatasetProfileOut(BaseModel):
    dataset_id: uuid.UUID
    row_count: NonNegInt
    columns: list[ColumnProfileOut]


def json_cell(value: Any) -> CellValue:
    """Python value from a published table -> JSON cell (dates ISO 8601; NaN/inf -> null)."""
    import math

    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value)
