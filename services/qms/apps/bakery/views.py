from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import mimetypes
import os
import time
from types import SimpleNamespace

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.db.models.deletion import ProtectedError
from django.http import FileResponse, Http404, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.notifications.services import notify
from apps.process_mining.services import safe_record_process_event

from .kanban_demo import can_manage_kanban_demo
from .forecast import WEEKS_BACK, daily_totals, predict_week
from .production_sheet import build_rows, shifts_for, totals
from .forms import (
    CustomerForm,
    IngredientForm,
    ProductionOrderCreateItemFormSet,
    ProductionOrderForm,
    ProductionOrderItemForm,
    ProductForm,
    RecipeForm,
    RecipeItemForm,
    VoiceMessageForm,
)
from .models import (
    Customer,
    FinishedGoodsStock,
    Ingredient,
    ProductionBatch,
    ProductionOrder,
    ProductionPlan,
    ProductionOrderItem,
    ProductionStage,
    ProductionUnit,
    Product,
    Recipe,
    RecipeItem,
    BatchStageHistory,
    VoiceMessage,
)
from .permissions import can_manage_catalog, can_manage_orders, can_move_batch, can_view_voice, role
from .services import (
    assign_batch_to_unit,
    confirm_order,
    move_batch,
    next_stage_for,
    pause_batch,
    previous_stage_for,
    repeat_order_for_next_week,
    resume_batch,
)


def batch_number_query(value):
    query = Q(batch_number__icontains=value)
    normalized = ProductionBatch.short_number_for(value)
    if normalized.startswith("B-") and normalized[2:].isdigit():
        query |= Q(batch_number__endswith=f"-{normalized[2:]}")
    if normalized.startswith("D-") and normalized[2:].isdigit():
        query |= Q(batch_number__iexact=f"DEMO-B-{int(normalized[2:]):04d}")
    return query


def visible_batch_number_query(value):
    normalized = (value or "").strip()
    if normalized.isdigit():
        return Q(daily_card_number=int(normalized))
    return Q(pk__isnull=True)


def filter_batches(request):
    qs = ProductionBatch.objects.select_related(
        "order_item__order__customer", "product", "current_stage", "assigned_to", "production_unit"
    ).prefetch_related("voice_messages")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            batch_number_query(q)
            | visible_batch_number_query(q)
            | Q(product__name__icontains=q)
            | Q(order_item__order__order_number__icontains=q)
        )
    for key, field in {
        "product": "product_id",
        "status": "status",
    }.items():
        value = request.GET.get(key)
        if value:
            qs = qs.filter(**{field: value})
    demo_filter = request.GET.get("demo", "work")
    if demo_filter == "demo":
        qs = qs.filter(is_demo=True)
    elif demo_filter == "all":
        pass
    else:
        qs = qs.filter(is_demo=False)
    return qs


def card_flags(card):
    """Метки карточки одним списком.

    Считаются здесь, а не в шаблоне: карточка бывает двух видов - партия и
    сгруппированный блок, - и у них по-разному лежит заказ. Ветвление на каждую
    метку превратило бы шапку карточки в четыре одинаковых условия, а пустой
    контейнер меток всё равно занимал бы место в сетке.
    """
    order = card.order if getattr(card, "is_group", False) else card.order_item.order
    flags = []
    if order.priority in {ProductionOrder.Priority.URGENT, ProductionOrder.Priority.HIGH}:
        flags.append({"kind": "urgent", "text": order.get_priority_display()})
    if card.has_blocking_problem:
        flags.append({"kind": "critical", "text": "проблема"})
    if card.is_demo:
        flags.append({"kind": "demo", "text": "demo"})
    return flags


def stage_lanes(stage, cards, units):
    """Разложить карточки этапа по устройствам.

    Первой идёт общая дорожка «Не распределено»: пока партию никуда не
    поставили, она ждёт именно там, и пустая доска должна начинаться с неё, а
    не с пяти пустых печей. Дальше - по одному месту на устройство.

    На дорожке устройства помещается ровно одна карточка. Если в базе их
    почему-то оказалось больше (ручная правка, гонка, которую не закрыл
    select_for_update), лишние показываются там же и помечены: спрятать их
    значило бы стереть партию с доски.
    """
    pool = {"unit": None, "key": "", "name": "Не распределено", "cards": [], "is_pool": True, "available": True}
    lanes = {
        unit.pk: {
            "unit": unit,
            "key": str(unit.pk),
            "name": unit.name,
            "cards": [],
            "is_pool": False,
            "available": unit.is_available,
        }
        for unit in units
    }
    for card in cards:
        lane = lanes.get(card.production_unit_id) or pool
        lane["cards"].append(card)
    return [pool] + [lanes[unit.pk] for unit in units]


def kanban_context(request):
    stages = list(
        ProductionStage.objects.filter(is_active=True)
        .prefetch_related(Prefetch("units", queryset=ProductionUnit.objects.filter(is_active=True)))
        .order_by("sequence")
    )
    batches = filter_batches(request)
    column_search = {stage.code: request.GET.get(f"stage_q_{stage.code}", "").strip() for stage in stages}
    columns = []
    for index, stage in enumerate(stages):
        items = batches.filter(current_stage=stage)
        if column_search[stage.code]:
            items = items.filter(
                Q(product__name__icontains=column_search[stage.code])
                | batch_number_query(column_search[stage.code])
                | visible_batch_number_query(column_search[stage.code])
            )
        items = list(items)
        cards = []
        grouped = {}
        for batch in items:
            order = batch.order_item.order
            if order.kanban_grouped:
                grouped.setdefault(order.pk, []).append(batch)
            else:
                cards.append(batch)
        for order_batches in grouped.values():
            first = order_batches[0]
            cards.append(SimpleNamespace(
                is_group=True,
                pk=first.pk,
                order=first.order_item.order,
                batches=order_batches,
                first_batch=first,
                # Блок стоит на устройстве целиком, поэтому место ему даёт
                # первая строка - остальные едут за ней и повторяют её ссылку.
                production_unit_id=first.production_unit_id,
                planned_finish=min(
                    (batch.planned_finish for batch in order_batches if batch.planned_finish),
                    default=None,
                ),
                has_blocking_problem=any(batch.has_blocking_problem for batch in order_batches),
                is_demo=any(batch.is_demo for batch in order_batches),
            ))
        cards.sort(key=lambda card: (
            card.planned_finish or datetime.max.replace(tzinfo=timezone.get_current_timezone()),
            card.pk,
        ))
        for card in cards:
            card.flags = card_flags(card)
        units = list(stage.units.all())
        lanes = stage_lanes(stage, cards, units)
        # prev_stage feeds the "← Назад" button, which exists because HTML5 drag
        # and drop fires no events from touch: on a phone or tablet the buttons
        # are the only way to move a batch at all.
        columns.append({
            "stage": stage,
            "batches": cards,
            "count": len(cards),
            "lanes": lanes,
            "has_units": bool(units),
            "busy": sum(1 for lane in lanes if not lane["is_pool"] and lane["cards"]),
            "capacity": len(units),
            "waiting": len(lanes[0]["cards"]),
            "query": column_search[stage.code],
            "has_next": index + 1 < len(stages),
            "prev_stage": stages[index - 1] if index else None,
        })
    # Where a card should send you back to. Not request.get_full_path: this same
    # template is served by kanban_partial for script refreshes, and there that
    # path is /bakery/board/partial/ - a fragment with no base template, styles
    # or navigation. The query string is the same either way, so filters survive.
    query = request.GET.urlencode()
    context = {
        "board_url": f"{reverse('bakery:kanban')}?{query}" if query else reverse("bakery:kanban"),
        "columns": columns,
        "products": Product.objects.filter(is_active=True),
        "statuses": ProductionBatch.Status.choices,
        "can_manage_demo": can_manage_kanban_demo(request.user),
        "demo_filter": request.GET.get("demo", "work"),
    }
    return context


@login_required
def kanban(request):
    context = kanban_context(request)
    return render(request, "bakery/kanban.html", context)


@login_required
def kanban_partial(request):
    return render(request, "bakery/kanban_board.html", kanban_context(request))


def kanban_change_marker():
    latest = BatchStageHistory.objects.order_by("-pk").values_list("pk", flat=True).first()
    return str(latest or 0)


@login_required
def kanban_events(request):
    def stream():
        marker = kanban_change_marker()
        yield f"event: ready\ndata: {marker}\n\n"
        started = time.monotonic()
        last_heartbeat = started
        while time.monotonic() - started < 300:
            time.sleep(2)
            current = kanban_change_marker()
            if current != marker:
                marker = current
                yield f"event: changed\ndata: {marker}\n\n"
            elif time.monotonic() - last_heartbeat >= 20:
                last_heartbeat = time.monotonic()
                yield ": keepalive\n\n"

    response = StreamingHttpResponse(stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


@login_required
def move_batch_view(request, pk):
    batch = get_object_or_404(ProductionBatch.objects.select_related("current_stage", "order_item__order"), pk=pk)
    if request.method != "POST":
        return redirect("bakery:kanban")
    stage = ProductionStage.objects.filter(pk=request.POST.get("stage")).first() or next_stage_for(batch)
    # Дорожка устройства - такая же цель броска, как колонка. Бросок внутри
    # своей колонки этап не меняет, а только переставляет карточку с места на
    # место, поэтому move_batch на него звать нечего: он бы отказал словами
    # «партия уже находится на этом этапе».
    unit, unit_error = requested_unit(request, stage or batch.current_stage)
    if unit_error:
        return unit_refusal(request, unit_error)
    if stage and batch.current_stage_id == stage.pk:
        return assign_only(request, batch, unit)
    # Both operands are read before move_batch runs, so neither may be None:
    # a batch on the last stage has no next stage, and a batch that never
    # entered production has no current one.
    going_back = bool(stage and batch.current_stage_id and stage.sequence < batch.current_stage.sequence)
    error = ""
    if stage is None:
        error = f"Партия {batch.display_batch_label} уже на последнем этапе."
    else:
        try:
            # allow_skip: dragging a card names a column, not a step. The two
            # buttons on a card can only ever reach a neighbour, so this changes
            # nothing for them; it is what lets a drag cross several columns.
            # move_batch still refuses a jump with no comment, and the drop
            # handler always sends one.
            # move_batch перечитывает партию под блокировкой и возвращает уже
            # переведённую: у переданного объекта этап остался прежним, и
            # распределение по нему отказало бы «устройство не того этапа».
            batch = move_batch(
                batch,
                stage,
                request.user,
                request.POST.get("comment", ""),
                require_comment=going_back,
                allow_skip=True,
            )
            if unit is not None:
                assign_batch_to_unit(batch, unit, request.user)
        except (PermissionDenied, ValidationError) as exc:
            # ValidationError.__str__ is repr(list(self)), which would print
            # ['Переход возможен только на соседний этап.'] - brackets, quotes
            # and all - onto the board.
            error = " ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        # Deliberately no messages.* here: a JSON response renders none, so the
        # queued text would surface on whatever page was opened next.
        return JsonResponse({"ok": not error, "error": error})
    if error:
        messages.error(request, error)
    else:
        messages.success(request, f"Партия {batch.display_batch_label} передана на этап {stage.name}.")
    return redirect(request.POST.get("next") or "bakery:kanban")


def requested_unit(request, stage):
    """Устройство из запроса: (устройство или None, текст отказа).

    Пустая строка - осознанный выбор «в Не распределено», а не отсутствие
    параметра, поэтому она и None различаются: снять партию с печи должно быть
    можно, а бросок мимо дорожек - не должен молча её снимать.
    """
    raw = request.POST.get("unit")
    if raw is None or raw == "":
        return None, ""
    unit = ProductionUnit.objects.select_related("stage").filter(pk=raw, is_active=True).first()
    if unit is None:
        return None, "Устройство не найдено."
    if stage is not None and unit.stage_id != stage.pk:
        return None, f"«{unit.name}» не относится к этапу {stage.name}."
    return unit, ""


def unit_refusal(request, error):
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"ok": False, "error": error})
    messages.error(request, error)
    return redirect(request.POST.get("next") or "bakery:kanban")


def assign_only(request, batch, unit):
    """Перестановка внутри этапа: этап тот же, меняется только устройство."""
    error = ""
    try:
        assign_batch_to_unit(batch, unit, request.user)
    except (PermissionDenied, ValidationError) as exc:
        error = " ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"ok": not error, "error": error})
    if error:
        messages.error(request, error)
    elif unit is None:
        messages.success(request, f"Партия {batch.display_batch_label} снята с устройства.")
    else:
        messages.success(request, f"Партия {batch.display_batch_label} поставлена на «{unit.name}».")
    return redirect(request.POST.get("next") or "bakery:kanban")


@login_required
def move_order_group_view(request, pk):
    """Move every batch in one visible grouped card to the same stage."""
    order = get_object_or_404(ProductionOrder, pk=pk, kanban_grouped=True)
    if request.method != "POST":
        return redirect("bakery:kanban")

    try:
        source_stage_id = int(request.POST.get("from_stage", ""))
    except (TypeError, ValueError):
        source_stage_id = 0
    batches = list(
        ProductionBatch.objects
        .select_related("current_stage", "order_item__order")
        .filter(order_item__order=order, current_stage_id=source_stage_id)
        .exclude(status=ProductionBatch.Status.CANCELLED)
        .order_by("pk")
    )
    error = ""
    stage = None
    if not batches:
        error = "В этом блоке больше нет партий на выбранном этапе."
    else:
        stage = ProductionStage.objects.filter(pk=request.POST.get("stage")).first()
        stage = stage or next_stage_for(batches[0])
        if stage is None:
            error = f"Заказ №{order.order_number} уже на последнем этапе."

    unit, unit_error = requested_unit(request, stage or (batches[0].current_stage if batches else None))
    if unit_error:
        return unit_refusal(request, unit_error)
    if not error and batches and batches[0].current_stage_id == stage.pk:
        return assign_only(request, batches[0], unit)

    if not error:
        try:
            with transaction.atomic():
                moved = []
                for batch in batches:
                    going_back = stage.sequence < batch.current_stage.sequence
                    moved.append(move_batch(
                        batch,
                        stage,
                        request.user,
                        request.POST.get("comment", ""),
                        require_comment=going_back,
                        allow_skip=True,
                    ))
                if unit is not None:
                    assign_batch_to_unit(moved[0], unit, request.user)
        except (PermissionDenied, ValidationError) as exc:
            error = " ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"ok": not error, "error": error})
    if error:
        messages.error(request, error)
    else:
        messages.success(request, f"Заказ №{order.order_number} передан на этап {stage.name} одним блоком.")
    return redirect(request.POST.get("next") or "bakery:kanban")


@login_required
def batch_action(request, pk, action):
    batch = get_object_or_404(ProductionBatch, pk=pk)
    try:
        if action == "pause":
            pause_batch(batch, request.user, request.POST.get("comment", ""))
            messages.success(request, "Партия остановлена.")
        elif action == "resume":
            resume_batch(batch, request.user, request.POST.get("comment", ""))
            messages.success(request, "Партия возобновлена.")
        elif action == "prev":
            stage = previous_stage_for(batch)
            move_batch(batch, stage, request.user, request.POST.get("comment", ""), require_comment=True)
            messages.success(request, "Партия возвращена на предыдущий этап.")
        elif action == "cancel" and can_manage_orders(request.user):
            batch.status = ProductionBatch.Status.CANCELLED
            batch.save(update_fields=["status", "updated_at"])
            messages.success(request, "Партия отменена.")
    except (PermissionDenied, ValidationError) as exc:
        messages.error(request, str(exc))
    return redirect("bakery:batch_detail", pk=batch.pk)


@login_required
def product_list(request):
    items = Product.objects.all()
    if request.GET.get("q"):
        items = items.filter(Q(name__icontains=request.GET["q"]) | Q(code__icontains=request.GET["q"]))
    if request.GET.get("category"):
        items = items.filter(category=request.GET["category"])
    if request.GET.get("active"):
        items = items.filter(is_active=request.GET["active"] == "1")
    return render(request, "bakery/product_list.html", {"items": items, "categories": Product.Category.choices})


@login_required
def product_detail(request, pk):
    item = get_object_or_404(Product, pk=pk)
    return render(request, "bakery/product_detail.html", {"item": item})


@login_required
def product_form(request, pk=None):
    if not can_manage_catalog(request.user):
        raise PermissionDenied
    item = get_object_or_404(Product, pk=pk) if pk else None
    form = ProductForm(request.POST or None, request.FILES or None, instance=item)
    if form.is_valid():
        form.save()
        messages.success(request, "Продукт сохранён.")
        return redirect("bakery:products")
    return render(request, "bakery/form.html", {"form": form, "title": "Продукт"})


@login_required
def product_disable(request, pk):
    if not can_manage_catalog(request.user):
        raise PermissionDenied
    product = get_object_or_404(Product, pk=pk)
    product.is_active = False
    product.save(update_fields=["is_active", "updated_at"])
    messages.success(request, "Продукт отключён.")
    return redirect("bakery:products")


@login_required
def ingredient_list(request):
    items = Ingredient.objects.all()
    if request.GET.get("q"):
        items = items.filter(Q(name__icontains=request.GET["q"]) | Q(code__icontains=request.GET["q"]))
    if request.GET.get("unit"):
        items = items.filter(unit=request.GET["unit"])
    return render(request, "bakery/ingredient_list.html", {"items": items, "units": Ingredient._meta.get_field("unit").choices})


@login_required
def ingredient_form(request, pk=None):
    if not can_manage_catalog(request.user):
        raise PermissionDenied
    item = get_object_or_404(Ingredient, pk=pk) if pk else None
    form = IngredientForm(request.POST or None, instance=item)
    if form.is_valid():
        form.save()
        messages.success(request, "Ингредиент сохранён.")
        return redirect("bakery:ingredients")
    return render(request, "bakery/form.html", {"form": form, "title": "Ингредиент"})


@login_required
def recipe_list(request):
    items = Recipe.objects.select_related("product", "approved_by")
    if request.GET.get("product"):
        items = items.filter(product_id=request.GET["product"])
    return render(request, "bakery/recipe_list.html", {"items": items, "products": Product.objects.filter(is_active=True)})


@login_required
def recipe_detail(request, pk):
    recipe = get_object_or_404(Recipe.objects.select_related("product").prefetch_related("items__ingredient"), pk=pk)
    if request.method == "POST" and can_manage_catalog(request.user):
        form = RecipeItemForm(request.POST)
        if form.is_valid():
            item = form.save(commit=False)
            item.recipe = recipe
            item.save()
            messages.success(request, "Ингредиент добавлен в рецептуру.")
            return redirect("bakery:recipe_detail", pk=recipe.pk)
    else:
        form = RecipeItemForm()
    quantity = request.GET.get("quantity")
    requirements = recipe.calculate_requirements(quantity) if quantity else []
    return render(request, "bakery/recipe_detail.html", {"recipe": recipe, "form": form, "requirements": requirements})


@login_required
def recipe_form(request, pk=None):
    if not can_manage_catalog(request.user):
        raise PermissionDenied
    item = get_object_or_404(Recipe, pk=pk) if pk else None
    form = RecipeForm(request.POST or None, instance=item)
    if form.is_valid():
        form.save()
        messages.success(request, "Рецептура сохранена.")
        return redirect("bakery:recipes")
    return render(request, "bakery/form.html", {"form": form, "title": "Рецептура"})


@login_required
def order_list(request):
    items = ProductionOrder.objects.select_related("customer", "created_by").prefetch_related(
        "items__product",
        "items__batches__current_stage",
    )
    if request.GET.get("status"):
        items = items.filter(status=request.GET["status"])
    if request.GET.get("q"):
        query = request.GET["q"].strip()
        items = items.filter(
            Q(order_number__icontains=query)
            | Q(items__product__name__icontains=query)
        ).distinct()
    items = list(items)
    _add_order_quantity_metrics(items)
    return render(request, "bakery/order_list.html", {"items": items, "statuses": ProductionOrder.Status.choices})


def _add_order_quantity_metrics(orders):
    """Display totals for the archive; product and stage names stay untouched."""
    for order in orders:
        planned = Decimal("0")
        ready = Decimal("0")
        started_at = None
        completed_at = None

        for line in order.items.all():
            planned += line.quantity or Decimal("0")
            for batch in line.batches.all():
                if batch.status == ProductionBatch.Status.CANCELLED:
                    continue
                if batch.actual_start and (started_at is None or batch.actual_start < started_at):
                    started_at = batch.actual_start
                if batch.actual_finish and (completed_at is None or batch.actual_finish > completed_at):
                    completed_at = batch.actual_finish
                if batch.status == ProductionBatch.Status.COMPLETED or (
                    batch.current_stage_id and batch.current_stage.code == "done"
                ):
                    ready += batch.actual_quantity if batch.actual_quantity is not None else batch.planned_quantity

        order.planned_quantity = planned
        order.ready_quantity = ready
        order.production_started_at = started_at
        order.production_completed_at = completed_at
        order.progress_percent = min(100, int((ready / planned) * 100)) if planned else 0
    return orders


@login_required
def order_detail(request, pk):
    order = get_object_or_404(
        ProductionOrder.objects
        .select_related("customer")
        .prefetch_related(
            "items__product",
            "items__recipe__items__ingredient",
            "items__batches__current_stage",
        ),
        pk=pk,
    )

    item_form = ProductionOrderItemForm()

    if request.method == "POST" and can_manage_orders(request.user):
        action = request.POST.get("action")

        if action == "delete":
            order_number = order.order_number
            try:
                order.delete()
            except ProtectedError:
                messages.error(
                    request,
                    "Заказ нельзя удалить: по нему уже созданы производственные партии.",
                )
                return redirect("bakery:order_detail", pk=order.pk)
            messages.success(request, f"Заказ №{order_number} удалён.")
            return redirect("bakery:orders")

        if action == "confirm":
            confirm_order(order, user=request.user)
            messages.success(
                request,
                "Заказ подтверждён, партии созданы.",
            )
            return redirect("bakery:order_detail", pk=order.pk)

        if action == "repeat_next_week":
            quantities = {}

            try:
                for line in order.items.all():
                    raw_quantity = request.POST.get(
                        f"quantity_{line.pk}",
                        "",
                    ).replace(",", ".")

                    quantities[line.pk] = Decimal(raw_quantity)

                new_order = repeat_order_for_next_week(
                    source_order=order,
                    quantities=quantities,
                    user=request.user,
                )

            except (InvalidOperation, ValueError):
                messages.error(
                    request,
                    "Проверьте введённые количества.",
                )

            except ValidationError as exc:
                messages.error(
                    request,
                    " ".join(exc.messages),
                )

            else:
                messages.success(
                    request,
                    f"Создан план на следующую неделю: "
                    f"заказ №{new_order.order_number}.",
                )
                return redirect(
                    "bakery:order_detail",
                    pk=new_order.pk,
                )

        else:
            item_form = ProductionOrderItemForm(request.POST)

            if item_form.is_valid():
                line = item_form.save(commit=False)
                line.order = order
                line.save()

                messages.success(request, "Позиция добавлена.")

                return redirect(
                    "bakery:order_detail",
                    pk=order.pk,
                )

    return render(
        request,
        "bakery/order_detail.html",
        {
            "order": order,
            "item_form": item_form,
        },
    )


@login_required
def order_form(request, pk=None):
    if not can_manage_orders(request.user):
        raise PermissionDenied

    if pk is None:
        formset = ProductionOrderCreateItemFormSet(request.POST or None, prefix="items")
        if request.method == "POST" and formset.is_valid():
            now = timezone.now()
            local_now = timezone.localtime(now)
            required_date = local_now.replace(hour=23, minute=59, second=59, microsecond=0)

            with transaction.atomic():
                customer, _ = Customer.objects.get_or_create(
                    name="Производство",
                    defaults={"notes": "Системная запись для заказов без клиента."},
                )
                order = ProductionOrder.objects.create(
                    customer=customer,
                    order_date=now,
                    required_date=required_date,
                    priority=ProductionOrder.Priority.NORMAL,
                    status=ProductionOrder.Status.DRAFT,
                    created_by=request.user,
                )
                for item_form in formset:
                    if not item_form.cleaned_data.get("product"):
                        continue
                    line = item_form.save(commit=False)
                    line.order = order
                    line.unit = line.product.unit
                    line.recipe = line.product.recipes.filter(is_active=True).first()
                    line.save()

                safe_record_process_event(
                    case_id=f"ORDER-{order.order_number}",
                    case_type="order",
                    activity="Создание заказа",
                    order=order,
                    user=request.user,
                    status=order.status,
                )

            messages.success(request, "Заказ с продуктами создан.")
            return redirect("bakery:order_detail", pk=order.pk)

        return render(
            request,
            "bakery/order_create.html",
            {"formset": formset},
        )

    item = get_object_or_404(ProductionOrder, pk=pk) if pk else None
    form = ProductionOrderForm(request.POST or None, instance=item)
    if form.is_valid():
        order = form.save(commit=False)
        if not order.created_by_id:
            order.created_by = request.user
        order.save()
        messages.success(request, "Заказ сохранён.")
        return redirect("bakery:order_detail", pk=order.pk)
    return render(request, "bakery/form.html", {"form": form, "title": "Заказ"})


@login_required
def batch_list(request):
    return render(request, "bakery/batch_list.html", {"items": filter_batches(request)})


@login_required
def batch_detail(request, pk):
    item = get_object_or_404(ProductionBatch.objects.select_related("order_item__order__customer", "product", "recipe", "current_stage", "assigned_to"), pk=pk)
    return render(request, "bakery/batch_detail.html", {"item": item, "next_stage": next_stage_for(item), "prev_stage": previous_stage_for(item)})


@login_required
def voice_list(request):
    items = VoiceMessage.objects.select_related("created_by", "order", "batch", "product", "stage", "command").filter(is_deleted=False)
    if request.GET.get("date"):
        items = items.filter(created_at__date=request.GET["date"])
    if request.GET.get("order"):
        items = items.filter(order_id=request.GET["order"])
    if request.GET.get("batch"):
        items = items.filter(batch_id=request.GET["batch"])
    form = VoiceMessageForm()
    return render(request, "bakery/voice_list.html", {"items": items, "form": form, "orders": ProductionOrder.objects.all(), "batches": ProductionBatch.objects.all()})


@login_required
def voice_upload(request):
    if request.method != "POST":
        return redirect("bakery:voice")
    form = VoiceMessageForm(request.POST, request.FILES)
    if form.is_valid():
        msg = form.save(commit=False)
        msg.created_by = request.user
        msg.clean()
        msg.save()
        notify(request.user, "Голосовое сообщение добавлено", msg.comment or msg.original_filename, "voice_message")
        messages.success(request, "Голосовое сообщение сохранено.")
    else:
        messages.error(request, "Не удалось сохранить голосовое сообщение.")
    return redirect("bakery:voice")


@login_required
def voice_audio(request, pk):
    msg = get_object_or_404(VoiceMessage, pk=pk, is_deleted=False)
    if not can_view_voice(request.user, msg):
        raise PermissionDenied
    if not msg.audio_file:
        raise Http404("У этого сообщения нет аудиофайла.")
    path = msg.audio_file.path
    content_type = msg.mime_type or mimetypes.guess_type(path)[0] or "application/octet-stream"
    return FileResponse(open(path, "rb"), content_type=content_type)


@login_required
def voice_delete(request, pk):
    msg = get_object_or_404(VoiceMessage, pk=pk)
    if msg.created_by_id != request.user.id and role(request.user) != "admin":
        raise PermissionDenied
    if role(request.user) == "admin" and request.POST.get("physical") == "1":
        msg.audio_file.delete(save=False)
        msg.delete()
        messages.success(request, "Файл физически удалён.")
    else:
        msg.is_deleted = True
        msg.save(update_fields=["is_deleted", "updated_at"])
        messages.success(request, "Сообщение удалено логически.")
    return redirect("bakery:voice")


@login_required
def stock_list(request):
    items = FinishedGoodsStock.objects.select_related("product", "batch", "received_by")
    return render(request, "bakery/stock_list.html", {"items": items})


@login_required
def reports(request):
    stage_rows = ProductionBatch.objects.values("current_stage__name").annotate(total=Count("id")).order_by("current_stage__sequence")
    return render(request, "bakery/reports.html", {
        "stage_rows": stage_rows,
        "orders_by_status": ProductionOrder.objects.values("status").annotate(total=Count("id")),
        "problems_by_stage": ProductionBatch.objects.filter(status="problem").values("current_stage__name").annotate(total=Count("id")),
        "stock": FinishedGoodsStock.objects.select_related("product", "batch")[:50],
    })


@login_required
def production_sheet(request):
    """Заказ на производство: план на дату и то, что по нему выпущено.

    Бумажная форма из цеха, но со заполненными столбцами смен - партии уже
    прошли по доске с отметками времени, и остаётся сложить.

    Количество редактируется. Оно хранится отдельно от заказов покупателей
    (ProductionPlan), потому что заказ - это то, что попросили, а план - то,
    что решили печь; правка одного не должна молча менять другое. Пока плана
    нет, показывается сумма заказов на эту дату - лист остаётся осмысленным с
    первого открытия.
    """
    raw_date = request.GET.get("date", "") or request.POST.get("date", "")
    try:
        order_date = datetime.strptime(raw_date, "%Y-%m-%d").date() if raw_date else timezone.localdate()
    except ValueError:
        order_date = timezone.localdate()

    if request.method == "POST":
        saved = _save_production_plan(request, order_date)
        if request.POST.get("queue_product") or request.POST.get("queue_selected"):
            if not can_manage_orders(request.user):
                raise PermissionDenied
            try:
                order, item_count = _queue_production_plan(
                    request,
                    order_date,
                    grouped=bool(request.POST.get("queue_selected")),
                )
            except ValidationError as exc:
                messages.error(request, " ".join(exc.messages))
            else:
                messages.success(
                    request,
                    f"Партия {order.display_batch_label} создана: {item_count} позиций отправлено в очередь одним блоком.",
                )
        else:
            messages.success(request, f"Сохранено позиций: {saved}.")
        return redirect(f"{reverse('bakery:production_sheet')}?date={order_date.isoformat()}")

    shifts = shifts_for(order_date, timezone.get_current_timezone())
    products = list(Product.objects.filter(is_active=True).order_by("name").values_list("id", "name"))

    ordered = {}
    for item in (
        ProductionOrderItem.objects.filter(order__required_date__date=order_date)
        .exclude(order__status=ProductionOrder.Status.CANCELLED)
        .exclude(order__is_demo=True)
    ):
        ordered[item.product_id] = ordered.get(item.product_id, Decimal(0)) + item.quantity

    planned = dict(ordered)
    for plan in ProductionPlan.objects.filter(date=order_date):
        planned[plan.product_id] = plan.quantity

    # Партия считается выпущенной в момент перевода на "Готово" - та же отметка,
    # из которой строится карта процесса, так что лист и аналитика рассказывают
    # одну историю.
    produced = {}
    for record in (
        BatchStageHistory.objects.filter(
            to_stage__code="done",
            created_at__gte=shifts[0].start,
            created_at__lt=shifts[-1].end,
        )
        .exclude(batch__is_demo=True)
        .select_related("batch")
    ):
        column = produced.setdefault(record.batch.product_id, [Decimal(0)] * len(shifts))
        quantity = record.batch.actual_quantity
        if quantity is None:
            quantity = record.batch.planned_quantity
        for index, shift in enumerate(shifts):
            if shift.contains(record.created_at):
                column[index] += quantity
                break

    opening = {}
    for record in FinishedGoodsStock.objects.filter(
        status=FinishedGoodsStock.Status.AVAILABLE,
        created_at__lt=shifts[0].start,
    ).exclude(batch__is_demo=True):
        opening[record.product_id] = opening.get(record.product_id, Decimal(0)) + record.quantity

    rows = build_rows(products, planned, produced, opening, len(shifts))
    queued = {}
    for batch in (
        ProductionBatch.objects.filter(order_item__order__required_date__date=order_date)
        .exclude(status=ProductionBatch.Status.CANCELLED)
        .exclude(is_demo=True)
    ):
        queued[batch.product_id] = queued.get(batch.product_id, Decimal("0")) + batch.planned_quantity
    for row in rows:
        row.queued = queued.get(row.product_id, Decimal("0"))
    sheet_totals = totals(rows, len(shifts))
    sheet_totals["queued"] = sum(queued.values(), Decimal("0"))
    context = {
        "order_date": order_date,
        "previous_date": (order_date - timedelta(days=1)).isoformat(),
        "next_date": (order_date + timedelta(days=1)).isoformat(),
        "shifts": shifts,
        "rows": rows,
        "totals": sheet_totals,
        "generated_at": timezone.localtime(),
        "ordered_totals": ordered,
    }
    return render(request, "bakery/production_sheet.html", context)


def _save_production_plan(request, order_date):
    """Записывает изменённые количества. Пустое поле стирает план, а не обнуляет.

    Разница существенная: ноль - это решение не печь, пустота - это отсутствие
    решения, и тогда лист возвращается к сумме заказов.
    """
    saved = 0
    for key, raw in request.POST.items():
        if not key.startswith("plan_"):
            continue
        try:
            product_id = int(key[len("plan_"):])
        except ValueError:
            continue
        raw = raw.strip().replace(",", ".")
        if raw == "":
            ProductionPlan.objects.filter(date=order_date, product_id=product_id).delete()
            continue
        try:
            quantity = Decimal(raw)
        except InvalidOperation:
            continue
        if quantity < 0:
            continue
        ProductionPlan.objects.update_or_create(
            date=order_date,
            product_id=product_id,
            defaults={"quantity": quantity, "updated_by": request.user},
        )
        saved += 1
    return saved


@transaction.atomic
def _queue_production_plan(request, order_date, grouped=False):
    if grouped:
        raw_ids = request.POST.getlist("selected_products")
        if not raw_ids:
            raise ValidationError("Отметьте галочками хотя бы одну позицию.")
    else:
        raw_ids = [request.POST.get("queue_product", "")]

    selections = []
    seen = set()
    for raw_id in raw_ids:
        try:
            product_id = int(raw_id)
        except (TypeError, ValueError):
            raise ValidationError("Некорректно выбрана позиция.")
        if product_id in seen:
            continue
        seen.add(product_id)

        raw_quantity = request.POST.get(f"queue_quantity_{product_id}", "").strip()
        if grouped and not raw_quantity:
            # Галочка должна быть достаточна для быстрого запуска: если отдельный
            # объём партии не задан, берём видимое значение из «Количество».
            raw_quantity = request.POST.get(f"plan_{product_id}", "").strip()
        try:
            quantity = Decimal(raw_quantity.replace(",", "."))
        except (InvalidOperation, TypeError, ValueError):
            raise ValidationError("Укажите количество для каждой выбранной позиции.")
        if quantity <= 0:
            raise ValidationError("Количество новой партии должно быть больше нуля.")

        product = Product.objects.filter(pk=product_id, is_active=True).first()
        if product is None:
            raise ValidationError("Один из выбранных продуктов не найден.")
        selections.append((product, quantity))

    customer, _ = Customer.objects.get_or_create(
        name="Производство",
        defaults={"notes": "Системная запись для заказов без клиента."},
    )
    required_date = timezone.make_aware(
        datetime.combine(order_date, datetime.max.time()),
        timezone.get_current_timezone(),
    )
    order = ProductionOrder.objects.create(
        customer=customer,
        order_date=timezone.now(),
        required_date=required_date,
        priority=ProductionOrder.Priority.NORMAL,
        status=ProductionOrder.Status.DRAFT,
        notes=f"Создан из заказа на производство за {order_date:%d.%m.%Y}.",
        created_by=request.user,
        kanban_grouped=grouped,
    )
    for product, quantity in selections:
        ProductionOrderItem.objects.create(
            order=order,
            product=product,
            quantity=quantity,
            unit=product.unit,
            recipe=product.recipes.filter(is_active=True).first(),
        )
    safe_record_process_event(
        case_id=f"ORDER-{order.order_number}",
        case_type="order",
        activity="Создание заказа на производство",
        order=order,
        user=request.user,
        status=order.status,
        event_data={"production_date": order_date.isoformat()},
    )
    confirm_order(order, user=request.user)
    return order, len(selections)


@login_required
def forecast(request):
    """Сколько печь на следующей неделе, по каждому дню.

    Считается по тому же дню недели за последние недели: суббота предсказывается
    по субботам. Для хлебозавода это не упрощение, а суть - спрос живёт неделей,
    и общая средняя размазала бы выходные по будням.

    За историю берётся факт выпуска - партии, доведённые до "Готово". Не заказы:
    заказать могли и то, что не испекли, а печь по прогнозу придётся столько,
    сколько цех реально способен и обычно делает.
    """
    start = timezone.localdate() + timedelta(days=1)
    raw_start = request.GET.get("from", "")
    if raw_start:
        try:
            start = datetime.strptime(raw_start, "%Y-%m-%d").date()
        except ValueError:
            pass

    weeks = WEEKS_BACK
    try:
        weeks = max(1, min(12, int(request.GET.get("weeks", WEEKS_BACK))))
    except (TypeError, ValueError):
        pass

    since = start - timedelta(weeks=weeks + 1)
    history = {}
    for record in (
        BatchStageHistory.objects.filter(to_stage__code="done", created_at__date__gte=since)
        .exclude(batch__is_demo=True)
        .select_related("batch", "batch__product")
    ):
        quantity = record.batch.actual_quantity
        if quantity is None:
            quantity = record.batch.planned_quantity
        day = timezone.localtime(record.created_at).date()
        per_product = history.setdefault(record.batch.product.name, {})
        per_product[day] = per_product.get(day, Decimal(0)) + quantity

    days = [start + timedelta(days=step) for step in range(7)]
    prediction = predict_week(history, start, len(days), weeks)
    rows = [
        {"product": product, "points": points, "total": sum((p.quantity for p in points), Decimal(0))}
        for product, points in prediction.items()
    ]
    # Продукты, по которым за все недели ничего не выпускали, засоряли бы лист
    # нулями - показываем только те, где прогноз есть о чём делать.
    rows = [row for row in rows if row["total"] > 0]

    context = {
        "days": days,
        "rows": rows,
        "daily": daily_totals({row["product"]: row["points"] for row in rows}, len(days)),
        "grand_total": sum((row["total"] for row in rows), Decimal(0)),
        "weeks": weeks,
        "start": start,
        "previous_week": (start - timedelta(days=7)).isoformat(),
        "next_week": (start + timedelta(days=7)).isoformat(),
        "history_days": len(history),
    }
    return render(request, "bakery/forecast.html", context)
