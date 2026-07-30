from django.contrib import admin

from .models import (
    BatchStageHistory,
    Customer,
    FinishedGoodsStock,
    Ingredient,
    KanbanDemoRun,
    OrderEvent,
    ProductionBatch,
    ProductionOrder,
    ProductionOrderItem,
    ProductionStage,
    Product,
    Recipe,
    RecipeItem,
    VoiceCommand,
    VoiceMessage,
)


class RecipeItemInline(admin.TabularInline):
    model = RecipeItem
    extra = 1


class ProductionOrderItemInline(admin.TabularInline):
    model = ProductionOrderItem
    extra = 1


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "category", "unit", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("code", "name")


@admin.register(Ingredient)
class IngredientAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "unit", "current_stock", "minimum_stock", "supplier", "is_active")
    list_filter = ("unit", "is_active")
    search_fields = ("code", "name", "supplier")


@admin.register(Recipe)
class RecipeAdmin(admin.ModelAdmin):
    list_display = ("product", "version", "output_quantity", "output_unit", "is_active", "approved_at")
    list_filter = ("is_active", "output_unit")
    search_fields = ("product__name", "name", "version")
    inlines = [RecipeItemInline]


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "email", "is_active")
    search_fields = ("name", "phone", "email")


@admin.register(ProductionOrder)
class ProductionOrderAdmin(admin.ModelAdmin):
    list_display = ("order_number", "customer", "required_date", "priority", "status")
    list_filter = ("priority", "status")
    search_fields = ("order_number", "customer__name")
    inlines = [ProductionOrderItemInline]


@admin.register(ProductionBatch)
class ProductionBatchAdmin(admin.ModelAdmin):
    list_display = ("batch_number", "product", "planned_quantity", "current_stage", "status", "assigned_to", "is_demo")
    list_filter = ("current_stage", "status", "is_demo", "demo_run")
    search_fields = ("batch_number", "product__name", "order_item__order__order_number")


@admin.register(KanbanDemoRun)
class KanbanDemoRunAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "status", "mode", "total_batches", "completed_batches", "speed_seconds", "created_by", "is_active")
    list_filter = ("status", "mode", "is_active")
    search_fields = ("name", "client_request_id")


admin.site.register(ProductionStage)
admin.site.register(BatchStageHistory)
admin.site.register(FinishedGoodsStock)
admin.site.register(VoiceMessage)
admin.site.register(VoiceCommand)
admin.site.register(OrderEvent)
