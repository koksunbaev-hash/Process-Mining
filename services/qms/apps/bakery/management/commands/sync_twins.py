"""Перелить текущее состояние доски в цифровые двойники оборудования.

Сигналы в apps/bakery/twins.py доставляют обновления по одному и без
гарантий: упавшая сеть или перезапуск стенда с двойниками оставляет витрину
отставшей. Эта команда - способ догнать: она проходит по всем устройствам с
заполненным twin_id и кладёт в каждый двойник то, что на устройстве стоит
прямо сейчас. Запускать после включения интеграции, после простоя Ditto или
просто когда витрине не верится.
"""

import json

from django.core.management.base import BaseCommand

from apps.bakery.models import ProductionUnit
from apps.bakery.twins import push_unit, twins_enabled, unit_product_payload


class Command(BaseCommand):
    help = "Отправить текущее состояние всех устройств в их двойники OpenTwins/Ditto."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Показать, что было бы отправлено, ничего не отправляя.",
        )

    def handle(self, *args, **options):
        units = list(ProductionUnit.objects.select_related("stage").exclude(twin_id=""))
        if not units:
            self.stdout.write(self.style.WARNING("Нет устройств с заполненным twin_id."))
            return
        if not options["dry_run"] and not twins_enabled():
            self.stdout.write(self.style.WARNING(
                "Интеграция выключена: задайте DITTO_ENABLED=True и DITTO_BASE_URL."
            ))
            return
        sent = 0
        for unit in units:
            if options["dry_run"]:
                payload = json.dumps(unit_product_payload(unit), ensure_ascii=False)
                self.stdout.write(f"{unit.name} -> {unit.twin_id}: {payload}")
                continue
            if push_unit(unit):
                sent += 1
                self.stdout.write(f"{unit.name} -> {unit.twin_id}: ok")
            else:
                self.stdout.write(self.style.ERROR(f"{unit.name} -> {unit.twin_id}: ошибка (см. лог)"))
        if not options["dry_run"]:
            self.stdout.write(self.style.SUCCESS(f"Обновлено двойников: {sent} из {len(units)}."))
