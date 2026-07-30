from django.core.management.base import BaseCommand
from django.db.models import Q

from apps.notifications.models import Notification


class Command(BaseCommand):
    help = "Удаляет старые уведомления Kanban demo и DEMO-B партий."

    def handle(self, *args, **options):
        queryset = Notification.objects.filter(
            Q(notification_type="kanban_demo")
            | Q(title__icontains="DEMO-B-")
            | Q(message__icontains="DEMO-B-")
            | Q(title__icontains="Kanban demo")
            | Q(message__icontains="Kanban demo")
        )
        count = queryset.count()
        queryset.delete()
        self.stdout.write(self.style.SUCCESS(f"Удалено demo-уведомлений: {count}"))
