"""Event-log intake for source systems.

This implements the contract a source system (the KMS/QMS bakery app) was built
against: it batches business events into a CSV, hands the batch over with a
checksum and an idempotency key, and expects a per-row verdict back.

Deliberately *not* under ``/api/v1``: the path is part of a contract that was
agreed before this service existed, and breaking it to satisfy our own URL
taste would mean changing code on the other side for nothing.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import datetime
from typing import Annotated, Any

import pandas as pd
from fastapi import APIRouter, File, Form, Header, UploadFile

from app.core import model
from app.deps import ApiKeyDep, LogServiceDep
from app.errors import ValidationError
from app.logging_config import get_logger
from app.schemas.integration import ImportError_, ImportResponse

log = get_logger(__name__)

router = APIRouter(prefix="/event-logs", tags=["integration"])

SCHEMA_VERSION = "1.0"

# The agreed column order. We read by header name rather than position - a
# source system that adds a trailing column should not break the import - but
# the required four are enforced.
REQUIRED_COLUMNS = ("event_id", "case_id", "activity", "timestamp")
KNOWN_COLUMNS = (
    "event_id", "case_id", "case_type", "activity", "timestamp",
    "user_id", "user_name", "resource", "product_id", "product_name",
    "batch_number", "order_number", "from_stage", "to_stage", "status",
    "quantity", "unit", "problem_type", "metadata",
)

# Columns that become first-class canonical fields; everything else is kept as
# a free-form attribute so no information from the source is thrown away.
_CANONICAL_COLUMNS = {"event_id", "case_id", "activity", "timestamp", "resource"}
_ATTRIBUTE_COLUMNS = tuple(c for c in KNOWN_COLUMNS if c not in _CANONICAL_COLUMNS)


def _decode(payload: bytes) -> str:
    try:
        return payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationError(
            "CSV must be UTF-8 encoded", details={"code": "INVALID_ENCODING"}
        ) from exc


def _parse_timestamp(raw: str) -> datetime | None:
    """ISO-8601 with timezone, per the contract. Returns None if unusable."""
    if not raw or not raw.strip():
        return None
    value = pd.to_datetime(raw.strip(), errors="coerce", utc=True)
    if value is pd.NaT or pd.isna(value):
        return None
    return value.tz_localize(None).to_pydatetime()


def _parse_metadata(raw: str) -> dict[str, Any]:
    if not raw or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


@router.post(
    "/import/",
    response_model=ImportResponse,
    summary="Import a batch of business events (CSV) from a source system",
)
async def import_events(
    logs: LogServiceDep,
    _: ApiKeyDep,
    file: Annotated[UploadFile, File(description="CSV, UTF-8, comma-separated")],
    export_id: Annotated[str, Form(description="UUID of this batch")],
    source: Annotated[str, Form(description="Originating system, e.g. kms_bakery")] = "unknown",
    schema_version: Annotated[str, Form()] = SCHEMA_VERSION,
    checksum: Annotated[str | None, Form(description="SHA-256 of the CSV bytes")] = None,
    events_count: Annotated[int | None, Form(description="Rows excluding the header")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Any:
    payload = await file.read()

    # A replayed batch must replay its answer, not import a second time. This
    # is what makes a source-side retry after a timeout safe.
    receipt_key = f"import:{idempotency_key or export_id}"
    previous = logs.repository.get_receipt(receipt_key)
    if previous is not None:
        log.info("import_replayed", extra={"export_id": export_id})
        return previous

    if checksum:
        actual = hashlib.sha256(payload).hexdigest()
        if actual.lower() != checksum.strip().lower():
            raise ValidationError(
                "CSV checksum does not match the declared value",
                details={"code": "CHECKSUM_MISMATCH", "expected": checksum, "actual": actual},
            )

    text = _decode(payload)
    reader = csv.DictReader(io.StringIO(text))
    headers = {h.strip() for h in (reader.fieldnames or [])}
    missing = [c for c in REQUIRED_COLUMNS if c not in headers]
    if missing:
        raise ValidationError(
            "CSV is missing required columns: " + ", ".join(missing),
            details={"code": "INVALID_SCHEMA", "missing": missing, "expected": list(KNOWN_COLUMNS)},
        )

    received = 0
    errors: list[ImportError_] = []
    by_case_type: dict[str, list[dict[str, Any]]] = {}

    for row in reader:
        received += 1
        event_id = (row.get("event_id") or "").strip()
        case_id = (row.get("case_id") or "").strip()
        activity = (row.get("activity") or "").strip()
        timestamp = _parse_timestamp(row.get("timestamp") or "")

        if not event_id:
            errors.append(ImportError_(event_id="", code="MISSING_EVENT_ID",
                                       message="event_id is required"))
            continue
        if not case_id:
            errors.append(ImportError_(event_id=event_id, code="MISSING_CASE_ID",
                                       message="case_id is required"))
            continue
        if not activity:
            errors.append(ImportError_(event_id=event_id, code="MISSING_ACTIVITY",
                                       message="activity is required"))
            continue
        if timestamp is None:
            errors.append(ImportError_(event_id=event_id, code="INVALID_TIMESTAMP",
                                       message="timestamp must be ISO-8601 with timezone"))
            continue

        attributes = {
            key: row[key]
            for key in _ATTRIBUTE_COLUMNS
            if key in row and row[key] not in (None, "")
        }
        attributes.pop("metadata", None)
        attributes.update(_parse_metadata(row.get("metadata") or ""))

        record = {
            model.EVENT_ID: event_id,
            model.CASE: case_id,
            model.ACTIVITY: activity,
            model.ACTIVITY_RAW: activity,
            model.TIMESTAMP: timestamp,
            model.RESOURCE: (row.get("resource") or row.get("user_name") or "").strip() or None,
            model.LIFECYCLE: None,
            **attributes,
        }
        by_case_type.setdefault((row.get("case_type") or "events").strip() or "events", []).append(
            record
        )

    accepted = 0
    duplicates = 0
    touched: list[str] = []

    for case_type, records in by_case_type.items():
        target = logs.get_or_create_stream_log(source=source, case_type=case_type)
        frame = model.normalize_dtypes(pd.DataFrame(records))
        _, added, skipped = logs.append_frame(target.log_id, frame, None)
        accepted += added
        duplicates += skipped
        touched.append(target.log_id)

    rejected = len(errors)
    body = ImportResponse(
        status="partially_accepted" if rejected else "accepted",
        export_id=export_id,
        received=received,
        accepted=accepted,
        duplicates=duplicates,
        rejected=rejected,
        errors=errors,
        log_ids=touched,
    )

    if events_count is not None and events_count != received:
        log.warning(
            "import_count_mismatch",
            extra={"export_id": export_id, "declared": events_count, "parsed": received},
        )

    payload_out = body.model_dump(mode="json")
    logs.repository.save_receipt(receipt_key, payload_out)
    log.info(
        "import_done",
        extra={
            "export_id": export_id, "source": source, "received": received,
            "accepted": accepted, "duplicates": duplicates, "rejected": rejected,
        },
    )
    return payload_out
