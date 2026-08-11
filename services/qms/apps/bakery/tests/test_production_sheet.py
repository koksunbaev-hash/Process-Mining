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
        row = Row(1, "Хлеб", by_shift=[Decimal(100), Decimal(250), Decimal(50)])
        self.assertEqual(row.produced, Decimal(400))

    def test_the_closing_balance_is_what_is_left_after_the_order(self):
        row = Row(1, "Хлеб", opening=Decimal(20), by_shift=[Decimal(300)], planned=Decimal(310))
        self.assertEqual(row.closing, Decimal(10))

    def test_a_shortfall_is_negative_and_flagged(self):
        row = Row(1, "Хлеб", opening=Decimal(0), by_shift=[Decimal(90)], planned=Decimal(100))
        self.assertEqual(row.closing, Decimal(-10))
        self.assertTrue(row.is_short)
        self.assertFalse(row.is_done)

    def test_meeting_the_plan_exactly_counts_as_done(self):
        row = Row(1, "Хлеб", by_shift=[Decimal(100)], planned=Decimal(100))
        self.assertTrue(row.is_done)
        self.assertFalse(row.is_short)

    def test_a_product_with_no_plan_is_not_done_merely_by_existing(self):
        """Иначе строка склада без заказа зеленела бы просто так."""
        row = Row(1, "Хлеб", by_shift=[Decimal(0)], planned=Decimal(0))
        self.assertFalse(row.is_done)


class BuildRowsTests(unittest.TestCase):
    def test_every_product_gets_a_row_even_with_nothing_on_it(self):
        """Лист - это весь ассортимент. Пустая строка тоже сведение, и место,
        куда вписать план, если решат печь."""
        rows = build_rows([(1, "Багет"), (2, "Батон")], {}, {}, {}, 3)
        self.assertEqual([r.product_name for r in rows], ["Багет", "Батон"])
        self.assertEqual(rows[0].by_shift, [Decimal(0)] * 3)

    def test_a_product_planned_but_not_baked_shows_as_short(self):
        rows = build_rows([(1, "Багет")], {1: Decimal(50)}, {}, {}, 3)
        self.assertTrue(rows[0].is_short)
        self.assertEqual(rows[0].closing, Decimal(-50))

    def test_the_order_of_products_is_the_order_given(self):
        """Сортировку выбирает вызывающий - в базе она уже по названию."""
        rows = build_rows([(9, "Ржаной"), (3, "Батон")], {}, {}, {}, 1)
        self.assertEqual([r.product_name for r in rows], ["Ржаной", "Батон"])

    def test_the_three_sources_meet_on_one_row(self):
        rows = build_rows(
            [(7, "Хлеб")],
            {7: Decimal(500)},
            {7: [Decimal(200), Decimal(250), Decimal(0)]},
            {7: Decimal(30)},
            3,
        )
        row = rows[0]
        self.assertEqual(row.product_id, 7)
        self.assertEqual(row.opening, Decimal(30))
        self.assertEqual(row.produced, Decimal(450))
        self.assertEqual(row.planned, Decimal(500))
        self.assertEqual(row.closing, Decimal(-20))

    def test_rows_do_not_share_one_list_of_shifts(self):
        """Иначе правка одной строки меняла бы все - список был бы один на всех."""
        rows = build_rows([(1, "А"), (2, "Б")], {}, {}, {}, 2)
        rows[0].by_shift[0] = Decimal(99)
        self.assertEqual(rows[1].by_shift[0], Decimal(0))


class TotalsTests(unittest.TestCase):
    def test_the_bottom_line_adds_up_every_column(self):
        rows = build_rows(
            [(1, "Хлеб"), (2, "Батон")],
            {1: Decimal(100), 2: Decimal(200)},
            {1: [Decimal(60), Decimal(40)], 2: [Decimal(100), Decimal(50)]},
            {1: Decimal(5)},
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
            [(1, "Хлеб"), (2, "Батон"), (3, "Багет")],
            {1: Decimal(100), 2: Decimal(10), 3: Decimal(5)},
            {1: [Decimal(20)], 2: [Decimal(10)]},
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
