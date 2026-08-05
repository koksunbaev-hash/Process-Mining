from django.core.management.base import BaseCommand
from django.db import transaction

from apps.bakery.models import ProductionBatch


class Command(BaseCommand):
    help = "Показывает или применяет короткие номера для старых длинных партий."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Реально обновить batch_number в базе.")
        parser.add_argument("--limit", type=int, default=0, help="Ограничить количество обновлений.")

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        limit = options["limit"]
        updated = 0
        skipped = 0

        qs = ProductionBatch.objects.order_by("id")
        if limit:
            qs = qs[:limit]

        with transaction.atomic():
            for batch in qs:
                new_number = batch.short_batch_number
                if not new_number or new_number == batch.batch_number:
                    skipped += 1
                    continue
                if ProductionBatch.objects.filter(batch_number=new_number).exclude(pk=batch.pk).exists():
                    skipped += 1
                    self.stdout.write(self.style.WARNING(f"Пропуск {batch.batch_number}: {new_number} уже занят."))
                    continue
                self.stdout.write(f"{batch.batch_number} -> {new_number}")
                if apply_changes:
                    batch.batch_number = new_number
                    batch.save(update_fields=["batch_number", "updated_at"])
                updated += 1

            if not apply_changes:
                transaction.set_rollback(True)

        mode = "обновлено" if apply_changes else "можно обновить"
        self.stdout.write(self.style.SUCCESS(f"{mode}: {updated}, пропущено: {skipped}"))
        if not apply_changes:
            self.stdout.write("Это был dry-run. Для применения запусти: python manage.py shorten_batch_numbers --apply")
