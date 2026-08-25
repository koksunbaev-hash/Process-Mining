"""Поток движений партий в общий InfluxDB.

В сеть тесты не ходят: транспорт подменяется, проверяется сборка точек и
дисциплина отправки. Дисциплина здесь важнее формата: выключенная
интеграция обязана молчать, демо-партии - не покидать стенд, а ошибка
записи - не ронять перемещение.
"""

from unittest import mock

from django.test import TestCase, override_settings

from apps.bakery import influx
from apps.bakery.models import BatchStageHistory

from .batch_workflow.factories import create_queued_batch, create_stage_list, create_user

LIVE = override_settings(
    INFLUX_ENABLED=True,
    INFLUX_URL="http://influx.invalid",
    INFLUX_ORG="opentwins",
    INFLUX_BUCKET="qms",
    INFLUX_TOKEN="test-token",
)


class LineProtocolTests(TestCase):
    def setUp(self):
        create_stage_list()
        self.user = create_user()
        self.batch = create_queued_batch(user=self.user)
        self.batch.refresh_from_db()
        self.history = self.batch.stage_history.latest("created_at")

    def test_the_point_names_the_batch_the_way_the_shop_does(self):
        line = influx.history_point(self.history)
        self.assertTrue(line.startswith("qms_batch_event,stage=queue"))
        self.assertIn(f'batch="{self.batch.display_batch_label}"', line)
        self.assertIn(f'case_id="{self.batch.batch_number}"', line)
        self.assertIn("quantity=100", line)
        # Время - наносекундами, девятнадцать знаков.
        self.assertRegex(line.rsplit(" ", 1)[1], r"^\d{19}$")

    def test_tags_survive_spaces_and_commas(self):
        """«Печь 3» в теге обязана стать «Печь\\ 3»: пробел в line protocol
        отделяет теги от полей, и без экранирования точка рассыпается."""
        self.assertEqual(influx._tag("Печь 3"), "Печь\\ 3")
        self.assertEqual(influx._tag("a,b=c"), "a\\,b\\=c")
        self.assertEqual(influx._field_str('со "скобками"'), '"со \\"скобками\\""')

    def test_the_batch_number_is_a_field_not_a_tag(self):
        """Партий за год - тысячи, и каждая своя серия раздула бы базу.
        Номер партии живёт в полях, теги - только малочисленные значения."""
        line = influx.history_point(self.history)
        tags = line.split(" ")[0]
        self.assertNotIn(self.batch.batch_number, tags)


class InlineThread:
    """Поток, работающий на месте: сигнал шлёт точку из фонового потока, и
    настоящий Thread обгонял бы проверки теста."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._target, self._args, self._kwargs = target, args, kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)


@LIVE
class DisciplineTests(TestCase):
    def setUp(self):
        create_stage_list()
        self.user = create_user()
        patcher = mock.patch.object(influx.threading, "Thread", InlineThread)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_transition_sends_exactly_its_own_point(self):
        with mock.patch.object(influx, "write_lines", return_value=True) as sent:
            with self.captureOnCommitCallbacks(execute=True):
                batch = create_queued_batch(user=self.user)
            batch.refresh_from_db()
        self.assertTrue(sent.called)
        lines = sent.call_args[0][0]
        self.assertEqual(len(lines), 1)
        self.assertIn(f'case_id="{batch.batch_number}"', lines[0])

    def test_demo_batches_never_leave_the_stand(self):
        """Общая витрина показывает завод, а не репетицию."""
        with mock.patch.object(influx, "write_lines", return_value=True) as sent:
            with self.captureOnCommitCallbacks(execute=True):
                batch = create_queued_batch(user=self.user)
                batch.refresh_from_db()
                batch.is_demo = True
                batch.save(update_fields=["is_demo"])
                BatchStageHistory.objects.create(
                    batch=batch, to_stage=batch.current_stage, comment="демо-переход"
                )
        for call in sent.call_args_list:
            for line in call[0][0]:
                self.assertNotIn("демо", line)

    def test_disabled_integration_stays_silent(self):
        with override_settings(INFLUX_ENABLED=False):
            with mock.patch.object(influx, "write_lines") as sent:
                with self.captureOnCommitCallbacks(execute=True):
                    create_queued_batch(user=self.user)
            sent.assert_not_called()

    def test_a_network_error_is_a_log_line_not_a_broken_move(self):
        """Ради этого всё и устроено как у Ditto: витрина отстанет на точку,
        а перемещение партии не заметит ничего."""
        import urllib.error

        def refuse(request, timeout):
            raise urllib.error.URLError("нет сети")

        with mock.patch.object(influx.urllib.request, "urlopen", side_effect=refuse):
            ok = influx.write_lines(["qms_batch_event,stage=queue x=1 1"])
        self.assertFalse(ok)


@LIVE
class SyncCommandTests(TestCase):
    def setUp(self):
        create_stage_list()
        self.user = create_user()

    def test_the_backfill_sends_history_and_skips_demo(self):
        from django.core.management import call_command
        from io import StringIO

        with self.captureOnCommitCallbacks(execute=True):
            with mock.patch.object(influx, "write_lines", return_value=True):
                real = create_queued_batch(user=self.user)
                demo = create_queued_batch(user=self.user, quantity=10)
        demo.refresh_from_db()
        demo.is_demo = True
        demo.save(update_fields=["is_demo"])
        real.refresh_from_db()

        sent_lines = []
        with mock.patch(
            "apps.bakery.management.commands.sync_influx.write_lines",
            side_effect=lambda lines: sent_lines.extend(lines) or True,
        ):
            out = StringIO()
            call_command("sync_influx", stdout=out)

        joined = "\n".join(sent_lines)
        self.assertIn(real.batch_number, joined)
        self.assertNotIn(demo.batch_number, joined)
        self.assertIn("отправлено", out.getvalue())
