from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from app.core import metrics, model


def _frame() -> pd.DataFrame:
    rows = []
    base = datetime(2026, 1, 1, 9, 0)
    for case in range(3):
        rows += [
            {model.CASE: f"c{case}", model.ACTIVITY: "a", model.TIMESTAMP: base},
            {model.CASE: f"c{case}", model.ACTIVITY: "b", model.TIMESTAMP: base + timedelta(minutes=10)},
            {model.CASE: f"c{case}", model.ACTIVITY: "c", model.TIMESTAMP: base + timedelta(minutes=70)},
        ]
    return model.normalize_dtypes(pd.DataFrame(rows))


def test_bottleneck_is_the_slowest_transition():
    result = metrics.bottlenecks(_frame())
    top = result["bottlenecks"][0]
    assert (top["source"], top["target"]) == ("b", "c")
    assert top["mean_duration_seconds"] == 3600


def test_variants_are_collapsed():
    result = metrics.variants(_frame())
    assert result["total_variants"] == 1
    assert result["items"][0]["cases"] == 3
    assert result["items"][0]["sequence"] == ["a", "b", "c"]


def test_statistics_overview():
    stats = metrics.statistics_overview(_frame())
    assert stats["events"] == 9
    assert stats["cases"] == 3
    assert stats["activities"] == 3
    assert stats["throughput_seconds"]["median"] == 4200


def test_rework_detection():
    frame = _frame()
    extra = frame.iloc[[0]].copy()
    extra[model.TIMESTAMP] = extra[model.TIMESTAMP] + pd.Timedelta(minutes=90)
    combined = model.normalize_dtypes(pd.concat([frame, extra], ignore_index=True))
    result = metrics.bottlenecks(combined)
    assert any(item["activity"] == "a" for item in result["rework"])
