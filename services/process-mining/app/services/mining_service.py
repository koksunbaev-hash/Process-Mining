"""Use-cases around discovery and analytics.

Every public method takes a canonical DataFrame, so the *same* code serves both
the stateful endpoints (``/logs/{id}/...``) and the stateless one-shot endpoint
(``/mine``). Results are cached by a fingerprint of (log identity + filters +
parameters).
"""

from __future__ import annotations

import time
from typing import Any

import pandas as pd

from app.config import Settings
from app.core import metrics as metrics_mod
from app.core import mining as mining_core
from app.core import rendering
from app.core.cache import TTLCache, fingerprint
from app.core.filtering import apply_filters
from app.errors import MiningError
from app.logging_config import get_logger
from app.schemas.common import Algorithm, OutputFormat
from app.schemas.mining import (
    ConformanceRequest,
    DiscoverRequest,
    DiscoverResponse,
    LogFilters,
)

log = get_logger(__name__)

_DISPATCH = {
    Algorithm.DFG_FREQUENCY: lambda frame, noise: mining_core.discover_dfg(frame, performance=False),
    Algorithm.DFG_PERFORMANCE: lambda frame, noise: mining_core.discover_dfg(frame, performance=True),
    Algorithm.PETRI_NET_INDUCTIVE: lambda frame, noise: mining_core.discover_petri_net(
        frame, heuristics=False, noise_threshold=noise
    ),
    Algorithm.PETRI_NET_HEURISTICS: lambda frame, noise: mining_core.discover_petri_net(
        frame, heuristics=True, noise_threshold=noise
    ),
    Algorithm.PROCESS_TREE: lambda frame, noise: mining_core.discover_process_tree(
        frame, noise_threshold=noise
    ),
    Algorithm.BPMN: lambda frame, noise: mining_core.discover_bpmn(frame, noise_threshold=noise),
}


class MiningService:
    def __init__(self, settings: Settings, cache: TTLCache) -> None:
        self.settings = settings
        self.cache = cache

    # ---- discovery -----------------------------------------------------
    def discover(
        self,
        frame: pd.DataFrame,
        request: DiscoverRequest,
        *,
        log_id: str | None = None,
        log_version: Any = None,
    ) -> DiscoverResponse:
        started = time.perf_counter()
        key = self._key(log_id, log_version, "discover", request.model_dump(mode="json"))

        if request.use_cache:
            cached = self.cache.get(key)
            if cached is not None:
                response = cached.model_copy(deep=True)
                response.cached = True
                response.computed_in_ms = round((time.perf_counter() - started) * 1000, 2)
                return response

        filtered = apply_filters(frame, request.filters)
        if filtered.empty:
            raise MiningError("No events left after filtering")

        handler = _DISPATCH.get(request.algorithm)
        if handler is None:  # pragma: no cover - enum guarantees coverage
            raise MiningError(f"Unsupported algorithm '{request.algorithm}'")

        result = handler(filtered, request.noise_threshold)

        response = DiscoverResponse(
            log_id=log_id,
            algorithm=request.algorithm,
            format=request.format.value,
            graph=result.graph,
            computed_in_ms=0,
        )

        if request.format != OutputFormat.JSON:
            if result.gviz_factory is None:
                raise MiningError(f"'{request.algorithm}' cannot be rendered as an image")
            options = {
                **request.render.model_dump(),
                "format": "svg" if request.format == OutputFormat.DOT else request.format.value,
            }
            gviz = result.gviz_factory(options)
            payload, content_type = rendering.render(
                gviz,
                request.format.value,
                timeout=self.settings.render_timeout_seconds,
            )
            response.image = payload
            response.content_type = content_type
            if request.format != OutputFormat.JSON:
                response.graph = result.graph  # graph always included: it is cheap and useful

        response.computed_in_ms = round((time.perf_counter() - started) * 1000, 2)
        if request.use_cache:
            self.cache.set(key, response)
        return response

    # ---- analytics -----------------------------------------------------
    def statistics(
        self,
        frame: pd.DataFrame,
        filters: LogFilters | None = None,
        *,
        log_id: str | None = None,
        log_version: Any = None,
    ) -> dict[str, Any]:
        key = self._key(log_id, log_version, "stats", _dump(filters))
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        result = metrics_mod.statistics_overview(apply_filters(frame, filters))
        result["log_id"] = log_id
        self.cache.set(key, result)
        return result

    def variants(
        self,
        frame: pd.DataFrame,
        filters: LogFilters | None = None,
        *,
        limit: int = 20,
        log_id: str | None = None,
        log_version: Any = None,
    ) -> dict[str, Any]:
        key = self._key(log_id, log_version, "variants", _dump(filters), limit)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        result = metrics_mod.variants(apply_filters(frame, filters), limit=limit)
        result["log_id"] = log_id
        self.cache.set(key, result)
        return result

    def bottlenecks(
        self,
        frame: pd.DataFrame,
        filters: LogFilters | None = None,
        *,
        limit: int = 10,
        log_id: str | None = None,
        log_version: Any = None,
    ) -> dict[str, Any]:
        key = self._key(log_id, log_version, "bottlenecks", _dump(filters), limit)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        result = metrics_mod.bottlenecks(apply_filters(frame, filters), top_n=limit)
        result["log_id"] = log_id
        self.cache.set(key, result)
        return result

    def conformance(
        self,
        frame: pd.DataFrame,
        request: ConformanceRequest,
        *,
        log_id: str | None = None,
        log_version: Any = None,
    ) -> dict[str, Any]:
        key = self._key(log_id, log_version, "conformance", request.model_dump(mode="json"))
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        filtered = apply_filters(frame, request.filters)
        if filtered.empty:
            raise MiningError("No events left after filtering")
        result = mining_core.conformance(
            filtered,
            heuristics=request.algorithm == "petri_net_heuristics",
            noise_threshold=request.noise_threshold,
            precision=request.compute_precision,
        )
        result["log_id"] = log_id
        self.cache.set(key, result)
        return result

    # ---- helpers -------------------------------------------------------
    @staticmethod
    def _key(log_id: str | None, version: Any, *parts: Any) -> str:
        prefix = log_id or "adhoc"
        return f"{prefix}:{fingerprint(version, *parts)}"


def _dump(filters: LogFilters | None) -> dict[str, Any]:
    return filters.model_dump(mode="json") if filters else {}
