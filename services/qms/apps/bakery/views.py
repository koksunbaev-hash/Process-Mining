import mimetypes
import os
import time

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Q
from django.http import FileResponse, Http404, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.notifications.services import notify
from apps.process_mining.services import safe_record_process_event

from .kanban_demo import can_manage_kanban_demo
from .forms import (
    CustomerForm,
    IngredientForm,
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
    ProductionOrderItem,
    ProductionStage,
    Product,
    Recipe,
    RecipeItem,
    BatchStageHistory,
    VoiceMessage,
)
from .permissions import can_manage_catalog, can_manage_orders, can_move_batch, can_view_voice, role
from .services import confirm_order, move_batch, next_stage_for, pause_batch, previous_stage_for, resume_batch


def batch_number_query(value):
    query = Q(batch_number__icontains=value)
    normalized = ProductionBatch.short_number_for(value)
    if normalized.startswith("B-") and normalized[2:].isdigit():
        query |= Q(batch_number__endswith=f"-{normalized[2:]}")
    if normalized.startswith("D-") and normalized[2:].isdigit():
        query |= Q(batch_number__iexact=f"DEMO-B-{int(normalized[2:]):04d}")
    return query


def filter_batches(request):
    qs = ProductionBatch.objects.select_related(
        "order_item__order__customer", "product", "current_stage", "assigned_to"
    ).prefetch_related("voice_messages")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            batch_number_query(q)
            | Q(product__name__icontains=q)
            | Q(order_item__order__order_number__icontains=q)
            | Q(order_item__order__customer__name__icontains=q)
        )
    for key, field in {
        "product": "product_id",
        "customer": "order_item__order__customer_id",
        "status": "status",
        "priority": "order_item__order__priority",
    }.items():
        value = request.GET.get(key)
        if value:
            qs = qs.filter(**{field: value})
    if request.GET.get("date"):
        qs = qs.filter(order_item__order__required_date__date=request.GET["date"])
    demo_filter = request.GET.get("demo", "work")
    if demo_filter == "demo":
        qs = qs.filter(is_demo=True)
    elif demo_filter == "all":
        pass
    else:
        qs = qs.filter(is_demo=False)
    return qs


def kanban_context(request):
    stages = list(ProductionStage.objects.filter(is_active=True).order_by("sequence"))
    batches = filter_batches(request)
    column_search = {stage.code: request.GET.get(f"stage_q_{stage.code}", "").strip() for stage in stages}
    columns = []
    for index, stage in enumerate(stages):
        items = batches.filter(current_stage=stage)
        if column_search[stage.code]:
            items = items.filter(Q(product__name__icontains=column_search[stage.code]) | batch_number_query(column_search[stage.code]))
        # prev_stage feeds the "← Назад" button, which exists because HTML5 drag
        # and drop fires no events from touch: on a phone or tablet the buttons
        # are the only way to move a batch at all.
        columns.append({
            "stage": stage,
            "batches": items,
            "count": items.count(),
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
        "customers": Customer.objects.filter(is_active=True),
        "statuses": ProductionBatch.Status.choices,
        "priorities": ProductionOrder.Priority.choices,
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
    # Both operands are read before move_batch runs, so neither may be None:
    # a batch on the last stage has no next stage, and a batch that never
    # entered production has no current one.
    going_back = bool(stage and batch.current_stage_id and stage.sequence < batch.current_stage.sequence)
    error = ""
    if stage is None:
        error = f"Партия {batch.batch_number} уже на последнем этапе."
    else:
        try:
            # allow_skip: dragging a card names a column, not a step. The two
            # buttons on a card can only ever reach a neighbour, so this changes
            # nothing for them; it is what lets a drag cross several columns.
            # move_batch still refuses a jump with no comment, and the drop
            # handler always sends one.
            move_batch(
                batch,
                stage,
                request.user,
                request.POST.get("comment", ""),
                require_comment=going_back,
                allow_skip=True,
            )
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
        messages.success(request, f"Партия {batch.batch_number} передана на этап {stage.name}.")
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
    items = ProductionOrder.objects.select_related("customer", "created_by").prefetch_related("items__product")
    if request.GET.get("status"):
        items = items.filter(status=request.GET["status"])
    return render(request, "bakery/order_list.html", {"items": items, "statuses": ProductionOrder.Status.choices})


@login_required
def order_detail(request, pk):
    order = get_object_or_404(ProductionOrder.objects.select_related("customer").prefetch_related("items__product", "items__recipe__items__ingredient", "items__batches__current_stage"), pk=pk)
    item_form = ProductionOrderItemForm()
    if request.method == "POST" and can_manage_orders(request.user):
        if request.POST.get("action") == "confirm":
            confirm_order(order, user=request.user)
            messages.success(request, "Заказ подтверждён, партии созданы.")
            return redirect("bakery:order_detail", pk=order.pk)
        item_form = ProductionOrderItemForm(request.POST)
        if item_form.is_valid():
            line = item_form.save(commit=False)
            line.order = order
            line.save()
            messages.success(request, "Позиция добавлена.")
            return redirect("bakery:order_detail", pk=order.pk)
    return render(request, "bakery/order_detail.html", {"order": order, "item_form": item_form})


@login_required
def order_form(request, pk=None):
    if not can_manage_orders(request.user):
        raise PermissionDenied
    item = get_object_or_404(ProductionOrder, pk=pk) if pk else None
    form = ProductionOrderForm(request.POST or None, instance=item)
    if form.is_valid():
        order = form.save(commit=False)
        created = order.pk is None
        if not order.created_by_id:
            order.created_by = request.user
        order.save()
        if created:
            safe_record_process_event(
                case_id=f"ORDER-{order.order_number}",
                case_type="order",
                activity="Создание заказа",
                order=order,
                user=request.user,
                status=order.status,
            )
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
