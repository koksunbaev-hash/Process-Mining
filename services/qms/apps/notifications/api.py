from rest_framework import serializers, viewsets

from apps.accounts.permissions import RolePermission

from .models import Notification
from .querysets import visible_notifications


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = "__all__"
        read_only_fields = ["recipient", "created_at"]


class NotificationViewSet(viewsets.ModelViewSet):
    serializer_class = NotificationSerializer
    permission_classes = [RolePermission]
    filterset_fields = ["is_read", "notification_type"]

    def get_queryset(self):
        return visible_notifications(Notification.objects.filter(recipient=self.request.user))
