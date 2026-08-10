"""Арифметика листа «Заказ на производство».

Без Django и без базы: границы смен и подсчёт — обычные функции над обычными
типами, и проверяются как таковые. Ошибка здесь означала бы, что цех печёт не
то количество, поэтому проверяется каждая колонка отдельно.
"""

from __future__ import annotations

import unittest
from datetime import date, datetime, time, timezone as dt_timezone
from decimal import Decimal

from apps.bakery.production_sheet import Row, build_rows, shifts_for, totals

UTC = dt_timezone.utc


class ShiftBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.shifts = shifts_for(date(2026, 8, 6), UTC)

    def test_three_columns_in_the_order_the_paper_form_has_them(self):
        self.assertEqual([s.label for s in self.shifts], ["2 смена", "1 смена", "2 смена"])

    def test_the_first_one_belongs_to_the_evening_before(self):
        """Хлеб на 6-е пекут с вечера 5-го - иначе смена не попала бы в заказ."""
        first = self.shifts[0]
        self.assertEqual(first.day_label, "05.08")
        self.assertEqual(first.start, datetime(2026, 8, 5, 20, 0, tzinfo=UTC))
        self.assertEqual(first.end, datetime(2026, 8, 6, 8, 0, tzinfo=UTC))

    def test_the_day_shift_is_the_second_column(self):
        second = self.shifts[1]
        self.assertEqual(second.day_label, "06.08")
        self.assertEqual(second.start, datetime(2026, 8, 6, 8, 0, tzinfo=UTC))
        self.assertEqual(second.end, datetime(2026, 8, 6, 20, 0, tzinfo=UTC))

    def test_the_last_one_runs_into_the_next_morning(self):
        third = self.shifts[2]
        self.assertEqual(third.start, datetime(2026, 8, 6, 20, 0, tzinfo=UTC))
        self.assertEqual(third.end, datetime(2026, 8, 7, 8, 0, tzinfo=UTC))

    def test_the_three_cover_the_day_without_gaps_or_overlaps(self):
        for earlier, later in zip(self.shifts, self.shifts[1:]):
            self.assertEqual(earlier.end, later.start)

    def test_a_moment_belongs_to_exactly_one_shift(self):
        moment = datetime(2026, 8, 6, 9, 30, tzinfo=UTC)
        self.assertEqual([s.contains(moment) for s in self.shifts], [False, True, False])

    def test_the_boundary_belongs_to_the_shift_it_starts(self):
        """Ровно 8:00 - это уже первая смена, а не хвост ночной."""
        eight = datetime(2026, 8, 6, 8, 0, tzinfo=UTC)
        self.assertFalse(self.shifts[0].contains(eight))
        self.assertTrue(self.shifts[1].contains(eight))

    def test_another_factory_keeps_other_hours(self):
        shifts = shifts_for(date(2026, 8, 6), UTC, time(6, 0), time(18, 0))
        self.assertEqual(shifts[1].start, datetime(2026, 8, 6, 6, 0, tzinfo=UTC))
        self.assertEqual(shifts[1].end, datetime(2026, 8, 6, 18, 0, tzinfo=UTC))


class RowTests(unittest.TestCase):
    def test_the_total_is_the_sum_of_the_shifts(self):
        row = Row("Хлеб", by_shift=[Decimal(100), Decimal(250), Decimal(50)])
        self.assertEqual(row.produced, Decimal(400))

    def test_the_closing_balance_is_what_is_left_after_the_order(self):
        row = Row("Хлеб", opening=Decimal(20), by_shift=[Decimal(300)], planned=Decimal(310))
        self.assertEqual(row.closing, Decimal(10))

    def test_a_shortfall_is_negative_and_flagged(self):
        row = Row("Хлеб", opening=Decimal(0), by_shift=[Decimal(90)], planned=Decimal(100))
        self.assertEqual(row.closing, Decimal(-10))
        self.assertTrue(row.is_short)
        self.assertFalse(row.is_done)

    def test_meeting_the_plan_exactly_counts_as_done(self):
        row = Row("Хлеб", by_shift=[Decimal(100)], planned=Decimal(100))
        self.assertTrue(row.is_done)
        self.assertFalse(row.is_short)

    def test_a_product_with_no_plan_is_not_done_merely_by_existing(self):
        """Иначе строка склада без заказа зеленела бы просто так."""
        row = Row("Хлеб", by_shift=[Decimal(0)], planned=Decimal(0))
        self.assertFalse(row.is_done)


class BuildRowsTests(unittest.TestCase):
    def test_a_product_present_only_in_the_plan_still_gets_a_row(self):
        """Именно эти строки и важны: заказали, но не сделали ни штуки."""
        rows = build_rows({"Багет": Decimal(50)}, {}, {}, 3)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].by_shift, [Decimal(0)] * 3)
        self.assertTrue(rows[0].is_short)

    def test_a_product_produced_without_a_plan_also_appears(self):
        rows = build_rows({}, {"Батон": [Decimal(10), Decimal(0), Decimal(0)]}, {}, 3)
        self.assertEqual(rows[0].product_name, "Батон")
        self.assertEqual(rows[0].closing, Decimal(10))

    def test_rows_are_sorted_by_name_ignoring_case(self):
        rows = build_rows({"Ржаной": Decimal(1), "багет": Decimal(1), "Батон": Decimal(1)}, {}, {}, 1)
        self.assertEqual([r.product_name for r in rows], ["багет", "Батон", "Ржаной"])

    def test_the_three_sources_meet_on_one_row(self):
        rows = build_rows(
            {"Хлеб": Decimal(500)},
            {"Хлеб": [Decimal(200), Decimal(250), Decimal(0)]},
            {"Хлеб": Decimal(30)},
            3,
        )
        row = rows[0]
        self.assertEqual(row.opening, Decimal(30))
        self.assertEqual(row.produced, Decimal(450))
        self.assertEqual(row.planned, Decimal(500))
        self.assertEqual(row.closing, Decimal(-20))


class TotalsTests(unittest.TestCase):
    def test_the_bottom_line_adds_up_every_column(self):
        rows = build_rows(
            {"Хлеб": Decimal(100), "Батон": Decimal(200)},
            {"Хлеб": [Decimal(60), Decimal(40)], "Батон": [Decimal(100), Decimal(50)]},
            {"Хлеб": Decimal(5)},
            2,
        )
        result = totals(rows, 2)
        self.assertEqual(result["opening"], Decimal(5))
        self.assertEqual(result["by_shift"], [Decimal(160), Decimal(90)])
        self.assertEqual(result["produced"], Decimal(250))
        self.assertEqual(result["planned"], Decimal(300))
        self.assertEqual(result["closing"], Decimal(-45))

    def test_it_counts_how_many_positions_are_short(self):
        rows = build_rows(
            {"Хлеб": Decimal(100), "Батон": Decimal(10), "Багет": Decimal(5)},
            {"Хлеб": [Decimal(20)], "Батон": [Decimal(10)]},
            {},
            1,
        )
        self.assertEqual(totals(rows, 1)["short"], 2)

    def test_an_empty_sheet_totals_to_zero_rather_than_failing(self):
        result = totals([], 3)
        self.assertEqual(result["produced"], Decimal(0))
        self.assertEqual(result["by_shift"], [Decimal(0)] * 3)
        self.assertEqual(result["short"], 0)


if __name__ == "__main__":
    unittest.main()
