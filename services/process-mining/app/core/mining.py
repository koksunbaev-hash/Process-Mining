"""Thin, defensive facade over pm4py.

Why a facade at all: pm4py's API drifts between minor versions and its
visualization internals move around. Every pm4py call in this service lives in
this one module, so an upgrade is a one-file change instead of a hunt.

All discovery functions return BOTH a renderer-agnostic
:class:`~app.schemas.mining.ProcessGraph` and (optionally) a graphviz object,
so consumers can either draw it themselves or ask us for an SVG/PNG.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.core import model
from app.errors import MiningError
from app.logging_config import get_logger
from app.schemas.common import Algorithm
from app.schemas.mining import GraphEdge, GraphNode, ProcessGraph

log = get_logger(__name__)


@dataclass(slots=True)
class DiscoveryResult:
    graph: ProcessGraph
    gviz_factory: Any | None = None  # callable -> graphviz.Digraph (lazy: only when rendering)


def _pm4py():
    try:
        import pm4py
    except ImportError as exc:  # pragma: no cover - deployment error
        raise MiningError("pm4py is not installed in this environment") from exc
    return pm4py


def _require_events(frame: pd.DataFrame, minimum: int = 2) -> None:
    if frame is None or len(frame) < minimum:
        raise MiningError(f"At least {minimum} events are required, got {0 if frame is None else len(frame)}")


def prepare(frame: pd.DataFrame) -> pd.DataFrame:
    """Canonical frame -> pm4py-formatted frame."""
    _require_events(frame)
    pm4py = _pm4py()
    pm_frame = model.to_pm4py_frame(frame)
    return pm4py.format_dataframe(
        pm_frame,
        case_id=model.PM4PY_CASE,
        activity_key=model.PM4PY_ACTIVITY,
        timestamp_key=model.PM4PY_TIMESTAMP,
    )


# --------------------------------------------------------------------------
# Directly-follows graphs
# --------------------------------------------------------------------------
def discover_dfg(frame: pd.DataFrame, *, performance: bool = False) -> DiscoveryResult:
    pm4py = _pm4py()
    pm_frame = prepare(frame)

    freq_dfg, start_activities, end_activities = pm4py.discover_dfg(pm_frame)
    activity_counts = frame[model.ACTIVITY].value_counts().to_dict()

    perf_dfg: dict[tuple[str, str], float] = {}
    if performance:
        perf_dfg, _, _ = pm4py.discover_performance_dfg(pm_frame)

    edge_durations = _edge_duration_stats(frame)

    nodes = [
        GraphNode(
            id=activity,
            label=activity,
            type="activity",
            frequency=int(count),
            metrics={
                "cases": int(frame[frame[model.ACTIVITY] == activity][model.CASE].nunique()),
            },
        )
        for activity, count in sorted(activity_counts.items(), key=lambda kv: -kv[1])
    ]

    edges: list[GraphEdge] = []
    for (source, target), count in freq_dfg.items():
        stats = edge_durations.get((source, target), {})
        perf_value = perf_dfg.get((source, target))
        if isinstance(perf_value, dict):
            perf_value = perf_value.get("mean")
        edges.append(
            GraphEdge(
                source=source,
                target=target,
                frequency=int(count),
                mean_duration_seconds=stats.get("mean", perf_value),
                median_duration_seconds=stats.get("median"),
                metrics={
                    "min_seconds": stats.get("min"),
                    "max_seconds": stats.get("max"),
                    "p95_seconds": stats.get("p95"),
                    "total_seconds": stats.get("total"),
                },
            )
        )
    edges.sort(key=lambda e: -(e.frequency or 0))

    algorithm = Algorithm.DFG_PERFORMANCE if performance else Algorithm.DFG_FREQUENCY
    graph = ProcessGraph(
        algorithm=algorithm,
        nodes=nodes,
        edges=edges,
        start_activities={str(k): int(v) for k, v in start_activities.items()},
        end_activities={str(k): int(v) for k, v in end_activities.items()},
        stats={
            "events": int(len(frame)),
            "cases": int(frame[model.CASE].nunique()),
            "activities": len(nodes),
            "arcs": len(edges),
        },
    )

    def factory(options: dict[str, Any]) -> Any:
        from pm4py.visualization.dfg import visualizer as dfg_visualizer

        variant = (
            dfg_visualizer.Variants.PERFORMANCE if performance else dfg_visualizer.Variants.FREQUENCY
        )
        source_dfg = perf_dfg if performance else freq_dfg
        if performance and not source_dfg:
            source_dfg, _, _ = pm4py.discover_performance_dfg(pm_frame)
        # string keys on purpose: pm4py resolves both enum and plain-string
        # parameter keys, and strings survive pm4py version bumps.
        parameters = {
            "format": options.get("format", "svg"),
            "start_activities": start_activities,
            "end_activities": end_activities,
        }
        gviz = dfg_visualizer.apply(
            source_dfg, log=pm_frame, variant=variant, parameters=parameters
        )
        _apply_graph_attrs(gviz, options)
        return gviz

    return DiscoveryResult(graph=graph, gviz_factory=factory)


# --------------------------------------------------------------------------
# Petri nets / process trees / BPMN
# --------------------------------------------------------------------------
def discover_petri_net(
    frame: pd.DataFrame, *, heuristics: bool = False, noise_threshold: float = 0.0
) -> DiscoveryResult:
    pm4py = _pm4py()
    pm_frame = prepare(frame)

    if heuristics:
        net, initial_marking, final_marking = pm4py.discover_petri_net_heuristics(
            pm_frame, dependency_threshold=max(noise_threshold, 0.5)
        )
        algorithm = Algorithm.PETRI_NET_HEURISTICS
    else:
        net, initial_marking, final_marking = pm4py.discover_petri_net_inductive(
            pm_frame, noise_threshold=noise_threshold
        )
        algorithm = Algorithm.PETRI_NET_INDUCTIVE

    activity_counts = frame[model.ACTIVITY].value_counts().to_dict()
    nodes: list[GraphNode] = []
    for place in net.places:
        nodes.append(GraphNode(id=f"p:{place.name}", label="", type="place"))
    for transition in net.transitions:
        label = transition.label
        nodes.append(
            GraphNode(
                id=f"t:{transition.name}",
                label=label or "",
                type="transition",
                frequency=int(activity_counts.get(label, 0)) if label else None,
                metrics={"silent": label is None},
            )
        )

    edges = [
        GraphEdge(
            source=_arc_id(arc.source),
            target=_arc_id(arc.target),
            metrics={"weight": getattr(arc, "weight", 1)},
        )
        for arc in net.arcs
    ]

    graph = ProcessGraph(
        algorithm=algorithm,
        nodes=nodes,
        edges=edges,
        start_activities={f"p:{p.name}": int(c) for p, c in initial_marking.items()},
        end_activities={f"p:{p.name}": int(c) for p, c in final_marking.items()},
        stats={
            "places": len(net.places),
            "transitions": len(net.transitions),
            "silent_transitions": sum(1 for t in net.transitions if t.label is None),
            "arcs": len(net.arcs),
            "soundness_checked": False,
        },
    )

    def factory(options: dict[str, Any]) -> Any:
        from pm4py.visualization.petri_net import visualizer as pn_visualizer

        gviz = pn_visualizer.apply(
            net,
            initial_marking,
            final_marking,
            parameters={"format": options.get("format", "svg")},
        )
        _apply_graph_attrs(gviz, options)
        return gviz

    return DiscoveryResult(graph=graph, gviz_factory=factory)


def discover_process_tree(frame: pd.DataFrame, *, noise_threshold: float = 0.0) -> DiscoveryResult:
    pm4py = _pm4py()
    pm_frame = prepare(frame)
    tree = pm4py.discover_process_tree_inductive(pm_frame, noise_threshold=noise_threshold)

    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    counter = {"n": 0}

    def walk(node: Any, parent_id: str | None) -> None:
        counter["n"] += 1
        node_id = f"n{counter['n']}"
        operator = getattr(node, "operator", None)
        label = str(operator) if operator is not None else (node.label or "tau")
        nodes.append(
            GraphNode(
                id=node_id,
                label=label,
                type="operator" if operator is not None else "activity",
            )
        )
        if parent_id:
            edges.append(GraphEdge(source=parent_id, target=node_id))
        for child in getattr(node, "children", []) or []:
            walk(child, node_id)

    walk(tree, None)

    graph = ProcessGraph(
        algorithm=Algorithm.PROCESS_TREE,
        nodes=nodes,
        edges=edges,
        stats={"nodes": len(nodes), "depth_hint": len(edges)},
    )

    def factory(options: dict[str, Any]) -> Any:
        from pm4py.visualization.process_tree import visualizer as pt_visualizer

        gviz = pt_visualizer.apply(tree, parameters={"format": options.get("format", "svg")})
        _apply_graph_attrs(gviz, options)
        return gviz

    return DiscoveryResult(graph=graph, gviz_factory=factory)


def discover_bpmn(frame: pd.DataFrame, *, noise_threshold: float = 0.0) -> DiscoveryResult:
    pm4py = _pm4py()
    pm_frame = prepare(frame)
    bpmn = pm4py.discover_bpmn_inductive(pm_frame, noise_threshold=noise_threshold)

    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    id_of: dict[Any, str] = {}

    for index, node in enumerate(bpmn.get_nodes()):
        node_id = f"b{index}"
        id_of[node] = node_id
        kind = type(node).__name__.lower()
        node_type = "activity"
        if "gateway" in kind:
            node_type = "gateway"
        elif "startevent" in kind:
            node_type = "start"
        elif "endevent" in kind:
            node_type = "end"
        nodes.append(
            GraphNode(
                id=node_id,
                label=str(getattr(node, "get_name", lambda: "")() or ""),
                type=node_type,
                metrics={"bpmn_type": type(node).__name__},
            )
        )

    for flow in bpmn.get_flows():
        source = id_of.get(flow.get_source())
        target = id_of.get(flow.get_target())
        if source and target:
            edges.append(GraphEdge(source=source, target=target))

    graph = ProcessGraph(
        algorithm=Algorithm.BPMN,
        nodes=nodes,
        edges=edges,
        stats={"nodes": len(nodes), "flows": len(edges)},
    )

    def factory(options: dict[str, Any]) -> Any:
        from pm4py.visualization.bpmn import visualizer as bpmn_visualizer

        gviz = bpmn_visualizer.apply(bpmn, parameters={"format": options.get("format", "svg")})
        _apply_graph_attrs(gviz, options)
        return gviz

    return DiscoveryResult(graph=graph, gviz_factory=factory)


# --------------------------------------------------------------------------
# Conformance
# --------------------------------------------------------------------------
def conformance(
    frame: pd.DataFrame, *, heuristics: bool = False, noise_threshold: float = 0.0, precision: bool = True
) -> dict[str, Any]:
    pm4py = _pm4py()
    pm_frame = prepare(frame)

    if heuristics:
        net, im, fm = pm4py.discover_petri_net_heuristics(pm_frame)
    else:
        net, im, fm = pm4py.discover_petri_net_inductive(pm_frame, noise_threshold=noise_threshold)

    fitness = pm4py.fitness_token_based_replay(pm_frame, net, im, fm)
    result: dict[str, Any] = {
        "fitness": {k: float(v) for k, v in fitness.items() if isinstance(v, (int, float))},
        "traces_evaluated": int(frame[model.CASE].nunique()),
    }
    if precision:
        try:
            result["precision"] = float(pm4py.precision_token_based_replay(pm_frame, net, im, fm))
        except Exception as exc:  # precision is expensive and can blow up on odd models
            log.warning("precision_failed", extra={"error": str(exc)})
            result["precision"] = None

    replayed = fitness.get("perc_fit_traces")
    if replayed is not None:
        result["deviating_cases"] = int(round(result["traces_evaluated"] * (1 - replayed / 100)))
    return result


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _arc_id(element: Any) -> str:
    from pm4py.objects.petri_net.obj import PetriNet

    prefix = "p" if isinstance(element, PetriNet.Place) else "t"
    return f"{prefix}:{element.name}"


def _apply_graph_attrs(gviz: Any, options: dict[str, Any]) -> None:
    gviz.graph_attr["rankdir"] = options.get("rankdir", "LR")
    gviz.graph_attr["bgcolor"] = options.get("bgcolor", "white")
    gviz.graph_attr["dpi"] = str(options.get("dpi", 150))
    if options.get("graph_title"):
        gviz.graph_attr["label"] = str(options["graph_title"])
        gviz.graph_attr["labelloc"] = "t"
        gviz.graph_attr["fontsize"] = str(int(options.get("font_size", 12)) + 4)
    gviz.node_attr["fontsize"] = str(options.get("font_size", 12))
    gviz.edge_attr["fontsize"] = str(options.get("font_size", 12))
    gviz.format = options.get("format", "svg")


def _edge_duration_stats(frame: pd.DataFrame) -> dict[tuple[str, str], dict[str, float]]:
    """Waiting time on every directly-follows arc, computed once in pandas."""
    if frame.empty:
        return {}
    ordered = frame.sort_values([model.CASE, model.TIMESTAMP], kind="stable")
    ordered = ordered.assign(
        next_activity=ordered.groupby(model.CASE, sort=False)[model.ACTIVITY].shift(-1),
        next_timestamp=ordered.groupby(model.CASE, sort=False)[model.TIMESTAMP].shift(-1),
    )
    ordered = ordered.dropna(subset=["next_activity", "next_timestamp"])
    if ordered.empty:
        return {}
    ordered = ordered.assign(
        delta=(ordered["next_timestamp"] - ordered[model.TIMESTAMP]).dt.total_seconds()
    )

    stats: dict[tuple[str, str], dict[str, float]] = {}
    for (source, target), group in ordered.groupby([model.ACTIVITY, "next_activity"], sort=False):
        values = [float(v) for v in group["delta"].tolist()]
        values.sort()
        stats[(str(source), str(target))] = {
            "mean": float(statistics.fmean(values)),
            "median": float(statistics.median(values)),
            "min": values[0],
            "max": values[-1],
            "p95": values[min(len(values) - 1, int(round(0.95 * (len(values) - 1))))],
            "total": float(sum(values)),
            "count": float(len(values)),
        }
    return stats


def edge_duration_stats(frame: pd.DataFrame) -> dict[tuple[str, str], dict[str, float]]:
    return _edge_duration_stats(frame)
