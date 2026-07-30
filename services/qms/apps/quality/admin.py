from django.contrib import admin

from .models import (
    ControlParameter,
    ControlPost,
    ControlRoute,
    ControlRouteStep,
    ControlType,
    Department,
    InspectionTemplate,
    InspectionTemplateParameter,
    NormativeDocument,
    QualityObject,
)


class InspectionTemplateParameterInline(admin.TabularInline):
    model = InspectionTemplateParameter
    extra = 0


class ControlRouteStepInline(admin.TabularInline):
    model = ControlRouteStep
    extra = 0


@admin.register(InspectionTemplate)
class InspectionTemplateAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "control_post", "version", "is_active")
    inlines = [InspectionTemplateParameterInline]


@admin.register(ControlRoute)
class ControlRouteAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "product_type", "is_active")
    inlines = [ControlRouteStepInline]


admin.site.register(Department)
admin.site.register(ControlType)
admin.site.register(ControlPost)
admin.site.register(ControlParameter)
admin.site.register(NormativeDocument)
admin.site.register(QualityObject)
