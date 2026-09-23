"""Автопилот демо-доски.

Проверяется не «красиво ли выглядит», а то, ради чего его вообще можно держать
на боевом стенде: он не трогает заводские данные, не заводит лишних прогонов,
двигает партии по одной с выдержкой на этапе и выключается насовсем.
"""

import os
import re
from datetime import date, timedelta
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.bakery.management.commands.kanban_autopilot import MAX_MOVES_PER_TICK, dwell_for, planned_batches
from apps.bakery.models import BatchStageHistory, KanbanDemoRun, ProductionBatch, ProductionOrder
from apps.bakery.tests.batch_workflow.factories import create_manual_batch

ON = {"KANBAN_AUTOPILOT_ENABLED": "1"}


def run(*args, **env):
    out = StringIO()
    with mock.patch.dict(os.environ, {**ON, **env}):
        call_command("kanban_autopilot", *args, stdout=out, stderr=out)
    return out.getvalue()


def in_queue():
    return ProductionBatch.objects.filter(is_demo=True, current_stage__code="queue").count()


def backdate(batch, minutes):
    """Сдвинуть последнюю запись истории в прошлое - как будто партия отстояла."""
    BatchStageHistory.objects.filter(batch=batch).update(
        created_at=timezone.now() - timedelta(minutes=minutes)
    )


class KanbanAutopilotTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("autopilot-admin", password="x")

    def test_disabled_unless_switched_on(self):
        """Выключён по умолчанию: свежий стенд не должен сам начать писать
        демо-партии в боевую базу только оттого, что команда есть в образе."""
        out = StringIO()
        with mock.patch.dict(os.environ, {"KANBAN_AUTOPILOT_ENABLED": "0"}):
            call_command("kanban_autopilot", "--force", stdout=out)
        self.assertIn("выключено", out.getvalue())
        self.assertFalse(KanbanDemoRun.objects.exists())

    def test_batches_leave_the_queue_one_at_a_time(self):
        """Главная жалоба к прежнему поведению: партии снимались с очереди
        пачкой по семь и шли дальше толпой. Запуск размазан по смене."""
        run("--force")
        demo_run = KanbanDemoRun.objects.get()
        self.assertGreater(demo_run.total_batches, 3)
        self.assertEqual(in_queue(), demo_run.total_batches - 1, "из очереди ушла не одна партия")

        run("--force")
        run("--force")
        self.assertGreaterEqual(in_queue(), demo_run.total_batches - 2,
                                "очередь опустошается быстрее расписания")

    def test_a_batch_waits_on_its_stage(self):
        """Партия должна отстоять на этапе, а не пролетать доску за такт."""
        run("--force")
        moving = ProductionBatch.objects.filter(is_demo=True).exclude(current_stage__code="queue").get()
        stage_before = moving.current_stage_id

        run("--force")
        moving.refresh_from_db()
        self.assertEqual(moving.current_stage_id, stage_before, "партия ушла, не отстояв этап")

        backdate(moving, 240)
        run("--force")
        moving.refresh_from_db()
        self.assertNotEqual(moving.current_stage_id, stage_before, "выдержка вышла, а партия стоит")

    def test_an_overdue_queue_is_released_one_at_a_time(self):
        """Отставшее расписание нагоняется по одной партии, а не залпом.

        Отставание бывает не только теоретически: простой контейнера,
        перезапуск сервера, первый день после включения."""
        run("--force")
        demo_run = KanbanDemoRun.objects.get()
        KanbanDemoRun.objects.filter(pk=demo_run.pk).update(started_at=timezone.now() - timedelta(hours=10))
        before = in_queue()
        run("--force")
        self.assertEqual(in_queue(), before - 1, "очередь ушла залпом")

    def test_the_morning_after_does_not_move_everything_at_once(self):
        """Ночью партии стоят на этапах, и к утру выдержка просрочена у всех
        сразу. Без предела на такт они сдвинулись бы в одну секунду - ровно то,
        от чего доска и должна была уйти."""
        run("--force")
        demo_run = KanbanDemoRun.objects.get()
        KanbanDemoRun.objects.filter(pk=demo_run.pk).update(started_at=timezone.now() - timedelta(hours=10))
        for _ in range(6):
            run("--force")
        in_work = ProductionBatch.objects.filter(is_demo=True).exclude(current_stage__code="queue")
        self.assertGreaterEqual(in_work.count(), 6)

        BatchStageHistory.objects.filter(batch__is_demo=True).update(created_at=timezone.now() - timedelta(hours=16))
        moved = int(re.search(r"сдвинуто (\d+)", run("--force")).group(1))
        self.assertGreaterEqual(moved, 2)
        self.assertLessEqual(moved, MAX_MOVES_PER_TICK)

    def test_yesterdays_run_gives_way_to_todays(self):
        """Недоехавший вчерашний прогон не должен держать доску: пока он
        активен, create_demo_run не заведёт сегодняшний, и утренней очереди
        не будет вовсе."""
        run("--force")
        yesterday = timezone.now() - timedelta(days=1)
        old = KanbanDemoRun.objects.get()
        KanbanDemoRun.objects.filter(pk=old.pk).update(started_at=yesterday, created_at=yesterday)

        run("--force")
        self.assertFalse(KanbanDemoRun.objects.filter(pk=old.pk).exists(), "вчерашний прогон остался")
        today = KanbanDemoRun.objects.get()
        self.assertEqual(timezone.localtime(today.created_at).date(), timezone.localdate())
        self.assertFalse(ProductionBatch.objects.filter(is_demo=True, demo_run_id=old.pk).exists())

    def test_dwell_is_stable_but_different_per_batch(self):
        """Команду будит cron - каждый раз новый процесс. Случайная выдержка
        означала бы, что партия то «пора двигать», то «ещё рано»."""
        self.assertEqual(dwell_for("DEMO-B-0001", "oven"), dwell_for("DEMO-B-0001", "oven"))
        self.assertNotEqual(dwell_for("DEMO-B-0001", "oven"), dwell_for("DEMO-B-0002", "oven"))
        self.assertNotEqual(dwell_for("DEMO-B-0001", "oven"), dwell_for("DEMO-B-0001", "mixing"))
        for stage in ("mixing", "forming", "proofing", "oven", "warehouse"):
            minutes = dwell_for("DEMO-B-0001", stage).total_seconds() / 60
            self.assertGreater(minutes, 10)
            self.assertLess(minutes, 60)

    def test_a_second_run_is_not_started_the_same_day(self):
        """Команда стоит в cron и вызывается раз в несколько минут. Если бы
        каждый вызов заводил прогон, к вечеру доска была бы завалена."""
        run("--force")
        run("--force")
        run("--force")
        self.assertEqual(KanbanDemoRun.objects.count(), 1)

    def test_real_data_is_left_alone(self):
        """Главное условие, на котором это вообще можно держать на боевом
        стенде: заводская партия не должна ни сдвинуться, ни пропасть."""
        real = create_manual_batch("mixing", self.user)
        stage_before, status_before = real.current_stage_id, real.status

        run("--force")
        backdate(real, 600)  # даже «отстоявшую» заводскую двигать нельзя
        run("--force")
        run("--stop")

        real.refresh_from_db()
        self.assertEqual(real.current_stage_id, stage_before, "заводскую партию сдвинуло")
        self.assertEqual(real.status, status_before)
        self.assertFalse(real.is_demo)
        self.assertTrue(ProductionBatch.objects.filter(pk=real.pk).exists(), "заводскую партию удалило")

    def test_stop_removes_everything(self):
        """Выключатель обязан не только остановить, но и убрать следы: иначе
        отключённый автопилот оставит доску навсегда заросшей."""
        run("--force")
        self.assertTrue(ProductionBatch.objects.filter(is_demo=True).exists())
        run("--stop")
        self.assertFalse(ProductionBatch.objects.filter(is_demo=True).exists())
        self.assertFalse(ProductionOrder.objects.filter(is_demo=True).exists())
        self.assertFalse(KanbanDemoRun.objects.exists())

    def test_stop_works_even_when_switched_off(self):
        """Убрать демо надо уметь и после того, как флаг уже сняли."""
        run("--force")
        out = StringIO()
        with mock.patch.dict(os.environ, {"KANBAN_AUTOPILOT_ENABLED": "0"}):
            call_command("kanban_autopilot", "--stop", stdout=out)
        self.assertFalse(ProductionBatch.objects.filter(is_demo=True).exists())

    def test_weekends_are_empty(self):
        """В настоящем журнале суббот и воскресений нет вовсе - цех по ним не
        работает. Демо, идущее в выходной, выдало бы себя сразу."""
        self.assertEqual(planned_batches(date(2026, 9, 26), 1.0), 0)  # суббота
        self.assertEqual(planned_batches(date(2026, 9, 27), 1.0), 0)  # воскресенье
        self.assertGreater(planned_batches(date(2026, 9, 23), 1.0), 0)  # среда

    def test_volume_scales_the_day(self):
        half = [planned_batches(date(2026, 9, 23), 0.5) for _ in range(40)]
        full = [planned_batches(date(2026, 9, 23), 1.0) for _ in range(40)]
        self.assertLess(sum(half) / len(half), sum(full) / len(full))


class BoardVisibilityTests(TestCase):
    """Как демо попадает на экран.

    Элемента управления на доске нет и быть не должно: фильтр
    «Рабочие/Демо/Все» оттуда убирали сознательно, и это стережёт
    `test_kanban_page_has_no_demo_controls_at_all` в test_kanban_demo.py.
    Сама выборка по `is_demo` осталась, поэтому демо показывают параметром в
    адресе — по нему и открывают доску на показах.
    """

    def setUp(self):
        self.user = get_user_model().objects.create_superuser("board-admin", password="x")
        self.client.force_login(self.user)

    def test_demo_is_hidden_by_default_and_shown_by_the_url(self):
        run("--force")
        number = ProductionBatch.objects.filter(is_demo=True).first().batch_number

        self.assertNotContains(self.client.get(reverse("bakery:kanban")), number)
        self.assertContains(self.client.get(reverse("bakery:kanban"), {"demo": "all"}), number)
        self.assertContains(self.client.get(reverse("bakery:kanban"), {"demo": "demo"}), number)

    def test_the_autopilot_adds_nothing_to_the_board(self):
        """Автопилот живёт в cron, а не в интерфейсе: доска не изменилась."""
        response = self.client.get(reverse("bakery:kanban"))
        self.assertNotContains(response, 'name="demo"')
        self.assertNotContains(response, "Демо процесса")
