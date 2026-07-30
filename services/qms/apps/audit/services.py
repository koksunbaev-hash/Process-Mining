from django.contrib.contenttypes.models import ContentType

from .middleware import get_current_request
from .models import AuditLog, StatusHistory


def client_ip():
    request = get_current_request()
    if not request:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def write_status_history(obj, previous_status, new_status, user=None, reason=""):
    StatusHistory.objects.create(
        content_type=ContentType.objects.get_for_model(obj),
        object_id=obj.pk,
        previous_status=previous_status or "",
        new_status=new_status,
        changed_by=user if getattr(user, "is_authenticated", False) else None,
        reason=reason,
    )
    write_audit("status_change", obj, user=user, changes={"from": previous_status, "to": new_status, "reason": reason})


def write_audit(action, obj, user=None, changes=None):
    AuditLog.objects.create(
        user=user if getattr(user, "is_authenticated", False) else None,
        action=action,
        model_name=obj.__class__.__name__,
        object_id=str(getattr(obj, "pk", "")),
        object_repr=str(obj)[:240],
        changes=changes or {},
        ip_address=client_ip(),
    )
