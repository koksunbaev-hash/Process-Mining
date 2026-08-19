from django.contrib import admin

from .models import (
    BatchStageHistory,
    Customer,
    FinishedGoodsStock,
    ForecastOverride,
    Ingredient,
    KanbanDemoRun,
    OrderEvent,
    ProductionBatch,
    ProductionOrder,
    ProductionOrderItem,
    ProductionStage,
    ProductionUnit,
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
    list_display = ("order_number", "display_batch_number", "batch_number_date", "status")
    list_filter = ("status", "batch_number_date")
    search_fields = ("order_number",)
    inlines = [ProductionOrderItemInline]


@admin.register(ProductionUnit)
class ProductionUnitAdmin(admin.ModelAdmin):
    """Оборудование цеха. Купленную шестую печь заводят здесь, не в коде."""

    list_display = ("name", "stage", "sequence", "status", "is_active", "twin_id")
    list_filter = ("stage", "status", "is_active")
    list_editable = ("sequence", "status", "is_active")
    search_fields = ("name", "twin_id")


@admin.register(ProductionBatch)
class ProductionBatchAdmin(admin.ModelAdmin):
    list_display = ("display_batch_number", "card_number_date", "batch_number", "product", "planned_quantity", "current_stage", "status", "assigned_to", "is_demo")
    list_filter = ("current_stage", "status", "card_number_date", "is_demo", "demo_run")
    # Видимый номер намеренно не в search_fields: admin ищет по icontains, а на
    # целочисленной колонке это падает на уровне SQL. Искать по нему есть где -
    # поиск на доске и в списке партий это умеет.
    search_fields = ("batch_number", "product__name", "order_item__order__order_number")


@admin.register(KanbanDemoRun)
class KanbanDemoRunAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "status", "mode", "total_batches", "completed_batches", "speed_seconds", "created_by", "is_active")
    list_filter = ("status", "mode", "is_active")
    search_fields = ("name", "client_request_id")


@admin.register(ForecastOverride)
class ForecastOverrideAdmin(admin.ModelAdmin):
    """Ручные правки прогноза. Снять правку - удалить строку."""

    list_display = ("product", "date", "quantity", "updated_by", "updated_at")
    list_filter = ("date",)
    search_fields = ("product__name",)


admin.site.register(ProductionStage)
admin.site.register(BatchStageHistory)
admin.site.register(FinishedGoodsStock)
admin.site.register(VoiceMessage)
admin.site.register(VoiceCommand)
admin.site.register(OrderEvent)
