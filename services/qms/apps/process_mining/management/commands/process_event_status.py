from django.core.management.base import BaseCommand
from django.db.models import Count

from apps.process_mining.models import ProcessEvent, ProcessEventExport


class Command(BaseCommand):
    help = "Показывает состояние очереди Process Mining событий."

    def handle(self, *args, **options):
        self.stdout.write("ProcessEvent:")
        for row in ProcessEvent.objects.values("export_status").annotate(total=Count("id")).order_by("export_status"):
            self.stdout.write(f"  {row['export_status']}: {row['total']}")
        self.stdout.write("Последние экспорты:")
        for export in ProcessEventExport.objects.order_by("-created_at")[:5]:
            self.stdout.write(f"  {export.export_id} {export.status} events={export.events_count} http={export.response_status_code} error={export.last_error[:120]}")
