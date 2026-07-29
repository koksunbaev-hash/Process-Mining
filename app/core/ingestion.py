"""Turning whatever the client sends into the canonical event log.

Supported inputs: CSV / TSV, XES (plain or .gz), JSON / JSONL, and raw event
lists coming from the API. Column detection is heuristic but explicit mapping
always wins.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from app.core import model
from app.core.mapping import MappingProfile
from app.errors import UnsupportedFormatError, ValidationError
from app.logging_config import get_logger

log = get_logger(__name__)

CASE_HINTS = ("case", "case_id", "caseid", "trace", "batch", "order", "ticket", "instance", "id")
ACTIVITY_HINTS = ("activity", "action", "event", "operation", "step", "task", "concept:name")
TIMESTAMP_HINTS = ("timestamp", "time", "date", "datetime", "start", "completed", "ts")
RESOURCE_HINTS = ("resource", "operator", "user", "agent", "worker", "employee", "org:resource")
LIFECYCLE_HINTS = ("lifecycle", "transition", "state", "status")


@dataclass(slots=True)
class IngestionResult:
    frame: pd.DataFrame
    detected_columns: dict[str, str | None] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _guess_column(columns: Sequence[str], hints: Sequence[str]) -> str | None:
    lowered = {str(c).lower().strip(): c for c in columns}
    for hint in hints:
        if hint in lowered:
            return lowered[hint]
    for hint in hints:
        for low, original in lowered.items():
            if hint in low:
                return original
    return None


def _sniff_separator(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def read_csv_bytes(
    payload: bytes,
    *,
    separator: str | None = None,
    encoding: str = "utf-8",
) -> pd.DataFrame:
    try:
        text = payload.decode(encoding, errors="replace")
    except LookupError as exc:
        raise ValidationError(f"Unknown encoding '{encoding}'") from exc
    if not text.strip():
        raise ValidationError("Uploaded file is empty")
    sep = separator or _sniff_separator(text[:8192])
    try:
        return pd.read_csv(io.StringIO(text), sep=sep, dtype=str, keep_default_na=False)
    except Exception as exc:  # pandas raises a zoo of exceptions
        raise ValidationError(f"Cannot parse CSV: {exc}") from exc


def read_xes_bytes(payload: bytes, filename: str = "log.xes") -> pd.DataFrame:
    """pm4py only reads XES from a path, so we stage the upload in a temp file."""
    import pm4py

    suffix = ".xes.gz" if filename.endswith(".gz") else ".xes"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        handle.write(payload)
        tmp_path = Path(handle.name)
    try:
        frame = pm4py.read_xes(str(tmp_path))
        if not isinstance(frame, pd.DataFrame):
            frame = pm4py.convert_to_dataframe(frame)
        return frame
    except Exception as exc:
        raise ValidationError(f"Cannot parse XES: {exc}") from exc
    finally:
        tmp_path.unlink(missing_ok=True)


def read_json_bytes(payload: bytes) -> pd.DataFrame:
    text = payload.decode("utf-8", errors="replace").strip()
    if not text:
        raise ValidationError("Uploaded file is empty")
    try:
        if text.startswith("[") or text.startswith("{"):
            data = json.loads(text)
            if isinstance(data, dict):
                data = data.get("events") or data.get("items") or data.get("data") or []
        else:  # JSON Lines
            data = [json.loads(line) for line in text.splitlines() if line.strip()]
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Cannot parse JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ValidationError("JSON payload must be a list of event objects")
    return pd.DataFrame(data)


def read_upload(payload: bytes, filename: str, *, encoding: str = "utf-8", separator: str | None = None) -> pd.DataFrame:
    name = (filename or "").lower()
    if name.endswith(".gz") and not name.endswith((".xes.gz",)):
        payload = gzip.decompress(payload)
        name = name[:-3]
    if name.endswith((".xes", ".xes.gz")):
        return read_xes_bytes(payload, name)
    if name.endswith((".json", ".jsonl", ".ndjson")):
        return read_json_bytes(payload)
    if name.endswith((".csv", ".tsv", ".txt")) or not name:
        return read_csv_bytes(payload, separator=separator or ("\t" if name.endswith(".tsv") else None), encoding=encoding)
    raise UnsupportedFormatError(
        f"Unsupported file type '{filename}'. Use CSV, TSV, XES(.gz), JSON or JSONL."
    )


def to_canonical(
    frame: pd.DataFrame,
    *,
    profile: MappingProfile,
    mapping: dict[str, str | None] | None = None,
    timestamp_format: str | None = None,
    keep_extra_columns: bool = True,
) -> IngestionResult:
    """Maps an arbitrary DataFrame onto the canonical schema."""
    if frame is None or frame.empty:
        raise ValidationError("The log contains no rows")

    mapping = {k: v for k, v in (mapping or {}).items() if v}
    columns = list(frame.columns)
    warnings: list[str] = []

    detected = {
        model.CASE: mapping.get(model.CASE) or _guess_column(columns, (model.PM4PY_CASE, *CASE_HINTS)),
        model.ACTIVITY: mapping.get(model.ACTIVITY)
        or _guess_column(columns, (model.PM4PY_ACTIVITY, *ACTIVITY_HINTS)),
        model.TIMESTAMP: mapping.get(model.TIMESTAMP)
        or _guess_column(columns, (model.PM4PY_TIMESTAMP, *TIMESTAMP_HINTS)),
        model.RESOURCE: mapping.get(model.RESOURCE) or _guess_column(columns, RESOURCE_HINTS),
        model.LIFECYCLE: mapping.get(model.LIFECYCLE) or _guess_column(columns, LIFECYCLE_HINTS),
    }

    missing = [k for k in (model.CASE, model.ACTIVITY, model.TIMESTAMP) if not detected[k]]
    if missing:
        raise ValidationError(
            "Could not detect required columns: " + ", ".join(missing),
            details={"available_columns": columns, "detected": detected},
        )

    canonical = pd.DataFrame()
    canonical[model.CASE] = frame[detected[model.CASE]]
    raw_activity = frame[detected[model.ACTIVITY]]
    canonical[model.ACTIVITY_RAW] = raw_activity

    normalized = [profile.normalize(value)[0] for value in raw_activity]
    canonical[model.ACTIVITY] = normalized

    if timestamp_format:
        parsed = pd.to_datetime(
            frame[detected[model.TIMESTAMP]], format=timestamp_format, errors="coerce", utc=True
        )
    else:
        parsed = pd.to_datetime(
            frame[detected[model.TIMESTAMP]], errors="coerce", utc=True, format="mixed"
        )
    canonical[model.TIMESTAMP] = parsed

    for key in (model.RESOURCE, model.LIFECYCLE):
        canonical[key] = frame[detected[key]] if detected[key] else None

    if keep_extra_columns:
        used = {v for v in detected.values() if v}
        for column in columns:
            if column in used:
                continue
            safe = str(column)
            if safe in canonical.columns:
                safe = f"attr_{safe}"
            canonical[safe] = frame[column]

    bad_timestamps = int(canonical[model.TIMESTAMP].isna().sum())
    if bad_timestamps:
        warnings.append(f"{bad_timestamps} row(s) had an unparsable timestamp and were dropped")
        canonical = canonical[canonical[model.TIMESTAMP].notna()]

    if canonical.empty:
        raise ValidationError("No rows left after timestamp parsing - check the timestamp column")

    unmatched = sum(1 for a in canonical[model.ACTIVITY] if a == profile.fallback)
    if profile.rules and unmatched:
        warnings.append(
            f"{unmatched} event(s) did not match any rule of profile '{profile.id}' "
            f"and fell back to '{profile.fallback}'"
        )

    return IngestionResult(
        frame=model.normalize_dtypes(canonical),
        detected_columns=detected,
        warnings=warnings,
    )


def events_to_frame(events: Iterable[Any], *, profile: MappingProfile) -> pd.DataFrame:
    """Builds the canonical frame from API ``EventIn`` objects."""
    rows: list[dict[str, Any]] = []
    now = pd.Timestamp.utcnow().tz_localize(None)
    for event in events:
        activity, _, _ = profile.normalize(event.activity)
        row: dict[str, Any] = {
            model.CASE: str(event.case_id),
            model.ACTIVITY: activity,
            model.ACTIVITY_RAW: event.activity,
            model.TIMESTAMP: event.timestamp or now,
            model.RESOURCE: event.resource,
            model.LIFECYCLE: event.lifecycle,
        }
        for key, value in (event.attributes or {}).items():
            if key not in row:
                row[key] = value
        rows.append(row)
    if not rows:
        raise ValidationError("No events provided")
    return model.normalize_dtypes(pd.DataFrame(rows))


def preview_columns(payload: bytes, filename: str, rows: int = 20) -> dict[str, Any]:
    """Cheap 'what is in this file?' endpoint helper - no mining involved."""
    frame = read_upload(payload, filename)
    columns = list(frame.columns)
    return {
        "columns": columns,
        "rows_previewed": int(min(rows, len(frame))),
        "suggested_mapping": {
            model.CASE: _guess_column(columns, (model.PM4PY_CASE, *CASE_HINTS)),
            model.ACTIVITY: _guess_column(columns, (model.PM4PY_ACTIVITY, *ACTIVITY_HINTS)),
            model.TIMESTAMP: _guess_column(columns, (model.PM4PY_TIMESTAMP, *TIMESTAMP_HINTS)),
            model.RESOURCE: _guess_column(columns, RESOURCE_HINTS),
            model.LIFECYCLE: _guess_column(columns, LIFECYCLE_HINTS),
        },
        "sample": frame.head(rows).astype(str).to_dict(orient="records"),
    }
