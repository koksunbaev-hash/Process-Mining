from rest_framework import serializers, viewsets

from apps.accounts.permissions import RolePermission

from .models import CorrectiveAction, Nonconformity


class NonconformitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Nonconformity
        fields = "__all__"
        read_only_fields = ["number", "created_at", "updated_at", "detected_by"]

    def create(self, validated_data):
        from .services import register_nonconformity

        return register_nonconformity(user=self.context["request"].user, **validated_data)


class CorrectiveActionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CorrectiveAction
        fields = "__all__"
        read_only_fields = ["number", "created_at", "created_by"]


class NonconformityViewSet(viewsets.ModelViewSet):
    queryset = Nonconformity.objects.select_related("quality_object", "control_post", "defect_type", "responsible_user")
    serializer_class = NonconformitySerializer
    permission_classes = [RolePermission]
    filterset_fields = ["status", "criticality", "control_post", "responsible_user"]


class CorrectiveActionViewSet(viewsets.ModelViewSet):
    queryset = CorrectiveAction.objects.select_related("nonconformity", "assigned_to")
    serializer_class = CorrectiveActionSerializer
    permission_classes = [RolePermission]
    filterset_fields = ["status", "assigned_to", "nonconformity"]
