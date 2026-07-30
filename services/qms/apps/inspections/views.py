from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.accounts.permissions import is_read_only_role
from apps.equipment.models import MeasuringEquipment
from apps.nonconformities.models import DefectType

from .models import InspectionAttachment, InspectionCard, InspectionTask
from .services import complete_card, start_task


def parse_decimal_input(value, label):
    if value in (None, ""):
        return None
    normalized = value.strip().replace(" ", "").replace(",", ".")
    try:
        return Decimal(normalized)
    except (InvalidOperation, ValueError):
        raise ValidationError(f"Поле «{label}» должно быть числом. Пример: 50 или 50,5.")


@login_required
def task_list(request):
    tasks = InspectionTask.objects.select_related("quality_object", "control_post", "assigned_to")
    tab = request.GET.get("tab", "")
    if tab:
        if tab == "overdue":
            tasks = tasks.filter(due_at__lt=timezone.now()).exclude(status__in=["completed", "cancelled"])
        elif tab == "reinspection":
            tasks = tasks.filter(status="awaiting_reinspection")
        else:
            tasks = tasks.filter(status=tab)
    return render(request, "inspections/task_list.html", {"tasks": tasks, "tab": tab})


@login_required
def task_detail(request, pk):
    task = get_object_or_404(
        InspectionTask.objects.select_related("quality_object", "control_post", "assigned_to"),
        pk=pk,
    )
    return render(request, "inspections/task_detail.html", {"task": task})


@login_required
def task_start(request, pk):
    if request.method != "POST":
        return redirect("inspections:task_detail", pk=pk)
    if is_read_only_role(request.user):
        messages.error(request, "Ваша роль доступна только для просмотра.")
        return redirect("inspections:task_detail", pk=pk)
    task = get_object_or_404(InspectionTask, pk=pk)
    try:
        card = start_task(task, request.user)
        messages.success(request, "Карта контроля открыта.")
        return redirect("inspections:card_detail", pk=card.pk)
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
        return redirect("inspections:task_detail", pk=pk)


@login_required
def card_list(request):
    cards = InspectionCard.objects.select_related("task", "quality_object", "control_post", "inspector")
    return render(request, "inspections/card_list.html", {"cards": cards})


@login_required
def card_detail(request, pk):
    card = get_object_or_404(
        InspectionCard.objects.select_related("task", "quality_object", "control_post", "inspector")
        .prefetch_related("results__parameter", "results__template_parameter", "attachments"),
        pk=pk,
    )
    equipment = MeasuringEquipment.objects.filter(is_active=True, status="available").order_by("name")
    defect_types = DefectType.objects.filter(is_active=True)
    return render(
        request,
        "inspections/card_detail.html",
        {"card": card, "equipment": equipment, "defect_types": defect_types},
    )


@login_required
def card_save(request, pk):
    card = get_object_or_404(InspectionCard.objects.prefetch_related("results__parameter"), pk=pk)
    if request.method != "POST" or is_read_only_role(request.user):
        return redirect("inspections:card_detail", pk=pk)
    try:
        for result in card.results.select_related("parameter", "template_parameter"):
            prefix = f"result_{result.pk}_"
            if result.parameter.value_type == "number":
                value = request.POST.get(prefix + "numeric_value")
                result.numeric_value = parse_decimal_input(value, result.parameter.name)
            elif result.parameter.value_type == "boolean":
                result.boolean_value = request.POST.get(prefix + "boolean_value") == "on"
            elif result.parameter.value_type == "conformity":
                result.conformity_value = request.POST.get(prefix + "conformity_value") == "on"
            else:
                result.text_value = request.POST.get(prefix + "text_value", "")
            result.comment = request.POST.get(prefix + "comment", "")
            equipment_id = request.POST.get(prefix + "equipment")
            result.measuring_equipment_id = equipment_id or None
            result.full_clean()
            result.save()
        card.comments = request.POST.get("comments", "")
        card.save(update_fields=["comments", "updated_at"])
        for uploaded_file in request.FILES.getlist("attachments"):
            InspectionAttachment.objects.create(
                inspection_card=card,
                file=uploaded_file,
                file_type=request.POST.get("attachment_type", "photo"),
                title=uploaded_file.name,
                comment=request.POST.get("attachment_comment", ""),
                uploaded_by=request.user,
            )
        messages.success(request, "Черновик карты сохранён.")
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    return redirect("inspections:card_detail", pk=pk)


@login_required
def card_complete(request, pk):
    if request.method != "POST":
        return redirect("inspections:card_detail", pk=pk)
    if is_read_only_role(request.user):
        messages.error(request, "Ваша роль доступна только для просмотра.")
        return redirect("inspections:card_detail", pk=pk)
    card = get_object_or_404(InspectionCard, pk=pk)
    try:
        complete_card(card, request.user)
        messages.success(request, "Карта контроля завершена.")
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    return redirect("inspections:card_detail", pk=pk)
