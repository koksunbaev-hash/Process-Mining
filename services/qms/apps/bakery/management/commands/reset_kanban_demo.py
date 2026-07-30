from django.core.management.base import BaseCommand, CommandError

from apps.bakery.kanban_demo import demo_user, reset_demo
from apps.bakery.models import KanbanDemoRun


class Command(BaseCommand):
    help = "Удаляет только данные конкретного Kanban demo-запуска."

    def add_arguments(self, parser):
        parser.add_argument("demo_run_id", type=int)
        parser.add_argument("--user", default="")

    def handle(self, *args, **options):
        user = demo_user(options["user"] or None)
        if not user:
            raise CommandError("Не найден администратор или диспетчер для сброса demo.")
        run = KanbanDemoRun.objects.get(pk=options["demo_run_id"])
        result = reset_demo(run, user)
        self.stdout.write(self.style.SUCCESS(f"DemoRun {options['demo_run_id']} сброшен."))
        self.stdout.write(f"Удалено партий: {result['deleted_batches']}")
        self.stdout.write(f"Удалено заказов: {result['deleted_orders']}")
