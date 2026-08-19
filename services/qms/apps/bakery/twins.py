"""Зеркало доски в цифровых двойниках оборудования (OpenTwins / Eclipse Ditto).

У каждого устройства цеха есть двойник в OpenTwins, и у двойника - фича
`product`. Этот модуль держит её в актуальном состоянии: как только партия
встала на печь, ушла с неё или сменила статус, в
`features/product/properties/value` двойника оказывается то, что печь делает
сейчас, - продукт, карточка, заказ, статус. Свободное устройство честно
говорит «свободно», а не показывает вчерашний хлеб.

Связь двух миров - поле ProductionUnit.twin_id: полный thingId двойника в
Ditto. Пустое поле означает «у устройства двойника нет», и такое устройство
модуль молча пропускает.

Доставка нарочно негарантированная: Ditto - витрина, а не источник истины.
Запись уходит после коммита, в фоновом потоке, с коротким таймаутом, и любая
ошибка - это строка в логе, а не сломанное перемещение партии. Пропущенное
обновление лечится командой `manage.py sync_twins`, которая переливает
текущее состояние всех устройств целиком.
"""

import base64
import json
import logging
import threading
import urllib.error
import urllib.request

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

logger = logging.getLogger(__name__)


def twins_enabled():
    return bool(settings.DITTO_ENABLED and settings.DITTO_BASE_URL)


# --------------------------------------------------------------------------
# Payload: что именно двойник рассказывает о своём устройстве
# --------------------------------------------------------------------------

def unit_occupants(unit):
    """Партии, стоящие на устройстве сейчас.

    Обычно одна, но сгруппированный заказ - это несколько строк ProductionBatch
    на одном устройстве, и двойник должен показать их все, а не первую попавшуюся.
    """
    from .models import ProductionBatch

    return list(
        ProductionBatch.objects.select_related("product", "current_stage", "order_item__order__customer")
        .filter(production_unit=unit)
        .exclude(status__in=[ProductionBatch.Status.COMPLETED, ProductionBatch.Status.CANCELLED])
        .order_by("pk")
    )


def unit_product_payload(unit):
    """Свойства фичи product двойника - плоские, как у measurements.

    Интерфейс OpenTwins печатает каждое свойство отдельной строкой с подписью,
    поэтому никаких вложенных объектов: только ключ и готовое к чтению
    значение. Пустые поля свободного устройства - прочерки, а не пропуски,
    чтобы карточка фичи не меняла форму от того, занята печь или нет.
    """
    now = timezone.localtime().strftime("%d.%m.%Y %H:%M")
    batches = unit_occupants(unit)
    if not batches:
        return {
            "product": "—",
            "quantity": "—",
            "card": "—",
            "order": "—",
            "customer": "—",
            "status": "свободно" if unit.is_available else unit.get_status_display(),
            "stage": unit.stage.name,
            "started_at": "—",
            "updated_at": now,
        }
    first = batches[0]
    order = first.order_item.order
    quantity = sum(float(batch.actual_quantity or batch.planned_quantity) for batch in batches)
    return {
        "product": ", ".join(batch.product.name for batch in batches),
        "quantity": f"{quantity:g} {first.unit}".strip(),
        "card": str(first.display_batch_number),
        "order": f"№{order.order_number}",
        "customer": order.customer.name if order.customer_id else "—",
        "status": first.get_status_display(),
        "stage": first.current_stage.name,
        "started_at": timezone.localtime(first.actual_start).strftime("%d.%m.%Y %H:%M") if first.actual_start else "—",
        "updated_at": now,
    }


# --------------------------------------------------------------------------
# Транспорт: PUT в Ditto
# --------------------------------------------------------------------------

def _put(url, payload):
    credentials = base64.b64encode(
        f"{settings.DITTO_USERNAME}:{settings.DITTO_PASSWORD}".encode()
    ).decode()
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode(),
        method="PUT",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Basic {credentials}",
        },
    )
    with urllib.request.urlopen(request, timeout=settings.DITTO_TIMEOUT_SECONDS) as response:
        response.read()


def put_feature_properties(thing_id, properties):
    """Записать свойства фичи product двойника целиком.

    Возвращает True при успехе. Ошибка сети или Ditto - предупреждение в логе:
    двойник отстанет от доски на одно обновление, а доска не заметит ничего.
    """
    base = f"{settings.DITTO_BASE_URL.rstrip('/')}/api/2/things/{thing_id}/features/product"
    try:
        try:
            _put(f"{base}/properties", properties)
        except urllib.error.HTTPError as exc:
            # 404 - у двойника ещё нет фичи product. Вложенный путь её не
            # создаёт, а PUT самой фичи - создаёт.
            if exc.code != 404:
                raise
            _put(base, {"properties": properties})
        return True
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("Ditto: не удалось обновить %s: %s", thing_id, exc)
        return False


def push_unit(unit):
    """Синхронно поднять состояние одного устройства в его двойник."""
    if not unit.twin_id:
        return False
    return put_feature_properties(unit.twin_id, unit_product_payload(unit))


def push_units_by_id(unit_ids):
    from .models import ProductionUnit

    for unit in ProductionUnit.objects.select_related("stage").filter(pk__in=unit_ids).exclude(twin_id=""):
        push_unit(unit)


# --------------------------------------------------------------------------
# Сигналы: доска шевельнулась - двойники узнали
# --------------------------------------------------------------------------

def schedule_sync(*unit_ids):
    """Отправить обновление устройств после коммита, не задерживая запрос.

    Поток на горсть PUT-ов дешевле, чем оператор, ждущий у перетащенной
    карточки, пока внешняя система ответит.
    """
    ids = sorted({unit_id for unit_id in unit_ids if unit_id})
    if not ids or not twins_enabled():
        return
    transaction.on_commit(
        lambda: threading.Thread(target=push_units_by_id, args=(ids,), daemon=True).start()
    )


@receiver(pre_save, sender="bakery.ProductionBatch")
def _remember_previous_unit(sender, instance, **kwargs):
    # Партия, уходя с печи, должна обновить и печь тоже - но после save()
    # прежнего устройства в строке уже нет. Подсмотреть его можно только до.
    if not twins_enabled() or instance.pk is None:
        return
    instance._twin_previous_unit_id = (
        sender.objects.filter(pk=instance.pk).values_list("production_unit_id", flat=True).first()
    )


@receiver(post_save, sender="bakery.ProductionBatch")
def _sync_after_save(sender, instance, **kwargs):
    schedule_sync(instance.production_unit_id, getattr(instance, "_twin_previous_unit_id", None))


@receiver(post_delete, sender="bakery.ProductionBatch")
def _sync_after_delete(sender, instance, **kwargs):
    schedule_sync(instance.production_unit_id)
