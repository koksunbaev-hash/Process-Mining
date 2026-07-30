from rest_framework import serializers, viewsets

from apps.accounts.permissions import RolePermission

from .models import MeasuringEquipment


class MeasuringEquipmentSerializer(serializers.ModelSerializer):
    verification_expired = serializers.BooleanField(read_only=True)
    verification_expiring_soon = serializers.BooleanField(read_only=True)
    available_for_use = serializers.BooleanField(read_only=True)

    class Meta:
        model = MeasuringEquipment
        fields = "__all__"


class MeasuringEquipmentViewSet(viewsets.ModelViewSet):
    queryset = MeasuringEquipment.objects.select_related("department", "responsible_user")
    serializer_class = MeasuringEquipmentSerializer
    permission_classes = [RolePermission]
    filterset_fields = ["status", "department", "is_active"]
