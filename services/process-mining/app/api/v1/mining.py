"""Discovery + analytics endpoints.

Two flavours of everything:
  * stateful  - ``/logs/{log_id}/...`` works on a stored log
  * stateless - ``/mine`` takes a file, answers, forgets

The stateless one is what most sibling projects will use: one HTTP call, no
lifecycle to manage.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status

from app.deps import ApiKeyDep, JobManagerDep, LogServiceDep, MiningServiceDep
from app.errors import ValidationError
from app.schemas.common import Algorithm, OutputFormat
from app.schemas.mining import (
    AssistantRequest,
    AssistantResponse,
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


def _query_filters(
    date_from: Annotated[datetime | None, Query(description="Keep events at or after this moment")] = None,
    date_to: Annotated[datetime | None, Query(description="Keep events at or before this moment")] = None,
    activities: Annotated[list[str] | None, Query(description="Keep only these activities")] = None,
    exclude_activities: Annotated[list[str] | None, Query(description="Drop these activities")] = None,
    resources: Annotated[list[str] | None, Query(description="Keep only these resources")] = None,
    variant_coverage: Annotated[
        float | None,
        Query(gt=0, le=1, description="Keep the top variants covering this share of cases"),
    ] = None,
) -> LogFilters | None:
    """The subset of ``LogFilters`` that fits in a query string.

    ``None`` when nothing was asked for, not an empty ``LogFilters``: the two
    are different cache keys, and an unfiltered call must keep hitting the
    entry it has always hit.
    """
    filters = LogFilters(
        date_from=date_from,
        date_to=date_to,
        activities_include=activities,
        activities_exclude=exclude_activities,
        resources=resources,
        variant_coverage=variant_coverage,
    )
    return filters if filters.model_dump(exclude_none=True) else None


FiltersDep = Annotated[LogFilters | None, Depends(_query_filters)]


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
    filters: FiltersDep,
    tenant: str | None = None,
) -> Any:
    record = logs.require(log_id, tenant)
    return await jobs.run_blocking(
        mining.statistics, record.frame, filters, log_id=log_id, log_version=record.updated_at
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
    filters: FiltersDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    tenant: str | None = None,
) -> Any:
    record = logs.require(log_id, tenant)
    return await jobs.run_blocking(
        mining.variants,
        record.frame,
        filters,
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
    filters: FiltersDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    tenant: str | None = None,
) -> Any:
    record = logs.require(log_id, tenant)
    return await jobs.run_blocking(
        mining.bottlenecks,
        record.frame,
        filters,
        limit=limit,
        log_id=log_id,
        log_version=record.updated_at,
    )


@router.get(
    "/logs/{log_id}/analyst",
    summary="Выводы и сводка по-русски: узкие места, аномалии, тренд",
)
async def analyst(
    log_id: str,
    logs: LogServiceDep,
    mining: MiningServiceDep,
    jobs: JobManagerDep,
    _: ApiKeyDep,
    filters: FiltersDep,
    tenant: str | None = None,
    narrate: bool = Query(
        False, description="Пересказать сводку языковой моделью, если она настроена"
    ),
) -> Any:
    record = logs.require(log_id, tenant)
    return await jobs.run_blocking(
        mining.analyst,
        record.frame,
        filters,
        log_id=log_id,
        log_version=record.updated_at,
        narrate=narrate,
    )


@router.post(
    "/logs/{log_id}/assistant",
    response_model=AssistantResponse,
    summary="Спросить о процессе словами: помощник посмотрит журнал и ответит",
)
async def assistant(
    log_id: str,
    payload: AssistantRequest,
    logs: LogServiceDep,
    mining: MiningServiceDep,
    jobs: JobManagerDep,
    _: ApiKeyDep,
    tenant: str | None = None,
) -> Any:
    record = logs.require(log_id, tenant)
    # Через пул: поход к модели идёт секундами, а обработчик - на общем
    # цикле событий, и держать его занятым всё это время нельзя.
    return await jobs.run_blocking(
        mining.ask,
        record.frame,
        payload.question,
        [turn.model_dump() for turn in payload.history],
        payload.filters,
        log_id=log_id,
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
