from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import render

from apps.accounts.permissions import user_role

from .models import AuditLog


@login_required
def audit_log_list(request):
    if user_role(request.user) not in {"admin", "manager", "director", "auditor", "production_dispatcher"}:
        raise PermissionDenied("Нет доступа к журналу действий.")
    logs = AuditLog.objects.select_related("user")
    if request.GET.get("user"):
        logs = logs.filter(user__username__icontains=request.GET["user"])
    if request.GET.get("action"):
        logs = logs.filter(action__icontains=request.GET["action"])
    if request.GET.get("path"):
        logs = logs.filter(object_repr__icontains=request.GET["path"])
    if request.GET.get("date"):
        logs = logs.filter(created_at__date=request.GET["date"])
    page_obj = Paginator(logs, 50).get_page(request.GET.get("page", 1))
    return render(request, "audit/log_list.html", {"page_obj": page_obj})
