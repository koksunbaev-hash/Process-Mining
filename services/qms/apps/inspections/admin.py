from django.contrib import admin

from .models import InspectionAttachment, InspectionCard, InspectionResult, InspectionTask, Reinspection


class InspectionResultInline(admin.TabularInline):
    model = InspectionResult
    extra = 0


@admin.register(InspectionCard)
class InspectionCardAdmin(admin.ModelAdmin):
    list_display = ("card_number", "task", "quality_object", "overall_result", "status")
    inlines = [InspectionResultInline]


admin.site.register(InspectionTask)
admin.site.register(InspectionAttachment)
admin.site.register(Reinspection)
