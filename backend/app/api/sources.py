"""Data source endpoints: /sources, /sources/{source_id}, /sources/{source_id}/preview.

Uploads are parsed from the raw request stream so the size limit is enforced while bytes arrive
(HTTP 413 before the file is fully written), never after Starlette has spooled the whole body.
Stored path convention: ``data_sources.stored_path`` is ``sources/<id>.csv``, relative to
``LOCALETL_DATA_DIR`` (architecture section 4).
"""

import hashlib
import logging
import os
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Annotated, Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import MultipartParser, parse_options_header
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.core.errors import ApiError
from app.core.settings import Settings, get_settings
from app.etl import CsvFormatError, CsvOptions, inspect_csv, preview_csv
from app.models import DataSource, Pipeline
from app.schemas.sources import (
    ColumnInfoOut,
    CsvPreviewOut,
    DataSourceOut,
    DataSourcePage,
    Delimiter,
    Encoding,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sources", tags=["sources"])

_FORM_FIELD_MAX_BYTES = 64 * 1024
_ENVELOPE_SLACK_BYTES = 1024 * 1024  # multipart framing + small form fields on top of the file
_MAX_FILENAME_CHARS = 255

_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    413: {"description": "Upload exceeds LOCALETL_MAX_UPLOAD_MB."},
    415: {"description": "File is not a CSV."},
    422: {"description": "Request or CSV failed validation."},
}


class UploadFields(BaseModel):
    """Non-file form fields of ``SourceUpload``. Error paths are the bare form field names."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    encoding: Encoding = "utf-8"
    delimiter: Delimiter = ","
    has_header: bool = True
    quote_char: Annotated[str, Field(min_length=1, max_length=1)] = '"'


def _invalid(path: str, message: str) -> ApiError:
    return ApiError(422, "validation_error", message, [{"path": path, "message": message}])


def _too_large(settings: Settings) -> ApiError:
    return ApiError(
        413,
        "payload_too_large",
        f"Upload exceeds the {settings.localetl_max_upload_mb} MB limit",
    )


@dataclass
class _Upload:
    """Result of streaming one multipart request."""

    tmp_path: Path
    filename: str = ""
    size: int = 0
    sha256: str = ""
    fields: dict[str, str] = field(default_factory=dict)
    has_file: bool = False


class _MultipartCollector:
    """python-multipart callbacks: file part -> temp file (size-capped), other parts -> fields."""

    def __init__(self, settings: Settings, upload: _Upload) -> None:
        self._settings = settings
        self._upload = upload
        self._limit = settings.max_upload_bytes
        self._header_name = b""
        self._header_value = b""
        self._headers: dict[str, bytes] = {}
        self._target: str | None = None  # "file" or a form field name
        self._buffer = bytearray()
        self._handle: Any = None
        self._digest = hashlib.sha256()
        self._seen: set[str] = set()

    # -- python-multipart callbacks -------------------------------------------------------
    def callbacks(self) -> dict[str, Any]:
        return {
            "on_part_begin": self._part_begin,
            "on_header_field": self._header_field,
            "on_header_value": self._header_value_cb,
            "on_header_end": self._header_end,
            "on_headers_finished": self._headers_finished,
            "on_part_data": self._part_data,
            "on_part_end": self._part_end,
        }

    def _part_begin(self) -> None:
        self._headers = {}
        self._header_name = b""
        self._header_value = b""
        self._target = None
        self._buffer = bytearray()

    def _header_field(self, data: bytes, start: int, end: int) -> None:
        self._header_name += data[start:end]

    def _header_value_cb(self, data: bytes, start: int, end: int) -> None:
        self._header_value += data[start:end]

    def _header_end(self) -> None:
        self._headers[self._header_name.decode("latin-1").lower()] = self._header_value
        self._header_name = b""
        self._header_value = b""

    def _headers_finished(self) -> None:
        _, params = parse_options_header(self._headers.get("content-disposition", b""))
        name = params.get(b"name", b"").decode("utf-8", "replace")
        raw_filename = params.get(b"filename")
        if name in self._seen:
            raise _invalid(name or "file", f"Form field '{name}' was sent more than once")
        self._seen.add(name)
        if raw_filename is not None or name == "file":
            if name != "file":
                raise _invalid(name, f"Unexpected file field '{name}'; send the CSV as 'file'")
            self._begin_file(raw_filename.decode("utf-8", "replace") if raw_filename else "")
        else:
            self._target = name

    def _begin_file(self, raw_filename: str) -> None:
        filename = raw_filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
        content_type = (
            parse_options_header(self._headers.get("content-type", b""))[0]
            .decode("latin-1")
            .lower()
        )
        if not (filename.lower().endswith(".csv") or content_type == "text/csv"):
            raise ApiError(
                415,
                "unsupported_media_type",
                "Only CSV files are accepted (a .csv filename or text/csv content type)",
            )
        if len(filename) > _MAX_FILENAME_CHARS:
            raise _invalid("file", f"Filename is longer than {_MAX_FILENAME_CHARS} characters")
        self._upload.filename = filename or "upload.csv"
        self._upload.has_file = True
        self._upload.tmp_path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self._upload.tmp_path.open("wb")
        self._target = "file"

    def _part_data(self, data: bytes, start: int, end: int) -> None:
        chunk = data[start:end]
        if self._target == "file":
            self._upload.size += len(chunk)
            if self._upload.size > self._limit:
                raise _too_large(self._settings)
            self._digest.update(chunk)
            self._handle.write(chunk)
        elif self._target is not None:
            self._buffer += chunk
            if len(self._buffer) > _FORM_FIELD_MAX_BYTES:
                raise _invalid(self._target, "Form field value is too large")

    def _part_end(self) -> None:
        if self._target == "file":
            self._handle.close()
            self._handle = None
            self._upload.sha256 = self._digest.hexdigest()
        elif self._target is not None:
            try:
                self._upload.fields[self._target] = self._buffer.decode("utf-8")
            except UnicodeDecodeError:
                raise _invalid(self._target, "Form field value is not valid UTF-8") from None
        self._target = None

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None


async def _receive_upload(request: Request, settings: Settings, upload: _Upload) -> None:
    content_type, params = parse_options_header(request.headers.get("content-type"))
    if content_type != b"multipart/form-data":
        raise ApiError(
            415,
            "unsupported_media_type",
            "Send the upload as multipart/form-data with a 'file' part",
        )
    boundary = params.get(b"boundary")
    if not boundary:
        raise _invalid("file", "Multipart boundary is missing from the Content-Type header")
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit():
        if int(declared) > settings.max_upload_bytes + _ENVELOPE_SLACK_BYTES:
            raise _too_large(settings)  # refuse before reading any of the body

    collector = _MultipartCollector(settings, upload)
    parser = MultipartParser(boundary, collector.callbacks())  # type: ignore[arg-type]
    try:
        async for chunk in request.stream():
            parser.write(chunk)
        parser.finalize()
    except MultipartParseError:
        raise _invalid("file", "Malformed multipart request body") from None
    finally:
        collector.close()


def _parse_fields(upload: _Upload) -> UploadFields:
    if not upload.has_file:
        raise _invalid("file", "A CSV file is required in the 'file' form field")
    try:
        return UploadFields.model_validate(upload.fields)
    except ValidationError as exc:
        details = [
            {"path": str(err["loc"][0]) if err["loc"] else "file", "message": str(err["msg"])}
            for err in exc.errors()
        ]
        raise ApiError(422, "validation_error", "Request validation failed", details) from None


def _to_out(row: DataSource) -> DataSourceOut:
    return DataSourceOut.model_validate(
        {
            "id": row.id,
            "name": row.name,
            "original_filename": row.original_filename,
            "size_bytes": row.size_bytes,
            "csv_options": row.csv_options,
            "columns": row.columns,
            "row_count": row.row_count,
            "created_at": row.created_at,
        }
    )


def _store_source(
    session: Session, settings: Settings, upload: _Upload, fields: UploadFields
) -> DataSource:
    """Blocking part of an upload: profile the temp file, move it into place, insert the row."""
    options = CsvOptions(
        encoding=fields.encoding,
        delimiter=fields.delimiter,
        has_header=fields.has_header,
        quote_char=fields.quote_char,
    )
    try:
        profile = inspect_csv(upload.tmp_path, options)
    except CsvFormatError as exc:
        raise _invalid("file", str(exc)) from None

    source_id = uuid.uuid4()
    stored_rel = f"sources/{source_id}.csv"
    dest = settings.localetl_data_dir / stored_rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.replace(upload.tmp_path, dest)
    try:
        row = DataSource(
            id=source_id,
            name=fields.name or upload.filename,
            original_filename=upload.filename,
            stored_path=stored_rel,
            size_bytes=upload.size,
            sha256=upload.sha256,
            csv_options=asdict(options),
            columns=[asdict(c) for c in profile.columns],
            row_count=profile.row_count,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
    except Exception:
        session.rollback()
        dest.unlink(missing_ok=True)
        raise
    return row


@router.post(
    "",
    operation_id="createSource",
    status_code=201,
    response_model=DataSourceOut,
    responses=_ERROR_RESPONSES,
    summary="Upload a CSV file as a new data source",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {"schema": {"$ref": "#/components/schemas/SourceUpload"}}
            },
        }
    },
)
async def create_source(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[Session, Depends(get_session)],
) -> DataSourceOut:
    upload = _Upload(tmp_path=settings.localetl_data_dir / "tmp" / f"{uuid.uuid4().hex}.upload")
    try:
        await _receive_upload(request, settings, upload)
        fields = _parse_fields(upload)
        row = await run_in_threadpool(_store_source, session, settings, upload, fields)
        return _to_out(row)
    finally:
        upload.tmp_path.unlink(missing_ok=True)


@router.get(
    "",
    operation_id="listSources",
    response_model=DataSourcePage,
    summary="List data sources, newest first",
)
def list_sources(
    session: Annotated[Session, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DataSourcePage:
    total = session.scalar(sa.select(sa.func.count()).select_from(DataSource)) or 0
    rows = session.scalars(
        sa.select(DataSource)
        .order_by(DataSource.created_at.desc(), DataSource.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return DataSourcePage(total=total, limit=limit, offset=offset, items=[_to_out(r) for r in rows])


def _get_or_404(session: Session, source_id: uuid.UUID) -> DataSource:
    row = session.get(DataSource, source_id)
    if row is None:
        raise ApiError(404, "not_found", "Data source not found")
    return row


@router.get("/{source_id}", operation_id="getSource", response_model=DataSourceOut)
def get_source(
    source_id: uuid.UUID, session: Annotated[Session, Depends(get_session)]
) -> DataSourceOut:
    return _to_out(_get_or_404(session, source_id))


@router.delete("/{source_id}", operation_id="deleteSource", status_code=204)
def delete_source(
    source_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    row = _get_or_404(session, source_id)
    conflict = ApiError(409, "conflict", "Data source is used by a pipeline and cannot be deleted")
    if session.scalar(sa.select(sa.func.count()).where(Pipeline.source_id == source_id)):
        raise conflict
    stored = settings.localetl_data_dir / row.stored_path
    try:
        session.delete(row)
        session.commit()
    except sa.exc.IntegrityError:  # a pipeline was created concurrently (FK RESTRICT)
        session.rollback()
        raise conflict from None
    stored.unlink(missing_ok=True)
    return Response(status_code=204)


@router.get("/{source_id}/preview", operation_id="previewSource", response_model=CsvPreviewOut)
def preview_source(
    source_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> CsvPreviewOut:
    row = _get_or_404(session, source_id)
    path = settings.localetl_data_dir / row.stored_path
    if not path.is_file():
        logger.error("stored file missing for data source %s: %s", source_id, path)
        raise ApiError(500, "internal_error", "Stored file for this data source is missing")
    try:
        preview = preview_csv(path, CsvOptions(**row.csv_options), limit=limit)
    except CsvFormatError as exc:
        raise _invalid("source_id", str(exc)) from None
    return CsvPreviewOut(
        source_id=source_id,
        columns=[ColumnInfoOut(**asdict(c)) for c in preview.columns],
        rows=preview.rows,
        sampled_rows=preview.sampled_rows,
    )
