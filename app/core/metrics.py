"""Business-level analytics on top of the canonical log.

A process map alone rarely answers "where do we lose time?". These functions
do, and they are plain pandas: no pm4py, no graphviz, so they are fast enough
to be called on every dashboard refresh.
"""

from __future__ import annotations

import statistics
from collections import Counter
from typing import Any

import pandas as pd

from app.core import model
from app.core.mining import edge_duration_stats


def _percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, int(round(q * (len(sorted_values) - 1))))
    return float(sorted_values[index])


def case_durations(frame: pd.DataFrame) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype="float64")
    grouped = frame.groupby(model.CASE, sort=False)[model.TIMESTAMP]
    return (grouped.max() - grouped.min()).dt.total_seconds()


def variants(frame: pd.DataFrame, *, limit: int = 20) -> dict[str, Any]:
    if frame.empty:
        return {"total_variants": 0, "covered_cases": 0, "items": []}

    sequences = frame.groupby(model.CASE, sort=False)[model.ACTIVITY].apply(tuple)
    durations = case_durations(frame)
    counts = Counter(sequences.tolist())
    total_cases = int(sequences.shape[0])

    items: list[dict[str, Any]] = []
    for rank, (sequence, cases) in enumerate(counts.most_common(limit), start=1):
        member_cases = sequences[sequences == sequence].index.tolist()
        member_durations = sorted(float(durations.get(c, 0.0)) for c in member_cases)
        items.append(
            {
                "rank": rank,
                "sequence": list(sequence),
                "cases": int(cases),
                "share": round(cases / total_cases, 6),
                "mean_duration_seconds": (
                    float(statistics.fmean(member_durations)) if member_durations else None
                ),
                "median_duration_seconds": (
                    float(statistics.median(member_durations)) if member_durations else None
                ),
                "example_case_ids": [str(c) for c in member_cases[:5]],
            }
        )

    return {
        "total_variants": len(counts),
        "covered_cases": sum(item["cases"] for item in items),
        "items": items,
    }


def statistics_overview(frame: pd.DataFrame, *, top_n: int = 25) -> dict[str, Any]:
    if frame.empty:
        return {
            "events": 0,
            "cases": 0,
            "activities": 0,
            "resources": 0,
            "variants": 0,
            "throughput_seconds": {},
            "activity_stats": [],
            "resource_stats": [],
            "cases_per_day": {},
        }

    durations = sorted(float(v) for v in case_durations(frame).tolist())
    throughput = {
        "mean": float(statistics.fmean(durations)) if durations else 0.0,
        "median": float(statistics.median(durations)) if durations else 0.0,
        "min": durations[0] if durations else 0.0,
        "max": durations[-1] if durations else 0.0,
        "p90": _percentile(durations, 0.90),
        "p95": _percentile(durations, 0.95),
    }

    service = _service_times(frame)
    activity_stats = []
    for activity, group in frame.groupby(model.ACTIVITY, sort=False):
        values = service.get(str(activity), [])
        activity_stats.append(
            {
                "activity": str(activity),
                "occurrences": int(len(group)),
                "cases": int(group[model.CASE].nunique()),
                "share_of_events": round(len(group) / len(frame), 6),
                "mean_waiting_after_seconds": (
                    float(statistics.fmean(values)) if values else None
                ),
                "first_seen": group[model.TIMESTAMP].min().isoformat(),
                "last_seen": group[model.TIMESTAMP].max().isoformat(),
            }
        )
    activity_stats.sort(key=lambda item: -item["occurrences"])

    resource_stats: list[dict[str, Any]] = []
    if frame[model.RESOURCE].notna().any():
        for resource, group in frame.dropna(subset=[model.RESOURCE]).groupby(
            model.RESOURCE, sort=False
        ):
            resource_stats.append(
                {
                    "resource": str(resource),
                    "events": int(len(group)),
                    "cases": int(group[model.CASE].nunique()),
                    "activities": int(group[model.ACTIVITY].nunique()),
                }
            )
        resource_stats.sort(key=lambda item: -item["events"])

    per_day = (
        frame.groupby(model.CASE, sort=False)[model.TIMESTAMP]
        .min()
        .dt.strftime("%Y-%m-%d")
        .value_counts()
        .sort_index()
    )

    return {
        "events": int(len(frame)),
        "cases": int(frame[model.CASE].nunique()),
        "activities": int(frame[model.ACTIVITY].nunique()),
        "resources": int(frame[model.RESOURCE].nunique(dropna=True)),
        "variants": int(frame.groupby(model.CASE, sort=False)[model.ACTIVITY].apply(tuple).nunique()),
        "start_time": frame[model.TIMESTAMP].min(),
        "end_time": frame[model.TIMESTAMP].max(),
        "throughput_seconds": throughput,
        "activity_stats": activity_stats[:top_n],
        "resource_stats": resource_stats[:top_n],
        "cases_per_day": {str(k): int(v) for k, v in per_day.items()},
    }


def _service_times(frame: pd.DataFrame) -> dict[str, list[float]]:
    """Seconds spent between an activity and the next one, per activity."""
    ordered = frame.sort_values([model.CASE, model.TIMESTAMP], kind="stable")
    delta = (
        ordered.groupby(model.CASE, sort=False)[model.TIMESTAMP].shift(-1) - ordered[model.TIMESTAMP]
    ).dt.total_seconds()
    result: dict[str, list[float]] = {}
    for activity, value in zip(ordered[model.ACTIVITY], delta, strict=False):
        if pd.notna(value):
            result.setdefault(str(activity), []).append(float(value))
    return result


def bottlenecks(frame: pd.DataFrame, *, top_n: int = 10) -> dict[str, Any]:
    """Ranks transitions by total time consumed - i.e. by real business impact.

    Ranking by *mean* duration surfaces rare freak cases; ranking by
    ``mean * occurrences`` surfaces what actually costs the company time.
    """
    if frame.empty:
        return {"bottlenecks": [], "rework": [], "self_loops": [], "total_flow_time_seconds": 0.0}

    edge_stats = edge_duration_stats(frame)
    total_flow = sum(stat["total"] for stat in edge_stats.values()) or 1.0

    items = [
        {
            "kind": "transition",
            "source": source,
            "target": target,
            "activity": None,
            "occurrences": int(stat["count"]),
            "mean_duration_seconds": round(stat["mean"], 3),
            "median_duration_seconds": round(stat["median"], 3),
            "p95_duration_seconds": round(stat["p95"], 3),
            "total_duration_seconds": round(stat["total"], 3),
            "share_of_total_time": round(stat["total"] / total_flow, 6),
        }
        for (source, target), stat in edge_stats.items()
    ]
    items.sort(key=lambda item: -item["total_duration_seconds"])

    sequences = frame.groupby(model.CASE, sort=False)[model.ACTIVITY].apply(list)
    rework: dict[str, dict[str, int]] = {}
    self_loops: set[str] = set()
    for sequence in sequences:
        counter = Counter(sequence)
        for activity, count in counter.items():
            if count > 1:
                entry = rework.setdefault(
                    activity,
                    {"cases_with_rework": 0, "total_repetitions": 0, "max_repetitions_in_case": 0},
                )
                entry["cases_with_rework"] += 1
                entry["total_repetitions"] += count - 1
                entry["max_repetitions_in_case"] = max(entry["max_repetitions_in_case"], count)
        for previous, current in zip(sequence, sequence[1:], strict=False):
            if previous == current:
                self_loops.add(str(previous))

    rework_items = [
        {"activity": activity, **values}
        for activity, values in sorted(
            rework.items(), key=lambda kv: -kv[1]["total_repetitions"]
        )
    ]

    return {
        "bottlenecks": items[:top_n],
        "rework": rework_items[:top_n],
        "self_loops": sorted(self_loops),
        "total_flow_time_seconds": round(total_flow, 3),
    }
