"""Точка входа FastAPI-приложения.

Запуск:
    uvicorn app.main:app --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app import __version__
from app.api.speech import router as speech_router
from app.config import settings
from app.database.database import init_db
from app.logging_setup import configure_logging
from app.schemas.speech import ErrorResponse, HealthResponse

logger = logging.getLogger("app.request")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Готовит логи и базу до приёма первого запроса."""
    configure_logging(settings)
    init_db()
    logging.getLogger(__name__).info(
        "Backend запущен: data=%s logs=%s", settings.data_dir, settings.log_dir
    )
    yield


app = FastAPI(
    title="Push-to-Talk Backend",
    version=__version__,
    description="Принимает распознанный на устройстве текст и хранит его в SQLite.",
    lifespan=lifespan,
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Пишет в лог каждый запрос: метод, путь, код ответа и длительность."""
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000

    logger.info(
        "%s %s status=%s duration_ms=%.1f",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    return response


@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Некорректный JSON или отсутствующее поле — 422 в едином формате."""
    logger.warning("%s %s отклонён схемой: %s", request.method, request.url.path, exc.errors())
    return JSONResponse(
        status_code=422,
        content={
            "status": "error",
            "message": "validation error",
            "detail": exc.errors(),
        },
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """Непредвиденный сбой не должен ронять процесс и раскрывать внутренности."""
    logger.exception("%s %s завершился ошибкой: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(message="internal server error").model_dump(),
    )


@app.get("/api/health", response_model=HealthResponse, tags=["service"])
def health() -> HealthResponse:
    """Проверка живости для клиента и мониторинга."""
    return HealthResponse(status="ok", version=__version__)


app.include_router(speech_router)
