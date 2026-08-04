from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
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
    ProductionStage,
    stock_expiration_for,
)
from .permissions import can_move_batch


def log_order_event(order, message, event_type="info", user=None, batch=None):
    return OrderEvent.objects.create(order=order, batch=batch, event_type=event_type, message=message, created_by=user)


@transaction.atomic
def confirm_order(order, user=None, assignee=None):
    queue = ProductionStage.objects.get(code="queue")
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
        if created:
            BatchStageHistory.objects.create(batch=batch, to_stage=queue, changed_by=user, comment="Партия поступила в очередь.")
            log_order_event(order, f"Партия {batch.batch_number} поступила в очередь.", "batch_queued", user=user, batch=batch)
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
                notify(batch.assigned_to, "Партия поступила в очередь", batch.batch_number, "batch_queued", reverse("bakery:batch_detail", args=[batch.pk]))
        batches.append(batch)
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
    batch.status = ProductionBatch.Status.COMPLETED if to_stage.code == "done" else ProductionBatch.Status.IN_PROGRESS
    if to_stage.code == "queue":
        batch.status = ProductionBatch.Status.QUEUED
    if to_stage.code == "done":
        batch.actual_finish = now
    if not batch.actual_start:
        batch.actual_start = now
    batch.save(update_fields=["current_stage", "status", "actual_start", "actual_finish", "updated_at"])
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
    log_order_event(order, f"Партия {batch.batch_number}: {from_stage.name} -> {to_stage.name}.", "stage_changed", user=user, batch=batch)
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
        notify(batch.assigned_to, "Партия перешла на новый этап", f"{batch.batch_number}: {to_stage.name}", "stage_changed", reverse("bakery:batch_detail", args=[batch.pk]))
    return batch


def pause_batch(batch, user, comment=""):
    if batch.status in {ProductionBatch.Status.PAUSED, ProductionBatch.Status.CANCELLED, ProductionBatch.Status.COMPLETED}:
        raise ValidationError("Партия в текущем статусе не может быть остановлена.")
    if not can_move_batch(user, batch.current_stage.code):
        raise PermissionDenied("Нет права останавливать эту партию.")
    batch.status = ProductionBatch.Status.PAUSED
    batch.save(update_fields=["status", "updated_at"])
    log_order_event(batch.order_item.order, f"Партия {batch.batch_number} остановлена. {comment}", "batch_paused", user=user, batch=batch)
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
    log_order_event(batch.order_item.order, f"Партия {batch.batch_number} возобновлена. {comment}", "batch_resumed", user=user, batch=batch)
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
