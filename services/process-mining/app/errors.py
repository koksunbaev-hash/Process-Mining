"""Domain exceptions and the single place where they turn into HTTP responses."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.logging_config import get_logger, request_id_ctx

log = get_logger(__name__)


class ServiceError(Exception):
    """Base class for every error the service raises on purpose."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "internal_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(ServiceError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class ValidationError(ServiceError):
    status_code = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422)
    code = "validation_error"


class PayloadTooLargeError(ServiceError):
    status_code = getattr(status, "HTTP_413_CONTENT_TOO_LARGE", 413)
    code = "payload_too_large"


class UnsupportedFormatError(ServiceError):
    status_code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    code = "unsupported_format"


class AuthError(ServiceError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthorized"


class FeatureDisabledError(ServiceError):
    status_code = status.HTTP_501_NOT_IMPLEMENTED
    code = "feature_disabled"


class RenderingError(ServiceError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "rendering_unavailable"


class SpeechUnavailableError(ServiceError):
    """The speech container is down, or ffmpeg is missing from the image.

    Separate from RenderingError because a caller retries it differently: the
    model comes back on its own, a missing binary never does.
    """

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "speech_unavailable"


class MiningError(ServiceError):
    status_code = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422)
    code = "mining_failed"


def _body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": request_id_ctx.get(),
        }
    }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ServiceError)
    async def _service_error(_: Request, exc: ServiceError) -> JSONResponse:
        if exc.status_code >= 500:
            log.exception("service_error", extra={"code": exc.code})
        else:
            log.warning("service_error", extra={"code": exc.code, "detail": exc.message})
        return JSONResponse(
            status_code=exc.status_code,
            content=_body(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def _request_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422),
            content=_body("validation_error", "Request payload is invalid", {"errors": exc.errors()}),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_body("http_error", str(exc.detail)),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_exception")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_body("internal_error", f"{type(exc).__name__}: {exc}"),
        )
