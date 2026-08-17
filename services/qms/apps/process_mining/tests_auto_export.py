"""Автоматическая отправка накопившихся событий в аналитику."""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.process_mining.models import ProcessEvent
from apps.process_mining.services import safe_record_process_event


def make_event(index: int):
    """Одно событие.

    Отправка навешена на фиксацию транзакции, а TestCase держит каждый тест
    внутри своей и откатывает её - без captureOnCommitCallbacks обработчик
    никогда не вызовется, и тест «проверял» бы отсутствие вызова.
    """
    return safe_record_process_event(
        case_id=f"B-{index:04d}",
        case_type=ProcessEvent.CaseType.BATCH,
        activity="Замес",
        occurred_at=timezone.now(),
    )


@override_settings(
    PROCESS_MINING_EVENT_LOG_URL="http://analytics.invalid/api/event-logs/import/",
    PROCESS_MINING_AUTO_EXPORT=True,
    PROCESS_MINING_AUTO_EXPORT_THRESHOLD=5,
)
class AutoExportTests(TestCase):
    """Порог, а не каждое событие: перевод партии рождает их пачками, и
    отдельный запрос на каждый шаг превратил бы работу в очередь к сети."""

    def _record(self, count, start=0):
        with self.captureOnCommitCallbacks(execute=True):
            for i in range(start, start + count):
                make_event(i)

    def test_it_waits_until_the_threshold(self):
        with patch("apps.process_mining.services.export_pending_events_to_process_mining") as export:
            self._record(4)
            export.assert_not_called()

    def test_it_fires_on_the_fifth(self):
        with patch("apps.process_mining.services.export_pending_events_to_process_mining") as export:
            export.return_value = {"sent": 5, "failed": 0}
            self._record(5)
            self.assertEqual(export.call_count, 1)

    def test_a_broken_analytics_service_does_not_lose_the_event(self):
        """Партия уже переведена; откатывать перевод из-за недоступной
        аналитики нельзя, а событие должно остаться в очереди."""
        with patch("apps.process_mining.services.export_pending_events_to_process_mining") as export:
            export.side_effect = RuntimeError("сеть недоступна")
            self._record(5)
        self.assertEqual(ProcessEvent.objects.count(), 5)
        self.assertEqual(
            ProcessEvent.objects.filter(export_status=ProcessEvent.ExportStatus.PENDING).count(), 5
        )

    @override_settings(PROCESS_MINING_AUTO_EXPORT=False)
    def test_it_can_be_turned_off(self):
        with patch("apps.process_mining.services.export_pending_events_to_process_mining") as export:
            self._record(9)
            export.assert_not_called()

    @override_settings(PROCESS_MINING_EVENT_LOG_URL="")
    def test_no_address_means_no_attempt(self):
        with patch("apps.process_mining.services.export_pending_events_to_process_mining") as export:
            self._record(9)
            export.assert_not_called()

    def test_already_sent_events_do_not_count_towards_the_threshold(self):
        ProcessEvent.objects.all().delete()
        with patch("apps.process_mining.services.export_pending_events_to_process_mining"):
            self._record(4)
        ProcessEvent.objects.update(export_status=ProcessEvent.ExportStatus.SENT)
        with patch("apps.process_mining.services.export_pending_events_to_process_mining") as export:
            self._record(1, start=99)
            export.assert_not_called()
