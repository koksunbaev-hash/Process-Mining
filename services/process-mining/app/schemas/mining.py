from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.schemas.common import Algorithm, Base, OutputFormat


class AssistantTurn(Base):
    """Одна реплика прошлой переписки. Историю хранит браузер, не сервер."""

    role: Literal["user", "assistant"]
    content: str = Field("", max_length=4000)


class AssistantRequest(Base):
    """Вопрос по журналу. Фильтры те же, что на экране: спрашивают о том,
    что видят, а не о журнале целиком."""

    question: str = Field(..., min_length=1, max_length=1000)
    history: list[AssistantTurn] = Field(default_factory=list, max_length=12)
    filters: LogFilters | None = None


class AssistantResponse(Base):
    log_id: str | None = None
    available: bool = Field(..., description="False - модель не настроена или не ответила")
    answer: str
    steps: list[dict[str, Any]] = Field(
        default_factory=list, description="Какие запросы к данным модель сделала по пути"
    )


class LogFilters(Base):
    """Applied *before* discovery. All filters are optional and combinable."""

    date_from: datetime | None = None
    date_to: datetime | None = None
    cases: list[str] | None = Field(None, description="Keep only these case ids")
    activities_include: list[str] | None = None
    activities_exclude: list[str] | None = None
    resources: list[str] | None = None
    start_activities: list[str] | None = Field(None, description="Keep cases starting with these")
    end_activities: list[str] | None = Field(None, description="Keep cases ending with these")
    min_case_length: int | None = Field(None, ge=1)
    max_case_length: int | None = Field(None, ge=1)
    variant_coverage: float | None = Field(
        None, gt=0, le=1, description="Keep top variants covering this share of cases (0..1)"
    )
    activity_coverage: float | None = Field(
        None, gt=0, le=1, description="Keep top activities covering this share of events (0..1)"
    )


class RenderOptions(Base):
    rankdir: Literal["LR", "TB"] = "LR"
    bgcolor: str = "white"
    font_size: int = Field(12, ge=6, le=48)
    graph_title: str | None = None
    dpi: int = Field(150, ge=72, le=600)


class DiscoverRequest(Base):
    algorithm: Algorithm = Algorithm.DFG_FREQUENCY
    format: OutputFormat = OutputFormat.JSON
    filters: LogFilters = Field(default_factory=LogFilters)
    render: RenderOptions = Field(default_factory=RenderOptions)
    noise_threshold: float = Field(
        0.0, ge=0, le=1, description="Inductive/heuristics miner noise filtering"
    )
    use_cache: bool = True


class GraphNode(Base):
    id: str
    label: str
    type: Literal["activity", "start", "end", "place", "transition", "gateway", "operator"] = (
        "activity"
    )
    frequency: int | None = None
    mean_duration_seconds: float | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(Base):
    source: str
    target: str
    label: str | None = None
    frequency: int | None = None
    mean_duration_seconds: float | None = None
    median_duration_seconds: float | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)


class ProcessGraph(Base):
    """Renderer-agnostic model: feed it to D3, Cytoscape, ELK, React Flow, anything."""

    algorithm: Algorithm
    directed: bool = True
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    start_activities: dict[str, int] = Field(default_factory=dict)
    end_activities: dict[str, int] = Field(default_factory=dict)
    stats: dict[str, Any] = Field(default_factory=dict)


class DiscoverResponse(Base):
    log_id: str | None = None
    algorithm: Algorithm
    format: str
    cached: bool = False
    computed_in_ms: float = 0
    graph: ProcessGraph | None = None
    image: str | None = Field(None, description="SVG/DOT source, or base64 PNG")
    content_type: str | None = None


class VariantOut(Base):
    rank: int
    sequence: list[str]
    cases: int
    share: float
    mean_duration_seconds: float | None = None
    median_duration_seconds: float | None = None
    example_case_ids: list[str] = Field(default_factory=list)


class VariantsResponse(Base):
    log_id: str | None = None
    total_variants: int
    covered_cases: int
    items: list[VariantOut]


class Bottleneck(Base):
    kind: Literal["transition", "activity"]
    source: str | None = None
    target: str | None = None
    activity: str | None = None
    occurrences: int
    mean_duration_seconds: float
    median_duration_seconds: float
    p95_duration_seconds: float
    total_duration_seconds: float
    share_of_total_time: float


class ReworkItem(Base):
    activity: str
    cases_with_rework: int
    total_repetitions: int
    max_repetitions_in_case: int


class StatisticsResponse(Base):
    log_id: str | None = None
    events: int
    cases: int
    activities: int
    resources: int
    variants: int
    start_time: datetime | None = None
    end_time: datetime | None = None
    throughput_seconds: dict[str, float] = Field(default_factory=dict)
    activity_stats: list[dict[str, Any]] = Field(default_factory=list)
    resource_stats: list[dict[str, Any]] = Field(default_factory=list)
    cases_per_day: dict[str, int] = Field(default_factory=dict)


class BottlenecksResponse(Base):
    log_id: str | None = None
    bottlenecks: list[Bottleneck]
    rework: list[ReworkItem]
    self_loops: list[str] = Field(default_factory=list)
    total_flow_time_seconds: float = 0


class ConformanceRequest(Base):
    algorithm: Literal["petri_net_inductive", "petri_net_heuristics"] = "petri_net_inductive"
    noise_threshold: float = Field(0.0, ge=0, le=1)
    compute_precision: bool = True
    filters: LogFilters = Field(default_factory=LogFilters)


class ConformanceResponse(Base):
    log_id: str | None = None
    fitness: dict[str, float]
    precision: float | None = None
    deviating_cases: int = 0
    traces_evaluated: int = 0


class JobOut(Base):
    job_id: str
    status: Literal["queued", "running", "succeeded", "failed", "expired"]
    kind: str
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    progress: float = 0
    result: dict[str, Any] | None = None
    error: str | None = None


class TranscriptionResponse(Base):
    text: str
    language: str
    duration_seconds: float
    activity: str | None = None
    activity_confidence: float | None = None
    matched_rule: str | None = None
