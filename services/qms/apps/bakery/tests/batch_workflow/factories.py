from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.bakery.models import (
    Customer,
    Ingredient,
    ProductionBatch,
    ProductionOrder,
    ProductionOrderItem,
    ProductionStage,
    Product,
    Recipe,
    RecipeItem,
    BatchStageHistory,
)
from apps.bakery.services import confirm_order
from apps.nonconformities.models import DefectType, Nonconformity
from apps.quality.models import ControlPost, ControlType, Department, QualityObject


STAGES = [
    ("queue", "Очередь"),
    ("mixing", "Замес"),
    ("forming", "Формовка"),
    ("proofing", "Расстойка"),
    ("oven", "Печь"),
    ("warehouse", "Склад"),
    ("done", "Готово"),
]


def create_user(username="dispatcher", role=UserProfile.Role.MANAGER, password="x", **kwargs):
    user, _ = get_user_model().objects.get_or_create(username=username, defaults=kwargs)
    user.set_password(password)
    user.save()
    user.profile.role = role
    user.profile.save()
    return user


def create_stage_list():
    stages = {}
    for sequence, (code, name) in enumerate(STAGES, start=1):
        stage, _ = ProductionStage.objects.update_or_create(
            code=code,
            defaults={"name": name, "sequence": sequence, "is_active": True},
        )
        stages[code] = stage
    return stages


def create_product(code="BREAD", name="Хлеб тестовый"):
    product, _ = Product.objects.get_or_create(
        code=code,
        defaults={
            "name": name,
            "category": Product.Category.BREAD,
            "unit": "шт",
            "weight_per_item": Decimal("0.500"),
            "shelf_life_hours": 36,
            "baking_duration_minutes": 30,
            "proofing_duration_minutes": 45,
            "mixing_duration_minutes": 15,
        },
    )
    return product


def create_recipe(product):
    flour, _ = Ingredient.objects.get_or_create(code=f"FLOUR-{product.code}", defaults={"name": "Мука", "unit": "кг", "current_stock": 100, "minimum_stock": 10})
    recipe, _ = Recipe.objects.get_or_create(product=product, version="1.0", defaults={"name": f"Рецептура {product.code}", "output_quantity": 100, "output_unit": "шт"})
    RecipeItem.objects.get_or_create(recipe=recipe, ingredient=flour, defaults={"quantity_for_batch": Decimal("25.000"), "sequence": 1})
    return recipe


def create_order(user=None, quantity=Decimal("100.000"), priority=ProductionOrder.Priority.NORMAL):
    user = user or create_user()
    product = create_product()
    recipe = create_recipe(product)
    customer = Customer.objects.create(name="Клиент workflow")
    order = ProductionOrder.objects.create(
        customer=customer,
        required_date=timezone.now() + timedelta(hours=8),
        priority=priority,
        created_by=user,
    )
    item = ProductionOrderItem.objects.create(order=order, product=product, quantity=quantity, unit="шт", recipe=recipe)
    return order, item


def create_order_with_two_items(user=None, quantity=Decimal("100.000")):
    """confirm_order makes one batch per order item, and that is the only way an
    order ends up carrying more than one batch."""
    user = user or create_user()
    order, first = create_order(user=user, quantity=quantity)
    product = create_product(code="BUN", name="Булочка тестовая")
    second = ProductionOrderItem.objects.create(
        order=order,
        product=product,
        quantity=quantity,
        unit="шт",
        recipe=create_recipe(product),
    )
    return order, first, second


def create_queued_batch(user=None, assignee=None, quantity=Decimal("100.000")):
    create_stage_list()
    user = user or create_user()
    order, _ = create_order(user=user, quantity=quantity)
    return confirm_order(order, user=user, assignee=assignee or user)[0]


def create_manual_batch(stage_code="queue", user=None, quantity=Decimal("100.000"), **kwargs):
    stages = create_stage_list()
    user = user or create_user()
    _, item = create_order(user=user, quantity=quantity)
    batch = ProductionBatch.objects.create(
        order_item=item,
        product=item.product,
        recipe=item.recipe,
        planned_quantity=quantity,
        unit="шт",
        current_stage=stages[stage_code],
        status=kwargs.pop("status", ProductionBatch.Status.QUEUED if stage_code == "queue" else ProductionBatch.Status.IN_PROGRESS),
        assigned_to=kwargs.pop("assigned_to", user),
        planned_start=kwargs.pop("planned_start", timezone.now()),
        planned_finish=kwargs.pop("planned_finish", timezone.now() + timedelta(hours=8)),
        **kwargs,
    )
    BatchStageHistory.objects.get_or_create(batch=batch, to_stage=batch.current_stage, defaults={"changed_by": user, "comment": "Партия создана для теста."})
    return batch


def create_problem(batch, criticality="critical", status="registered", code="WF-PROBLEM"):
    dept, _ = Department.objects.get_or_create(code="WF", defaults={"name": "Workflow"})
    control_type, _ = ControlType.objects.get_or_create(code="WF", defaults={"name": "Workflow control"})
    post, _ = ControlPost.objects.get_or_create(
        code="WF",
        defaults={"name": "Workflow post", "department": dept, "control_type": control_type},
    )
    defect, _ = DefectType.objects.get_or_create(
        code=code,
        defaults={"name": "Проблема партии", "criticality": criticality, "object_block_required": criticality == "critical"},
    )
    qobj, _ = QualityObject.objects.get_or_create(
        unique_number=f"WF-{batch.pk}",
        defaults={
            "object_type": "finished_product",
            "product_name": batch.product.name,
            "quantity": 1,
            "department": dept,
        },
    )
    return Nonconformity.objects.create(
        quality_object=qobj,
        control_post=post,
        defect_type=defect,
        description="Проблема рабочего процесса партии",
        criticality=criticality,
        status=status,
        affected_quantity=1,
        responsible_department=dept,
        bakery_order=batch.order_item.order,
        bakery_batch=batch,
        bakery_product=batch.product,
        bakery_stage=batch.current_stage,
    )
