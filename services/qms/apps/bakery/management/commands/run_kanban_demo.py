from django.core.management.base import BaseCommand, CommandError

from apps.bakery.kanban_demo import demo_user, run_demo_until_done
from apps.bakery.models import KanbanDemoRun


class Command(BaseCommand):
    help = "Запускает Kanban demo до завершения через реальные переходы партий."

    def add_arguments(self, parser):
        parser.add_argument("demo_run_id", type=int)
        parser.add_argument("--user", default="")
        parser.add_argument("--no-sleep", action="store_true")
        parser.add_argument("--max-ticks", type=int, default=500)

    def handle(self, *args, **options):
        user = demo_user(options["user"] or None)
        if not user:
            raise CommandError("Не найден администратор или диспетчер для запуска demo.")
        run = KanbanDemoRun.objects.get(pk=options["demo_run_id"])
        result = run_demo_until_done(run, user, sleep=not options["no_sleep"], max_ticks=options["max_ticks"])
        self.stdout.write(f"DemoRun ID: {run.pk}")
        self.stdout.write(f"Статус: {result['status']}")
        self.stdout.write(f"Готово: {result['completed_batches']} из {result['total_batches']} ({result['progress_percent']}%)")
        if result.get("last_error"):
            self.stdout.write(self.style.WARNING(result["last_error"]))
