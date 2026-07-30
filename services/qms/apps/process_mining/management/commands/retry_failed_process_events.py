from django.core.management.base import BaseCommand

from apps.process_mining.services import retry_failed_events


class Command(BaseCommand):
    help = "Возвращает failed ProcessEvent в pending для повторной отправки."

    def handle(self, *args, **options):
        count = retry_failed_events()
        self.stdout.write(self.style.SUCCESS(f"Возвращено в pending: {count}"))
