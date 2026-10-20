"""Dataset endpoints: /datasets, /datasets/{id}, /rows, /profile.

The physical table is ``datasets.<table_name>`` where ``table_name`` and the column list come from
the registry row (never the request). Identifiers are re-checked against the contract pattern,
quoted by SQLAlchemy, and only registry columns are selected, so ``_localetl_*`` never leaves the
API. ``sort`` is validated against the registry's column names.
"""

import re
import uuid
from typing import Annotated, Any, Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.core.errors import ApiError
from app.models import Dataset
from app.schemas.datasets import (
    ColumnProfileOut,
    DatasetColumnOut,
    DatasetOut,
    DatasetPage,
    DatasetProfileOut,
    DatasetRowPage,
    TopValue,
    json_cell,
)

router = APIRouter(prefix="/datasets", tags=["datasets"])

_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_RANGE_TYPES = {"integer", "float", "date", "datetime"}
_ROW_NUMBER = "_localetl_row_number"


def _to_out(row: Dataset) -> DatasetOut:
    return DatasetOut.model_validate(
        {
            "id": row.id,
            "table_name": row.table_name,
            "pipeline_id": row.pipeline_id,
            "last_run_id": row.last_run_id,
            "row_count": row.row_count,
            "columns": row.columns,
            "published_at": row.published_at,
        }
    )


def _dataset_or_404(session: Session, dataset_id: uuid.UUID) -> Dataset:
    row = session.get(Dataset, dataset_id)
    if row is None:
        raise ApiError(404, "not_found", "Dataset not found")
    return row


def _table(row: Dataset, extra: tuple[str, ...] = ()) -> sa.TableClause:
    """Quoted ``datasets.<table>`` with the registry's columns (plus named internal ones)."""
    names = [c["name"] for c in row.columns]
    for ident in (row.table_name, *names):
        if not _IDENTIFIER.match(ident):
            raise ApiError(500, "internal_error", "Dataset registry holds an invalid identifier")
    return sa.table(row.table_name, *(sa.column(n) for n in (*names, *extra)), schema="datasets")


def _missing_table() -> ApiError:
    return ApiError(500, "internal_error", "The published table for this dataset is missing")


@router.get("", operation_id="listDatasets", response_model=DatasetPage)
def list_datasets(
    session: Annotated[Session, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DatasetPage:
    total = session.scalar(sa.select(sa.func.count()).select_from(Dataset)) or 0
    rows = session.scalars(
        sa.select(Dataset)
        .order_by(Dataset.published_at.desc(), Dataset.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return DatasetPage(total=total, limit=limit, offset=offset, items=[_to_out(r) for r in rows])


@router.get("/{dataset_id}", operation_id="getDataset", response_model=DatasetOut)
def get_dataset(
    dataset_id: uuid.UUID, session: Annotated[Session, Depends(get_session)]
) -> DatasetOut:
    return _to_out(_dataset_or_404(session, dataset_id))


@router.get("/{dataset_id}/rows", operation_id="listDatasetRows", response_model=DatasetRowPage)
def list_dataset_rows(
    dataset_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    sort: str | None = None,
    order: Literal["asc", "desc"] = "asc",
) -> DatasetRowPage:
    row = _dataset_or_404(session, dataset_id)
    names = [c["name"] for c in row.columns]
    if sort is not None and sort not in names:
        raise ApiError(
            422,
            "validation_error",
            "Request validation failed",
            [{"path": "/sort", "message": f"unknown column; must be one of {names}"}],
        )
    table = _table(row, (_ROW_NUMBER,))
    direction = sa.desc if order == "desc" else sa.asc
    ordering = [direction(table.c[sort])] if sort is not None else []
    ordering.append(
        direction(table.c[_ROW_NUMBER]) if sort is None else sa.asc(table.c[_ROW_NUMBER])
    )
    try:
        total = session.scalar(sa.select(sa.func.count()).select_from(table)) or 0
        result = session.execute(
            sa.select(*(table.c[n] for n in names)).order_by(*ordering).limit(limit).offset(offset)
        ).all()
    except sa.exc.ProgrammingError:
        session.rollback()
        raise _missing_table() from None
    items = [{n: json_cell(v) for n, v in zip(names, r, strict=True)} for r in result]
    return DatasetRowPage(
        total=total,
        limit=limit,
        offset=offset,
        columns=[DatasetColumnOut.model_validate(c) for c in row.columns],
        items=items,
    )


@router.get(
    "/{dataset_id}/profile", operation_id="getDatasetProfile", response_model=DatasetProfileOut
)
def get_dataset_profile(
    dataset_id: uuid.UUID, session: Annotated[Session, Depends(get_session)]
) -> DatasetProfileOut:
    row = _dataset_or_404(session, dataset_id)
    table = _table(row)
    cols: list[dict[str, Any]] = row.columns
    selects: list[sa.ColumnElement[Any]] = [sa.func.count().label("n")]
    for i, c in enumerate(cols):
        col = table.c[c["name"]]
        selects += [
            sa.func.count(col).label(f"nn{i}"),
            sa.func.count(sa.distinct(col)).label(f"d{i}"),
        ]
        if c["type"] in _RANGE_TYPES:
            selects += [sa.func.min(col).label(f"mn{i}"), sa.func.max(col).label(f"mx{i}")]
    profiles: list[ColumnProfileOut] = []
    try:
        stats = session.execute(sa.select(*selects)).one()._mapping
        for i, c in enumerate(cols):
            col = table.c[c["name"]]
            count = sa.func.count().label("c")
            tops = session.execute(
                sa.select(col, count)
                .where(col.is_not(None))
                .group_by(col)
                .order_by(count.desc(), col.asc())
                .limit(10)
            ).all()
            ranged = c["type"] in _RANGE_TYPES
            profiles.append(
                ColumnProfileOut(
                    name=c["name"],
                    type=c["type"],
                    null_count=stats["n"] - stats[f"nn{i}"],
                    distinct_count=stats[f"d{i}"],
                    min=json_cell(stats[f"mn{i}"]) if ranged else None,
                    max=json_cell(stats[f"mx{i}"]) if ranged else None,
                    top_values=[TopValue(value=json_cell(v), count=n) for v, n in tops],
                )
            )
    except sa.exc.ProgrammingError:
        session.rollback()
        raise _missing_table() from None
    return DatasetProfileOut(dataset_id=row.id, row_count=stats["n"], columns=profiles)
