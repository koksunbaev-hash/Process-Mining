"""Убрать вчерашнее из колонки «Готово» - утренняя уборка доски.

Запускается по расписанию в 7:55, чтобы к восьми смена подходила к чистой
доске и складывала на неё только сегодняшнее.

Ничего не удаляет. На партии висит история этапов, из которой строится карта
процесса, считаются столбцы смен в листе заказа и уходит поток в Influx;
убирается только показ на доске. Партию по-прежнему видно в списке партий,
в поиске и в карточке заказа.

Команда идемпотентна: второй запуск подряд не находит ничего. Пропущенный
запуск - тоже не беда, следующий уберёт всё накопившееся разом, а до него
доску подстрахует граница производственного дня в самой выборке.

    python manage.py clear_done_board --dry-run   # посмотреть, не трогая
    python manage.py clear_done_board             # убрать
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.bakery.services import sweep_done_board

# Длинный список в лог не нужен: важно число и на что оно похоже.
SHOWN = 8


class Command(BaseCommand):
    help = "Убрать с доски партии, доехавшие до «Готово» раньше среза."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Показать, что было бы убрано, ничего не меняя.",
        )

    def handle(self, *args, **options):
        cutoff = timezone.now()
        swept = sweep_done_board(cutoff=cutoff, dry_run=options["dry_run"])

        local = timezone.localtime(cutoff).strftime("%d.%m.%Y %H:%M")
        if not swept:
            self.stdout.write(f"{local}: в «Готово» убирать нечего.")
            return

        for row in swept[:SHOWN]:
            finished = (
                timezone.localtime(row["finished"]).strftime("%d.%m %H:%M")
                if row["finished"]
                else "без отметки времени"
            )
            self.stdout.write(f"  {row['label']:22s} {row['product'][:38]:38s} готово {finished}")
        if len(swept) > SHOWN:
            self.stdout.write(f"  … и ещё {len(swept) - SHOWN}")

        verb = "было бы убрано" if options["dry_run"] else "убрано с доски"
        self.stdout.write(self.style.SUCCESS(f"{local}: {verb} партий: {len(swept)}"))
