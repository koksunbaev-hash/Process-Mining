"""Заказ на производство — то, что в цеху до сих пор носят на бумаге.

Лист повторяет форму, по которой на хлебозаводе работают сегодня: слева
наименования, справа план на дату, а между ними смены, в которые этот план
закрывают. Разница одна и существенная: столбцы смен здесь не пустые. Всё, что
нужно для их заполнения, система уже знает — партии проходят по доске с
отметками времени, и остаётся сложить.

Почему смен три, а не две. Хлеб на дату пекут начиная с вечера накануне,
поэтому в бумажной форме и стоят подряд «2 смена», «1 смена», «2 смена»: вторая
смена предыдущего дня, затем обе смены самого дня. Порядок хронологический, и
он же сохранён здесь.

Модуль не импортирует Django вообще: и границы смен, и подсчёт — обычные
функции над обычными типами. Поэтому их можно проверить, не поднимая ни базу,
ни настройки, и ошибка в арифметике находится за секунду, а не в цеху.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as date_cls, datetime, time, timedelta, tzinfo
from decimal import Decimal

# Границы смен по умолчанию — обычные для хлебозавода: дневная с 8:00 до 20:00,
# ночная с 20:00 до 8:00 следующего дня. У другого предприятия они будут
# другими, поэтому передаются аргументом, а не зашиты.
SHIFT_ONE_START = time(8, 0)
SHIFT_TWO_START = time(20, 0)


@dataclass(frozen=True)
class Shift:
    """Одна колонка смены: как назвать и какой промежуток времени считать."""

    label: str
    day_label: str
    start: datetime
    end: datetime

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment < self.end


def shifts_for(
    order_date: date_cls,
    zone: tzinfo | None = None,
    shift_one_start: time = SHIFT_ONE_START,
    shift_two_start: time = SHIFT_TWO_START,
) -> list[Shift]:
    """Три смены, закрывающие заказ на дату, в хронологическом порядке.

    Вечер накануне, затем день и вечер самой даты — ровно как в бумажной форме.
    """
    def moment(day: date_cls, at: time) -> datetime:
        return datetime.combine(day, at, tzinfo=zone)

    previous = order_date - timedelta(days=1)
    return [
        Shift(
            label="2 смена",
            day_label=previous.strftime("%d.%m"),
            start=moment(previous, shift_two_start),
            end=moment(order_date, shift_one_start),
        ),
        Shift(
            label="1 смена",
            day_label=order_date.strftime("%d.%m"),
            start=moment(order_date, shift_one_start),
            end=moment(order_date, shift_two_start),
        ),
        Shift(
            label="2 смена",
            day_label=order_date.strftime("%d.%m"),
            start=moment(order_date, shift_two_start),
            end=moment(order_date + timedelta(days=1), shift_one_start),
        ),
    ]


@dataclass
class Row:
    """Строка листа: один продукт."""

    product_name: str
    opening: Decimal = Decimal(0)
    by_shift: list[Decimal] = field(default_factory=list)
    planned: Decimal = Decimal(0)

    @property
    def produced(self) -> Decimal:
        """Столбец «Итог» — сколько выпущено за все три смены."""
        return sum(self.by_shift, Decimal(0))

    @property
    def closing(self) -> Decimal:
        """Столбец «Остаток» справа: что было плюс что сделали минус что нужно.

        Отрицательное значение — это недовыпуск, и его видно сразу. Именно за
        этим на бумаге и следят: правый столбец должен сойтись в ноль.
        """
        return self.opening + self.produced - self.planned

    @property
    def is_short(self) -> bool:
        return self.closing < 0

    @property
    def is_done(self) -> bool:
        return self.planned > 0 and self.produced >= self.planned


def build_rows(planned_by_product, produced_by_product_and_shift, opening_by_product, shift_count):
    """Складывает три источника в строки листа.

    Аргументы — обычные словари, а не запросы: так эту функцию можно проверить
    на выдуманных числах, и так же видно, что она ничего не знает про базу.

    ``produced_by_product_and_shift`` — словарь ``{продукт: [смена1, смена2, ...]}``.
    """
    names = set(planned_by_product) | set(produced_by_product_and_shift) | set(opening_by_product)
    rows = []
    for name in sorted(names, key=lambda value: value.lower()):
        rows.append(
            Row(
                product_name=name,
                opening=opening_by_product.get(name, Decimal(0)),
                by_shift=produced_by_product_and_shift.get(name, [Decimal(0)] * shift_count),
                planned=planned_by_product.get(name, Decimal(0)),
            )
        )
    return rows


def totals(rows, shift_count):
    """Итоговая строка внизу листа."""
    return {
        "opening": sum((row.opening for row in rows), Decimal(0)),
        "by_shift": [
            sum((row.by_shift[index] for row in rows), Decimal(0)) for index in range(shift_count)
        ],
        "produced": sum((row.produced for row in rows), Decimal(0)),
        "planned": sum((row.planned for row in rows), Decimal(0)),
        "closing": sum((row.closing for row in rows), Decimal(0)),
        "short": sum(1 for row in rows if row.is_short),
    }
