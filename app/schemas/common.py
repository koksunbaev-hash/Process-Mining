from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class Base(BaseModel):
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class Page(Base, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class ErrorBody(Base):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str = "-"


class ErrorResponse(Base):
    error: ErrorBody


class HealthResponse(Base):
    status: str
    service: str
    version: str
    environment: str
    checks: dict[str, Any] = Field(default_factory=dict)
    time: datetime


class OutputFormat(StrEnum):
    JSON = "json"
    SVG = "svg"
    PNG = "png"
    DOT = "dot"


class Algorithm(StrEnum):
    DFG_FREQUENCY = "dfg_frequency"
    DFG_PERFORMANCE = "dfg_performance"
    PETRI_NET_INDUCTIVE = "petri_net_inductive"
    PETRI_NET_HEURISTICS = "petri_net_heuristics"
    PROCESS_TREE = "process_tree"
    BPMN = "bpmn"
