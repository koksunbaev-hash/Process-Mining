import random
import time
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count
from django.urls import reverse
from django.utils import timezone

from apps.notifications.models import Notification
from apps.notifications.services import notify
from apps.nonconformities.models import Nonconformity

from .models import (
    BatchStageHistory,
    Customer,
    FinishedGoodsStock,
    KanbanDemoRun,
    Product,
    ProductionBatch,
    ProductionOrder,
    ProductionOrderItem,
    ProductionStage,
    Unit,
)
from .permissions import role
from .services import move_batch, next_stage_for


WORKFLOW_CODES = ["queue", "mixing", "forming", "proofing", "oven", "warehouse", "done"]
DEMO_PRODUCT_NAMES = [
    "Хлеб «Деревенский»",
    "Батон",
    "Бородинский хлеб",
    "Формовой хлеб",
    "Булочка",
    "Багет",
]
DEMO_QUANTITIES = [Decimal("100"), Decimal("200"), Decimal("300"), Decimal("500"), Decimal("1000")]


def can_manage_kanban_demo(user):
    return bool(user and user.is_authenticated and role(user) in {"admin", "manager", "director", "production_dispatcher"})


def require_demo_permission(user):
    if not can_manage_kanban_demo(user):
        raise PermissionDenied("Нет права управлять Kanban demo.")


def ensure_demo_stages():
    names = {
        "queue": "Очередь",
        "mixing": "Замес",
        "forming": "Формовка",
        "proofing": "Расстойка",
        "oven": "Печь",
        "warehouse": "Склад",
        "done": "Готово",
    }
    stages = {}
    for sequence, code in enumerate(WORKFLOW_CODES, start=1):
        stage, _ = ProductionStage.objects.update_or_create(
            code=code,
            defaults={"name": names[code], "sequence": sequence, "is_active": True},
        )
        stages[code] = stage
    return stages


def demo_products():
    products = list(Product.objects.filter(is_active=True, name__in=DEMO_PRODUCT_NAMES).order_by("name"))
    if len(products) >= 3:
        return products
    defaults = {
        "Хлеб «Деревенский»": Product.Category.BREAD,
        "Батон": Product.Category.LOAF,
        "Бородинский хлеб": Product.Category.BREAD,
        "Формовой хлеб": Product.Category.BREAD,
        "Булочка": Product.Category.BUN,
        "Багет": Product.Category.BAGUETTE,
    }
    for index, (name, category) in enumerate(defaults.items(), start=1):
        Product.objects.get_or_create(
            code=f"DEMO-PROD-{index:02d}",
            defaults={
                "name": name,
                "category": category,
                "unit": Unit.PCS,
                "shelf_life_hours": 36,
                "is_active": True,
            },
        )
    return list(Product.objects.filter(is_active=True, name__in=DEMO_PRODUCT_NAMES).order_by("name"))


@transaction.atomic
def create_demo_run(
    *,
    user,
    count=100,
    name="Kanban demo",
    speed_seconds=2,
    mode=KanbanDemoRun.Mode.WAVE,
    client_request_id=None,
    simulate_pauses=False,
    simulate_problems=False,
    simulate_returns=False,
):
    require_demo_permission(user)
    if client_request_id:
        existing = KanbanDemoRun.objects.filter(client_request_id=client_request_id, is_active=True).first()
        if existing:
            return existing
    active = KanbanDemoRun.objects.filter(is_active=True).exclude(status__in=[KanbanDemoRun.Status.COMPLETED, KanbanDemoRun.Status.STOPPED]).first()
    if active:
        return active
    stages = ensure_demo_stages()
    products = demo_products()
    customer, _ = Customer.objects.get_or_create(
        name="DEMO клиент хлебозавода",
        defaults={"phone": "+7 000 000 00 00", "notes": "Демо-данные Kanban", "is_active": True},
    )
    run = KanbanDemoRun.objects.create(
        name=name,
        total_batches=count,
        speed_seconds=Decimal(str(speed_seconds)),
        mode=mode,
        client_request_id=client_request_id,
        simulate_pauses=simulate_pauses,
        simulate_problems=simulate_problems,
        simulate_returns=simulate_returns,
        created_by=user,
    )
    now = timezone.now()
    for index in range(1, count + 1):
        product = products[(index - 1) % len(products)]
        quantity = DEMO_QUANTITIES[(index - 1) % len(DEMO_QUANTITIES)]
        order, _ = ProductionOrder.objects.update_or_create(
            order_number=f"DEMO-O-{index:04d}",
            defaults={
                "customer": customer,
                "required_date": now + timedelta(hours=8 + index % 8),
                "priority": ProductionOrder.Priority.NORMAL,
                "status": ProductionOrder.Status.QUEUED,
                "notes": f"DEMO RUN {run.pk}",
                "created_by": user,
                "is_demo": True,
                "demo_run": run,
            },
        )
        item, _ = ProductionOrderItem.objects.update_or_create(
            order=order,
            product=product,
            defaults={
                "quantity": quantity,
                "unit": Unit.PCS,
                "recipe": product.recipes.filter(is_active=True).first(),
                "notes": f"DEMO RUN {run.pk}",
                "is_demo": True,
                "demo_run": run,
            },
        )
        batch, _ = ProductionBatch.objects.update_or_create(
            batch_number=f"DEMO-B-{index:04d}",
            defaults={
                "order_item": item,
                "product": product,
                "recipe": item.recipe,
                "planned_quantity": quantity,
                "actual_quantity": None,
                "unit": Unit.PCS,
                "current_stage": stages["queue"],
                "status": ProductionBatch.Status.QUEUED,
                "assigned_to": user,
                "planned_start": now,
                "planned_finish": now + timedelta(hours=12),
                "actual_start": now,
                "actual_finish": None,
                "notes": f"DEMO RUN {run.pk}",
                "is_demo": True,
                "demo_run": run,
            },
        )
        BatchStageHistory.objects.get_or_create(
            batch=batch,
            from_stage=None,
            to_stage=stages["queue"],
            defaults={"changed_by": user, "comment": "DEMO: партия поступила в очередь."},
        )
    return run


def demo_status(run):
    stages = {code: 0 for code in WORKFLOW_CODES}
    counts = run.batches.values("current_stage__code").annotate(total=Count("id"))
    for row in counts:
        stages[row["current_stage__code"]] = row["total"]
    completed = stages.get("done", 0)
    if run.completed_batches != completed:
        run.completed_batches = completed
        update = ["completed_batches", "updated_at"]
        if completed >= run.total_batches and run.status == KanbanDemoRun.Status.RUNNING:
            run.status = KanbanDemoRun.Status.COMPLETED
            run.finished_at = timezone.now()
            update.extend(["status", "finished_at"])
        run.save(update_fields=update)
    progress = int((completed / run.total_batches) * 100) if run.total_batches else 0
    return {
        "id": run.pk,
        "name": run.name,
        "status": run.status,
        "mode": run.mode,
        "speed_seconds": float(run.speed_seconds),
        "total_batches": run.total_batches,
        "completed_batches": completed,
        "progress_percent": progress,
        "stages": stages,
        "last_error": run.last_error,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
    }


def start_demo(run, user):
    require_demo_permission(user)
    if run.status in {KanbanDemoRun.Status.COMPLETED, KanbanDemoRun.Status.STOPPED}:
        raise ValidationError("Этот demo run уже завершён или остановлен.")
    run.status = KanbanDemoRun.Status.RUNNING
    run.started_at = run.started_at or timezone.now()
    run.paused_at = None
    run.save(update_fields=["status", "started_at", "paused_at", "updated_at"])
    return run


def pause_demo(run, user):
    require_demo_permission(user)
    run.status = KanbanDemoRun.Status.PAUSED
    run.paused_at = timezone.now()
    run.save(update_fields=["status", "paused_at", "updated_at"])
    return run


def stop_demo(run, user):
    require_demo_permission(user)
    run.status = KanbanDemoRun.Status.STOPPED
    run.finished_at = timezone.now()
    run.is_active = False
    run.save(update_fields=["status", "finished_at", "is_active", "updated_at"])
    return run


def tick_limit(run):
    if run.mode == KanbanDemoRun.Mode.SEQUENTIAL:
        return 1
    if run.mode == KanbanDemoRun.Mode.FAST:
        return 10
    if run.mode == KanbanDemoRun.Mode.RANDOM:
        return 5
    return 7


@transaction.atomic
def tick_demo(run, user):
    require_demo_permission(user)
    run = KanbanDemoRun.objects.select_for_update().get(pk=run.pk)
    if run.status != KanbanDemoRun.Status.RUNNING:
        return {"changed_batches": [], "errors": [], **demo_status(run)}
    batches = list(
        run.batches.select_for_update()
        .select_related("current_stage", "order_item__order", "product")
        .exclude(current_stage__code="done")
        .exclude(status__in=[ProductionBatch.Status.CANCELLED, ProductionBatch.Status.COMPLETED])
        .order_by("-current_stage__sequence", "id")
    )
    if run.mode == KanbanDemoRun.Mode.RANDOM:
        random.shuffle(batches)
    changed = []
    errors = []
    for batch in batches[: tick_limit(run)]:
        target = next_stage_for(batch)
        if not target:
            continue
        try:
            move_batch(batch, target, user, f"DEMO: переход на этап {target.name}")
            batch.refresh_from_db()
            changed.append({"id": batch.pk, "batch_number": batch.batch_number, "stage": batch.current_stage.code})
        except (PermissionDenied, ValidationError) as exc:
            errors.append({"batch": batch.batch_number, "error": str(exc)})
        except Exception as exc:
            errors.append({"batch": batch.batch_number, "error": str(exc)})
    run.last_error = "; ".join(f"{item['batch']}: {item['error']}" for item in errors[:3])
    run.save(update_fields=["last_error", "updated_at"])
    status = demo_status(run)
    status["changed_batches"] = changed
    status["errors"] = errors
    return status


@transaction.atomic
def reset_demo(run, user):
    require_demo_permission(user)
    batch_ids = list(run.batches.values_list("id", flat=True))
    order_ids = list(run.orders.values_list("id", flat=True))
    urls = [reverse("bakery:batch_detail", args=[pk]) for pk in batch_ids]
    Notification.objects.filter(related_url__in=urls).delete()
    Notification.objects.filter(notification_type="kanban_demo", related_url=reverse("bakery:kanban")).delete()
    Nonconformity.objects.filter(bakery_batch_id__in=batch_ids).exclude(status__in=[Nonconformity.Status.CLOSED, Nonconformity.Status.RESOLVED]).delete()
    FinishedGoodsStock.objects.filter(demo_run=run, is_demo=True).delete()
    BatchStageHistory.objects.filter(batch_id__in=batch_ids).delete()
    ProductionBatch.objects.filter(demo_run=run, is_demo=True).delete()
    ProductionOrderItem.objects.filter(demo_run=run, is_demo=True).delete()
    ProductionOrder.objects.filter(demo_run=run, is_demo=True).delete()
    run.status = KanbanDemoRun.Status.STOPPED
    run.is_active = False
    run.finished_at = timezone.now()
    run.save(update_fields=["status", "is_active", "finished_at", "updated_at"])
    run.delete()
    return {"deleted_batches": len(batch_ids), "deleted_orders": len(order_ids)}


def run_demo_until_done(run, user, sleep=True, max_ticks=500):
    start_demo(run, user)
    ticks = 0
    while ticks < max_ticks:
        result = tick_demo(run, user)
        ticks += 1
        if result["status"] == KanbanDemoRun.Status.COMPLETED:
            return result
        if sleep:
            time.sleep(float(run.speed_seconds))
    run.status = KanbanDemoRun.Status.FAILED
    run.last_error = "Demo не завершилось за лимит tick."
    run.save(update_fields=["status", "last_error", "updated_at"])
    return demo_status(run)


def demo_user(username=None):
    User = get_user_model()
    if username:
        return User.objects.get(username=username)
    user = User.objects.filter(is_superuser=True).first()
    if user:
        return user
    return User.objects.filter(profile__role__in=["admin", "production_dispatcher", "manager", "director"]).first()
