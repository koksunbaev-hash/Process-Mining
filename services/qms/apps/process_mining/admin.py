from django.contrib import admin

from .models import ProcessEvent, ProcessEventExport


@admin.register(ProcessEvent)
class ProcessEventAdmin(admin.ModelAdmin):
    list_display = ("event_id", "case_id", "activity", "occurred_at", "export_status", "export_attempts", "exported_at")
    list_filter = ("export_status", "case_type", "activity", "occurred_at")
    search_fields = ("event_id", "case_id", "batch__batch_number", "order__order_number")
    readonly_fields = ("event_id", "activity", "occurred_at", "created_at")


@admin.register(ProcessEventExport)
class ProcessEventExportAdmin(admin.ModelAdmin):
    list_display = ("export_id", "status", "events_count", "attempts", "response_status_code", "created_at", "finished_at")
    list_filter = ("status", "created_at")
    search_fields = ("export_id", "checksum", "last_error")
    readonly_fields = ("export_id", "checksum", "csv_content", "created_at", "started_at", "finished_at")
