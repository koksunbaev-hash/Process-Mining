from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max
from django.urls import reverse
from django.utils import timezone

from apps.notifications.services import notify
from apps.process_mining.services import process_event_for_batch_transition, safe_record_process_event

from .models import (
    BatchStageHistory,
    FinishedGoodsStock,
    OrderEvent,
    ProductionBatch,
    ProductionOrder,
    ProductionOrderItem,
    ProductionStage,
    ProductionUnit,
    stock_expiration_for,
)
from .permissions import can_move_batch


def log_order_event(order, message, event_type="info", user=None, batch=None):
    return OrderEvent.objects.create(order=order, batch=batch, event_type=event_type, message=message, created_by=user)


# Партия ушла с доски - её число снова свободно. Всё остальное занято:
# завершённую и отменённую смена уже не ищет, а любую другую может.
CLOSED_BATCH_STATUSES = ("completed", "cancelled")


def numbers_busy_on_board(exclude_date=None, exclude_order=None):
    """Числа, занятые незакрытыми партиями других дней.

    Именно других: внутри одного дня порядок и так возрастающий, а вот
    вчерашняя партия, не дошедшая до «Готово», честно держит своё число -
    оно написано мелом на её тележке.
    """
    rows = (
        ProductionBatch.objects.exclude(status__in=CLOSED_BATCH_STATUSES)
        .exclude(daily_card_number=None)
        .exclude(is_demo=True)
    )
    if exclude_date is not None:
        rows = rows.exclude(card_number_date=exclude_date)
    if exclude_order is not None:
        rows = rows.exclude(order_item__order=exclude_order)
    return set(rows.values_list("daily_card_number", flat=True))


def next_free_number(current, busy):
    """Следующее число, которого нет на доске."""
    candidate = current + 1
    while candidate in busy:
        candidate += 1
    return candidate


def assign_daily_batch_number(order):
    """Give one visible production-party number to the whole order block.

    The technical ProductionBatch rows remain unique process-mining cases, but
    operators see one short number shared by every product in the block.
    Numbering restarts for each production date.
    """
    if order.is_demo:
        return None
    production_date = timezone.localtime(order.required_date).date()
    if order.batch_number_date == production_date and order.daily_batch_number is not None:
        return order.daily_batch_number

    current = (
        ProductionOrder.objects.select_for_update()
        .filter(batch_number_date=production_date)
        .aggregate(value=Max("daily_batch_number"))["value"]
        or 0
    )
    candidate = current + 1
    while ProductionOrder.objects.filter(
        batch_number_date=production_date,
        daily_batch_number=candidate,
    ).exists():
        candidate += 1
    order.batch_number_date = production_date
    order.daily_batch_number = candidate
    order.save(update_fields=["batch_number_date", "daily_batch_number", "updated_at"])
    return candidate


def assign_batch_card_numbers(order, batches):
    """Assign visible daily numbers to Kanban cards.

    A grouped production party shares one number across its technical product
    rows. Ordinary batches receive separate numbers even if they happen to
    belong to the same historical order.
    """
    if order.is_demo or not batches:
        return
    production_date = timezone.localtime(order.required_date).date()
    if all(
        batch.card_number_date == production_date and batch.daily_card_number is not None
        for batch in batches
    ):
        return
    # Ряд дня общий для карточек и для заказов: номер заказа - это номер его
    # первой карточки, а на паре (дата, номер) заказа висит уникальный индекс.
    # Считать максимум только по карточкам мало: заказ, подтверждённый без
    # позиций, успевает занять номер из assign_daily_batch_number, до которого
    # карточки ещё не дошли, и следующий же заказ упёрся бы в него.
    current = max(
        ProductionBatch.objects.select_for_update()
        .filter(card_number_date=production_date)
        .aggregate(value=Max("daily_card_number"))["value"]
        or 0,
        ProductionOrder.objects.exclude(pk=order.pk)
        .filter(batch_number_date=production_date)
        .aggregate(value=Max("daily_batch_number"))["value"]
        or 0,
    )
    # Числа, которые держат незакрытые партии прошлых дней. Свой заказ
    # исключаем: его собственные карточки сейчас как раз перенумеровываются.
    busy = numbers_busy_on_board(exclude_date=production_date, exclude_order=order)

    first_number = None
    if order.kanban_grouped:
        current = next_free_number(current, busy)
        for batch in batches:
            batch.daily_card_number = current
            batch.card_number_date = production_date
            batch.save(update_fields=["daily_card_number", "card_number_date", "updated_at"])
        first_number = current
    else:
        for batch in batches:
            current = next_free_number(current, busy)
            batch.daily_card_number = current
            batch.card_number_date = production_date
            batch.save(update_fields=["daily_card_number", "card_number_date", "updated_at"])
            first_number = first_number or current
    order.daily_batch_number = first_number
    order.batch_number_date = production_date
    order.save(update_fields=["daily_batch_number", "batch_number_date", "updated_at"])


def block_batches(batch):
    """Строки, которые едут вместе с этой партией.

    Сгруппированный заказ показан на доске одной карточкой, и устройство он
    занимает тоже одно - значит и ставить на устройство его надо целиком.
    Обычная партия отвечает сама за себя.
    """
    if not batch.order_item.order.kanban_grouped:
        return [batch]
    return list(
        ProductionBatch.objects.select_related("current_stage", "order_item__order")
        .filter(order_item__order_id=batch.order_item.order_id, current_stage_id=batch.current_stage_id)
        .exclude(status__in=[ProductionBatch.Status.COMPLETED, ProductionBatch.Status.CANCELLED])
        .order_by("pk")
    )


def unit_occupant(unit, exclude_order_id=None):
    """Карточка, которая сейчас стоит на устройстве, или None.

    Завершённые и отменённые не в счёт: они устройство уже отпустили, а строка
    с ссылкой остаётся ради истории.
    """
    qs = (
        ProductionBatch.objects.select_related("order_item__order", "product")
        .filter(production_unit=unit)
        .exclude(status__in=[ProductionBatch.Status.COMPLETED, ProductionBatch.Status.CANCELLED])
    )
    if exclude_order_id is not None:
        qs = qs.exclude(order_item__order_id=exclude_order_id)
    return qs.first()


@transaction.atomic
def assign_batch_to_unit(batch, unit, user=None, comment=""):
    """Поставить партию на устройство. unit=None - снять в «Не распределено».

    Занятость проверяется здесь, а не ограничением базы: сгруппированный блок -
    это несколько строк ProductionBatch на одном устройстве, и уникальный
    индекс по колонке запретил бы ровно тот случай, ради которого группировка
    и сделана. select_for_update закрывает гонку двух операторов, потянувшихся
    к одной печи.
    """
    order_id = batch.order_item.order_id
    # Снять партию с устройства - такое же распоряжение её судьбой, как
    # поставить: проверка прав общая для обоих направлений, иначе печь мог бы
    # освободить кто угодно.
    if not can_move_batch(user, batch.current_stage.code):
        raise PermissionDenied("Нет права распределять партии на этом этапе.")
    if unit is not None:
        if unit.stage_id != batch.current_stage_id:
            raise ValidationError(
                f"«{unit.name}» стоит на этапе {unit.stage.name}, а партия на этапе {batch.current_stage.name}."
            )
        if not unit.is_available:
            raise ValidationError(f"«{unit.name}» сейчас недоступно: {unit.get_status_display()}.")
        # Блокируем устройство, а не партию: спор идёт за место, и второй
        # оператор должен дождаться первого именно здесь.
        ProductionUnit.objects.select_for_update().filter(pk=unit.pk).first()
        taken = unit_occupant(unit, exclude_order_id=order_id)
        if taken is not None:
            raise ValidationError(f"«{unit.name}» занято: партия {taken.display_batch_number}.")

    rows = block_batches(batch)
    previous = next((row.production_unit for row in rows if row.production_unit_id), None)
    if previous is not None and unit is not None and previous.pk == unit.pk:
        return unit
    for row in rows:
        row.production_unit = unit
        row.save(update_fields=["production_unit", "updated_at"])
    batch.production_unit = unit

    order = batch.order_item.order
    if unit is None:
        message = f"Партия {batch.display_batch_label} снята с «{previous.name}»." if previous else None
    elif previous is not None:
        message = f"Партия {batch.display_batch_label}: «{previous.name}» -> «{unit.name}»."
    else:
        message = f"Партия {batch.display_batch_label} поставлена на «{unit.name}»."
    if message:
        log_order_event(order, f"{message} {comment}".strip(), "unit_assigned", user=user, batch=batch)
        safe_record_process_event(
            case_id=batch.batch_number,
            case_type="batch",
            activity="Распределение на устройство",
            batch=batch,
            user=user,
            from_stage=batch.current_stage.code,
            to_stage=batch.current_stage.code,
            status=batch.status,
            quantity=batch.actual_quantity or batch.planned_quantity,
            unit=batch.unit,
            # Ресурс - то, чем событие ценно для аналитики: без него в логе
            # видно «партия побывала на этапе Печь», но не видно, что печей
            # пять и загружены они неравномерно.
            resource=unit.name if unit else "",
            event_data={"unit": unit.name if unit else "", "previous_unit": previous.name if previous else ""},
        )
    return unit


def free_units_for_stage(stage):
    """Свободные устройства этапа, в порядке их номеров."""
    busy = set(
        ProductionBatch.objects.filter(production_unit__stage=stage)
        .exclude(status__in=[ProductionBatch.Status.COMPLETED, ProductionBatch.Status.CANCELLED])
        .values_list("production_unit_id", flat=True)
    )
    return [
        unit
        for unit in ProductionUnit.objects.filter(stage=stage, is_active=True, status=ProductionUnit.Status.AVAILABLE)
        if unit.pk not in busy
    ]


@transaction.atomic
def repeat_order_for_next_week(source_order, quantities, user):
    source_items = list(
        source_order.items.select_related("product", "recipe")
    )

    if not source_items:
        raise ValidationError("В исходном заказе нет продукции.")

    new_order = ProductionOrder.objects.create(
        customer=source_order.customer,
        order_date=source_order.order_date + timedelta(days=7),
        required_date=source_order.required_date + timedelta(days=7),
        priority=source_order.priority,
        status=ProductionOrder.Status.DRAFT,
        notes=f"Повтор заказа №{source_order.order_number}. {source_order.notes}".strip(),
        created_by=user,
        is_demo=False,
    )

    new_items = []

    for source_item in source_items:
        quantity = quantities.get(source_item.pk)

        if quantity is None or quantity <= 0:
            raise ValidationError(
                f"Укажите корректное количество для продукта "
                f"«{source_item.product.name}»."
            )

        new_items.append(
            ProductionOrderItem(
                order=new_order,
                product=source_item.product,
                quantity=quantity,
                unit=source_item.unit,
                recipe=source_item.recipe,
                notes=source_item.notes,
                is_demo=False,
            )
        )

    ProductionOrderItem.objects.bulk_create(new_items)

    log_order_event(
        new_order,
        f"План повторён на основе заказа №{source_order.order_number}.",
        "order_repeated",
        user=user,
    )

    safe_record_process_event(
        case_id=f"ORDER-{new_order.order_number}",
        case_type="order",
        activity="Повторение производственного плана",
        order=new_order,
        user=user,
        status=new_order.status,
        event_data={
            "source_order_id": source_order.pk,
            "source_order_number": source_order.order_number,
            "shift_days": 7,
        },
    )

    return new_order


@transaction.atomic
def confirm_order(order, user=None, assignee=None):
    queue = ProductionStage.objects.get(code="queue")
    assign_daily_batch_number(order)
    order.status = ProductionOrder.Status.QUEUED
    order.save(update_fields=["status", "updated_at"])
    log_order_event(order, "Заказ подтверждён, партии созданы.", "order_confirmed", user=user)
    safe_record_process_event(
        case_id=f"ORDER-{order.order_number}",
        case_type="order",
        activity="Подтверждение заказа",
        order=order,
        user=user,
        status=order.status,
        event_data={"order_number": order.order_number},
    )
    batches = []
    created_batches = []
    for item in order.items.select_related("product", "recipe"):
        recipe = item.recipe or item.product.recipes.filter(is_active=True).first()
        batch, created = ProductionBatch.objects.get_or_create(
            order_item=item,
            defaults={
                "product": item.product,
                "recipe": recipe,
                "planned_quantity": item.quantity,
                "unit": item.unit,
                "current_stage": queue,
                "status": ProductionBatch.Status.QUEUED,
                "assigned_to": assignee or user,
                "actual_start": timezone.now(),
            },
        )
        batches.append(batch)
        if created:
            created_batches.append(batch)

    # Номера раздаются до первой записи в историю и до уведомлений: и то и
    # другое называет партию так, как её называют в цеху, а до этой строки
    # видимого номера у партии ещё нет.
    assign_batch_card_numbers(order, batches)

    for batch in created_batches:
        BatchStageHistory.objects.create(batch=batch, to_stage=queue, changed_by=user, comment="Партия поступила в очередь.")
        log_order_event(order, f"Партия {batch.display_batch_label} поступила в очередь.", "batch_queued", user=user, batch=batch)
        safe_record_process_event(
            case_id=batch.batch_number,
            case_type="batch",
            activity="Создание производственной партии",
            batch=batch,
            user=user,
            to_stage=queue.code,
            status=batch.status,
            quantity=batch.planned_quantity,
            unit=batch.unit,
        )
        safe_record_process_event(
            case_id=batch.batch_number,
            case_type="batch",
            activity="Партия поступила в очередь",
            batch=batch,
            user=user,
            to_stage=queue.code,
            status=batch.status,
            quantity=batch.planned_quantity,
            unit=batch.unit,
        )
        if batch.assigned_to and not batch.is_demo:
            notify(batch.assigned_to, "Партия поступила в очередь", f"Партия {batch.display_batch_label}", "batch_queued", reverse("bakery:batch_detail", args=[batch.pk]))
    return batches


def next_stage_for(batch):
    if not batch.current_stage_id:
        return None
    return ProductionStage.objects.filter(sequence__gt=batch.current_stage.sequence, is_active=True).order_by("sequence").first()


def previous_stage_for(batch):
    if not batch.current_stage_id:
        return None
    return ProductionStage.objects.filter(sequence__lt=batch.current_stage.sequence, is_active=True).order_by("-sequence").first()


def skipped_stages_between(from_stage, to_stage):
    """Active stages a jump would step over. Empty for an adjacent move."""
    low, high = sorted([from_stage.sequence, to_stage.sequence])
    return list(
        ProductionStage.objects.filter(sequence__gt=low, sequence__lt=high, is_active=True).order_by("sequence")
    )


@transaction.atomic
def move_batch(batch, to_stage, user, comment="", require_comment=False, allow_skip=False):
    """allow_skip lets a batch go straight to any stage instead of the next one.

    Off by default, so the board, the API and the chain keep refusing to step
    over a stage. Callers that pass it must supply a comment: the history records
    the jump honestly as one row from where the batch was to where it went, and
    without a reason nobody reading it later can tell a deliberate diversion from
    a mis-click.
    """
    batch = ProductionBatch.objects.select_for_update().select_related("current_stage", "order_item__order").get(pk=batch.pk)
    if not to_stage:
        raise ValidationError("Этап не найден.")
    if batch.status in {ProductionBatch.Status.PAUSED, ProductionBatch.Status.CANCELLED, ProductionBatch.Status.COMPLETED}:
        raise ValidationError("Партия в текущем статусе не может быть передана на другой этап.")
    if batch.status == ProductionBatch.Status.PROBLEM and batch.has_blocking_problem:
        raise ValidationError("Партия заблокирована критической проблемой.")
    if to_stage.sequence == batch.current_stage.sequence:
        raise ValidationError("Партия уже находится на этом этапе.")
    skipped = skipped_stages_between(batch.current_stage, to_stage)
    if skipped and not allow_skip:
        raise ValidationError("Переход возможен только на соседний этап.")
    can_move_from_stage = can_move_batch(user, batch.current_stage.code)
    can_take_next_stage = to_stage.sequence > batch.current_stage.sequence and can_move_batch(user, to_stage.code)
    if not (can_move_from_stage or can_take_next_stage):
        raise PermissionDenied("Нет права переводить эту партию.")
    if batch.has_blocking_problem and to_stage.sequence > batch.current_stage.sequence:
        raise ValidationError("Партия заблокирована критической проблемой.")
    if (require_comment or to_stage.sequence < batch.current_stage.sequence) and not comment.strip():
        raise ValidationError("Для возврата на предыдущий этап нужен комментарий.")
    if skipped and not comment.strip():
        raise ValidationError("Для перехода через этап нужен комментарий.")
    if skipped:
        # Spelled out in the history, because "Замес -> Склад" alone does not say
        # whether the stages in between were skipped or simply never existed.
        names = ", ".join(stage.name for stage in skipped)
        comment = f"{comment.strip()} (минуя этапы: {names})"
    now = timezone.now()
    from_stage = batch.current_stage
    previous = batch.stage_history.order_by("-created_at").first()
    started_at = previous.created_at if previous else batch.actual_start or batch.created_at
    BatchStageHistory.objects.create(
        batch=batch,
        from_stage=from_stage,
        to_stage=to_stage,
        started_at=started_at,
        finished_at=now,
        changed_by=user,
        comment=comment,
    )
    batch.current_stage = to_stage
    # Устройство принадлежит этапу, поэтому уходя с этапа партия его
    # освобождает - иначе печь осталась бы занятой партией, которая уже на
    # складе, и следующую было бы некуда поставить. На новом этапе партия
    # встаёт в «Не распределено» и ждёт, пока её туда поставят.
    batch.production_unit = None
    batch.status = ProductionBatch.Status.COMPLETED if to_stage.code == "done" else ProductionBatch.Status.IN_PROGRESS
    if to_stage.code == "queue":
        batch.status = ProductionBatch.Status.QUEUED
    if to_stage.code == "done":
        batch.actual_finish = now
    if not batch.actual_start:
        batch.actual_start = now
    batch.save(update_fields=["current_stage", "production_unit", "status", "actual_start", "actual_finish", "updated_at"])
    order = batch.order_item.order
    if to_stage.code == "done":
        # An order can carry several batches - confirm_order makes one per order
        # item - so finishing this one does not finish the order. The batch above
        # is already saved, so it counts itself out of this query; a cancelled
        # batch is not something anyone is still waiting for.
        waiting = (
            ProductionBatch.objects.filter(order_item__order_id=order.pk)
            .exclude(status=ProductionBatch.Status.CANCELLED)
            .exclude(current_stage__code="done")
            .exists()
        )
        order.status = ProductionOrder.Status.IN_PRODUCTION if waiting else ProductionOrder.Status.READY
    else:
        order.status = ProductionOrder.Status.IN_PRODUCTION
    order.save(update_fields=["status", "updated_at"])
    log_order_event(order, f"Партия {batch.display_batch_label}: {from_stage.name} -> {to_stage.name}.", "stage_changed", user=user, batch=batch)
    if to_stage.code == "warehouse":
        stock, stock_created = FinishedGoodsStock.objects.get_or_create(
            batch=batch,
            defaults={
                "product": batch.product,
                "quantity": batch.actual_quantity or batch.planned_quantity,
                "unit": batch.unit,
                "expiration_date": stock_expiration_for(batch),
                "warehouse_location": "Основной склад",
                "received_by": user,
                "is_demo": batch.is_demo,
                "demo_run": batch.demo_run,
            },
        )
        if stock_created:
            safe_record_process_event(
                case_id=batch.batch_number,
                case_type="batch",
                activity="Приём продукции на склад",
                occurred_at=now,
                batch=batch,
                user=user,
                from_stage=from_stage.code,
                to_stage=to_stage.code,
                status=batch.status,
                quantity=stock.quantity,
                unit=stock.unit,
                event_data={"warehouse_location": stock.warehouse_location},
            )
    process_event_for_batch_transition(batch, from_stage, to_stage, user, occurred_at=now, comment=comment)
    if batch.assigned_to and not batch.is_demo:
        notify(batch.assigned_to, "Партия перешла на новый этап", f"Партия {batch.display_batch_label}: {to_stage.name}", "stage_changed", reverse("bakery:batch_detail", args=[batch.pk]))
    return batch


def pause_batch(batch, user, comment=""):
    if batch.status in {ProductionBatch.Status.PAUSED, ProductionBatch.Status.CANCELLED, ProductionBatch.Status.COMPLETED}:
        raise ValidationError("Партия в текущем статусе не может быть остановлена.")
    if not can_move_batch(user, batch.current_stage.code):
        raise PermissionDenied("Нет права останавливать эту партию.")
    batch.status = ProductionBatch.Status.PAUSED
    batch.save(update_fields=["status", "updated_at"])
    log_order_event(batch.order_item.order, f"Партия {batch.display_batch_label} остановлена. {comment}", "batch_paused", user=user, batch=batch)
    safe_record_process_event(
        case_id=batch.batch_number,
        case_type="batch",
        activity="Пауза партии",
        batch=batch,
        user=user,
        from_stage=batch.current_stage.code,
        to_stage=batch.current_stage.code,
        status=batch.status,
        quantity=batch.actual_quantity or batch.planned_quantity,
        unit=batch.unit,
        event_data={"comment": comment},
    )


def resume_batch(batch, user, comment=""):
    if batch.status != ProductionBatch.Status.PAUSED:
        raise ValidationError("Возобновить можно только остановленную партию.")
    if not can_move_batch(user, batch.current_stage.code):
        raise PermissionDenied("Нет права возобновлять эту партию.")
    batch.status = ProductionBatch.Status.IN_PROGRESS
    batch.save(update_fields=["status", "updated_at"])
    log_order_event(batch.order_item.order, f"Партия {batch.display_batch_label} возобновлена. {comment}", "batch_resumed", user=user, batch=batch)
    safe_record_process_event(
        case_id=batch.batch_number,
        case_type="batch",
        activity="Возобновление партии",
        batch=batch,
        user=user,
        from_stage=batch.current_stage.code,
        to_stage=batch.current_stage.code,
        status=batch.status,
        quantity=batch.actual_quantity or batch.planned_quantity,
        unit=batch.unit,
        event_data={"comment": comment},
    )


# ---------------------------------------------------------------------------
# Удаление с доски: ошибочная партия или целиком ошибочный заказ.
# ---------------------------------------------------------------------------

def _refuse_if_stocked(batches):
    """Партию, дошедшую до склада, удалять нельзя - и это не наш каприз.

    Складская запись держит партию защищённым ключом: на неё могли уже
    сослаться отгрузки. Такое не «удаляют», а списывают со склада - там есть
    кому ответить за расхождение остатков.
    """
    stocked = [batch for batch in batches if hasattr(batch, "stock_record")]
    if stocked:
        names = ", ".join(batch.display_batch_label for batch in stocked)
        raise ValidationError(
            f"Партия {names} уже принята на склад. Сначала спишите её со склада, "
            "затем удаляйте."
        )


def _drop_unsent_events(batch_ids, order_ids=()):
    """Убрать из очереди экспорта то, что ещё не уехало в аналитику.

    Оба внешних ключа - SET_NULL: неотправленное событие удалённой партии
    потеряло бы единственную привязку и уехало бы в карту процесса строкой-
    сиротой. Отправленные не трогаем - их уже не вернуть, и честная история
    «создали по ошибке и удалили» лучше дыры в журнале.
    """
    from apps.process_mining.models import ProcessEvent
    from django.db.models import Q

    condition = Q(batch_id__in=list(batch_ids))
    if order_ids:
        condition |= Q(order_id__in=list(order_ids))
    ProcessEvent.objects.filter(condition).exclude(
        export_status=ProcessEvent.ExportStatus.SENT
    ).delete()


@transaction.atomic
def delete_batch(batch, user):
    """Удалить одну ошибочную партию с доски.

    История этапов уходит каскадом, голосовые сообщения и отправленные события
    остаются без привязки (SET_NULL) - это след, а не мусор. Двойник машины
    обновится сам: post_delete-сигнал в twins.py освобождает табло.
    """
    from apps.audit.services import write_audit

    _refuse_if_stocked([batch])
    label = batch.display_batch_label
    write_audit(
        "batch_deleted", batch, user=user,
        changes={"batch": label, "stage": batch.current_stage.code if batch.current_stage_id else ""},
    )
    _drop_unsent_events([batch.pk])
    batch.delete()
    return label


@transaction.atomic
def delete_order_with_batches(order, user):
    """Удалить ошибочный заказ целиком - с партиями, позициями, событиями.

    Существующее удаление на странице заказа отказывает, едва созданы партии
    (order_item - PROTECT), и ошибочный заказ, доехавший до доски, было не
    удалить вообще. Здесь порядок обратный правильный: сначала партии, потом
    сам заказ - и заказ уводит позиции каскадом.
    """
    from apps.audit.services import write_audit

    batches = list(
        ProductionBatch.objects.select_related("current_stage")
        .filter(order_item__order=order)
    )
    _refuse_if_stocked(batches)
    number = order.order_number
    write_audit(
        "order_deleted_with_batches", order, user=user,
        changes={"order": number, "batches": [batch.display_batch_label for batch in batches]},
    )
    _drop_unsent_events([batch.pk for batch in batches], [order.pk])
    for batch in batches:
        batch.delete()
    order.delete()
    return number, len(batches)
