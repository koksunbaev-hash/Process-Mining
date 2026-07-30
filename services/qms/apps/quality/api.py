from rest_framework import serializers, viewsets

from apps.accounts.permissions import RolePermission

from .models import ControlParameter, ControlPost, ControlRoute, QualityObject


class ControlPostSerializer(serializers.ModelSerializer):
    class Meta:
        model = ControlPost
        fields = "__all__"


class ControlParameterSerializer(serializers.ModelSerializer):
    class Meta:
        model = ControlParameter
        fields = "__all__"


class ControlRouteSerializer(serializers.ModelSerializer):
    class Meta:
        model = ControlRoute
        fields = "__all__"


class QualityObjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = QualityObject
        fields = "__all__"
        read_only_fields = ["created_by", "created_at", "updated_at"]

    def create(self, validated_data):
        from .services import create_quality_object_with_route

        return create_quality_object_with_route(user=self.context["request"].user, **validated_data)


class ControlPostViewSet(viewsets.ModelViewSet):
    queryset = ControlPost.objects.select_related("department", "control_type", "responsible_user")
    serializer_class = ControlPostSerializer
    permission_classes = [RolePermission]
    filterset_fields = ["department", "control_type", "is_active"]


class ControlParameterViewSet(viewsets.ModelViewSet):
    queryset = ControlParameter.objects.all()
    serializer_class = ControlParameterSerializer
    permission_classes = [RolePermission]
    filterset_fields = ["value_type", "criticality", "is_active"]


class ControlRouteViewSet(viewsets.ModelViewSet):
    queryset = ControlRoute.objects.all()
    serializer_class = ControlRouteSerializer
    permission_classes = [RolePermission]
    filterset_fields = ["is_active", "product_type"]


class QualityObjectViewSet(viewsets.ModelViewSet):
    queryset = QualityObject.objects.select_related("department", "route", "current_control_post")
    serializer_class = QualityObjectSerializer
    permission_classes = [RolePermission]
    filterset_fields = ["quality_status", "object_type", "department", "current_control_post", "batch_number", "serial_number"]
