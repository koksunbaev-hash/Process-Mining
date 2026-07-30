from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.permissions import is_read_only_role
from apps.inspections.services import create_reinspection

from .models import CorrectiveAction, DefectType, Nonconformity, NonconformityCause
from .services import assign_corrective_action, close_nonconformity, register_nonconformity


@login_required
def nonconformity_list(request):
    items = Nonconformity.objects.select_related(
        "quality_object", "control_post", "responsible_user", "defect_type", "bakery_order", "bakery_batch", "bakery_product", "bakery_stage"
    ).filter(
        Q(bakery_order__isnull=False)
        | Q(bakery_batch__isnull=False)
        | Q(bakery_product__isnull=False)
        | Q(bakery_stage__isnull=False)
    )
    if request.GET.get("status"):
        items = items.filter(status=request.GET["status"])
    if request.GET.get("criticality"):
        items = items.filter(criticality=request.GET["criticality"])
    return render(request, "nonconformities/list.html", {"items": items})


@login_required
def nonconformity_detail(request, pk):
    item = get_object_or_404(Nonconformity.objects.select_related("quality_object", "control_post", "defect_type"), pk=pk)
    return render(request, "nonconformities/detail.html", {"item": item})


@login_required
def create_from_card(request, card_id):
    from apps.inspections.models import InspectionCard

    card = get_object_or_404(InspectionCard, pk=card_id)
    if request.method == "POST" and not is_read_only_role(request.user):
        defect_type = get_object_or_404(DefectType, pk=request.POST["defect_type"])
        cause = NonconformityCause.objects.filter(pk=request.POST.get("suspected_cause") or 0).first()
        nc = register_nonconformity(
            user=request.user,
            quality_object=card.quality_object,
            inspection_card=card,
            control_post=card.control_post,
            defect_type=defect_type,
            description=request.POST.get("description", ""),
            criticality=defect_type.criticality,
            affected_quantity=request.POST.get("affected_quantity") or 1,
            suspected_cause=cause,
            responsible_department=card.quality_object.department,
            responsible_user=card.task.assigned_to,
        )
        messages.success(request, "Несоответствие зарегистрировано.")
        return redirect("nonconformities:detail", pk=nc.pk)
    return render(request, "nonconformities/form.html", {"card": card, "defect_types": DefectType.objects.filter(is_active=True), "causes": NonconformityCause.objects.filter(is_active=True)})


@login_required
def assign_action(request, pk):
    nc = get_object_or_404(Nonconformity, pk=pk)
    if request.method == "POST" and not is_read_only_role(request.user):
        assign_corrective_action(
            nc,
            user=request.user,
            title=request.POST.get("title", "Корректирующее действие"),
            action_plan=request.POST.get("action_plan", ""),
            assigned_to_id=request.POST.get("assigned_to") or None,
        )
        messages.success(request, "Корректирующее действие назначено.")
    return redirect("nonconformities:detail", pk=pk)


@login_required
def close_item(request, pk):
    nc = get_object_or_404(Nonconformity, pk=pk)
    try:
        close_nonconformity(nc, request.user)
        messages.success(request, "Несоответствие закрыто.")
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    return redirect("nonconformities:detail", pk=pk)


@login_required
def create_reinspection_view(request, pk):
    nc = get_object_or_404(Nonconformity, pk=pk)
    try:
        create_reinspection(nc, inspector=request.user, user=request.user)
        messages.success(request, "Повторный контроль создан.")
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    return redirect("nonconformities:detail", pk=pk)


@login_required
def actions_list(request):
    actions = CorrectiveAction.objects.select_related("nonconformity", "assigned_to")
    return render(request, "nonconformities/actions.html", {"actions": actions})
