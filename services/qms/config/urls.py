from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from apps.equipment.api import MeasuringEquipmentViewSet
from apps.bakery.api import (
    BatchStageHistoryViewSet,
    CustomerViewSet,
    FinishedGoodsStockViewSet,
    IngredientViewSet,
    KanbanDemoActionView,
    KanbanDemoCreateView,
    KanbanDemoStatusView,
    ProcessMiningCallbackView,
    ProductionBatchViewSet,
    ProductionOrderItemViewSet,
    ProductionOrderViewSet,
    ProductionStageViewSet,
    ProductViewSet,
    RecipeViewSet,
    VoiceCommandConfirmView,
    VoiceCommandRejectView,
    VoiceMessageViewSet,
)
from apps.inspections.api import (
    InspectionCardViewSet,
    InspectionResultViewSet,
    InspectionTaskViewSet,
    ReinspectionViewSet,
)
from apps.nonconformities.api import CorrectiveActionViewSet, NonconformityViewSet
from apps.notifications.api import NotificationViewSet
from apps.quality.api import (
    ControlParameterViewSet,
    ControlPostViewSet,
    ControlRouteViewSet,
    QualityObjectViewSet,
)

router = DefaultRouter()
router.register("quality-objects", QualityObjectViewSet)
router.register("control-posts", ControlPostViewSet)
router.register("control-parameters", ControlParameterViewSet)
router.register("routes", ControlRouteViewSet)
router.register("tasks", InspectionTaskViewSet)
router.register("inspection-cards", InspectionCardViewSet)
router.register("inspection-results", InspectionResultViewSet)
router.register("nonconformities", NonconformityViewSet)
router.register("problems", NonconformityViewSet, basename="problem")
router.register("corrective-actions", CorrectiveActionViewSet)
router.register("equipment", MeasuringEquipmentViewSet)
router.register("notifications", NotificationViewSet, basename="notification")
router.register("reinspections", ReinspectionViewSet)
router.register("products", ProductViewSet, basename="product")
router.register("ingredients", IngredientViewSet, basename="ingredient")
router.register("recipes", RecipeViewSet, basename="recipe")
router.register("customers", CustomerViewSet, basename="customer")
router.register("orders", ProductionOrderViewSet, basename="order")
router.register("order-items", ProductionOrderItemViewSet, basename="order-item")
router.register("batches", ProductionBatchViewSet, basename="batch")
router.register("production-stages", ProductionStageViewSet, basename="production-stage")
router.register("stage-history", BatchStageHistoryViewSet, basename="stage-history")
router.register("voice-messages", VoiceMessageViewSet, basename="voice-message")
router.register("finished-stock", FinishedGoodsStockViewSet, basename="finished-stock")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("apps.dashboard.urls")),
    path("bakery/", include("apps.bakery.urls")),
    path("objects/", include("apps.quality.urls")),
    path("tasks/", include("apps.inspections.urls")),
    path("nonconformities/", include("apps.nonconformities.urls")),
    path("equipment/", include("apps.equipment.urls")),
    path("reports/", include("apps.reports.urls")),
    path("notifications/", include("apps.notifications.urls")),
    path("audit/", include("apps.audit.urls")),
    path("process-mining/", include("apps.process_mining.urls")),
    path("api/", include(router.urls)),
    path("api/process-mining/callback/", ProcessMiningCallbackView.as_view(), name="process-mining-callback"),
    path("api/voice-commands/<int:pk>/confirm/", VoiceCommandConfirmView.as_view(), name="voice-command-confirm"),
    path("api/voice-commands/<int:pk>/reject/", VoiceCommandRejectView.as_view(), name="voice-command-reject"),
    path("api/kanban-demo/create/", KanbanDemoCreateView.as_view(), name="kanban-demo-create"),
    path("api/kanban-demo/<int:pk>/status/", KanbanDemoStatusView.as_view(), name="kanban-demo-status"),
    path("api/kanban-demo/<int:pk>/<str:action>/", KanbanDemoActionView.as_view(), name="kanban-demo-action"),
    path("api/auth/", include("rest_framework.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
