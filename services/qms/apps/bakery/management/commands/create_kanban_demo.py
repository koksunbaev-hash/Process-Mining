from django.core.management.base import BaseCommand, CommandError

from apps.bakery.kanban_demo import create_demo_run, demo_status, demo_user, reset_demo
from apps.bakery.models import KanbanDemoRun


class Command(BaseCommand):
    help = "Создаёт демонстрационный Kanban-запуск с тестовыми партиями."

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=100)
        parser.add_argument("--name", default="Kanban demo")
        parser.add_argument("--speed", type=float, default=2)
        parser.add_argument("--mode", default=KanbanDemoRun.Mode.WAVE, choices=[choice[0] for choice in KanbanDemoRun.Mode.choices])
        parser.add_argument("--reset", action="store_true")
        parser.add_argument("--user", default="")
        parser.add_argument("--client-request-id", default="")

    def handle(self, *args, **options):
        user = demo_user(options["user"] or None)
        if not user:
            raise CommandError("Не найден администратор или диспетчер для создания demo.")
        if options["reset"]:
            for run in list(KanbanDemoRun.objects.all()):
                reset_demo(run, user)
        run = create_demo_run(
            user=user,
            count=options["count"],
            name=options["name"],
            speed_seconds=options["speed"],
            mode=options["mode"],
            client_request_id=options["client_request_id"] or None,
        )
        status = demo_status(run)
        self.stdout.write(self.style.SUCCESS(f"DemoRun ID: {run.pk}"))
        self.stdout.write(f"Статус: {status['status']}")
        self.stdout.write(f"Партии: {status['total_batches']}")
        self.stdout.write(f"Готово: {status['completed_batches']} ({status['progress_percent']}%)")
