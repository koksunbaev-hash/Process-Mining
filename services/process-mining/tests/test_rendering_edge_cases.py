"""Rendering cases that only appear on real logs."""
from __future__ import annotations

import pandas as pd
import pytest

from app.core import mining, model


@pytest.fixture
def log_with_isolated_activity() -> pd.DataFrame:
    """One activity that only ever occurs in single-event cases.

    Such an activity has no directly-follows pair, so it is never drawn as a
    node - yet it is both a start and an end activity. Passing it to the
    renderer used to raise KeyError and return HTTP 500.
    """
    rows = [
        {"case_id": "c1", "activity": "Отгрузка", "timestamp": "2026-06-01T10:00:00"},
        {"case_id": "c1", "activity": "Счёт-фактура", "timestamp": "2026-06-03T10:00:00"},
        {"case_id": "c2", "activity": "Оплата (касса)", "timestamp": "2026-06-02T10:00:00"},
    ]
    return model.normalize_dtypes(pd.DataFrame(rows))


@pytest.mark.parametrize("performance", [False, True])
def test_isolated_activity_still_renders(log_with_isolated_activity, performance):
    result = mining.discover_dfg(log_with_isolated_activity, performance=performance)
    gviz = result.gviz_factory({"format": "svg", "rankdir": "LR"})
    assert gviz is not None
    # The activity stays in the graph model even though it is not drawn.
    assert any(node.label == "Оплата (касса)" for node in result.graph.nodes)
