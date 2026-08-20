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

from . import speech_kk
from .models import (
    ProductionBatch,
    ProductionStage,
    ProductionUnit,
    VoiceCommand,
    VoiceMessage,
    format_daily_number,
    parse_daily_number,
)
from .permissions import can_view_voice
from .services import assign_batch_to_unit, log_order_event, move_batch, pause_batch, resume_batch


STAGE_ALIASES = {
    "очеред": "queue",
    "замес": "mixing",
    "формов": "forming",
    "фармов": "forming",
    "рассто": "proofing",
    # Как расстойку слышат модели на живых записях: лишняя "р" и разъехавшаяся
    # граница слова. Обе формы взяты из настоящих транскриптов, не выдуманы.
    "расстр": "proofing",
    "тойка": "proofing",
    "печ": "oven",
    "выпеч": "oven",
    "склад": "warehouse",
    "готов": "done",
    # Kazakh. The stage names themselves are Russian loanwords and are already
    # matched above - "замеске" contains "замес", "формовкаға" contains
    # "формов" - so only the words that are genuinely Kazakh need listing.
    #
    # "пешке"/"пеште" rather than a bare "пеш": that fragment also sits inside
    # "успешно", and a substring match cannot tell the difference.
    # Written folded (see speech_kk.fold): "қойма" is matched as "койма",
    # because that is what the text has been reduced to by the time it gets
    # here. One spelling instead of the several Whisper produces.
    "кезек": "queue",
    "пешке": "oven",
    "пеште": "oven",
    "койма": "warehouse",
    "дайын": "done",
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

# The same sentence in Kazakh puts the verb last: "замес бітті" is "mixing is
# finished", so the batch moves on rather than back. Without this the stage name
# is the only word the fallback can see, and it would send the batch to the
# stage it has just left.
KK_COMPLETED_RE = re.compile(
    r"([а-яё]+)\s+(?:битти|битирди|аякталды|дайын болды)",
    re.IGNORECASE,
)

# Kazakh words for the actions that are not a move. Folded, same as the stages.
KK_INTENT_WORDS = {
    "pause": ("токтат", "токта", "кидирт", "уакытша"),
    "resume": ("жалгастыр", "жалгас", "кайта баста"),
    "problem": ("маселе", "акау", "куйип", "куйди", "бузылды", "жараксыз"),
    "comment": ("пикир", "ескертпе", "тусиниктеме"),
}


def _said(folded, group):
    return any(word in folded for word in KK_INTENT_WORDS[group])

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
        data = command.extracted_data or {}
        if data.get("unit_problem"):
            # Отсчёт до заведомого отказа - три секунды впустую и непонимание,
            # что именно не так.
            return False
        target = ProductionStage.objects.filter(code=data.get("to_stage") or "").first()
        if not target:
            return False
        if target.sequence != batch.current_stage.sequence:
            return True
        # Этап тот же, но названо устройство - значит команда распределяющая, и
        # делать ей есть что. Без этой ветки «партия 3 на печь 2», сказанная про
        # партию, которая уже в печи, единственная из всех ждала бы нажатия.
        return bool(data.get("unit"))
    return True


def callback_url():
    return settings.PROCESS_MINING_CALLBACK_URL or "/api/process-mining/callback/"


def process_mining_context():
    recent_batches = list(ProductionBatch.objects.order_by("-id")[:50])
    visible_numbers = list(dict.fromkeys(
        ProductionBatch.objects
        .filter(daily_card_number__isnull=False)
        .exclude(status__in=[ProductionBatch.Status.COMPLETED, ProductionBatch.Status.CANCELLED])
        .order_by("-card_number_date", "-daily_card_number")
        .values_list("daily_card_number", flat=True)[:100]
    ))
    return {
        "stages": ["Очередь", "Замес", "Формовка", "Расстойка", "Печь", "Склад", "Готово"],
        # Распознаватель должен ждать «печь два» как одно целое. Без списка он
        # слышит там номер партии и отдаёт команду, которой никто не отдавал.
        "units": list(
            ProductionUnit.objects.filter(is_active=True).order_by("stage__sequence", "sequence").values_list("name", flat=True)
        ),
        "batch_numbers": [format_daily_number(number) for number in visible_numbers] + [batch.batch_number for batch in recent_batches],
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
        # Empty means "whatever the analytics service is configured for". The
        # language of the shop floor is a property of the deployment, not of
        # this call, and hardcoding "ru" here quietly overrode PM_STT_LANGUAGE
        # - the setting looked applied and the model kept being told Russian.
        "language": settings.VOICE_LANGUAGE,
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


# Как устройство называют вслух. Слева - корень, который останется от любого
# падежа («на печи», «в печку», «пешке»); справа - корень названия в базе.
# Это быстрый и несомненный путь; всё, что мимо него, ловится по звучанию ниже.
UNIT_ALIASES = {
    "печ": "печ",
    "выпеч": "печ",
    # По-казахски печь - «пеш», и в цеху её так и зовут. Остальные устройства
    # там называют русскими словами, поэтому пары им не нужно.
    "пеш": "печ",
    "миксер": "миксер",
    "тестомес": "миксер",
    "шкаф": "шкаф",
    "расстоечн": "шкаф",
    "формовщ": "формовщ",
    "формовочн": "формовщ",
}

# Слово с числом - вот и весь признак кандидата. Какое из слов окажется
# названием устройства, решают словарь и звучание, а не эта строка: перечислять
# здесь корни значило бы вернуться к списку, который никогда не кончается.
# Номер обязателен - «на печь» это этап, «на печь 2» это место.
UNIT_CANDIDATE_RE = re.compile(r"\b([а-яё]{3,})\s*[№#]?\s*(\d{1,2})\b", flags=re.IGNORECASE)


def _unit_key(value):
    """«Печь № 2» -> «печь2». Речь не произносит ни пробелов, ни решёток."""
    return re.sub(r"[^0-9a-zа-яё]", "", (value or "").lower().replace("ё", "е"))


def unit_vocabulary():
    """Основа названия устройства -> {номер: устройство}.

    Словарь строится из самих устройств, а не из таблицы в коде: названия
    придумывает цех, и купленный «Тестомес 4» должен опознаваться голосом сразу
    после того, как его завели в админке.
    """
    vocabulary = {}
    for unit in ProductionUnit.objects.filter(is_active=True).select_related("stage"):
        key = _unit_key(unit.name)
        tail = re.search(r"(\d+)$", key)
        if not tail:
            continue
        vocabulary.setdefault(key[: tail.start()], {})[int(tail.group(1))] = unit
    return vocabulary


def match_unit_stem(word, vocabulary):
    """Основа названия устройства, которую услышали в этом слове."""
    for root, canonical in UNIT_ALIASES.items():
        if word.startswith(root):
            for stem in vocabulary:
                if stem.startswith(canonical):
                    return stem
    # Точного корня нет - ищем ближайшее по написанию. «Фармовщик» через «а»
    # распознаватель выдаёт регулярно: этап по нему опознавался (в таблице
    # этапов эта форма есть), а устройство - нет, и команда выполнялась
    # наполовину: партия уезжала на этап и оставалась ни на чём.
    return speech_kk.nearest(word, list(vocabulary))


def extract_unit(text):
    """(название устройства, код его этапа, текст без него, причина отказа).

    Устройство вынимается из фразы до разбора номера партии. Иначе «партия 3 на
    печь 2» разбиралась бы двумя числами подряд, и какое из них номер партии,
    зависело бы от того, что оператор назвал первым.

    Четвёртое значение - причина, по которой названное устройство не нашлось.
    Молчать здесь нельзя: команду с неопознанным устройством выполнять нечем, а
    выполнить её частью - перевести партию на этап и бросить - хуже, чем
    отказать. Ровно так и терялась «он алты фармовщик екіге».
    """
    folded = speech_kk.fold(text or "")
    vocabulary = unit_vocabulary()
    if not vocabulary:
        return "", "", text, ""
    for match in UNIT_CANDIDATE_RE.finditer(folded):
        stem = match_unit_stem(match.group(1).replace("ё", "е"), vocabulary)
        if not stem:
            continue
        number = int(match.group(2))
        unit = vocabulary[stem].get(number)
        if unit is None:
            names = ", ".join(sorted(u.name for u in vocabulary[stem].values()))
            return "", "", text, f"Устройства с номером {number} нет. Есть: {names}."
        rest = folded[: match.start()] + " " + folded[match.end():]
        # Устройство называет и этап. «Печь 2» об этом молчит - там слова
        # совпали случайно, - а «миксер 3» и «шкаф 1» этапов «Замес» и
        # «Расстойка» вслух не произносят вовсе, и без этого команда упиралась
        # бы в «не понял, на какой этап переводить».
        return unit.name, unit.stage.code, rest, ""
    return _extract_unit_by_sound(folded, text, vocabulary)


# Казахский называет номер машины падежным словом, и распознаватель мнёт его
# как хочет: «миксер екіге» приходит как «мик сергей», «шкаф үшке» - как
# «шкаф ішкі». Точный разбор выше такое не берёт - там после слова ждётся
# цифра. Здесь фраза сравнивается целиком: склеенные соседние слова против
# склейки «основа + числительное» для каждой машины.
KK_UNIT_NUMBERS = {
    1: ("бірге", "бірінші"),
    2: ("екіге", "екінші"),
    3: ("үшке", "үшінші"),
    4: ("төртке", "төртінші"),
    5: ("беске", "бесінші"),
}


def _extract_unit_by_sound(folded, original, vocabulary):
    tokens = re.findall(r"[а-яё]+", folded)
    windows = []
    for index, token in enumerate(tokens):
        if len(token) >= 6:
            windows.append((token, (token,)))
        if index + 1 < len(tokens):
            windows.append((token + tokens[index + 1], (token, tokens[index + 1])))

    # Лучшее расстояние на каждую машину. Цели складываются через fold, как и
    # сама фраза: без этого казахская «і» в «екіге» спорила бы с русской «и»
    # из расшифровки и раздувала расстояние на ровном месте.
    per_unit = {}
    for stem, units in vocabulary.items():
        for number, unit in units.items():
            for numword in KK_UNIT_NUMBERS.get(number, ()):
                target = speech_kk.fold(stem + numword)
                for joined, used in windows:
                    if joined == stem:
                        continue  # голая основа без номера машину не называет
                    distance = speech_kk._distance(joined, target)
                    ratio = distance / len(target)
                    key = unit.pk
                    if key not in per_unit or distance < per_unit[key][0]:
                        per_unit[key] = (distance, ratio, unit, used)

    ranked = sorted(per_unit.values(), key=lambda row: (row[0], row[1]))
    # Порог 0.30 подобран на настоящих записях со стенда: «шкафішкі» до
    # «шкафүшке» - 0.22, «миксерегілген» до «миксерекіге» - 0.27.
    if not ranked or ranked[0][1] > 0.30:
        return "", "", original, ""
    # Ничья между разными машинами - отказ, а не выбор первой попавшейся:
    # «формовщики где» одинаково близко к первому и второму формовщику, и
    # угадывать здесь значит увозить партию не туда. Переспросить дешевле.
    # Принимаем, когда лучший заметно лучше второго: либо на два шага по
    # расстоянию, либо второй сам за пределами доверия.
    if len(ranked) > 1:
        gap_ok = ranked[1][0] - ranked[0][0] >= 2
        runner_far = ranked[0][1] <= 0.28 and ranked[1][1] >= 0.35
        if not (gap_ok or runner_far):
            return "", "", original, ""
    _, _, unit, used = ranked[0]
    rest = folded
    for token in used:
        rest = re.sub(r"\b%s\b" % re.escape(token), " ", rest, count=1)
    return unit.name, unit.stage.code, rest, ""


def resolve_unit(name, stage):
    if not name or stage is None:
        return None
    return ProductionUnit.objects.filter(stage=stage, name=name, is_active=True).first()


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
        # Номер сверх сотни выглядит как «А1», а в базе лежит числом. Пробуем
        # его первым и только для значений от ста: _squash оставляет от «А1»
        # одну единицу - кириллица в нём не выживает, - и поиск уходил к
        # партии номер 01. Ниже сотни разбирать нечего, а «Б1» рискует быть
        # техническим номером партии, поэтому там всё идёт прежним путём.
        lettered = parse_daily_number(number)
        if lettered is not None and lettered >= 100:
            visible = (
                ProductionBatch.objects.select_related("current_stage", "order_item__order")
                .filter(daily_card_number=lettered)
                .exclude(status__in=["completed", "cancelled"])
                .order_by("-card_number_date", "id")
                .first()
            )
            if visible:
                return visible

        wanted_digits = _squash(number)
        if wanted_digits.isdigit():
            # The number printed on the Kanban card is scoped to a production
            # day and shared by all product rows in a grouped party. Prefer the
            # newest active day, then return one representative row; command
            # execution expands it back to the whole grouped party.
            visible = (
                ProductionBatch.objects.select_related("current_stage", "order_item__order")
                .filter(daily_card_number=int(wanted_digits))
                .exclude(status__in=["completed", "cancelled"])
                .order_by("-card_number_date", "id")
                .first()
            )
            if visible:
                return visible
        batch = ProductionBatch.objects.select_related("current_stage").filter(
            batch_number__iexact=number
        ).first()
        if batch:
            return batch
        # Whisper writes "B107" as often as "B-107", and an exact match then
        # fails on a command that was spoken perfectly. Compare the way it
        # sounds instead: letters and digits only.
        wanted = _squash(number)
        active_candidates = ProductionBatch.objects.select_related("current_stage").exclude(
            status__in=["completed", "cancelled"]
        )
        if wanted:
            if wanted.isdigit():
                # Spoken Kazakh often drops the letter entirely - the operator
                # says the digits and nothing else. Digits alone are not enough
                # to identify a batch when B-154 and D-154 can both exist, so
                # this only answers when exactly one batch in flight ends with
                # them.
                matches = [
                    candidate
                    for candidate in active_candidates
                    if _squash(candidate.batch_number).endswith(wanted)
                    or _squash(candidate.short_batch_number).endswith(wanted)
                ]
                if len(matches) == 1:
                    return matches[0]
            else:
                for candidate in active_candidates:
                    short = _squash(candidate.short_batch_number)
                    prefix_short = f"{_squash(candidate.batch_number)[:1]}{short}" if short else ""
                    if _squash(candidate.batch_number) == wanted or short == wanted or prefix_short == wanted:
                        return candidate

    order_number = (data.get("order_number") or "").strip()
    if not order_number:
        return None
    active = ProductionBatch.objects.select_related("current_stage").filter(
        order_item__order__order_number__iendswith=order_number
    ).exclude(status__in=["completed", "cancelled"])
    return active.first() if active.count() == 1 else None


def create_voice_command(voice):
    try:
        existing = voice.command
    except VoiceCommand.DoesNotExist:
        existing = None
    if existing and existing.status in {VoiceCommand.Status.EXECUTED, VoiceCommand.Status.REJECTED}:
        return existing
    parsed = parse_voice_command(voice.transcript, voice.confidence)

    # На заводе говорят подряд, не отпуская кнопку: «339 на формовку, 348 на
    # формовку». Разбор брал первый номер с последним этапом - выполнял то,
    # чего не говорили, и терял вторую партию молча. Теперь одна команда несёт
    # все переходы: сказано одним нажатием - подтверждается одним нажатием.
    #
    # Не отдельные записи на каждый переход: связь с сообщением один-к-одному,
    # и разводить её ради этого значит менять схему живой базы.
    prepared = speech_kk.prepare(voice.transcript or "")
    chunks = split_commands(prepared)
    parsed["moves"] = []
    if len(chunks) > 1:
        for chunk in chunks:
            piece = parse_voice_command(chunk, voice.confidence)
            found = resolve_batch(piece)
            parsed["moves"].append({
                "spoken": piece.get("batch_number", ""),
                "batch_number": found.batch_number if found else "",
                "display_batch_number": found.display_batch_label if found else "",
                "to_stage": piece.get("to_stage", ""),
                "resolved": bool(found),
            })
        # Ведущей остаётся первая: на ней держатся все проверки ниже.
        parsed.update({k: v for k, v in parse_voice_command(chunks[0], voice.confidence).items()
                       if k != "moves"})

    batch = resolve_batch(parsed)
    if batch:
        parsed["spoken_batch_number"] = parsed.get("batch_number", "")
        parsed["batch_number"] = batch.batch_number
        # Карточка подтверждения показывает display_batch_number: оператор
        # назвал двузначный номер и должен увидеть его же, а не технический,
        # которым партию не называет никто. Технический остаётся рядом - на нём
        # держится сверка в confirm_voice_command.
        parsed["display_batch_number"] = batch.display_batch_label
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
    # Kazakh letters down to their Russian lookalikes once, here, so every
    # pattern and every dictionary below needs a single spelling. Russian text
    # contains none of those letters and passes through unchanged.
    normalized = speech_kk.fold(normalized)

    directive = DIRECTIVE_RE.search(normalized)
    if directive:
        code = stage_from_word(directive.group(1))
        if code:
            return code

    for phrase, code in NEXT_BY_PHRASE.items():
        if phrase in normalized:
            return code

    for pattern in (COMPLETED_RE, KK_COMPLETED_RE):
        completed = pattern.search(normalized)
        if completed:
            code = stage_from_word(completed.group(1))
            if code in STAGE_ORDER:
                index = STAGE_ORDER.index(code)
                if index + 1 < len(STAGE_ORDER):
                    return STAGE_ORDER[index + 1]

    # Last one wins - but last in the sentence, not last in this dictionary.
    # Kazakh leans on this branch far more than Russian does, because the
    # destination is carried by the ending rather than by a verb: "формовкаға"
    # *is* the instruction. In "замес бітті, формовкаға" both stages appear, and
    # only word order says which one the batch is going to.
    found = ""
    rightmost = -1
    for part, code in STAGE_ALIASES.items():
        position = normalized.rfind(part)
        if position > rightmost:
            rightmost = position
            found = code
    if found:
        return found

    # Ничего не совпало буквально. Распознаватель пишет то, что услышал, и
    # «расстойка» приходит как «ростойкова» - дописывать каждый такой вариант
    # в таблицу бесполезно, список не кончится. Последняя попытка - ближайшее
    # по написанию, с порогом, за которым уже начинаются ложные срабатывания.
    return speech_kk.stage_by_sound(normalized)


def split_commands(text):
    """Одна запись - сколько угодно команд.

    На заводе говорят подряд, не отпуская кнопку: «339 на формовку, 348 на
    формовку». Разбор рассчитан на одну команду и брал первый номер с последним
    этапом - то есть выполнял то, чего не говорили, и терял вторую партию
    молча.

    Режем по номерам: каждый номер начинает свою команду и забирает всё до
    следующего. Номер - это то, что уже приведено к цифрам speech_kk.prepare(),
    так что резать можно по ним, не разбирая язык заново.

    Одна команда возвращается как есть - список из одного куска. Тогда всё, что
    ниже по течению, не обязано знать, был ли текст разбит.
    """
    if not text:
        return []

    # Позиции чисел длиной от двух цифр: одиночная цифра слишком часто бывает
    # частью слова или количеством, а не номером партии.
    starts = [m.start() for m in re.finditer(r"\d{2,}", text)]
    if len(starts) < 2:
        return [text]

    parts = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(text)
        chunk = text[start:end].strip(" ,.;")
        if chunk:
            parts.append(chunk)

    # Кусок без этапа - это не команда, а хвост предыдущей: «339 и 348 на
    # формовку» не два приказа, а один на две партии. Такое не угадываем и
    # возвращаем текст целиком, чтобы человек подтвердил сам.
    if any(not resolve_target_stage(speech_kk.fold(part)) for part in parts):
        return [text]
    return parts


def parse_voice_command(text, confidence=None):
    # Kazakh arrives with the batch number spelled out - "бір бес төрт" - and
    # the prefix letter in Cyrillic, because speech carries no alphabet. Both
    # are rewritten before anything below goes looking for a batch. Russian
    # transcripts pass through this untouched.
    text = speech_kk.prepare(text)
    # Устройство вынимается первым: его номер - такая же цифра, как номер
    # партии, и оставленный в строке он спорил бы с ней за первое совпадение.
    unit_name, unit_stage, text_without_unit, unit_problem = extract_unit(text)
    normalized = text.lower().replace("№", " ")
    batch_match = re.search(
    r"\b(?:парт(?:ия|ию|ии)\s*[№#]?\s*)?((?:DEMO[-\s]?)?[BD][-\s]?\d+(?:-\d+)?(?:-\d+)?|\d+)\b",
    text_without_unit,
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
    to_stage = resolve_target_stage(normalized) or unit_stage
    folded = speech_kk.fold(normalized)
    if "пауз" in folded or "останов" in folded or _said(folded, "pause"):
        intent = VoiceCommand.Intent.PAUSE_BATCH
    elif "возобнов" in folded or "продолж" in folded or _said(folded, "resume"):
        intent = VoiceCommand.Intent.RESUME_BATCH
    elif (
        "проблем" in folded
        or "обнаруж" in folded
        # Корень, а не «подгора»: партия женского рода, и в цеху говорят
        # «подгорела». Прежняя форма ловила «подгорает» и «подгорание» - то
        # есть всё, кроме того, что произносят на самом деле.
        or "подгор" in folded
        or _said(folded, "problem")
    ):
        intent = VoiceCommand.Intent.CREATE_PROBLEM
    elif to_stage == "warehouse":
        intent = VoiceCommand.Intent.ACCEPT_TO_WAREHOUSE
    elif to_stage == "done":
        intent = VoiceCommand.Intent.COMPLETE_BATCH
    elif "коммент" in folded or _said(folded, "comment"):
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
        "unit": unit_name,
        "unit_problem": unit_problem,
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
    command.extracted_data["display_batch_number"] = batch.display_batch_label
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
        if data.get("unit_problem"):
            # Устройство названо, но не опознано. Перевести партию на этап и
            # бросить её нераспределённой - это выполнить половину команды и
            # промолчать про вторую; отказ честнее.
            raise ValidationError(data["unit_problem"])
        spoken_unit = data.get("unit") or ""
        # «Партия 3 на печь 2», сказанная про партию, которая уже в печи, - это
        # распределение, а не перевод. Звать move_batch на свой же этап значит
        # получить отказ «партия уже находится на этом этапе» на команду,
        # которая совершенно осмысленна.
        if spoken_unit and batch.current_stage_id == target.pk:
            unit = resolve_unit(spoken_unit, target)
            if unit is None:
                raise ValidationError(f"«{spoken_unit}» не найдено на этапе {target.name}.")
            assign_batch_to_unit(batch, unit, user, data.get("comment", ""))
            command.extracted_data["unit"] = unit.name
            command.status = VoiceCommand.Status.EXECUTED
            command.confirmed_by = user
            command.executed_at = timezone.now()
            command.extracted_data["from_stage"] = expected_stage
            command.save(update_fields=["status", "confirmed_by", "executed_at", "extracted_data", "updated_at"])
            write_audit("voice_command_executed", command, user=user, changes=command.extracted_data)
            return command
        # allow_skip: spoken orders name a destination, not a step. "B-102
        # закончил замес, отправить в склад" is a legitimate thing to say, and
        # refusing it because Склад is four stages away helps nobody. The jump is
        # recorded as such, and move_batch still demands a comment for it.
        movement_batches = [batch]
        if batch.order_item.order.kanban_grouped:
            movement_batches = list(
                ProductionBatch.objects.select_for_update()
                .select_related("current_stage", "order_item__order")
                .filter(
                    order_item__order=batch.order_item.order,
                    current_stage_id=batch.current_stage_id,
                )
                .exclude(status__in=[ProductionBatch.Status.COMPLETED, ProductionBatch.Status.CANCELLED])
                .order_by("pk")
            )
        moved = []
        for movement_batch in movement_batches:
            moved.append(move_batch(
                movement_batch,
                target,
                user,
                data.get("comment", ""),
                require_comment=target.sequence < movement_batch.current_stage.sequence,
                allow_skip=True,
            ))
        if spoken_unit:
            unit = resolve_unit(spoken_unit, target)
            if unit is None:
                raise ValidationError(f"«{spoken_unit}» не найдено на этапе {target.name}.")
            # Именно moved[0], а не batch: move_batch возвращает перечитанную
            # партию, а у переданной этап остался прежним.
            assign_batch_to_unit(moved[0], unit, user, data.get("comment", ""))
            command.extracted_data["unit"] = unit.name

        # Остальные партии из той же фразы. Первая уже переведена выше; здесь
        # идут те, что были названы следом. Каждая своим переходом - если одна
        # из них заблокирована, остальные всё равно доедут, а отказ вернётся
        # человеку списком.
        refused = []
        for extra in (data.get("moves") or [])[1:]:
            other = ProductionBatch.objects.filter(batch_number=extra.get("batch_number") or "").first()
            stage = ProductionStage.objects.filter(code=extra.get("to_stage") or "").first()
            if not other or not stage:
                refused.append(extra.get("spoken") or "?")
                continue
            try:
                move_batch(other, stage, user, data.get("comment", ""),
                           require_comment=stage.sequence < other.current_stage.sequence,
                           allow_skip=True)
            except (ValidationError, ConflictError) as exc:
                refused.append(f"{other.display_batch_label}: {exc}")
        if refused:
            raise ValidationError("Часть партий не переведена — " + "; ".join(refused))
    elif intent == VoiceCommand.Intent.PAUSE_BATCH:
        pause_batch(batch, user, data.get("comment", ""))
    elif intent == VoiceCommand.Intent.RESUME_BATCH:
        resume_batch(batch, user, data.get("comment", ""))
    elif intent == VoiceCommand.Intent.CREATE_PROBLEM:
        create_problem_from_voice(batch, user, data.get("comment", ""))
        notify(batch.assigned_to or user, "Создана проблема по голосовой команде", f"Партия {batch.display_batch_label}", "voice_problem", reverse("bakery:batch_detail", args=[batch.pk]))
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
    # unique_number держится за технический номер - он и должен быть уникальным
    # навсегда, а видимый повторяется каждый день. Человеку карточка показывает
    # поле batch_number, туда и кладём номер, которым партию называют в цеху.
    qobj, _ = QualityObject.objects.get_or_create(unique_number=f"VOICE-{batch.batch_number}", defaults={"object_type": "finished_product", "product_name": batch.product.name, "batch_number": batch.display_batch_label, "quantity": 1, "department": dept, "created_by": user})
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
