from django.contrib import admin

from .models import AuditLog, StatusHistory


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "action", "model_name", "object_repr", "ip_address")
    list_filter = ("action", "model_name", "created_at")
    search_fields = ("user__username", "object_repr", "model_name", "object_id")
    readonly_fields = ("user", "action", "model_name", "object_id", "object_repr", "changes", "ip_address", "created_at")


@admin.register(StatusHistory)
class StatusHistoryAdmin(admin.ModelAdmin):
    list_display = ("changed_at", "content_type", "object_id", "previous_status", "new_status", "changed_by")
    list_filter = ("content_type", "new_status", "changed_at")
    search_fields = ("object_id", "reason")
