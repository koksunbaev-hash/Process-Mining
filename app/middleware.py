"""Cross-cutting HTTP middleware: request ids, access logs, body size guard."""

from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.logging_config import get_logger, request_id_ctx

log = get_logger("app.access")

REQUEST_ID_HEADER = "X-Request-ID"


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex[:16]
        token = request_id_ctx.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            request_id_ctx.reset(token)
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers["X-Response-Time-ms"] = str(elapsed_ms)
        log.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": elapsed_ms,
                "request_id": request_id,
            },
        )
        return response


class MaxBodySizeMiddleware(BaseHTTPMiddleware):
    """Rejects oversized uploads early, based on Content-Length."""

    def __init__(self, app, max_bytes: int) -> None:  # noqa: ANN001
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        raw_length = request.headers.get("content-length")
        if raw_length and raw_length.isdigit() and int(raw_length) > self.max_bytes:
            return JSONResponse(
                status_code=413,
                content={
                    "error": {
                        "code": "payload_too_large",
                        "message": f"Body exceeds {self.max_bytes} bytes",
                        "details": {},
                        "request_id": request_id_ctx.get(),
                    }
                },
            )
        return await call_next(request)
