from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.accounts.permissions import user_role

from .console_token import console_link
from .models import ProcessEvent, ProcessEventExport
from .services import build_events_csv, export_pending_events_to_process_mining, retry_failed_events


def can_view_integration(user):
    return bool(user and user.is_authenticated and user_role(user) in {"admin", "manager"})


@login_required
def dashboard(request):
    if not can_view_integration(request.user):
        raise PermissionDenied
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "export_now":
            result = export_pending_events_to_process_mining()
            messages.success(request, f"Экспорт обработал событий: {result['events_count']}")
        elif action == "retry_failed":
            count = retry_failed_events()
            messages.success(request, f"Возвращено в очередь: {count}")
        elif action == "check_connection":
            messages.info(request, "URL настроен." if settings.PROCESS_MINING_EVENT_LOG_URL else "PROCESS_MINING_EVENT_LOG_URL не настроен.")
        return redirect("process_mining:dashboard")
    counts = {item["export_status"]: item["total"] for item in ProcessEvent.objects.values("export_status").annotate(total=Count("id"))}
    last_success = ProcessEventExport.objects.filter(status__in=[ProcessEventExport.Status.ACCEPTED, ProcessEventExport.Status.PARTIALLY_ACCEPTED]).order_by("-finished_at").first()
    last_export = ProcessEventExport.objects.order_by("-created_at").first()
    return render(
        request,
        "process_mining/dashboard.html",
        {
            "url": settings.PROCESS_MINING_EVENT_LOG_URL,
            "console_url": console_link(),
            "source": settings.PROCESS_MINING_SOURCE,
            "counts": counts,
            "last_success": last_success,
            "last_export": last_export,
            "exports": ProcessEventExport.objects.all()[:20],
        },
    )


@login_required
def download_last_csv(request):
    if not can_view_integration(request.user):
        raise PermissionDenied
    events = ProcessEvent.objects.select_related("user", "product", "batch", "order").order_by("occurred_at", "id")
    if not events.exists():
        return HttpResponse("Событий для CSV пока нет.", status=404)

    csv_content = build_events_csv(events.iterator())
    file_name = f"kms_process_events_{timezone.now():%Y%m%d_%H%M%S}.csv"
    # BOM lets Excel detect UTF-8 correctly when the CSV contains Cyrillic.
    response = HttpResponse("\ufeff" + csv_content, content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{file_name}"'
    return response
