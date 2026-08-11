"""Прогноз на неделю: арифметика без базы.

Проверяется главное свойство метода — что он держит недельный ритм. Если
суббота начнёт предсказываться по будням, заказчик увидит недопечённые выходные
и перестанет верить цифре целиком.
"""

from __future__ import annotations

import unittest
from datetime import date, timedelta
from decimal import Decimal

from apps.bakery.forecast import daily_totals, predict_day, predict_week, week_totals

# 2026-08-10 — понедельник.
MONDAY = date(2026, 8, 10)
SATURDAY = date(2026, 8, 15)


def weeks_before(day, count):
    return [day - timedelta(weeks=step) for step in range(1, count + 1)]


class PredictDayTests(unittest.TestCase):
    def test_it_averages_the_same_weekday(self):
        history = dict(zip(weeks_before(MONDAY, 4), [Decimal(100), Decimal(120), Decimal(80), Decimal(100)]))
        self.assertEqual(predict_day(history, MONDAY).quantity, Decimal(100))

    def test_other_weekdays_do_not_leak_in(self):
        """Ради этого метод и выбран: суббота считается по субботам."""
        history = {}
        for step in range(1, 5):
            history[SATURDAY - timedelta(weeks=step)] = Decimal(500)
            history[MONDAY - timedelta(weeks=step)] = Decimal(50)
        self.assertEqual(predict_day(history, SATURDAY).quantity, Decimal(500))
        self.assertEqual(predict_day(history, MONDAY).quantity, Decimal(50))

    def test_missing_weeks_are_skipped_not_counted_as_zero(self):
        """Иначе день, которого нет в истории, тянул бы прогноз вниз."""
        history = {MONDAY - timedelta(weeks=1): Decimal(200)}
        point = predict_day(history, MONDAY)
        self.assertEqual(point.quantity, Decimal(200))
        self.assertEqual(point.samples, 1)

    def test_an_honest_zero_does_count(self):
        """Не пекли в этот день - это факт, а не пробел в данных."""
        history = {
            MONDAY - timedelta(weeks=1): Decimal(0),
            MONDAY - timedelta(weeks=2): Decimal(100),
        }
        self.assertEqual(predict_day(history, MONDAY).quantity, Decimal(50))

    def test_no_history_at_all_gives_zero_and_says_so(self):
        point = predict_day({}, MONDAY)
        self.assertEqual(point.quantity, Decimal(0))
        self.assertEqual(point.samples, 0)
        self.assertEqual(point.confidence, "none")

    def test_confidence_reports_how_many_days_it_stands_on(self):
        few = {MONDAY - timedelta(weeks=1): Decimal(10)}
        many = dict(zip(weeks_before(MONDAY, 3), [Decimal(10)] * 3))
        self.assertEqual(predict_day(few, MONDAY).confidence, "low")
        self.assertEqual(predict_day(many, MONDAY).confidence, "high")

    def test_the_result_is_whole_loaves(self):
        """Полбулки не пекут."""
        history = dict(zip(weeks_before(MONDAY, 3), [Decimal(10), Decimal(11), Decimal(10)]))
        self.assertEqual(predict_day(history, MONDAY).quantity, Decimal(10))

    def test_it_looks_no_further_back_than_asked(self):
        history = {MONDAY - timedelta(weeks=step): Decimal(100) for step in range(1, 9)}
        history[MONDAY - timedelta(weeks=8)] = Decimal(9999)
        self.assertEqual(predict_day(history, MONDAY, weeks=4).quantity, Decimal(100))


class PredictWeekTests(unittest.TestCase):
    def setUp(self):
        self.history = {
            "Багет": {MONDAY - timedelta(weeks=w): Decimal(40) for w in range(1, 5)},
            "Хлеб": {MONDAY - timedelta(weeks=w): Decimal(300) for w in range(1, 5)},
        }

    def test_seven_days_for_every_product(self):
        prediction = predict_week(self.history, MONDAY)
        self.assertEqual(sorted(prediction), ["Багет", "Хлеб"])
        for points in prediction.values():
            self.assertEqual(len(points), 7)

    def test_the_horizon_starts_where_asked(self):
        points = predict_week(self.history, MONDAY)["Хлеб"]
        self.assertEqual(points[0].date, MONDAY)
        self.assertEqual(points[6].date, MONDAY + timedelta(days=6))

    def test_days_without_their_own_history_come_back_zero(self):
        """История есть только на понедельники - остальные дни пусты, и это видно."""
        points = predict_week(self.history, MONDAY)["Хлеб"]
        self.assertEqual(points[0].quantity, Decimal(300))
        self.assertEqual([p.quantity for p in points[1:]], [Decimal(0)] * 6)

    def test_products_come_out_sorted_by_name(self):
        prediction = predict_week({"Ржаной": {}, "багет": {}, "Батон": {}}, MONDAY)
        self.assertEqual(list(prediction), ["багет", "Батон", "Ржаной"])


class TotalsTests(unittest.TestCase):
    def test_the_week_total_per_product(self):
        history = {"Хлеб": {MONDAY - timedelta(weeks=w): Decimal(100) for w in range(1, 5)}}
        self.assertEqual(week_totals(predict_week(history, MONDAY))["Хлеб"], Decimal(100))

    def test_the_daily_bottom_line_adds_products_up(self):
        history = {
            "Хлеб": {MONDAY - timedelta(weeks=w): Decimal(100) for w in range(1, 5)},
            "Багет": {MONDAY - timedelta(weeks=w): Decimal(25) for w in range(1, 5)},
        }
        totals = daily_totals(predict_week(history, MONDAY), 7)
        self.assertEqual(totals[0], Decimal(125))
        self.assertEqual(totals[1], Decimal(0))

    def test_an_empty_forecast_totals_to_nothing_rather_than_failing(self):
        self.assertEqual(daily_totals({}, 7), [Decimal(0)] * 7)
        self.assertEqual(week_totals({}), {})


if __name__ == "__main__":
    unittest.main()
