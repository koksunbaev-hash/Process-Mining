import csv
import hashlib
import json
import logging
import urllib.error
import urllib.request
from decimal import Decimal
from io import StringIO

from django.conf import settings
from django.db import DatabaseError, transaction
from django.utils import timezone

from apps.bakery.models import ProductionBatch, ProductionOrder

from .models import ProcessEvent, ProcessEventExport

logger = logging.getLogger(__name__)

CSV_COLUMNS = [
    "event_id",
    "case_id",
    "case_type",
    "activity",
    "timestamp",
    "user_id",
    "user_name",
    "resource",
    "product_id",
    "product_name",
    "batch_number",
    "order_number",
    "from_stage",
    "to_stage",
    "status",
    "quantity",
    "unit",
    "problem_type",
    "metadata",
]


def safe_record_process_event(**kwargs):
    try:
        return record_process_event(**kwargs)
    except Exception:
        logger.exception("Process Mining event recording failed")
        return None


def record_process_event(
    *,
    case_id,
    case_type,
    activity,
    occurred_at=None,
    batch=None,
    order=None,
    user=None,
    product=None,
    from_stage="",
    to_stage="",
    status="",
    quantity=None,
    unit="",
    problem_type="",
    resource="",
    event_data=None,
):
    occurred_at = occurred_at or timezone.now()
    if batch and not order:
        order = batch.order_item.order
    if batch and not product:
        product = batch.product
    if not resource and user:
        resource = getattr(getattr(user, "profile", None), "get_role_display", lambda: "")() or getattr(user, "username", "")
    return ProcessEvent.objects.create(
        case_id=case_id,
        case_type=case_type,
        activity=activity,
        occurred_at=occurred_at,
        batch=batch,
        order=order,
        user=user if getattr(user, "is_authenticated", False) else None,
        product=product,
        from_stage=from_stage or "",
        to_stage=to_stage or "",
        status=status or "",
        quantity=quantity,
        unit=unit or "",
        problem_type=problem_type or "",
        resource=resource or "",
        event_data=event_data or {},
    )


def activity_for_stage(to_stage):
    return {
        "queue": "Партия поступила в очередь",
        "mixing": "Начало замеса",
        "forming": "Передача на формовку",
        "proofing": "Передача на расстойку",
        "oven": "Передача в печь",
        "warehouse": "Приём продукции на склад",
        "done": "Завершение партии",
    }.get(to_stage, f"Переход на этап {to_stage}")


def process_event_for_batch_transition(batch, from_stage, to_stage, user, occurred_at=None, comment=""):
    direction = "return" if from_stage and to_stage and to_stage.sequence < from_stage.sequence else "forward"
    activity = "Возврат партии на предыдущий этап" if direction == "return" else activity_for_stage(to_stage.code)
    return safe_record_process_event(
        case_id=batch.batch_number,
        case_type=ProcessEvent.CaseType.BATCH,
        activity=activity,
        occurred_at=occurred_at,
        batch=batch,
        user=user,
        from_stage=from_stage.code if from_stage else "",
        to_stage=to_stage.code if to_stage else "",
        status=batch.status,
        quantity=batch.actual_quantity or batch.planned_quantity,
        unit=batch.unit,
        # is_demo travels in the metadata as well as on the FK, because reset_demo
        # deletes the batch and the FK is SET_NULL - the flag has to outlive it.
        event_data={"comment": comment, "direction": direction, "is_demo": bool(batch.is_demo)},
    )


def row_for_event(event):
    metadata = json.dumps(event.event_data or {}, ensure_ascii=False, separators=(",", ":"), default=str)
    user_name = ""
    if event.user_id:
        user_name = event.user.get_full_name() or event.user.username
    return {
        "event_id": str(event.event_id),
        "case_id": event.case_id,
        "case_type": event.case_type,
        "activity": event.activity,
        "timestamp": event.occurred_at.isoformat(),
        "user_id": event.user_id or "",
        "user_name": user_name,
        "resource": event.resource,
        "product_id": event.product_id or "",
        "product_name": event.product.name if event.product_id else "",
        "batch_number": event.batch.batch_number if event.batch_id else "",
        "order_number": event.order.order_number if event.order_id else "",
        "from_stage": event.from_stage,
        "to_stage": event.to_stage,
        "status": event.status,
        "quantity": str(event.quantity) if event.quantity is not None else "",
        "unit": event.unit,
        "problem_type": event.problem_type,
        "metadata": metadata,
    }


def build_events_csv(events):
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for event in events:
        writer.writerow(row_for_event(event))
    return output.getvalue()


def csv_checksum(csv_text):
    return hashlib.sha256(csv_text.encode("utf-8")).hexdigest()


def choose_pending_events(batch_size):
    # Demo transitions are recorded like any other, but once they reach the
    # analytics service there is no taking them back: the batch is deleted on
    # reset and the DEMO-B-0001 case stays in the log for good, inside every map
    # and every KPI drawn from it. Cheaper to never send them.
    #
    # Filtered by id against a subquery rather than by batch__is_demo: both FKs
    # are nullable, so a join lookup becomes a LEFT OUTER JOIN, and PostgreSQL
    # refuses SELECT ... FOR UPDATE on the nullable side of one. SQLite ignores
    # FOR UPDATE entirely, so that failure only ever shows up in production.
    demo_batches = ProductionBatch.objects.filter(is_demo=True).values("pk")
    demo_orders = ProductionOrder.objects.filter(is_demo=True).values("pk")
    queryset = (
        ProcessEvent.objects.filter(export_status=ProcessEvent.ExportStatus.PENDING)
        .exclude(batch_id__in=demo_batches)
        .exclude(order_id__in=demo_orders)
        .order_by("created_at", "id")
    )
    try:
        return list(queryset.select_for_update(skip_locked=True)[:batch_size])
    except DatabaseError:
        return list(queryset.select_for_update()[:batch_size])


def mark_retry(events, error):
    now = timezone.now()
    max_retries = settings.PROCESS_MINING_MAX_RETRIES
    for event in events:
        event.export_attempts += 1
        event.last_attempt_at = now
        event.last_error = str(error)
        event.export_status = ProcessEvent.ExportStatus.DEAD_LETTER if event.export_attempts >= max_retries else ProcessEvent.ExportStatus.PENDING
        event.save(update_fields=["export_attempts", "last_attempt_at", "last_error", "export_status"])


def multipart_body(boundary, fields, file_name, csv_text):
    chunks = []
    for name, value in fields.items():
        chunks.extend([f"--{boundary}", f'Content-Disposition: form-data; name="{name}"', "", str(value)])
    chunks.extend([
        f"--{boundary}",
        f'Content-Disposition: form-data; name="file"; filename="{file_name}"',
        "Content-Type: text/csv; charset=utf-8",
        "",
    ])
    body = "\r\n".join(chunks).encode("utf-8") + b"\r\n" + csv_text.encode("utf-8") + f"\r\n--{boundary}--\r\n".encode("utf-8")
    return body


def send_csv_to_process_mining(export, csv_text, checksum):
    if not settings.PROCESS_MINING_EVENT_LOG_URL:
        raise RuntimeError("PROCESS_MINING_EVENT_LOG_URL не настроен.")
    boundary = f"----kms-events-{export.export_id}"
    fields = {
        "export_id": str(export.export_id),
        "source": settings.PROCESS_MINING_SOURCE,
        "schema_version": settings.PROCESS_MINING_SCHEMA_VERSION,
        "checksum": checksum,
        "events_count": export.events_count,
    }
    body = multipart_body(boundary, fields, export.file_name, csv_text)
    request = urllib.request.Request(
        settings.PROCESS_MINING_EVENT_LOG_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {settings.PROCESS_MINING_API_TOKEN}",
            "Idempotency-Key": str(export.export_id),
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    timeout = settings.PROCESS_MINING_CONNECT_TIMEOUT + settings.PROCESS_MINING_READ_TIMEOUT
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8") or "{}"
        return response.status, json.loads(raw)


def apply_response(events, export, response_data):
    status = response_data.get("status", "accepted")
    errors = {item.get("event_id"): item for item in response_data.get("errors", [])}
    now = timezone.now()
    for event in events:
        error = errors.get(str(event.event_id))
        event.export_attempts += 1
        event.last_attempt_at = now
        event.export = export
        if error:
            event.export_status = ProcessEvent.ExportStatus.FAILED
            event.last_error = f"{error.get('code', 'REJECTED')}: {error.get('message', '')}".strip()
        else:
            event.export_status = ProcessEvent.ExportStatus.SENT
            event.exported_at = now
            event.last_error = ""
        event.save(update_fields=["export_attempts", "last_attempt_at", "export", "export_status", "exported_at", "last_error"])
    export.status = ProcessEventExport.Status.PARTIALLY_ACCEPTED if status == "partially_accepted" or errors else ProcessEventExport.Status.ACCEPTED
    export.finished_at = now
    export.save(update_fields=["status", "finished_at"])


def export_pending_events_to_process_mining(batch_size=None, dry_run=False):
    batch_size = int(batch_size or settings.PROCESS_MINING_BATCH_SIZE)
    with transaction.atomic():
        events = choose_pending_events(batch_size)
        if not events:
            return {"events_count": 0, "csv": "", "export": None, "sent": 0, "failed": 0}
        csv_text = build_events_csv(events)
        checksum = csv_checksum(csv_text)
        if dry_run:
            return {"events_count": len(events), "csv": csv_text, "checksum": checksum, "export": None, "sent": 0, "failed": 0}
        export = ProcessEventExport.objects.create(
            status=ProcessEventExport.Status.SENDING,
            events_count=len(events),
            file_name=f"kms_process_events_{timezone.now().strftime('%Y%m%d_%H%M%S')}.csv",
            checksum=checksum,
            attempts=1,
            csv_content=csv_text,
            started_at=timezone.now(),
        )
        ProcessEvent.objects.filter(pk__in=[event.pk for event in events]).update(
            export_status=ProcessEvent.ExportStatus.PROCESSING,
            export=export,
            last_attempt_at=timezone.now(),
        )
    try:
        status_code, data = send_csv_to_process_mining(export, csv_text, checksum)
        export.response_status_code = status_code
        export.response_body = json.dumps(data, ensure_ascii=False)
        export.save(update_fields=["response_status_code", "response_body"])
        apply_response(events, export, data)
        return {"events_count": len(events), "export": export, "sent": ProcessEvent.objects.filter(export=export, export_status=ProcessEvent.ExportStatus.SENT).count(), "failed": ProcessEvent.objects.filter(export=export, export_status=ProcessEvent.ExportStatus.FAILED).count()}
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, RuntimeError) as exc:
        export.status = ProcessEventExport.Status.FAILED
        export.finished_at = timezone.now()
        export.last_error = str(exc)
        export.save(update_fields=["status", "finished_at", "last_error"])
        mark_retry(events, exc)
        return {"events_count": len(events), "export": export, "sent": 0, "failed": len(events), "error": str(exc)}


def retry_failed_events():
    updated = ProcessEvent.objects.filter(export_status=ProcessEvent.ExportStatus.FAILED).update(export_status=ProcessEvent.ExportStatus.PENDING, last_error="")
    return updated
