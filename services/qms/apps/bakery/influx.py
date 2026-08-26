"""Поток производственных событий в общий InfluxDB (influx.digitalegiz.kz).

Телеметрия счётчиков попадает туда своим путём - от устройств через MQTT и
Telegraf. Производственной части в общей базе не было вовсе: движения партий
уходили только в Ditto, на 3D-сцену локальной Grafana стенда. Этот модуль
дописывает второй поток - каждое движение партии становится точкой, и общая
Grafana строит по ним что угодно рядом с киловаттами тех же машин.

Точка - это переход партии на этап:

    qms_batch_event,stage=oven,product=BAG-01,unit=Печь\\ 3,
        thingId=digitalegiz:ESP32_Dala_Meter_001994
        batch="03 от 24.08.2026",case_id="B-1165",order="0384",
        quantity=50,from_stage="proofing" 1756012800000000000

Теги - только малочисленные значения: код этапа, код продукта, имя машины и
её thingId. Номера партий и заказов - поля: серия на каждую партию раздула бы
базу. thingId - тот же тег, которым помечена телеметрия счётчиков, и это
единственное место, где два потока сходятся: по нему панель кладёт продукт с
машины рядом с её киловаттами.

Доставка нарочно негарантированная, как у Ditto: Influx - витрина, а не
источник истины. Запись уходит после коммита, в фоновом потоке, с коротким
таймаутом; любая ошибка - строка в логе, а не сломанное перемещение. Дыра
лечится командой `manage.py sync_influx`, переливающей историю целиком, -
точки идемпотентны по (тегам, времени), и перелить их дважды не страшно.
"""

import logging
import threading
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

logger = logging.getLogger(__name__)


def influx_enabled():
    return bool(
        settings.INFLUX_ENABLED and settings.INFLUX_URL and settings.INFLUX_TOKEN
    )


# --------------------------------------------------------------------------
# Line protocol: экранирование по правилам Influx
# --------------------------------------------------------------------------

def _tag(value):
    """Значение тега: запятая, пробел и равно экранируются обратной косой."""
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace(",", "\\,")
        .replace(" ", "\\ ")
        .replace("=", "\\=")
    )


def _field_str(value):
    """Строковое поле: в кавычках, кавычка и косая экранированы."""
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def history_point(history):
    """Одна строка line protocol из одной записи истории этапов.

    Время - момент перевода, с точностью до наносекунд: у двух переводов в
    одну и ту же секунду разные микросекунды, и точки не затирают друг друга.
    """
    batch = history.batch
    product = batch.product
    unit = batch.production_unit

    tags = [("stage", history.to_stage.code)]
    if history.from_stage:
        tags.append(("from", history.from_stage.code))
    if product and product.code:
        tags.append(("product", product.code))
    if unit:
        tags.append(("unit", unit.name))
        # Единственный ключ, по которому производственная точка сходится с
        # киловаттами той же машины: телеметрия счётчиков приходит от Telegraf
        # с тегом `thingId`, и имя машины ей неизвестно. Отсюда и написание -
        # camelCase, как у телеметрии: join в Flux сводит колонки по имени, и
        # `thing_id` пришлось бы переименовывать в каждой панели. Машин
        # столько же, сколько имён в теге `unit`, так что серий не прибавится.
        if unit.twin_id:
            tags.append(("thingId", unit.twin_id))

    fields = [
        ("batch", _field_str(batch.display_batch_label)),
        ("case_id", _field_str(batch.batch_number)),
        ("stage_name", _field_str(history.to_stage.name)),
    ]
    if product:
        fields.append(("product_name", _field_str(product.name)))
    order = batch.order_item.order if batch.order_item else None
    if order:
        fields.append(("order", _field_str(order.order_number)))
    if batch.planned_quantity is not None:
        fields.append(("quantity", f"{float(batch.planned_quantity):g}"))

    tag_part = ",".join(f"{key}={_tag(value)}" for key, value in tags)
    field_part = ",".join(f"{key}={value}" for key, value in fields)
    stamp = int(history.created_at.timestamp() * 1_000_000_000)
    return f"qms_batch_event,{tag_part} {field_part} {stamp}"


def unit_state_point(unit, at=None):
    """Одна строка line protocol - что на машине стоит прямо сейчас.

    Второе измерение рядом с историей, и заведено оно ради панели. По
    `qms_batch_event` вопрос «что на печи сейчас» отвечается кружным путём:
    взять окно пошире, сгруппировать по машине, взять последнюю точку в каждой
    группе и не забыть, что ответ - это «что было в последний раз», а не
    «сейчас». Свободная печь при этом продолжает показывать вчерашний хлеб,
    потому что события «партия ушла» в истории переводов просто нет.

    Здесь всё это уже сделано: одна точка на машину, переписывается при каждом
    движении доски, свободная машина честно говорит «свободно». Запрос к ней -
    `filter` да `last()`, без окон и группировок.

    Теги - машина, этап и её `thingId`; значения - поля. `quantity_unit`
    назван не `unit` нарочно: тег и поле с одним именем Influx не различает.
    """
    from .twins import unit_product_value

    value = unit_product_value(unit)

    tags = [("unit", unit.name), ("stage", unit.stage.code)]
    if unit.twin_id:
        tags.append(("thingId", unit.twin_id))

    # Тип поля Influx фиксирует первой записью навсегда, поэтому количество -
    # всегда число, а пустота свободной машины - пустая строка, не пропуск.
    fields = [
        ("product", _field_str(value["product"])),
        ("quantity", f"{float(value['quantity']):g}"),
        ("quantity_unit", _field_str(value["unit"])),
        ("card", _field_str(value["card"])),
        ("order", _field_str(value["order"])),
        ("customer", _field_str(value["customer"])),
        ("status", _field_str(value["status"])),
        ("stage_name", _field_str(unit.stage.name)),
        ("started_at", _field_str(value["started_at"])),
    ]

    tag_part = ",".join(f"{key}={_tag(item)}" for key, item in tags)
    field_part = ",".join(f"{key}={item}" for key, item in fields)
    stamp = int((at or timezone.now()).timestamp() * 1_000_000_000)
    return f"qms_unit_state,{tag_part} {field_part} {stamp}"


# --------------------------------------------------------------------------
# Транспорт: POST /api/v2/write
# --------------------------------------------------------------------------

def write_lines(lines):
    """Отправить строки line protocol. True - принято.

    Ошибка - предупреждение в логе: витрина отстанет на точку, производство
    не заметит ничего.
    """
    if not lines:
        return True
    url = (
        f"{settings.INFLUX_URL.rstrip('/')}/api/v2/write"
        f"?org={urllib.parse.quote(settings.INFLUX_ORG)}"
        f"&bucket={urllib.parse.quote(settings.INFLUX_BUCKET)}"
        f"&precision=ns"
    )
    request = urllib.request.Request(
        url,
        data="\n".join(lines).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "text/plain; charset=utf-8",
            "Authorization": f"Token {settings.INFLUX_TOKEN}",
        },
    )
    try:
        with urllib.request.urlopen(
            request, timeout=settings.INFLUX_TIMEOUT_SECONDS
        ) as response:
            response.read()
        return True
    except urllib.error.HTTPError as exc:
        # Тело ответа Influx называет причину - без него в логе только код.
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:200]
        except OSError:
            pass
        logger.warning("Influx: запись отклонена (%s): %s", exc.code, detail)
        return False
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("Influx: запись не удалась: %s", exc)
        return False


def push_unit_states_by_id(unit_ids):
    from .models import ProductionUnit

    units = ProductionUnit.objects.select_related("stage").filter(pk__in=unit_ids)
    write_lines([unit_state_point(unit) for unit in units])


def push_history_by_id(history_ids):
    from .models import BatchStageHistory

    rows = (
        BatchStageHistory.objects.select_related(
            "batch__product",
            "batch__production_unit",
            "batch__order_item__order",
            "from_stage",
            "to_stage",
        )
        .filter(pk__in=history_ids)
    )
    write_lines([history_point(row) for row in rows])


# --------------------------------------------------------------------------
# Сигнал: партия перешла на этап - точка ушла
# --------------------------------------------------------------------------

@receiver(post_save, sender="bakery.BatchStageHistory")
def _push_after_transition(sender, instance, created, **kwargs):
    """История этапов пишется ровно в момент перевода - лучшей зацепки нет.

    Демо-партии не отправляются: общая витрина показывает завод, а не
    репетицию.
    """
    if not created or not influx_enabled():
        return
    if instance.batch.is_demo:
        return
    transaction.on_commit(
        lambda: threading.Thread(
            target=push_history_by_id, args=([instance.pk],), daemon=True
        ).start()
    )


# --------------------------------------------------------------------------
# Сигналы: доска шевельнулась - состояние машин переписано
# --------------------------------------------------------------------------

def schedule_state_sync(*unit_ids):
    ids = sorted({unit_id for unit_id in unit_ids if unit_id})
    if not ids or not influx_enabled():
        return
    transaction.on_commit(
        lambda: threading.Thread(
            target=push_unit_states_by_id, args=(ids,), daemon=True
        ).start()
    )


@receiver(pre_save, sender="bakery.ProductionBatch")
def _remember_previous_unit(sender, instance, **kwargs):
    # Партия, уходя с печи, обязана обновить и печь тоже - иначе покинутая
    # машина осталась бы занятой навсегда. После save() прежнего устройства в
    # строке уже нет, подсмотреть его можно только до.
    if not influx_enabled() or instance.pk is None:
        return
    instance._influx_previous_unit_id = (
        sender.objects.filter(pk=instance.pk)
        .values_list("production_unit_id", flat=True)
        .first()
    )


@receiver(post_save, sender="bakery.ProductionBatch")
def _push_state_after_save(sender, instance, **kwargs):
    if instance.is_demo:
        return
    schedule_state_sync(
        instance.production_unit_id, getattr(instance, "_influx_previous_unit_id", None)
    )


@receiver(post_delete, sender="bakery.ProductionBatch")
def _push_state_after_delete(sender, instance, **kwargs):
    if instance.is_demo:
        return
    schedule_state_sync(instance.production_unit_id)
