from django.urls import path

from . import views

app_name = "bakery"

urlpatterns = [
    path("board/", views.kanban, name="kanban"),
    path("board/partial/", views.kanban_partial, name="kanban_partial"),
    path("board/events/", views.kanban_events, name="kanban_events"),
    path("batches/<int:pk>/move/", views.move_batch_view, name="move_batch"),
    path("order-groups/<int:pk>/move/", views.move_order_group_view, name="move_order_group"),
    path("batches/<int:pk>/delete/", views.delete_batch_view, name="delete_batch"),
    path("order-groups/<int:pk>/delete/", views.delete_order_group_view, name="delete_order_group"),
    path("batches/<int:pk>/<str:action>/", views.batch_action, name="batch_action"),
    path("products/", views.product_list, name="products"),
    path("products/new/", views.product_form, name="product_new"),
    path("products/<int:pk>/", views.product_detail, name="product_detail"),
    path("products/<int:pk>/edit/", views.product_form, name="product_edit"),
    path("products/<int:pk>/disable/", views.product_disable, name="product_disable"),
    path("ingredients/", views.ingredient_list, name="ingredients"),
    path("ingredients/new/", views.ingredient_form, name="ingredient_new"),
    path("ingredients/<int:pk>/edit/", views.ingredient_form, name="ingredient_edit"),
    path("recipes/", views.recipe_list, name="recipes"),
    path("recipes/new/", views.recipe_form, name="recipe_new"),
    path("recipes/<int:pk>/", views.recipe_detail, name="recipe_detail"),
    path("recipes/<int:pk>/edit/", views.recipe_form, name="recipe_edit"),
    path("production-sheet/", views.production_sheet, name="production_sheet"),
    path("forecast/", views.forecast, name="forecast"),
    path("forecast/override/", views.forecast_override, name="forecast_override"),
    path("orders/", views.order_list, name="orders"),
    path("orders/new/", views.order_form, name="order_new"),
    path("orders/<int:pk>/", views.order_detail, name="order_detail"),
    path("orders/<int:pk>/edit/", views.order_form, name="order_edit"),
    path("batches/", views.batch_list, name="batches"),
    path("batches/<int:pk>/", views.batch_detail, name="batch_detail"),
    path("voice/", views.voice_list, name="voice"),
    path("voice/upload/", views.voice_upload, name="voice_upload"),
    path("voice/<int:pk>/audio/", views.voice_audio, name="voice_audio"),
    path("voice/<int:pk>/delete/", views.voice_delete, name="voice_delete"),
    path("stock/", views.stock_list, name="stock"),
    path("reports/", views.reports, name="reports"),
]
