"""Связать машины цеха с их двойниками, не набирая идентификаторы руками.

В цеху не одни печи: миксеры, формовщики, расстоечные шкафы - тринадцать
машин, и у каждой свой `thingId` в Ditto. В интерфейсе OpenTwins эти
идентификаторы обрезаны многоточием, а различаются последними символами, так
что переписывание их в админку - тринадцать шансов ошибиться на один символ и
потом искать, почему у одной печи панель пустая.

Команда показывает каталог двойников рядом со списком машин QMS, разложив и
то и другое по типам оборудования, и умеет проставлять связь по паре
«машина = thingId». Льдогенераторы в QMS не заведены - у них есть телеметрия,
но нет партий, - и в список машин они не попадают; это не ошибка.

    manage.py twin_ids                      посмотреть каталог и что уже связано
    manage.py twin_ids --set "Печь 1=digitalegiz:ESP32_Dala_Meter_001994"
    manage.py twin_ids --clear "Печь 1"     развязать
"""

import urllib.error

from django.core.management.base import BaseCommand, CommandError

from apps.bakery.models import ProductionUnit
from apps.bakery.twins import fetch_things, twins_enabled

#: Слово в начале имени, по которому и двойник, и машина относятся к одному
#: типу оборудования. Порядок - как на доске.
KINDS = ["Миксер", "Формовщик", "Шкаф", "Печь", "Льдогенератор"]


def kind_of(name):
    for kind in KINDS:
        if name.lower().startswith(kind.lower()):
            return kind
    return "Прочее"


class Command(BaseCommand):
    help = "Показать двойники Ditto рядом с машинами QMS и связать их."

    def add_arguments(self, parser):
        parser.add_argument(
            "--set",
            action="append",
            default=[],
            metavar='"Машина=thingId"',
            help="Связать машину с двойником. Можно повторять.",
        )
        parser.add_argument(
            "--clear",
            action="append",
            default=[],
            metavar='"Машина"',
            help="Убрать связь у машины. Можно повторять.",
        )

    def handle(self, *args, **options):
        if options["set"] or options["clear"]:
            self._apply(options["set"], options["clear"])
            self.stdout.write("")

        self._show_units()
        if twins_enabled():
            self._show_catalog()
        else:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(
                "Каталог двойников не показан: нужны DITTO_ENABLED=True и DITTO_BASE_URL."
            ))

    # ------------------------------------------------------------------ set

    def _apply(self, pairs, names_to_clear):
        for pair in pairs:
            if "=" not in pair:
                raise CommandError(f'Ожидалось "Машина=thingId", получено: {pair}')
            name, thing_id = (part.strip() for part in pair.split("=", 1))
            unit = ProductionUnit.objects.filter(name__iexact=name).first()
            if unit is None:
                raise CommandError(f"Машина не найдена: {name}")
            # Один двойник на две машины - это молча разъезжающаяся панель:
            # обе пишут в одну серию, и кто последний, того и данные.
            taken = ProductionUnit.objects.filter(twin_id=thing_id).exclude(pk=unit.pk).first()
            if taken:
                raise CommandError(f"Этот двойник уже у машины «{taken.name}».")
            unit.twin_id = thing_id
            unit.save(update_fields=["twin_id"])
            self.stdout.write(self.style.SUCCESS(f"{unit.name} → {thing_id}"))

        for name in names_to_clear:
            unit = ProductionUnit.objects.filter(name__iexact=name.strip()).first()
            if unit is None:
                raise CommandError(f"Машина не найдена: {name}")
            unit.twin_id = ""
            unit.save(update_fields=["twin_id"])
            self.stdout.write(self.style.SUCCESS(f"{unit.name} → связь убрана"))

    # ----------------------------------------------------------------- show

    def _show_units(self):
        units = list(ProductionUnit.objects.select_related("stage"))
        if not units:
            self.stdout.write(self.style.WARNING("В QMS нет ни одной машины."))
            return
        bound = sum(1 for unit in units if unit.twin_id)
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"Машины QMS ({bound} из {len(units)} связаны с двойниками)"
        ))
        for unit in units:
            mark = unit.twin_id or "— двойника нет"
            style = self.style.SUCCESS if unit.twin_id else self.style.WARNING
            self.stdout.write(f"  {unit.name:<16} {style(mark)}")

    def _show_catalog(self):
        try:
            things = fetch_things()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError) as exc:
            self.stdout.write("")
            self.stdout.write(self.style.ERROR(f"Ditto не ответил: {exc}"))
            return

        taken = set(ProductionUnit.objects.exclude(twin_id="").values_list("twin_id", flat=True))
        by_kind = {}
        for thing_id, name in things:
            by_kind.setdefault(kind_of(name or thing_id), []).append((thing_id, name))

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(f"Двойники в Ditto ({len(things)})"))
        for kind in KINDS + ["Прочее"]:
            rows = by_kind.get(kind)
            if not rows:
                continue
            self.stdout.write(f"  {kind}:")
            for thing_id, name in rows:
                mark = "уже связан" if thing_id in taken else "свободен"
                style = self.style.SUCCESS if thing_id in taken else self.style.NOTICE
                label = name or "(без имени)"
                self.stdout.write(f"    {label:<38} {thing_id:<46} {style(mark)}")
