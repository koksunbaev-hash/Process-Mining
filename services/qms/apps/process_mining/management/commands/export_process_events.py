from django.core.management.base import BaseCommand

from apps.process_mining.services import export_pending_events_to_process_mining


class Command(BaseCommand):
    help = "Экспортирует pending ProcessEvent в Process Mining CSV API."

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=None)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--limit", type=int, default=1)

    def handle(self, *args, **options):
        total = 0
        for _ in range(options["limit"]):
            result = export_pending_events_to_process_mining(batch_size=options["batch_size"], dry_run=options["dry_run"])
            total += result["events_count"]
            self.stdout.write(f"events={result['events_count']} sent={result.get('sent', 0)} failed={result.get('failed', 0)}")
            if options["dry_run"] and result["csv"]:
                self.stdout.write(result["csv"])
            if not result["events_count"]:
                break
        self.stdout.write(self.style.SUCCESS(f"Всего обработано: {total}"))
