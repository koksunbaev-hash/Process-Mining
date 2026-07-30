import threading
from django.utils import timezone


_local = threading.local()


class CurrentRequestMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _local.request = request
        try:
            response = self.get_response(request)
            self.write_request_audit(request, response)
            return response
        finally:
            _local.request = None

    def write_request_audit(self, request, response):
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return
        if not getattr(request, "user", None) or not request.user.is_authenticated:
            return
        if request.path.startswith(("/static/", "/media/")):
            return
        if getattr(response, "status_code", 500) >= 500:
            return
        from .models import AuditLog

        excluded = {"csrfmiddlewaretoken", "password", "password1", "password2"}
        fields = {
            key: "***" if key.lower() in excluded else request.POST.getlist(key)
            for key in request.POST.keys()
        }
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
        ip_address = forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")
        AuditLog.objects.create(
            user=request.user,
            action=f"{request.method} {response.status_code}",
            model_name="HTTP",
            object_id="",
            object_repr=request.path[:240],
            changes={
                "path": request.path,
                "method": request.method,
                "status_code": response.status_code,
                "fields": fields,
                "query": request.GET.dict(),
                "at": timezone.now().isoformat(),
            },
            ip_address=ip_address,
        )


def get_current_request():
    return getattr(_local, "request", None)
