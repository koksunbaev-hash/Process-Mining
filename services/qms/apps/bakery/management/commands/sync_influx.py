"""Перелить историю движений партий в общий InfluxDB.

Сигналы в apps/bakery/influx.py доставляют точки по одной и без гарантий:
пока интеграция была выключена или сеть лежала, в базе копились дыры. Эта
команда проходит по всей истории этапов и отправляет её пачками. Точки
идемпотентны по (тегам, времени) - переливка поверх уже отправленного
ничего не задваивает, поэтому команду можно запускать сколько угодно.

Запускать после включения интеграции - чтобы Grafana сразу получила
историю, а не начинала с чистого листа.
"""

from django.core.management.base import BaseCommand

from apps.bakery.influx import history_point, influx_enabled, write_lines
from apps.bakery.models import BatchStageHistory

# Пачка держит запрос коротким: сто тысяч строк одним POST - это таймаут,
# а не переливка.
CHUNK = 500


class Command(BaseCommand):
    help = "Отправить историю движений партий в общий InfluxDB."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            help="Сколько последних дней переливать (по умолчанию - всю историю).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Показать, что было бы отправлено, ничего не отправляя.",
        )

    def handle(self, *args, **options):
        if not options["dry_run"] and not influx_enabled():
            self.stdout.write(self.style.WARNING(
                "Интеграция выключена: нужны INFLUX_ENABLED=True, INFLUX_URL и INFLUX_TOKEN."
            ))
            return

        rows = (
            BatchStageHistory.objects.select_related(
                "batch__product",
                "batch__production_unit",
                "batch__order_item__order",
                "from_stage",
                "to_stage",
            )
            .filter(batch__is_demo=False)
            .order_by("created_at")
        )
        if options["days"]:
            from datetime import timedelta

            from django.utils import timezone

            rows = rows.filter(created_at__gte=timezone.now() - timedelta(days=options["days"]))

        lines, sent, failed = [], 0, 0
        for row in rows.iterator(chunk_size=CHUNK):
            lines.append(history_point(row))
            if len(lines) >= CHUNK:
                sent, failed = self._flush(lines, sent, failed, options["dry_run"])
        if lines:
            sent, failed = self._flush(lines, sent, failed, options["dry_run"])

        verb = "показано" if options["dry_run"] else "отправлено"
        summary = f"Точек {verb}: {sent}"
        if failed:
            summary += f", не доставлено пачек: {failed}"
            self.stdout.write(self.style.WARNING(summary))
        else:
            self.stdout.write(self.style.SUCCESS(summary))

    def _flush(self, lines, sent, failed, dry_run):
        if dry_run:
            for line in lines[:3]:
                self.stdout.write("  " + line)
            if len(lines) > 3:
                self.stdout.write(f"  … и ещё {len(lines) - 3}")
            sent += len(lines)
        elif write_lines(lines):
            sent += len(lines)
        else:
            failed += 1
        lines.clear()
        return sent, failed
