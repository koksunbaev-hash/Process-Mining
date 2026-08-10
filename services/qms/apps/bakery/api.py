import json
import hmac
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404
from django.utils import timezone
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied as ApiPermissionDenied, ValidationError as ApiValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .kanban_demo import (
    can_manage_kanban_demo,
    create_demo_run,
    demo_status,
    pause_demo,
    reset_demo,
    start_demo,
    stop_demo,
    tick_demo,
)
from .models import (
    BatchStageHistory,
    Customer,
    FinishedGoodsStock,
    Ingredient,
    KanbanDemoRun,
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
from .permissions import BakeryPermission, can_view_voice
from .services import confirm_order, move_batch, next_stage_for
from apps.process_mining.services import safe_record_process_event
from .voice_process_mining import (
    ConflictError,
    confirm_voice_command,
    create_voice_command,
    handle_process_mining_callback,
    may_auto_confirm,
    reject_voice_command,
    resolve_batch,
    send_voice_to_process_mining,
    verify_process_mining_signature,
)


def _bearer_token(request):
    value = request.headers.get("Authorization", "")
    if value.lower().startswith("bearer "):
        return value.split(" ", 1)[1].strip()
    return request.headers.get("X-PushToTalk-Token", "").strip()


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = "__all__"


class IngredientSerializer(serializers.ModelSerializer):
    is_low_stock = serializers.BooleanField(read_only=True)

    class Meta:
        model = Ingredient
        fields = "__all__"


class RecipeItemSerializer(serializers.ModelSerializer):
    ingredient_name = serializers.CharField(source="ingredient.name", read_only=True)
    unit = serializers.CharField(source="ingredient.unit", read_only=True)

    class Meta:
        model = RecipeItem
        fields = "__all__"


class RecipeSerializer(serializers.ModelSerializer):
    items = RecipeItemSerializer(many=True, read_only=True)

    class Meta:
        model = Recipe
        fields = "__all__"


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = "__all__"


class ProductionOrderItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = ProductionOrderItem
        fields = "__all__"


class ProductionOrderSerializer(serializers.ModelSerializer):
    items = ProductionOrderItemSerializer(many=True, read_only=True)

    class Meta:
        model = ProductionOrder
        fields = "__all__"


class ProductionStageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductionStage
        fields = "__all__"


class BatchStageHistorySerializer(serializers.ModelSerializer):
    from_stage_name = serializers.CharField(source="from_stage.name", read_only=True)
    to_stage_name = serializers.CharField(source="to_stage.name", read_only=True)

    class Meta:
        model = BatchStageHistory
        fields = "__all__"


class ProductionBatchSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    stage_name = serializers.CharField(source="current_stage.name", read_only=True)
    order_number = serializers.CharField(source="order_item.order.order_number", read_only=True)

    class Meta:
        model = ProductionBatch
        fields = "__all__"


class VoiceMessageSerializer(serializers.ModelSerializer):
    audio_url = serializers.SerializerMethodField()
    command_id = serializers.IntegerField(source="command.id", read_only=True)

    class Meta:
        model = VoiceMessage
        fields = "__all__"
        read_only_fields = (
            "created_by",
            "original_filename",
            "mime_type",
            "file_size",
            "external_task_id",
            "processing_error",
            "processed_at",
            "confidence",
        )

    def get_audio_url(self, obj):
        return f"/bakery/voice/{obj.pk}/audio/"

    def validate_audio_file(self, value):
        self.instance = self.instance or VoiceMessage()
        self.instance.original_filename = value.name
        self.instance.mime_type = getattr(value, "content_type", "") or ""
        self.instance.file_size = value.size
        self.instance.audio_file = value
        self.instance.clean()
        return value

    def create(self, validated_data):
        file = validated_data.get("audio_file")
        validated_data["original_filename"] = file.name
        validated_data["mime_type"] = getattr(file, "content_type", "") or ""
        validated_data["file_size"] = file.size
        validated_data["created_by"] = self.context["request"].user
        obj = super().create(validated_data)
        obj.clean()
        return obj


class FinishedGoodsStockSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    batch_number = serializers.CharField(source="batch.batch_number", read_only=True)

    class Meta:
        model = FinishedGoodsStock
        fields = "__all__"


class KanbanDemoRunSerializer(serializers.ModelSerializer):
    progress_percent = serializers.SerializerMethodField()

    class Meta:
        model = KanbanDemoRun
        fields = "__all__"
        read_only_fields = ("created_by", "completed_batches", "started_at", "paused_at", "finished_at", "last_error")

    def get_progress_percent(self, obj):
        return int((obj.completed_batches / obj.total_batches) * 100) if obj.total_batches else 0


class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    permission_classes = [BakeryPermission]
    filterset_fields = ["category", "is_active"]
    search_fields = ["code", "name"]


class IngredientViewSet(viewsets.ModelViewSet):
    queryset = Ingredient.objects.all()
    serializer_class = IngredientSerializer
    permission_classes = [BakeryPermission]
    filterset_fields = ["unit", "is_active"]
    search_fields = ["code", "name", "supplier"]


class RecipeViewSet(viewsets.ModelViewSet):
    queryset = Recipe.objects.select_related("product", "approved_by").prefetch_related("items__ingredient")
    serializer_class = RecipeSerializer
    permission_classes = [BakeryPermission]
    filterset_fields = ["product", "is_active"]


class CustomerViewSet(viewsets.ModelViewSet):
    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer
    permission_classes = [BakeryPermission]
    search_fields = ["name", "phone", "email"]


class ProductionOrderViewSet(viewsets.ModelViewSet):
    queryset = ProductionOrder.objects.select_related("customer", "created_by").prefetch_related("items")
    serializer_class = ProductionOrderSerializer
    permission_classes = [BakeryPermission]
    filterset_fields = ["status", "priority", "customer"]
    search_fields = ["order_number", "customer__name"]

    def perform_create(self, serializer):
        order = serializer.save(created_by=self.request.user)
        safe_record_process_event(
            case_id=f"ORDER-{order.order_number}",
            case_type="order",
            activity="Создание заказа",
            order=order,
            user=self.request.user,
            status=order.status,
        )

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        batches = confirm_order(self.get_object(), user=request.user)
        return Response({"created_batches": [batch.pk for batch in batches]})


class ProductionOrderItemViewSet(viewsets.ModelViewSet):
    queryset = ProductionOrderItem.objects.select_related("order", "product", "recipe")
    serializer_class = ProductionOrderItemSerializer
    permission_classes = [BakeryPermission]
    filterset_fields = ["order", "product"]


class ProductionBatchViewSet(viewsets.ModelViewSet):
    queryset = ProductionBatch.objects.select_related("order_item__order__customer", "product", "recipe", "current_stage", "assigned_to")
    serializer_class = ProductionBatchSerializer
    permission_classes = [BakeryPermission]
    filterset_fields = ["status", "current_stage", "product", "assigned_to", "is_demo", "demo_run"]
    search_fields = ["batch_number", "order_item__order__order_number", "product__name"]

    @action(detail=True, methods=["post"])
    def next_stage(self, request, pk=None):
        batch = self.get_object()
        stage = next_stage_for(batch)
        if not stage:
            return Response({"detail": "Следующего этапа нет."}, status=400)
        try:
            move_batch(batch, stage, request.user, request.data.get("comment", ""))
        except PermissionDenied as exc:
            raise ApiPermissionDenied(str(exc))
        except ValidationError as exc:
            raise ApiValidationError({"detail": exc.messages})
        batch.refresh_from_db()
        return Response(self.get_serializer(batch).data)

    @action(detail=True, methods=["post"])
    def move(self, request, pk=None):
        batch = self.get_object()
        stage = ProductionStage.objects.get(pk=request.data["stage"])
        try:
            move_batch(batch, stage, request.user, request.data.get("comment", ""), require_comment=stage.sequence < batch.current_stage.sequence)
        except PermissionDenied as exc:
            raise ApiPermissionDenied(str(exc))
        except ValidationError as exc:
            raise ApiValidationError({"detail": exc.messages})
        batch.refresh_from_db()
        return Response(self.get_serializer(batch).data)


class ProductionStageViewSet(viewsets.ModelViewSet):
    queryset = ProductionStage.objects.all()
    serializer_class = ProductionStageSerializer
    permission_classes = [BakeryPermission]


class BatchStageHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = BatchStageHistory.objects.select_related("batch", "from_stage", "to_stage", "changed_by")
    serializer_class = BatchStageHistorySerializer
    permission_classes = [BakeryPermission]
    filterset_fields = ["batch", "from_stage", "to_stage", "changed_by"]


class VoiceMessageViewSet(viewsets.ModelViewSet):
    queryset = VoiceMessage.objects.select_related("created_by", "order", "batch", "product", "stage").filter(is_deleted=False)
    serializer_class = VoiceMessageSerializer
    permission_classes = [BakeryPermission]
    parser_classes = [MultiPartParser, FormParser]
    filterset_fields = ["created_by", "order", "batch", "product", "stage"]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user.is_authenticated:
            return qs.none()
        role = getattr(getattr(user, "profile", None), "role", None)
        if user.is_superuser or role in {"admin", "production_dispatcher", "manager", "director", "quality_manager", "auditor", "technologist"}:
            return qs
        return qs.filter(created_by=user)

    def create(self, request, *args, **kwargs):
        client_request_id = request.data.get("client_request_id")
        if client_request_id:
            existing = VoiceMessage.objects.filter(client_request_id=client_request_id).first()
            if existing:
                if not can_view_voice(request.user, existing):
                    raise ApiPermissionDenied("Нет доступа к голосовому сообщению.")
                return Response(self.get_serializer(existing).data)
        response = super().create(request, *args, **kwargs)
        voice = VoiceMessage.objects.get(pk=response.data["id"])
        send_voice_to_process_mining(voice)
        return Response(self.get_serializer(voice).data, status=response.status_code)

    @action(detail=True, methods=["get"])
    def status(self, request, pk=None):
        voice = self.get_object()
        payload = {
            "id": voice.pk,
            "status": voice.transcription_status,
            "transcript": voice.transcript,
            "confidence": float(voice.confidence) if voice.confidence is not None else None,
            "processing_error": voice.processing_error,
            "command": None,
        }
        command = getattr(voice, "command", None)
        if command:
            data = dict(command.extracted_data)
            batch = resolve_batch(data)
            if batch:
                data["batch_id"] = batch.pk
                data["current_stage"] = batch.current_stage.name
                data["current_stage_code"] = batch.current_stage.code
                data["from_stage"] = data.get("from_stage") or batch.current_stage.code
                if data.get("to_stage"):
                    data["next_stage"] = ProductionStage.objects.filter(code=data["to_stage"]).values_list("name", flat=True).first()
            payload["command"] = {
                "id": command.pk,
                "intent": command.intent,
                "status": command.status,
                "confidence": float(command.confidence) if command.confidence is not None else None,
                "extracted_data": data,
                # Whether the widget may run this on a countdown rather than a
                # click. Decided here, not in the browser: it depends on stage
                # order, which the widget has no way of knowing.
                "auto_confirm": may_auto_confirm(command, batch),
                "auto_confirm_seconds": settings.VOICE_AUTOCONFIRM_SECONDS,
            }
        return Response(payload)

    def perform_destroy(self, instance):
        instance.is_deleted = True
        instance.save(update_fields=["is_deleted", "updated_at"])


class ProcessMiningCallbackView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        raw_body = request.body
        if not verify_process_mining_signature(raw_body, request.headers):
            raise ApiPermissionDenied("Неверная подпись callback.")
        payload = json.loads(raw_body.decode("utf-8") or "{}")
        with transaction.atomic():
            voice, command = handle_process_mining_callback(payload)
            user = voice.created_by
            if not user and settings.PUSHTOTALK_DEFAULT_USERNAME:
                user = get_user_model().objects.filter(username=settings.PUSHTOTALK_DEFAULT_USERNAME).first()
            if command and user and command.status == VoiceCommand.Status.DETECTED:
                try:
                    command = confirm_voice_command(command, user)
                except (ConflictError, PermissionDenied, ValidationError, Http404) as exc:
                    command.status = VoiceCommand.Status.NEEDS_REVIEW
                    command.error_message = str(exc)
                    command.extracted_data["review_reason"] = str(exc)
                    command.save(update_fields=["status", "error_message", "extracted_data", "updated_at"])
        return Response({"ok": True, "voice_message_id": voice.pk, "command_id": command.pk if command else None})


class VoiceCommandConfirmView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        command = VoiceCommand.objects.select_related("voice_message").get(pk=pk)
        if not can_view_voice(request.user, command.voice_message):
            raise ApiPermissionDenied("Нет доступа к голосовой команде.")
        try:
            command = confirm_voice_command(command, request.user)
        except ConflictError as exc:
            return Response({"detail": str(exc)}, status=409)
        except PermissionDenied as exc:
            raise ApiPermissionDenied(str(exc))
        except ValidationError as exc:
            raise ApiValidationError({"detail": exc.messages})
        except Http404 as exc:
            return Response({"detail": str(exc)}, status=404)
        return Response({"id": command.pk, "status": command.status, "executed_at": command.executed_at})


class VoiceCommandRejectView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        command = VoiceCommand.objects.select_related("voice_message").get(pk=pk)
        try:
            command = reject_voice_command(command, request.user)
        except PermissionDenied as exc:
            raise ApiPermissionDenied(str(exc))
        return Response({"id": command.pk, "status": command.status})


class PushToTalkTextCommandView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        expected_token = getattr(settings, "PUSHTOTALK_API_TOKEN", "")
        if not expected_token:
            return Response({"detail": "PUSHTOTALK_API_TOKEN не настроен."}, status=503)
        if not hmac.compare_digest(_bearer_token(request), expected_token):
            raise ApiPermissionDenied("Неверный PushToTalk API token.")

        text = str(request.data.get("text", "")).strip()
        if not text:
            return Response({"detail": "text обязателен."}, status=400)

        client_request_id = str(request.data.get("client_request_id", "")).strip() or None
        if client_request_id:
            existing = VoiceMessage.objects.filter(client_request_id=client_request_id).first()
            if existing:
                command = getattr(existing, "command", None)
                return Response(
                    {
                        "status": "ok",
                        "voice_message_id": existing.pk,
                        "command_id": command.pk if command else None,
                        "duplicate": True,
                    }
                )

        user = None
        username = getattr(settings, "PUSHTOTALK_DEFAULT_USERNAME", "")
        if username:
            user = get_user_model().objects.filter(username=username).first()

        confidence = Decimal(str(request.data.get("confidence") or getattr(settings, "PUSHTOTALK_COMMAND_CONFIDENCE", 0.90)))
        with transaction.atomic():
            voice = VoiceMessage.objects.create(
                audio_file="",
                original_filename="pushtotalk-text",
                mime_type="text/plain",
                file_size=0,
                created_by=user,
                transcript=text,
                transcription_status=VoiceMessage.TranscriptionStatus.COMPLETED,
                confidence=confidence,
                client_request_id=client_request_id,
                processed_at=timezone.now(),
                comment=str(request.data.get("source", "pushtotalk")),
            )
            command = create_voice_command(voice)
        executed = False
        if command and user and command.status == VoiceCommand.Status.DETECTED:
            try:
                command = confirm_voice_command(command, user)
                executed = command.status == VoiceCommand.Status.EXECUTED
            except ConflictError as exc:
                return Response({"detail": str(exc), "voice_message_id": voice.pk, "command_id": command.pk}, status=409)
            except PermissionDenied as exc:
                raise ApiPermissionDenied(str(exc))
            except ValidationError as exc:
                raise ApiValidationError({"detail": exc.messages})
            except Http404 as exc:
                return Response({"detail": str(exc), "voice_message_id": voice.pk, "command_id": command.pk}, status=404)
        return Response(
            {
                "status": "ok",
                "voice_message_id": voice.pk,
                "command_id": command.pk if command else None,
                "command_status": command.status if command else None,
                "executed": executed,
            },
            status=201,
        )


class FinishedGoodsStockViewSet(viewsets.ModelViewSet):
    queryset = FinishedGoodsStock.objects.select_related("product", "batch", "received_by")
    serializer_class = FinishedGoodsStockSerializer
    permission_classes = [BakeryPermission]
    filterset_fields = ["product", "batch", "status", "received_by"]


class KanbanDemoCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not can_manage_kanban_demo(request.user):
            raise ApiPermissionDenied("Нет права управлять Kanban demo.")

        def as_bool(value):
            return value is True or str(value).lower() in {"1", "true", "yes", "on"}

        if as_bool(request.data.get("reset", False)):
            for run in list(KanbanDemoRun.objects.all()):
                reset_demo(run, request.user)
        run = create_demo_run(
            user=request.user,
            count=int(request.data.get("count") or 100),
            name=request.data.get("name") or "Kanban demo",
            speed_seconds=request.data.get("speed_seconds") or 2,
            mode=request.data.get("mode") or KanbanDemoRun.Mode.WAVE,
            client_request_id=request.data.get("client_request_id"),
            simulate_pauses=as_bool(request.data.get("simulate_pauses", False)),
            simulate_problems=as_bool(request.data.get("simulate_problems", False)),
            simulate_returns=as_bool(request.data.get("simulate_returns", False)),
        )
        return Response(demo_status(run), status=201)


class KanbanDemoActionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, action):
        if not can_manage_kanban_demo(request.user):
            raise ApiPermissionDenied("Нет права управлять Kanban demo.")
        run = KanbanDemoRun.objects.get(pk=pk)
        try:
            if action == "start":
                start_demo(run, request.user)
                payload = demo_status(run)
            elif action == "pause":
                pause_demo(run, request.user)
                payload = demo_status(run)
            elif action == "resume":
                start_demo(run, request.user)
                payload = demo_status(run)
            elif action == "stop":
                stop_demo(run, request.user)
                payload = demo_status(run)
            elif action == "tick":
                payload = tick_demo(run, request.user)
            elif action == "reset":
                payload = reset_demo(run, request.user)
            else:
                return Response({"detail": "Неизвестное действие."}, status=404)
        except PermissionDenied as exc:
            raise ApiPermissionDenied(str(exc))
        except ValidationError as exc:
            raise ApiValidationError({"detail": exc.messages})
        return Response(payload)


class KanbanDemoStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        if not can_manage_kanban_demo(request.user):
            raise ApiPermissionDenied("Нет права управлять Kanban demo.")
        return Response(demo_status(KanbanDemoRun.objects.get(pk=pk)))
