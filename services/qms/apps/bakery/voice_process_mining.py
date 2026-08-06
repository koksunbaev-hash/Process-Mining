import hashlib
import hmac
import json
import re
import urllib.error
import urllib.request
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404
from django.urls import reverse
from django.utils import timezone

from apps.audit.services import write_audit
from apps.nonconformities.models import DefectType, Nonconformity
from apps.notifications.services import notify
from apps.quality.models import ControlPost, ControlType, Department, QualityObject

from .models import ProductionBatch, ProductionStage, VoiceCommand, VoiceMessage
from .permissions import can_view_voice
from .services import log_order_event, move_batch, pause_batch, resume_batch


STAGE_ALIASES = {
    "очеред": "queue",
    "замес": "mixing",
    "формов": "forming",
    "рассто": "proofing",
    "печ": "oven",
    "выпеч": "oven",
    "склад": "warehouse",
    "готов": "done",
}

STAGE_ORDER = ["queue", "mixing", "forming", "proofing", "oven", "warehouse", "done"]

# "отправить в склад", "передай на формовку", "перевести в печь". A named
# destination is an instruction; "закончила замес" is an inference about what
# comes next. When a sentence carries both - which is how people actually speak,
# "B-102 закончил замес, отправить в склад" - the instruction wins.
DIRECTIVE_RE = re.compile(
    r"(?:отправ\w*|переда\w*|перевед\w*|перевест\w*|переме\w*|сразу|прямо)\s+"
    r"(?:e[её]|его|их|партию|батч)?\s*"
    r"(?:в|на|к)\s+([а-яё]+)",
    re.IGNORECASE,
)

# Gender and number vary in speech - "закончил", "закончила", "завершили" - so
# match the stem rather than listing every form.
COMPLETED_RE = re.compile(r"(?:законч|заверш|сдела|доде?ла)\w*\s+(?:этап\s+)?([а-яё]+)", re.IGNORECASE)

NEXT_BY_PHRASE = {
    "закончила замес": "forming",
    "завершила замес": "forming",
    "закончить замес": "forming",
    "передать на формовку": "forming",
    "отправлена на расстойку": "proofing",
    "отправить на расстойку": "proofing",
    "передать на расстойку": "proofing",
    "отправлена в печь": "oven",
    "отправить в печь": "oven",
    "передать в печь": "oven",
    "поступила на склад": "warehouse",
    "принять на склад": "warehouse",
    "передать на склад": "warehouse",
    "партия готова": "done",
    "готова": "done",
}


def may_auto_confirm(command, batch):
    """Whether the widget may run this command on a timer instead of a click.

    Everything the operator can say now qualifies - jumps over a stage, steps
    back, problems raised - on the explicit instruction that the countdown is
    the confirmation. The two remaining refusals are not policy: a command with
    nothing to act on would spend three seconds counting down to an error, and a
    genuinely low score is the one signal that the words themselves are in doubt.
    In practice the plugin reports no score at all, so that branch never fires.
    """
    if command.status != VoiceCommand.Status.DETECTED:
        return False
    if not batch:
        return False
    if command.intent in {
        VoiceCommand.Intent.MOVE_BATCH,
        VoiceCommand.Intent.ACCEPT_TO_WAREHOUSE,
        VoiceCommand.Intent.COMPLETE_BATCH,
    }:
        if not batch.current_stage_id:
            return False
        target = ProductionStage.objects.filter(code=(command.extracted_data or {}).get("to_stage") or "").first()
        return bool(target) and target.sequence != batch.current_stage.sequence
    return True


def callback_url():
    return settings.PROCESS_MINING_CALLBACK_URL or "/api/process-mining/callback/"


def process_mining_context():
    recent_batches = list(ProductionBatch.objects.order_by("-id")[:50])
    return {
        "stages": ["Очередь", "Замес", "Формовка", "Расстойка", "Печь", "Склад", "Готово"],
        "batch_numbers": [batch.batch_number for batch in recent_batches],
        "batch_aliases": [batch.short_batch_number for batch in recent_batches],
    }


def send_voice_to_process_mining(voice_message):
    if not settings.PROCESS_MINING_API_URL:
        voice_message.transcription_status = VoiceMessage.TranscriptionStatus.FAILED
        voice_message.processing_error = "Сервис Process Mining не настроен. Укажите PROCESS_MINING_API_URL и токен."
        voice_message.save(update_fields=["transcription_status", "processing_error", "updated_at"])
        return None

    payload = {
        "external_id": str(voice_message.pk),
        "client_request_id": voice_message.client_request_id or "",
        "language": "ru",
        "callback_url": callback_url(),
        "context": json.dumps(process_mining_context(), ensure_ascii=False),
    }
    boundary = f"----kms{voice_message.pk}{int(timezone.now().timestamp())}"
    body = build_multipart_body(boundary, payload, voice_message)
    request = urllib.request.Request(
        settings.PROCESS_MINING_API_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {settings.PROCESS_MINING_API_TOKEN}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.PROCESS_MINING_TIMEOUT_SECONDS) as response:
            data = json.loads(response.read().decode("utf-8") or "{}")
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        voice_message.transcription_status = VoiceMessage.TranscriptionStatus.FAILED
        voice_message.processing_error = str(exc)
        voice_message.save(update_fields=["transcription_status", "processing_error", "updated_at"])
        return None

    voice_message.external_task_id = data.get("task_id", "") or voice_message.external_task_id
    voice_message.transcription_status = data.get("status") or VoiceMessage.TranscriptionStatus.SENT
    voice_message.save(update_fields=["external_task_id", "transcription_status", "updated_at"])
    return data


def build_multipart_body(boundary, fields, voice_message):
    lines = []
    for name, value in fields.items():
        lines.extend([
            f"--{boundary}",
            f'Content-Disposition: form-data; name="{name}"',
            "",
            str(value),
        ])
    filename = voice_message.original_filename or "voice.webm"
    content = voice_message.audio_file.read()
    lines.extend([
        f"--{boundary}",
        f'Content-Disposition: form-data; name="audio_file"; filename="{filename}"',
        f"Content-Type: {voice_message.mime_type or 'application/octet-stream'}",
        "",
    ])
    body = "\r\n".join(lines).encode("utf-8") + b"\r\n" + content + f"\r\n--{boundary}--\r\n".encode("utf-8")
    return body


def verify_process_mining_signature(raw_body, headers):
    secret = settings.PROCESS_MINING_CALLBACK_SECRET
    if not secret:
        return False
    api_key = headers.get("X-Process-Mining-Secret")
    if api_key and hmac.compare_digest(api_key, secret):
        return True
    signature = headers.get("X-Process-Mining-Signature", "")
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, f"sha256={digest}") or hmac.compare_digest(signature, digest)


def handle_process_mining_callback(payload):
    voice = VoiceMessage.objects.select_for_update().get(pk=payload["external_id"])
    voice.external_task_id = payload.get("task_id", "") or voice.external_task_id
    voice.transcription_status = payload.get("status", VoiceMessage.TranscriptionStatus.COMPLETED)
    if voice.transcription_status == VoiceMessage.TranscriptionStatus.FAILED:
        voice.processing_error = payload.get("error", "") or payload.get("error_code", "")
    else:
        voice.transcript = payload.get("transcript", "")
        voice.confidence = Decimal(str(payload.get("confidence", "0") or "0"))
    voice.processed_at = timezone.now()
    voice.save(update_fields=["external_task_id", "transcription_status", "processing_error", "transcript", "confidence", "processed_at", "updated_at"])
    command = None
    if voice.transcription_status == VoiceMessage.TranscriptionStatus.COMPLETED and voice.transcript:
        command = create_voice_command(voice)
    return voice, command


def _squash(value):
    """B-107, B107, b 107 -> b107. Speech does not pronounce punctuation."""
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def resolve_batch(data):
    """Finds the batch a command refers to: by batch number, else by order.

    Falling back to the order number turns a dead end into a working command,
    because one order normally has a single batch in flight. When an order has
    several at once the reference really is ambiguous, so we refuse rather than
    move the wrong one.
    """
    number = (data.get("batch_number") or "").strip()
    if number:
        batch = ProductionBatch.objects.select_related("current_stage").filter(
            batch_number__iexact=number
        ).first()
        if batch:
            return batch
        # Whisper writes "B107" as often as "B-107", and an exact match then
        # fails on a command that was spoken perfectly. Compare the way it
        # sounds instead: letters and digits only.
        wanted = _squash(number)
        if wanted:
            for candidate in ProductionBatch.objects.select_related("current_stage").exclude(
                status__in=["completed", "cancelled"]
            ):
                if _squash(candidate.batch_number) == wanted or _squash(candidate.short_batch_number) == wanted:
                    return candidate

    order_number = (data.get("order_number") or "").strip()
    if not order_number:
        return None
    active = ProductionBatch.objects.select_related("current_stage").filter(
        order_item__order__order_number__iendswith=order_number
    ).exclude(status__in=["completed", "cancelled"])
    return active.first() if active.count() == 1 else None


def create_voice_command(voice):
    parsed = parse_voice_command(voice.transcript, voice.confidence)
    batch = resolve_batch(parsed)
    if batch:
        parsed["spoken_batch_number"] = parsed.get("batch_number", "")
        parsed["batch_number"] = batch.batch_number
        parsed["from_stage"] = batch.current_stage.code
        parsed["current_stage"] = batch.current_stage.name
    # No score is not a low score. The plugin reports none at all, so this used
    # to read 0.0000, fall under the threshold and mark every single command -
    # correct ones included - as needing review. The widget already treats zero
    # as "no claim" and hides the warning; the server now agrees with it.
    status = (
        VoiceCommand.Status.NEEDS_REVIEW
        if voice.confidence is not None and Decimal("0") < voice.confidence < Decimal("0.8000")
        else VoiceCommand.Status.DETECTED
    )
    command, _ = VoiceCommand.objects.update_or_create(
        voice_message=voice,
        defaults={
            "intent": parsed["intent"],
            "extracted_data": parsed,
            "confidence": voice.confidence,
            "status": status,
        },
    )
    return command


def stage_from_word(word):
    """Единственное слово -> код этапа. «формовку», «складе», «печь»."""
    word = (word or "").lower()
    for part, code in STAGE_ALIASES.items():
        if word.startswith(part):
            return code
    return ""


def resolve_target_stage(normalized):
    """Where the speaker wants the batch, in order of how explicit they were.

    1. A named destination - "отправить в склад". This is an order, and it is
       what makes a free move possible: the target need not be the next stage.
    2. A finished stage - "закончил замес" - which implies the one after it.
    3. Any stage mentioned at all, last one wins. The old behaviour, kept as a
       fallback for phrasings the two rules above do not cover.
    """
    directive = DIRECTIVE_RE.search(normalized)
    if directive:
        code = stage_from_word(directive.group(1))
        if code:
            return code

    for phrase, code in NEXT_BY_PHRASE.items():
        if phrase in normalized:
            return code

    completed = COMPLETED_RE.search(normalized)
    if completed:
        code = stage_from_word(completed.group(1))
        if code in STAGE_ORDER:
            index = STAGE_ORDER.index(code)
            if index + 1 < len(STAGE_ORDER):
                return STAGE_ORDER[index + 1]

    found = ""
    for part, code in STAGE_ALIASES.items():
        if part in normalized:
            found = code
    return found


def parse_voice_command(text, confidence=None):
    normalized = text.lower().replace("№", " ")
    batch_match = re.search(
    r"\b(?:парт(?:ия|ию|ии)\s*[№#]?\s*)?((?:DEMO[-\s]?)?[BD][-\s]?\d+(?:-\d+)?(?:-\d+)?|\d+)\b",
    text,
    flags=re.IGNORECASE,
    )

    batch_number = (
    batch_match.group(1).upper().replace(" ", "-")
    if batch_match
    else ""
    )
    # An operator names the order as readily as the batch ("заказ 13"), and a
    # spoken number never carries the stored prefix - keep the digits and
    # resolve them loosely in resolve_batch().
    order_match = re.search(r"заказ\w*\s*([a-zа-я0-9][a-zа-я0-9\-]*)", normalized, flags=re.IGNORECASE)
    order_number = order_match.group(1).upper().strip("-") if order_match else ""
    to_stage = resolve_target_stage(normalized)
    if "пауз" in normalized or "останов" in normalized:
        intent = VoiceCommand.Intent.PAUSE_BATCH
    elif "возобнов" in normalized or "продолж" in normalized:
        intent = VoiceCommand.Intent.RESUME_BATCH
    elif "проблем" in normalized or "обнаруж" in normalized or "подгора" in normalized:
        intent = VoiceCommand.Intent.CREATE_PROBLEM
    elif to_stage == "warehouse":
        intent = VoiceCommand.Intent.ACCEPT_TO_WAREHOUSE
    elif to_stage == "done":
        intent = VoiceCommand.Intent.COMPLETE_BATCH
    elif "коммент" in normalized:
        intent = VoiceCommand.Intent.ADD_COMMENT
    else:
        intent = VoiceCommand.Intent.MOVE_BATCH
    quantity = None
    quantity_match = re.search(r"количеств[оа]?\s+(\d+(?:[,.]\d+)?)", normalized)
    if quantity_match:
        quantity = quantity_match.group(1).replace(",", ".")
    comment = build_comment(intent, to_stage, text)
    return {
        "intent": intent,
        "batch_number": batch_number,
        "order_number": order_number,
        "to_stage": to_stage,
        "comment": comment,
        "quantity": quantity,
        "confidence": float(confidence or 0),
    }


def build_comment(intent, to_stage, text):
    if intent == VoiceCommand.Intent.PAUSE_BATCH:
        return "Партия остановлена по голосовой команде"
    if intent == VoiceCommand.Intent.RESUME_BATCH:
        return "Партия возобновлена по голосовой команде"
    if intent == VoiceCommand.Intent.CREATE_PROBLEM:
        return text
    comments = {
        "forming": "Замес завершён",
        "proofing": "Формовка завершена",
        "oven": "Расстойка завершена",
        "warehouse": "Партия поступила на склад",
        "done": "Партия готова",
        "mixing": "Партия передана на замес",
    }
    return comments.get(to_stage, text)


@transaction.atomic
def confirm_voice_command(command, user):
    command = VoiceCommand.objects.select_for_update().select_related("voice_message").get(pk=command.pk)
    if command.status == VoiceCommand.Status.EXECUTED:
        raise ValidationError("Команда уже выполнена.")
    if command.status == VoiceCommand.Status.REJECTED:
        raise ValidationError("Команда отклонена.")
    data = command.extracted_data
    found = resolve_batch(data)
    batch = (
        ProductionBatch.objects.select_for_update()
        .select_related("current_stage", "order_item__order")
        .filter(pk=found.pk)
        .first()
        if found
        else None
    )
    if not batch:
        command.status = VoiceCommand.Status.FAILED
        command.error_message = "Партия не найдена."
        command.save(update_fields=["status", "error_message", "updated_at"])
        raise Http404("Партия не найдена.")
    if data.get("batch_number") != batch.batch_number:
        command.extracted_data["spoken_batch_number"] = data.get("batch_number", "")
        command.extracted_data["batch_number"] = batch.batch_number
    expected_stage = data.get("from_stage") or batch.current_stage.code
    if data.get("from_stage") and batch.current_stage.code != data["from_stage"]:
        raise ConflictError(f"Этап партии изменился: сейчас {batch.current_stage.name}.")

    intent = command.intent
    if intent in {VoiceCommand.Intent.MOVE_BATCH, VoiceCommand.Intent.ACCEPT_TO_WAREHOUSE, VoiceCommand.Intent.COMPLETE_BATCH}:
        if data.get("quantity") and intent == VoiceCommand.Intent.ACCEPT_TO_WAREHOUSE:
            batch.actual_quantity = Decimal(str(data["quantity"]))
            batch.save(update_fields=["actual_quantity", "updated_at"])
        target = ProductionStage.objects.filter(code=data.get("to_stage") or "").first()
        if not target:
            raise ValidationError("Не понял, на какой этап переводить партию. Назовите этап.")
        # allow_skip: spoken orders name a destination, not a step. "B-102
        # закончил замес, отправить в склад" is a legitimate thing to say, and
        # refusing it because Склад is four stages away helps nobody. The jump is
        # recorded as such, and move_batch still demands a comment for it.
        move_batch(
            batch,
            target,
            user,
            data.get("comment", ""),
            require_comment=target.sequence < batch.current_stage.sequence,
            allow_skip=True,
        )
    elif intent == VoiceCommand.Intent.PAUSE_BATCH:
        pause_batch(batch, user, data.get("comment", ""))
    elif intent == VoiceCommand.Intent.RESUME_BATCH:
        resume_batch(batch, user, data.get("comment", ""))
    elif intent == VoiceCommand.Intent.CREATE_PROBLEM:
        create_problem_from_voice(batch, user, data.get("comment", ""))
        notify(batch.assigned_to or user, "Создана проблема по голосовой команде", batch.batch_number, "voice_problem", reverse("bakery:batch_detail", args=[batch.pk]))
    elif intent == VoiceCommand.Intent.ADD_COMMENT:
        log_order_event(batch.order_item.order, data.get("comment", ""), "voice_comment", user=user, batch=batch)
    command.status = VoiceCommand.Status.EXECUTED
    command.confirmed_by = user
    command.executed_at = timezone.now()
    command.extracted_data["from_stage"] = expected_stage
    command.save(update_fields=["status", "confirmed_by", "executed_at", "extracted_data", "updated_at"])
    write_audit("voice_command_executed", command, user=user, changes=command.extracted_data)
    return command


def reject_voice_command(command, user):
    if command.voice_message.created_by_id != user.id and not can_view_voice(user, command.voice_message):
        raise PermissionDenied("Нет доступа к голосовой команде.")
    command.status = VoiceCommand.Status.REJECTED
    command.confirmed_by = user
    command.save(update_fields=["status", "confirmed_by", "updated_at"])
    write_audit("voice_command_rejected", command, user=user, changes=command.extracted_data)
    return command


def create_problem_from_voice(batch, user, description):
    dept, _ = Department.objects.get_or_create(code="BAKERY", defaults={"name": "Хлебозавод"})
    control_type, _ = ControlType.objects.get_or_create(code="bakery-problem", defaults={"name": "Производственная проблема"})
    post, _ = ControlPost.objects.get_or_create(code="BAKERY-NC", defaults={"name": "Контроль хлебозавода", "department": dept, "control_type": control_type, "sequence": 1})
    defect, _ = DefectType.objects.get_or_create(code="VOICE-PROBLEM", defaults={"name": "Проблема из голосовой команды", "category": "хлебозавод", "criticality": "critical", "object_block_required": True})
    qobj, _ = QualityObject.objects.get_or_create(unique_number=f"VOICE-{batch.batch_number}", defaults={"object_type": "finished_product", "product_name": batch.product.name, "quantity": 1, "department": dept, "created_by": user})
    problem = Nonconformity.objects.create(
        quality_object=qobj,
        control_post=post,
        detected_by=user,
        defect_type=defect,
        description=description or "Проблема создана по голосовой команде.",
        criticality="critical",
        affected_quantity=1,
        responsible_department=dept,
        responsible_user=batch.assigned_to,
        bakery_order=batch.order_item.order,
        bakery_batch=batch,
        bakery_product=batch.product,
        bakery_stage=batch.current_stage,
    )
    batch.status = ProductionBatch.Status.PROBLEM
    batch.save(update_fields=["status", "updated_at"])
    return problem


class ConflictError(Exception):
    pass
