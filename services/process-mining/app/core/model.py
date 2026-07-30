"""The canonical in-memory representation of an event log.

Every ingestion path (CSV, XES, JSON, voice) converges to this exact DataFrame
shape, and every analysis reads only from it. That single contract is what
makes the service reusable across projects.
"""

from __future__ import annotations

import pandas as pd

# canonical column names used everywhere inside the service
CASE = "case_id"
ACTIVITY = "activity"
TIMESTAMP = "timestamp"
RESOURCE = "resource"
LIFECYCLE = "lifecycle"
ACTIVITY_RAW = "activity_raw"

# Optional, and the reason appending can be made idempotent: when a source
# system supplies a stable id per event, re-delivering the same batch is a
# no-op instead of silently doubling every metric.
EVENT_ID = "event_id"

CANONICAL_COLUMNS = [EVENT_ID, CASE, ACTIVITY, ACTIVITY_RAW, TIMESTAMP, RESOURCE, LIFECYCLE]

# pm4py / XES standard names
PM4PY_CASE = "case:concept:name"
PM4PY_ACTIVITY = "concept:name"
PM4PY_TIMESTAMP = "time:timestamp"
PM4PY_RESOURCE = "org:resource"
PM4PY_LIFECYCLE = "lifecycle:transition"

TO_PM4PY = {
    CASE: PM4PY_CASE,
    ACTIVITY: PM4PY_ACTIVITY,
    TIMESTAMP: PM4PY_TIMESTAMP,
    RESOURCE: PM4PY_RESOURCE,
    LIFECYCLE: PM4PY_LIFECYCLE,
}
FROM_PM4PY = {v: k for k, v in TO_PM4PY.items()}


def empty_frame() -> pd.DataFrame:
    return normalize_dtypes(pd.DataFrame(columns=CANONICAL_COLUMNS))


def normalize_dtypes(frame: pd.DataFrame) -> pd.DataFrame:
    """Guarantees column presence, dtypes and tz-naive UTC timestamps.

    Mixing tz-aware and tz-naive timestamps is *the* classic pm4py crash
    (``ValueError: Cannot mix tz-aware with tz-naive values``). We kill it once,
    here, so no downstream code has to care.
    """
    frame = frame.copy()

    for column in CANONICAL_COLUMNS:
        if column not in frame.columns:
            frame[column] = None

    frame[TIMESTAMP] = pd.to_datetime(frame[TIMESTAMP], utc=True, errors="coerce")
    if getattr(frame[TIMESTAMP].dtype, "tz", None) is not None:
        frame[TIMESTAMP] = frame[TIMESTAMP].dt.tz_localize(None)

    for column in (EVENT_ID, CASE, ACTIVITY, ACTIVITY_RAW, RESOURCE, LIFECYCLE):
        series = frame[column].astype("object")
        frame[column] = [None if pd.isna(v) else str(v) for v in series]

    frame[CASE] = [v if v else "unknown" for v in frame[CASE]]
    frame[ACTIVITY] = [v if v else "unknown" for v in frame[ACTIVITY]]

    extras = [c for c in frame.columns if c not in CANONICAL_COLUMNS]
    frame = frame[CANONICAL_COLUMNS + extras]
    return frame.sort_values([CASE, TIMESTAMP], kind="stable").reset_index(drop=True)


def to_pm4py_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Renames canonical columns to the XES names pm4py expects."""
    out = frame.rename(columns=TO_PM4PY).copy()
    out[PM4PY_CASE] = out[PM4PY_CASE].astype(str)
    out[PM4PY_ACTIVITY] = out[PM4PY_ACTIVITY].astype(str)
    out = out.dropna(subset=[PM4PY_TIMESTAMP])
    return out.sort_values([PM4PY_CASE, PM4PY_TIMESTAMP], kind="stable").reset_index(drop=True)
