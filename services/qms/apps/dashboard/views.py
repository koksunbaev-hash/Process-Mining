from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import render
from django.utils import timezone

from apps.inspections.models import InspectionTask
from apps.bakery.models import ProductionBatch, ProductionOrder, ProductionStage
from apps.nonconformities.models import Nonconformity
from apps.quality.models import ControlPost, QualityObject


@login_required
def index(request):
    now = timezone.now()
    if ProductionStage.objects.exists() or ProductionBatch.objects.exists():
        batches = ProductionBatch.objects.select_related("current_stage")
        context = {
            "new_orders": ProductionOrder.objects.filter(status__in=["draft", "confirmed"]).count(),
            "queue": batches.filter(current_stage__code="queue").count(),
            "mixing": batches.filter(current_stage__code="mixing").count(),
            "forming": batches.filter(current_stage__code="forming").count(),
            "proofing": batches.filter(current_stage__code="proofing").count(),
            "oven": batches.filter(current_stage__code="oven").count(),
            "warehouse": batches.filter(current_stage__code="warehouse").count(),
            "done_today": batches.filter(current_stage__code="done", actual_finish__date=timezone.localdate()).count(),
            "overdue_orders": ProductionOrder.objects.filter(required_date__lt=now).exclude(status__in=["ready", "shipped", "cancelled"]).count(),
            "problem_batches": batches.filter(status="problem").count(),
            "stage_counts": list(batches.values("current_stage__name").annotate(total=Count("id")).order_by("current_stage__sequence")),
            "latest_nc": Nonconformity.objects.select_related("bakery_batch", "bakery_product", "defect_type")[:6],
            "bakery_dashboard": True,
        }
        return render(request, "dashboard/index.html", context)
    tasks = InspectionTask.objects.all()
    nonconformities = Nonconformity.objects.all()
    total_completed = tasks.filter(status="completed").count()
    first_pass = total_completed
    cards_with_deviation = tasks.filter(card__results__is_within_tolerance=False).distinct().count()
    if total_completed:
        first_pass = max(total_completed - cards_with_deviation, 0)
    context = {
        "awaiting": QualityObject.objects.filter(quality_status="awaiting_control").count(),
        "in_work": tasks.filter(status="in_progress").count(),
        "overdue": tasks.filter(due_at__lt=now).exclude(status__in=["completed", "cancelled"]).count(),
        "open_nc": nonconformities.exclude(status__in=["closed", "rejected"]).count(),
        "critical_nc": nonconformities.filter(criticality="critical").exclude(status__in=["closed", "rejected"]).count(),
        "quarantine": QualityObject.objects.filter(quality_status__in=["quarantine", "blocked"]).count(),
        "reinspection": tasks.filter(status="awaiting_reinspection").count(),
        "first_pass_rate": round(first_pass / total_completed * 100, 1) if total_completed else 100,
        "avg_control_time": "45 мин",
        "posts": ControlPost.objects.annotate(
            queue_count=Count("inspectiontask", filter=Q(inspectiontask__status__in=["new", "assigned"])),
            active_count=Count("inspectiontask", filter=Q(inspectiontask__status="in_progress")),
        ),
        "latest_nc": nonconformities.select_related("quality_object", "defect_type")[:6],
        "overdue_actions": [],
        "severity_counts": list(nonconformities.values("criticality").annotate(total=Count("id"))),
    }
    return render(request, "dashboard/index.html", context)
