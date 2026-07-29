"""Discovery + analytics endpoints.

Two flavours of everything:
  * stateful  - ``/logs/{log_id}/...`` works on a stored log
  * stateless - ``/mine`` takes a file, answers, forgets

The stateless one is what most sibling projects will use: one HTTP call, no
lifecycle to manage.
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Query, Response, UploadFile, status

from app.deps import ApiKeyDep, JobManagerDep, LogServiceDep, MiningServiceDep
from app.errors import ValidationError
from app.schemas.common import Algorithm, OutputFormat
from app.schemas.mining import (
    BottlenecksResponse,
    ConformanceRequest,
    ConformanceResponse,
    DiscoverRequest,
    DiscoverResponse,
    JobOut,
    LogFilters,
    StatisticsResponse,
    VariantsResponse,
)

router = APIRouter(tags=["mining"])


def _parse_json_form(raw: str | None, model: type, field: str) -> Any:
    if not raw:
        return model()
    try:
        return model.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValidationError(f"'{field}' must be a valid JSON object: {exc}") from exc


def _image_response(result: DiscoverResponse) -> Response:
    import base64

    if result.content_type == "image/png":
        return Response(content=base64.b64decode(result.image or ""), media_type="image/png")
    return Response(content=result.image or "", media_type=result.content_type or "text/plain")


# ---------------------------------------------------------------------------
# stateful
# ---------------------------------------------------------------------------
@router.post(
    "/logs/{log_id}/discover",
    response_model=DiscoverResponse,
    summary="Discover a process model from a stored log",
)
async def discover(
    log_id: str,
    payload: DiscoverRequest,
    logs: LogServiceDep,
    mining: MiningServiceDep,
    jobs: JobManagerDep,
    _: ApiKeyDep,
    tenant: str | None = None,
    raw: Annotated[bool, Query(description="Return the image itself instead of JSON")] = False,
) -> Any:
    record = logs.require(log_id, tenant)
    result = await jobs.run_blocking(
        mining.discover, record.frame, payload, log_id=log_id, log_version=record.updated_at
    )
    if raw and payload.format != OutputFormat.JSON:
        return _image_response(result)
    return result


@router.get(
    "/logs/{log_id}/map",
    summary="Shortcut: render the process map as an image (GET, embeddable in an <img>)",
    response_class=Response,
)
async def process_map(
    log_id: str,
    logs: LogServiceDep,
    mining: MiningServiceDep,
    jobs: JobManagerDep,
    _: ApiKeyDep,
    algorithm: Algorithm = Algorithm.DFG_FREQUENCY,
    image_format: Annotated[OutputFormat, Query(alias="format")] = OutputFormat.SVG,
    variant_coverage: Annotated[float | None, Query(gt=0, le=1)] = None,
    rankdir: str = "LR",
    tenant: str | None = None,
) -> Response:
    record = logs.require(log_id, tenant)
    request = DiscoverRequest(
        algorithm=algorithm,
        format=image_format,
        filters=LogFilters(variant_coverage=variant_coverage),
    )
    request.render.rankdir = "TB" if rankdir.upper() == "TB" else "LR"
    result = await jobs.run_blocking(
        mining.discover, record.frame, request, log_id=log_id, log_version=record.updated_at
    )
    if image_format == OutputFormat.JSON:
        return Response(
            content=result.model_dump_json(exclude_none=True), media_type="application/json"
        )
    return _image_response(result)


@router.post(
    "/logs/{log_id}/discover/async",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Same as /discover but returns a job id immediately",
)
async def discover_async(
    log_id: str,
    payload: DiscoverRequest,
    logs: LogServiceDep,
    mining: MiningServiceDep,
    jobs: JobManagerDep,
    _: ApiKeyDep,
    tenant: str | None = None,
) -> Any:
    record = logs.require(log_id, tenant)

    def task() -> dict[str, Any]:
        return mining.discover(
            record.frame, payload, log_id=log_id, log_version=record.updated_at
        ).model_dump(mode="json")

    return jobs.submit(f"discover:{payload.algorithm.value}", task)


@router.get(
    "/logs/{log_id}/statistics", response_model=StatisticsResponse, summary="KPI overview"
)
async def statistics(
    log_id: str, logs: LogServiceDep, mining: MiningServiceDep, jobs: JobManagerDep, _: ApiKeyDep,
    tenant: str | None = None,
) -> Any:
    record = logs.require(log_id, tenant)
    return await jobs.run_blocking(
        mining.statistics, record.frame, None, log_id=log_id, log_version=record.updated_at
    )


@router.get(
    "/logs/{log_id}/variants", response_model=VariantsResponse, summary="Most frequent paths"
)
async def variants(
    log_id: str,
    logs: LogServiceDep,
    mining: MiningServiceDep,
    jobs: JobManagerDep,
    _: ApiKeyDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    tenant: str | None = None,
) -> Any:
    record = logs.require(log_id, tenant)
    return await jobs.run_blocking(
        mining.variants,
        record.frame,
        None,
        limit=limit,
        log_id=log_id,
        log_version=record.updated_at,
    )


@router.get(
    "/logs/{log_id}/bottlenecks",
    response_model=BottlenecksResponse,
    summary="Where the time actually goes (ranked by total time, not by average)",
)
async def bottlenecks(
    log_id: str,
    logs: LogServiceDep,
    mining: MiningServiceDep,
    jobs: JobManagerDep,
    _: ApiKeyDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    tenant: str | None = None,
) -> Any:
    record = logs.require(log_id, tenant)
    return await jobs.run_blocking(
        mining.bottlenecks,
        record.frame,
        None,
        limit=limit,
        log_id=log_id,
        log_version=record.updated_at,
    )


@router.post(
    "/logs/{log_id}/conformance",
    response_model=ConformanceResponse,
    summary="How well reality matches the discovered model (fitness / precision)",
)
async def conformance(
    log_id: str,
    payload: ConformanceRequest,
    logs: LogServiceDep,
    mining: MiningServiceDep,
    jobs: JobManagerDep,
    _: ApiKeyDep,
    tenant: str | None = None,
) -> Any:
    record = logs.require(log_id, tenant)
    return await jobs.run_blocking(
        mining.conformance, record.frame, payload, log_id=log_id, log_version=record.updated_at
    )


# ---------------------------------------------------------------------------
# stateless one-shot
# ---------------------------------------------------------------------------
@router.post(
    "/mine",
    summary="One-shot: upload a file, get the model back, nothing is stored",
)
async def mine_once(
    logs: LogServiceDep,
    mining: MiningServiceDep,
    jobs: JobManagerDep,
    _: ApiKeyDep,
    file: Annotated[UploadFile, File(description="CSV, TSV, XES(.gz), JSON or JSONL")],
    algorithm: Annotated[Algorithm, Form()] = Algorithm.DFG_FREQUENCY,
    output_format: Annotated[OutputFormat, Form(alias="format")] = OutputFormat.JSON,
    mapping_profile: Annotated[str | None, Form()] = None,
    columns: Annotated[str | None, Form(description="JSON column mapping")] = None,
    filters: Annotated[str | None, Form(description="JSON LogFilters")] = None,
    noise_threshold: Annotated[float, Form(ge=0, le=1)] = 0.0,
    rankdir: Annotated[str, Form(description="Graph layout direction: LR or TB")] = "LR",
    include_statistics: Annotated[bool, Form()] = True,
    raw: Annotated[bool, Query(description="Return the image itself instead of JSON")] = False,
) -> Any:
    from app.schemas.logs import ColumnMapping

    payload = await file.read()
    result = logs.frame_from_upload(
        payload=payload,
        filename=file.filename or "upload.csv",
        mapping_profile=mapping_profile,
        columns=_parse_json_form(columns, ColumnMapping, "columns"),
    )

    request = DiscoverRequest(
        algorithm=algorithm,
        format=output_format,
        filters=_parse_json_form(filters, LogFilters, "filters"),
        noise_threshold=noise_threshold,
        use_cache=False,
    )
    request.render.rankdir = "TB" if rankdir.upper() == "TB" else "LR"
    discovered = await jobs.run_blocking(mining.discover, result.frame, request)

    if raw and output_format != OutputFormat.JSON:
        return _image_response(discovered)

    body: dict[str, Any] = {
        "result": discovered.model_dump(mode="json", exclude_none=True),
        "warnings": result.warnings,
        "detected_columns": result.detected_columns,
    }
    if include_statistics:
        body["statistics"] = await jobs.run_blocking(
            mining.statistics, result.frame, request.filters
        )
        body["bottlenecks"] = await jobs.run_blocking(
            mining.bottlenecks, result.frame, request.filters, limit=10
        )
        body["variants"] = await jobs.run_blocking(
            mining.variants, result.frame, request.filters, limit=10
        )
    return body
