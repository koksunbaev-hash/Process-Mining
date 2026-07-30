from rest_framework import serializers, viewsets

from apps.accounts.permissions import RolePermission

from .models import InspectionCard, InspectionResult, InspectionTask, Reinspection


class InspectionTaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = InspectionTask
        fields = "__all__"
        read_only_fields = ["task_number", "created_at"]


class InspectionCardSerializer(serializers.ModelSerializer):
    class Meta:
        model = InspectionCard
        fields = "__all__"
        read_only_fields = ["card_number", "created_at", "updated_at"]


class InspectionResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = InspectionResult
        fields = "__all__"

    def validate(self, attrs):
        instance = InspectionResult(**attrs)
        instance.clean()
        return attrs


class ReinspectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Reinspection
        fields = "__all__"
        read_only_fields = ["number"]


class InspectionTaskViewSet(viewsets.ModelViewSet):
    queryset = InspectionTask.objects.select_related("quality_object", "control_post", "assigned_to")
    serializer_class = InspectionTaskSerializer
    permission_classes = [RolePermission]
    filterset_fields = ["status", "control_post", "assigned_to", "is_overdue"]


class InspectionCardViewSet(viewsets.ModelViewSet):
    queryset = InspectionCard.objects.select_related("task", "quality_object", "control_post", "inspector")
    serializer_class = InspectionCardSerializer
    permission_classes = [RolePermission]
    filterset_fields = ["status", "overall_result", "control_post", "inspector"]


class InspectionResultViewSet(viewsets.ModelViewSet):
    queryset = InspectionResult.objects.select_related("inspection_card", "parameter", "measuring_equipment")
    serializer_class = InspectionResultSerializer
    permission_classes = [RolePermission]
    filterset_fields = ["inspection_card", "parameter", "is_within_tolerance"]


class ReinspectionViewSet(viewsets.ModelViewSet):
    queryset = Reinspection.objects.select_related("nonconformity", "quality_object", "inspector")
    serializer_class = ReinspectionSerializer
    permission_classes = [RolePermission]
    filterset_fields = ["result", "inspector"]
