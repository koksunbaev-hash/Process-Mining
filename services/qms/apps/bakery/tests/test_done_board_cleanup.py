"""Утренняя уборка колонки «Готово».

Проверяется то, ради чего всё и сделано: в восемь утра смена подходит к доске,
на которой нет вчерашнего, — и при этом ни одна строка не потеряна. Второе
важнее первого: доска это вид, а история этапов кормит карту процесса, столбцы
смен в листе заказа и поток в Influx.

Граница дня проверяется отдельно и без базы: это обычная функция над обычным
временем, и ошибка в ней стоила бы выпуска ночной смены.
"""

import unittest
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.bakery.models import BatchStageHistory, ProductionBatch, ProductionStage
from apps.bakery.production_sheet import board_day_start
from apps.bakery.services import sweep_done_board

UTC = dt_timezone.utc


class BoardDayStartTests(unittest.TestCase):
    """Последние наступившие 8:00 — и ни минутой позже."""

    def test_during_the_day_the_boundary_is_this_morning(self):
        moment = datetime(2026, 8, 25, 14, 30, tzinfo=UTC)
        self.assertEqual(board_day_start(moment), datetime(2026, 8, 25, 8, 0, tzinfo=UTC))

    def test_at_night_the_boundary_is_still_yesterday_morning(self):
        """Ночная смена печёт с восьми вечера до восьми утра. В три часа ночи
        её выпуск обязан оставаться на доске - иначе он пропадал бы прямо
        из-под рук у смены, которая его сделала."""
        moment = datetime(2026, 8, 25, 3, 0, tzinfo=UTC)
        self.assertEqual(board_day_start(moment), datetime(2026, 8, 24, 8, 0, tzinfo=UTC))

    def test_seven_fifty_five_still_belongs_to_the_day_before(self):
        """Ровно тот момент, когда приходит уборка."""
        moment = datetime(2026, 8, 25, 7, 55, tzinfo=UTC)
        self.assertEqual(board_day_start(moment), datetime(2026, 8, 24, 8, 0, tzinfo=UTC))

    def test_eight_sharp_steps_over(self):
        moment = datetime(2026, 8, 25, 8, 0, tzinfo=UTC)
        self.assertEqual(board_day_start(moment), datetime(2026, 8, 25, 8, 0, tzinfo=UTC))

    def test_another_factory_keeps_other_hours(self):
        moment = datetime(2026, 8, 25, 5, 0, tzinfo=UTC)
        self.assertEqual(
            board_day_start(moment, shift_one_start=time(6, 0)),
            datetime(2026, 8, 24, 6, 0, tzinfo=UTC),
        )


class DoneBoardSweepTests(TestCase):
    def setUp(self):
        from .batch_workflow.factories import create_queued_batch, create_stage_list, create_user

        create_stage_list()
        self.user = create_user()
        self.done = ProductionStage.objects.get(code="done")
        self.batch = create_queued_batch(user=self.user)
        self.batch.refresh_from_db()

    def finish(self, batch, when):
        batch.current_stage = self.done
        batch.status = ProductionBatch.Status.COMPLETED
        batch.actual_finish = when
        batch.save(update_fields=["current_stage", "status", "actual_finish"])

    def test_yesterdays_batch_leaves_the_board(self):
        self.finish(self.batch, timezone.now() - timedelta(days=1))

        swept = sweep_done_board()

        self.assertEqual(len(swept), 1)
        self.batch.refresh_from_db()
        self.assertIsNotNone(self.batch.board_cleared_at)

    def test_nothing_is_deleted_and_the_history_survives(self):
        """Ради этого всё и устроено отметкой, а не удалением: из истории
        этапов строится карта процесса и считаются смены в листе заказа."""
        self.finish(self.batch, timezone.now() - timedelta(days=1))
        history_before = BatchStageHistory.objects.filter(batch=self.batch).count()

        sweep_done_board()

        self.assertTrue(ProductionBatch.objects.filter(pk=self.batch.pk).exists())
        self.assertEqual(BatchStageHistory.objects.filter(batch=self.batch).count(), history_before)

    def test_a_batch_still_in_production_is_not_touched(self):
        """Уборка про «Готово». Партия, застрявшая в печи со вчера, остаётся:
        её ещё делают."""
        swept = sweep_done_board()

        self.assertEqual(swept, [])
        self.batch.refresh_from_db()
        self.assertIsNone(self.batch.board_cleared_at)

    def test_running_it_twice_finds_nothing_the_second_time(self):
        self.finish(self.batch, timezone.now() - timedelta(days=1))

        self.assertEqual(len(sweep_done_board()), 1)
        self.assertEqual(sweep_done_board(), [])

    def test_a_dry_run_only_looks(self):
        self.finish(self.batch, timezone.now() - timedelta(days=1))

        swept = sweep_done_board(dry_run=True)

        self.assertEqual(len(swept), 1)
        self.batch.refresh_from_db()
        self.assertIsNone(self.batch.board_cleared_at)

    def test_the_sweep_moves_updated_at_so_open_boards_redraw(self):
        """Массовый update() не трогает auto_now, а по updated_at доска у
        соседа понимает, что пора перерисоваться."""
        self.finish(self.batch, timezone.now() - timedelta(days=1))
        self.batch.refresh_from_db()
        before = self.batch.updated_at

        sweep_done_board()

        self.batch.refresh_from_db()
        self.assertGreater(self.batch.updated_at, before)

    def test_the_command_says_what_it_removed(self):
        self.finish(self.batch, timezone.now() - timedelta(days=1))
        out = StringIO()

        call_command("clear_done_board", stdout=out)

        printed = out.getvalue()
        self.assertIn(self.batch.display_batch_label, printed)
        self.assertIn("убрано с доски партий: 1", printed)

    def test_the_command_on_a_clean_board_says_so(self):
        out = StringIO()

        call_command("clear_done_board", stdout=out)

        self.assertIn("убирать нечего", out.getvalue())


class DoneColumnOnTheBoardTests(TestCase):
    """Вторая половина замысла: даже если уборка не отработала, доска сама
    не показывает вчерашнее."""

    def setUp(self):
        from .batch_workflow.factories import create_queued_batch, create_stage_list, create_user

        create_stage_list()
        self.user = create_user()
        self.user.profile.role = UserProfile.Role.MANAGER
        self.user.profile.save(update_fields=["role"])
        self.client.force_login(self.user)
        self.done = ProductionStage.objects.get(code="done")
        self.batch = create_queued_batch(user=self.user)
        self.batch.refresh_from_db()

    def done_column(self):
        response = self.client.get(reverse("bakery:kanban"))
        for column in response.context["columns"]:
            if column["stage"].code == "done":
                return column
        raise AssertionError("колонки «Готово» на доске нет")

    def finish(self, when):
        self.batch.current_stage = self.done
        self.batch.status = ProductionBatch.Status.COMPLETED
        self.batch.actual_finish = when
        self.batch.save(update_fields=["current_stage", "status", "actual_finish"])

    def test_todays_batch_is_on_the_board(self):
        self.finish(timezone.now())

        self.assertEqual(len(self.done_column()["batches"]), 1)

    def test_yesterdays_batch_is_gone_even_without_the_sweep(self):
        self.finish(timezone.now() - timedelta(days=2))

        self.assertEqual(self.done_column()["batches"], [])
        # И это именно вид, а не удаление.
        self.assertTrue(ProductionBatch.objects.filter(pk=self.batch.pk).exists())

    def test_a_swept_batch_is_gone_the_same_minute(self):
        """Уборка в 7:55 обязана убрать сегодняшнее «Готово» сразу, не дожидаясь
        восьми: смена подходит к доске уже чистой."""
        self.finish(timezone.now())
        sweep_done_board()

        self.assertEqual(self.done_column()["batches"], [])

    def test_the_swept_batch_is_still_findable_in_the_list(self):
        """Убрали с доски - не спрятали от человека: партию по-прежнему видно."""
        self.finish(timezone.now())
        sweep_done_board()

        response = self.client.get(reverse("bakery:batches"))

        self.assertContains(response, reverse("bakery:batch_detail", args=[self.batch.pk]))
