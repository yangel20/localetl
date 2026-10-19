"""Contract `Error` responses (contracts/openapi.yaml, components.schemas.Error)."""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

_CODE_BY_STATUS: dict[int, str] = {
    404: "not_found",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
}


def error_body(
    code: str, message: str, details: list[dict[str, str]] | None = None
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"error": error}


class ApiError(Exception):
    """Raise from endpoints to produce a contract `Error` response."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def json_pointer(loc: tuple[Any, ...] | list[Any]) -> str:
    """Convert a pydantic/FastAPI `loc` to a JSON Pointer (leading body/query/path dropped
    unless it is the only element)."""
    parts = list(loc)
    if len(parts) > 1 and parts[0] in ("body", "query", "path", "form"):
        parts = parts[1:]
    return "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in parts)


def _response(status: int, body: dict[str, Any]) -> JSONResponse:
    return JSONResponse(status_code=status, content=body)


async def _api_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    return _response(exc.status_code, error_body(exc.code, exc.message, exc.details))


async def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    details = [
        {"path": json_pointer(err["loc"]), "message": str(err["msg"])} for err in exc.errors()
    ]
    return _response(422, error_body("validation_error", "Request validation failed", details))


async def _http_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    # Contract has no code for e.g. 405; report it as validation_error rather than invent one.
    code = _CODE_BY_STATUS.get(
        exc.status_code, "internal_error" if exc.status_code >= 500 else "validation_error"
    )
    message = "Resource not found" if exc.status_code == 404 else str(exc.detail)
    return _response(exc.status_code, error_body(code, message))


async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error", exc_info=exc)
    return _response(500, error_body("internal_error", "Internal server error"))


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unhandled)
