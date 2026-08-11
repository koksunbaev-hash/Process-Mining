"""Прогноз выпуска на следующую неделю.

Метод выбран самый скучный из работающих: среднее по тому же дню недели за
последние несколько недель. Для хлебозавода это не упрощение, а суть — спрос
здесь живёт неделей. Суббота не похожа на вторник, и никакая общая средняя
этого не покажет: она размажет выходные по будням и наоборот.

Почему не что-то умнее. Любую цифру, показанную заказчику, придётся объяснить,
и «столько же, сколько в прошлые четыре субботы» объясняется за одну фразу.
Модель, которая объясняется за абзац, в разговоре о том, сколько печь завтра,
проигрывает — даже если ошибается чуть реже.

Django здесь нет: на вход словари, на выход числа, и всё проверяется без базы.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_cls, timedelta
from decimal import Decimal, ROUND_HALF_UP

# Сколько одинаковых дней недели усреднять. Четыре — это месяц: достаточно,
# чтобы случайный всплеск не увёл прогноз, и мало, чтобы прошлогодние привычки
# не тянули назад.
WEEKS_BACK = 4


@dataclass(frozen=True)
class Point:
    """Одна клетка прогноза: сколько и насколько это обосновано."""

    date: date_cls
    quantity: Decimal
    samples: int

    @property
    def confidence(self) -> str:
        """Не проценты, а честное «на скольких днях это построено».

        Проценты пришлось бы придумывать, а число наблюдений — факт.
        """
        if self.samples >= 3:
            return "high"
        if self.samples >= 1:
            return "low"
        return "none"


def _same_weekday_dates(target: date_cls, weeks: int) -> list[date_cls]:
    return [target - timedelta(weeks=step) for step in range(1, weeks + 1)]


def predict_day(history: dict[date_cls, Decimal], target: date_cls, weeks: int = WEEKS_BACK) -> Point:
    """Сколько ждать в этот день по тем же дням недели до него.

    Дни, которых в истории нет, в среднее не идут — иначе выпускной день,
    которого просто не было в данных, утянул бы прогноз к нулю. А вот день,
    когда честно испекли ноль, считается: это факт, а не пробел.
    """
    samples = [history[day] for day in _same_weekday_dates(target, weeks) if day in history]
    if not samples:
        return Point(target, Decimal(0), 0)
    average = sum(samples, Decimal(0)) / Decimal(len(samples))
    return Point(target, average.quantize(Decimal("1"), rounding=ROUND_HALF_UP), len(samples))


def predict_week(
    history_by_product: dict[str, dict[date_cls, Decimal]],
    start: date_cls,
    days: int = 7,
    weeks: int = WEEKS_BACK,
) -> dict[str, list[Point]]:
    """Неделя вперёд по каждому продукту, начиная с ``start``."""
    horizon = [start + timedelta(days=step) for step in range(days)]
    return {
        product: [predict_day(history, day, weeks) for day in horizon]
        for product, history in sorted(history_by_product.items(), key=lambda pair: pair[0].lower())
    }


def week_totals(prediction: dict[str, list[Point]]) -> dict[str, Decimal]:
    """Сколько всего по каждому продукту за неделю."""
    return {product: sum((point.quantity for point in points), Decimal(0)) for product, points in prediction.items()}


def daily_totals(prediction: dict[str, list[Point]], days: int) -> list[Decimal]:
    """Нижняя строка: сколько всего печь в каждый день."""
    return [
        sum((points[index].quantity for points in prediction.values()), Decimal(0))
        for index in range(days)
    ]
