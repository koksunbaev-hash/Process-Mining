from __future__ import annotations

from pathlib import Path

import pytest

from app.core import ingestion, model
from app.core.mapping import MappingRegistry
from app.errors import ValidationError


@pytest.fixture
def profile():
    return MappingRegistry(Path("config/activities.yaml")).get("generic")


def test_csv_columns_are_auto_detected(sample_csv, profile):
    frame = ingestion.read_csv_bytes(sample_csv)
    result = ingestion.to_canonical(frame, profile=profile)

    assert result.detected_columns[model.CASE] == "batch"
    assert result.detected_columns[model.ACTIVITY] == "step"
    assert result.detected_columns[model.TIMESTAMP] == "event_time"
    assert len(result.frame) == 25
    assert result.frame[model.TIMESTAMP].dt.tz is None


def test_missing_required_column_is_reported(profile):
    import pandas as pd

    frame = pd.DataFrame({"foo": [1, 2], "bar": [3, 4]})
    with pytest.raises(ValidationError):
        ingestion.to_canonical(frame, profile=profile)


def test_mixed_timezones_do_not_explode(profile):
    import pandas as pd

    frame = pd.DataFrame(
        {
            "case": ["a", "a"],
            "activity": ["x", "y"],
            "timestamp": ["2026-01-01T10:00:00+03:00", "2026-01-01T09:00:00Z"],
        }
    )
    result = ingestion.to_canonical(frame, profile=profile)
    assert result.frame[model.TIMESTAMP].dt.tz is None
    assert len(result.frame) == 2
