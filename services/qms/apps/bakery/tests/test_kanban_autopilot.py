"""Автопилот демо-доски.

Проверяется не «красиво ли выглядит», а то, ради чего его вообще можно держать
на боевом стенде: он не трогает заводские данные, не заводит лишних прогонов и
выключается насовсем.
"""

import os
from datetime import date
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.bakery.management.commands.kanban_autopilot import planned_batches
from apps.bakery.models import KanbanDemoRun, ProductionBatch, ProductionOrder
from apps.bakery.tests.batch_workflow.factories import create_manual_batch

ON = {"KANBAN_AUTOPILOT_ENABLED": "1"}


def run(*args, **env):
    out = StringIO()
    with mock.patch.dict(os.environ, {**ON, **env}):
        call_command("kanban_autopilot", *args, stdout=out, stderr=out)
    return out.getvalue()


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

    def test_creates_one_run_and_moves_batches(self):
        run("--force")
        demo_run = KanbanDemoRun.objects.get()
        self.assertEqual(demo_run.status, KanbanDemoRun.Status.RUNNING)
        batches = ProductionBatch.objects.filter(is_demo=True)
        self.assertEqual(batches.count(), demo_run.total_batches)
        self.assertTrue(all(batch.demo_run_id == demo_run.pk for batch in batches))

        before = list(batches.values_list("pk", "current_stage__sequence"))
        run("--force")
        after = dict(batches.values_list("pk", "current_stage__sequence"))
        moved = [pk for pk, sequence in before if after[pk] > sequence]
        self.assertTrue(moved, "такт не сдвинул ни одной партии")

    def test_a_second_run_is_not_started_the_same_day(self):
        """Команда стоит в cron и вызывается раз в полчаса. Если бы каждый
        вызов заводил прогон, к вечеру доска была бы завалена."""
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
