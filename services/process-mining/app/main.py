"""Application factory and composition root.

Everything is wired exactly once here, on startup, and hung off ``app.state``.
No module-level singletons, no import-time side effects - which is what makes
the whole thing testable and safe to run with multiple workers.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import integration, transcriptions
from app.api.router import api_router, voice_router
from app.api.v1 import health
from app.config import Settings, get_settings
from app.core.cache import TTLCache
from app.core.mapping import MappingRegistry
from app.errors import register_exception_handlers
from app.jobs.manager import JobManager
from app.logging_config import configure_logging, get_logger
from app.middleware import MaxBodySizeMiddleware, RequestContextMiddleware
from app.services.log_service import LogService
from app.services.mining_service import MiningService
from app.services.stt import SttService
from app.services.transcription import TranscriptionService
from app.storage import build_repository

log = get_logger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

DESCRIPTION = """
Process mining as a service. Upload an event log (CSV / XES / JSON) or stream
events in over HTTP, and get back process models, KPIs, variants, bottlenecks
and conformance metrics.

**Two ways to use it**

* **Stateless** - `POST /api/v1/mine` with a file. One call, full answer, nothing stored.
* **Stateful** - `POST /api/v1/logs` once, then discover / filter / append incrementally.

Every model is returned both as a **renderer-agnostic JSON graph** (nodes +
edges + metrics, feed it to D3 / Cytoscape / React Flow) and as a ready-made
**SVG / PNG** image.

Authenticate with `X-API-Key: <key>` or `Authorization: Bearer <key>`.
"""


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        settings.ensure_dirs()
        cache = TTLCache(max_items=256, ttl_seconds=900)
        mappings = MappingRegistry(settings.mapping_config, settings.default_mapping_profile)
        repository = build_repository(settings)
        job_manager = JobManager(
            max_workers=settings.max_concurrent_jobs, ttl_seconds=settings.job_ttl_seconds
        )

        application.state.settings = settings
        application.state.cache = cache
        application.state.mappings = mappings
        application.state.repository = repository
        application.state.job_manager = job_manager
        application.state.log_service = LogService(repository, mappings, settings, cache)
        application.state.mining_service = MiningService(settings, cache)
        application.state.transcription_service = TranscriptionService(settings, mappings)
        application.state.stt_service = SttService(settings)

        log.info(
            "service_started",
            extra={
                "environment": settings.environment,
                "storage": settings.storage_backend,
                "auth": settings.auth_enabled,
                "voice": settings.voice_enabled,
            },
        )
        try:
            yield
        finally:
            job_manager.shutdown()
            log.info("service_stopped")

    application = FastAPI(
        title="Process Mining Service",
        description=DESCRIPTION,
        version=settings.version,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    application.add_middleware(GZipMiddleware, minimum_size=1024)
    application.add_middleware(MaxBodySizeMiddleware, max_bytes=settings.max_upload_bytes)
    application.add_middleware(RequestContextMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-Response-Time-ms"],
    )

    register_exception_handlers(application)

    application.include_router(health.router)
    application.include_router(api_router, prefix=settings.api_prefix)
    # Fixed, unversioned paths: source systems were built against them.
    application.include_router(integration.router, prefix="/api")
    application.include_router(transcriptions.router, prefix="/api")
    if settings.voice_enabled:
        application.include_router(voice_router, prefix=settings.api_prefix)

    if STATIC_DIR.exists():
        application.mount("/ui", StaticFiles(directory=STATIC_DIR, html=True), name="ui")

        @application.get("/", include_in_schema=False)
        async def root() -> FileResponse:
            return FileResponse(STATIC_DIR / "index.html")

    else:  # pragma: no cover

        @application.get("/", include_in_schema=False)
        async def root() -> JSONResponse:
            return JSONResponse({"service": settings.app_name, "docs": "/docs"})

    return application


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    config = get_settings()
    uvicorn.run("app.main:app", host=config.host, port=config.port, reload=config.debug)
