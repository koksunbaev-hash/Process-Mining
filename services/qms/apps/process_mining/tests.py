import csv
import json
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.bakery.models import FinishedGoodsStock, ProductionBatch
from apps.bakery.tests.batch_workflow.factories import create_manual_batch, create_user
from apps.bakery.tests.batch_workflow.helpers import move_batch, stage

from .models import ProcessEvent, ProcessEventExport
from .services import (
    CSV_COLUMNS,
    apply_response,
    build_events_csv,
    csv_checksum,
    export_pending_events_to_process_mining,
    multipart_body,
    record_process_event,
    retry_failed_events,
    row_for_event,
    safe_record_process_event,
    send_csv_to_process_mining,
)


class ProcessMiningEventTests(TestCase):
    def setUp(self):
        self.user = create_user(username="pm-admin", role=UserProfile.Role.ADMIN)
        self.batch = create_manual_batch(user=self.user)

    def create_event(self, activity="Начало замеса", **kwargs):
        return record_process_event(
            case_id=kwargs.pop("case_id", self.batch.batch_number),
            case_type=kwargs.pop("case_type", ProcessEvent.CaseType.BATCH),
            activity=activity,
            batch=kwargs.pop("batch", self.batch),
            user=kwargs.pop("user", self.user),
            from_stage=kwargs.pop("from_stage", "queue"),
            to_stage=kwargs.pop("to_stage", "mixing"),
            status=kwargs.pop("status", "in_progress"),
            quantity=kwargs.pop("quantity", Decimal("100.000")),
            unit=kwargs.pop("unit", "шт"),
            event_data=kwargs.pop("event_data", {"comment": "тесто, соль"}),
            **kwargs,
        )

    def test_record_process_event_creates_pending_event(self):
        event = self.create_event()
        self.assertEqual(event.export_status, ProcessEvent.ExportStatus.PENDING)
        self.assertEqual(event.case_id, self.batch.batch_number)
        self.assertEqual(event.activity, "Начало замеса")

    def test_event_id_is_unique(self):
        first = self.create_event()
        second = self.create_event(activity="Передача на формовку")
        self.assertNotEqual(first.event_id, second.event_id)

    def test_event_id_is_not_editable(self):
        field = ProcessEvent._meta.get_field("event_id")
        self.assertFalse(field.editable)

    def test_timestamp_is_timezone_aware(self):
        event = self.create_event()
        self.assertTrue(timezone.is_aware(event.occurred_at))

    def test_batch_relations_are_filled_from_batch(self):
        event = self.create_event(order=None, product=None)
        self.assertEqual(event.order, self.batch.order_item.order)
        self.assertEqual(event.product, self.batch.product)

    def test_anonymous_user_is_not_saved(self):
        class Anonymous:
            is_authenticated = False

        event = self.create_event(user=Anonymous())
        self.assertIsNone(event.user)

    def test_safe_record_does_not_break_business_flow(self):
        with patch("apps.process_mining.services.record_process_event", side_effect=RuntimeError("offline")):
            self.assertIsNone(safe_record_process_event(case_id="B-1", case_type="batch", activity="x"))

    def test_move_batch_creates_process_event(self):
        ProcessEvent.objects.all().delete()
        move_batch(self.batch, "mixing", self.user, "замес начат")
        event = ProcessEvent.objects.get()
        self.assertEqual(event.case_id, self.batch.batch_number)
        self.assertEqual(event.from_stage, "queue")
        self.assertEqual(event.to_stage, "mixing")
        self.assertEqual(event.user, self.user)

    def test_invalid_transition_does_not_create_event(self):
        ProcessEvent.objects.all().delete()
        with self.assertRaises(Exception):
            move_batch(self.batch, "oven", self.user, "нельзя")
        self.assertEqual(ProcessEvent.objects.count(), 0)

    def test_warehouse_transition_records_stock_event(self):
        ProcessEvent.objects.all().delete()
        for code in ["mixing", "forming", "proofing", "oven", "warehouse"]:
            move_batch(self.batch, code, self.user, f"to {code}")
        self.assertTrue(FinishedGoodsStock.objects.filter(batch=self.batch).exists())
        self.assertTrue(ProcessEvent.objects.filter(batch=self.batch, to_stage="warehouse").exists())
        self.assertTrue(ProcessEvent.objects.filter(batch=self.batch, activity__contains="склад").exists())

    def test_done_transition_records_completion(self):
        ProcessEvent.objects.all().delete()
        for code in ["mixing", "forming", "proofing", "oven", "warehouse", "done"]:
            move_batch(self.batch, code, self.user, f"to {code}")
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.status, ProductionBatch.Status.COMPLETED)
        self.assertTrue(ProcessEvent.objects.filter(batch=self.batch, to_stage="done").exists())


class ProcessMiningCsvTests(TestCase):
    def setUp(self):
        self.user = create_user(username="pm-csv", role=UserProfile.Role.ADMIN)
        self.batch = create_manual_batch(user=self.user)
        self.event = record_process_event(
            case_id=self.batch.batch_number,
            case_type=ProcessEvent.CaseType.BATCH,
            activity='Замес, "ручной"',
            batch=self.batch,
            user=self.user,
            from_stage="queue",
            to_stage="mixing",
            status="in_progress",
            quantity=Decimal("125.500"),
            unit="шт",
            problem_type="",
            event_data={"note": "строка\nс переносом", "ru": "хлеб"},
        )

    def parse_csv(self, text):
        return list(csv.DictReader(StringIO(text)))

    def test_csv_contains_required_columns_in_order(self):
        header = build_events_csv([self.event]).splitlines()[0].split(",")
        self.assertEqual(header, CSV_COLUMNS)

    def test_csv_has_one_row_per_event(self):
        rows = self.parse_csv(build_events_csv([self.event]))
        self.assertEqual(len(rows), 1)

    def test_csv_preserves_russian_text(self):
        text = build_events_csv([self.event])
        self.assertIn("хлеб", text)
        self.assertIn("Замес", text)

    def test_csv_is_utf8_encodable(self):
        build_events_csv([self.event]).encode("utf-8")

    def test_csv_escapes_commas_quotes_and_newlines(self):
        row = self.parse_csv(build_events_csv([self.event]))[0]
        self.assertEqual(row["activity"], 'Замес, "ручной"')
        self.assertEqual(json.loads(row["metadata"])["note"], "строка\nс переносом")

    def test_row_contains_iso_timestamp_with_timezone(self):
        row = row_for_event(self.event)
        self.assertIn("+", row["timestamp"])

    def test_metadata_is_compact_json(self):
        row = row_for_event(self.event)
        self.assertEqual(json.loads(row["metadata"])["ru"], "хлеб")
        self.assertNotIn(": ", row["metadata"])

    def test_quantity_is_serialized_as_decimal_string(self):
        self.assertEqual(row_for_event(self.event)["quantity"], "125.500")

    def test_checksum_is_stable(self):
        text = build_events_csv([self.event])
        self.assertEqual(csv_checksum(text), csv_checksum(text))

    def test_multipart_body_contains_csv_and_fields(self):
        body = multipart_body("boundary", {"export_id": "1", "source": "kms"}, "events.csv", "a,b\n1,2\n")
        self.assertIn(b'name="source"', body)
        self.assertIn(b"a,b\n1,2", body)


class ProcessMiningExportTests(TestCase):
    def setUp(self):
        self.user = create_user(username="pm-export", role=UserProfile.Role.ADMIN)
        self.batch = create_manual_batch(user=self.user)

    def create_events(self, count):
        events = []
        for index in range(count):
            events.append(
                record_process_event(
                    case_id=f"B-{index}",
                    case_type=ProcessEvent.CaseType.BATCH,
                    activity=f"Событие {index}",
                    batch=self.batch,
                    user=self.user,
                )
            )
        return events

    def accepted_response(self, *args, **kwargs):
        return 200, {"status": "accepted", "received": 10, "accepted": 10, "duplicates": 0, "rejected": 0, "errors": []}

    @patch("apps.process_mining.services.send_csv_to_process_mining")
    def test_empty_package_is_not_sent(self, mocked):
        result = export_pending_events_to_process_mining()
        self.assertEqual(result["events_count"], 0)
        mocked.assert_not_called()

    @patch("apps.process_mining.services.send_csv_to_process_mining")
    def test_batch_size_is_respected(self, mocked):
        self.create_events(3)
        mocked.side_effect = self.accepted_response
        result = export_pending_events_to_process_mining(batch_size=2)
        self.assertEqual(result["events_count"], 2)
        self.assertEqual(ProcessEvent.objects.filter(export_status=ProcessEvent.ExportStatus.PENDING).count(), 1)

    @patch("apps.process_mining.services.send_csv_to_process_mining")
    def test_success_marks_events_sent(self, mocked):
        self.create_events(2)
        mocked.side_effect = self.accepted_response
        export_pending_events_to_process_mining()
        self.assertEqual(ProcessEvent.objects.filter(export_status=ProcessEvent.ExportStatus.SENT).count(), 2)

    @patch("apps.process_mining.services.send_csv_to_process_mining")
    def test_success_creates_export_batch(self, mocked):
        self.create_events(1)
        mocked.side_effect = self.accepted_response
        export_pending_events_to_process_mining()
        export = ProcessEventExport.objects.get()
        self.assertEqual(export.status, ProcessEventExport.Status.ACCEPTED)
        self.assertTrue(export.checksum)

    @patch("apps.process_mining.services.send_csv_to_process_mining")
    def test_export_saves_response_status_and_body(self, mocked):
        self.create_events(1)
        mocked.return_value = (202, {"status": "accepted", "errors": []})
        export_pending_events_to_process_mining()
        export = ProcessEventExport.objects.get()
        self.assertEqual(export.response_status_code, 202)
        self.assertIn("accepted", export.response_body)

    @patch("apps.process_mining.services.send_csv_to_process_mining")
    def test_partial_response_marks_only_rejected_failed(self, mocked):
        events = self.create_events(2)
        mocked.return_value = (
            200,
            {
                "status": "partially_accepted",
                "errors": [{"event_id": str(events[0].event_id), "code": "INVALID_TIMESTAMP", "message": "bad"}],
            },
        )
        export_pending_events_to_process_mining()
        events[0].refresh_from_db()
        events[1].refresh_from_db()
        self.assertEqual(events[0].export_status, ProcessEvent.ExportStatus.FAILED)
        self.assertEqual(events[1].export_status, ProcessEvent.ExportStatus.SENT)

    @patch("apps.process_mining.services.send_csv_to_process_mining")
    def test_duplicates_are_treated_as_sent(self, mocked):
        self.create_events(1)
        mocked.return_value = (200, {"status": "accepted", "accepted": 0, "duplicates": 1, "errors": []})
        export_pending_events_to_process_mining()
        self.assertEqual(ProcessEvent.objects.get().export_status, ProcessEvent.ExportStatus.SENT)

    @patch("apps.process_mining.services.send_csv_to_process_mining", side_effect=TimeoutError("timeout"))
    def test_timeout_returns_events_to_pending(self, mocked):
        event = self.create_events(1)[0]
        export_pending_events_to_process_mining()
        event.refresh_from_db()
        self.assertEqual(event.export_status, ProcessEvent.ExportStatus.PENDING)
        self.assertIn("timeout", event.last_error)

    @override_settings(PROCESS_MINING_MAX_RETRIES=1)
    @patch("apps.process_mining.services.send_csv_to_process_mining", side_effect=TimeoutError("timeout"))
    def test_max_retries_moves_to_dead_letter(self, mocked):
        event = self.create_events(1)[0]
        export_pending_events_to_process_mining()
        event.refresh_from_db()
        self.assertEqual(event.export_status, ProcessEvent.ExportStatus.DEAD_LETTER)

    @patch("apps.process_mining.services.send_csv_to_process_mining")
    def test_dry_run_does_not_change_statuses(self, mocked):
        event = self.create_events(1)[0]
        result = export_pending_events_to_process_mining(dry_run=True)
        event.refresh_from_db()
        self.assertEqual(event.export_status, ProcessEvent.ExportStatus.PENDING)
        self.assertIn("event_id", result["csv"])
        mocked.assert_not_called()

    def test_retry_failed_events_returns_failed_to_pending(self):
        event = self.create_events(1)[0]
        event.export_status = ProcessEvent.ExportStatus.FAILED
        event.save(update_fields=["export_status"])
        self.assertEqual(retry_failed_events(), 1)
        event.refresh_from_db()
        self.assertEqual(event.export_status, ProcessEvent.ExportStatus.PENDING)

    @patch("apps.process_mining.services.send_csv_to_process_mining")
    def test_processing_status_is_set_before_http_call(self, mocked):
        self.create_events(1)

        def inspect_processing(export, csv_text, checksum):
            self.assertEqual(ProcessEvent.objects.filter(export_status=ProcessEvent.ExportStatus.PROCESSING).count(), 1)
            return 200, {"status": "accepted", "errors": []}

        mocked.side_effect = inspect_processing
        export_pending_events_to_process_mining()

    @patch("apps.process_mining.services.send_csv_to_process_mining")
    def test_http_500_is_recorded_as_failure(self, mocked):
        self.create_events(1)
        mocked.side_effect = OSError("HTTP Error 500")
        result = export_pending_events_to_process_mining()
        self.assertIn("HTTP Error 500", result["error"])
        self.assertEqual(ProcessEventExport.objects.get().status, ProcessEventExport.Status.FAILED)

    @patch("apps.process_mining.services.send_csv_to_process_mining")
    def test_invalid_json_error_returns_pending(self, mocked):
        self.create_events(1)
        mocked.side_effect = json.JSONDecodeError("bad", "x", 0)
        export_pending_events_to_process_mining()
        self.assertEqual(ProcessEvent.objects.get().export_status, ProcessEvent.ExportStatus.PENDING)

    def test_apply_response_saves_failed_error_message(self):
        event = self.create_events(1)[0]
        export = ProcessEventExport.objects.create(events_count=1)
        apply_response([event], export, {"status": "partially_accepted", "errors": [{"event_id": str(event.event_id), "code": "BAD", "message": "wrong"}]})
        event.refresh_from_db()
        self.assertEqual(event.export_status, ProcessEvent.ExportStatus.FAILED)
        self.assertIn("BAD", event.last_error)

    @override_settings(
        PROCESS_MINING_EVENT_LOG_URL="https://pm.example/api/event-logs/import/",
        PROCESS_MINING_API_TOKEN="secret-token",
    )
    @patch("apps.process_mining.services.urllib.request.urlopen")
    def test_api_token_is_sent_in_header(self, mocked):
        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"status":"accepted","errors":[]}'

        mocked.return_value = Response()
        export = ProcessEventExport.objects.create(events_count=1, file_name="events.csv")
        send_csv_to_process_mining(export, "event_id,case_id,activity,timestamp\n", "abc")
        request = mocked.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer secret-token")
        self.assertEqual(request.get_header("Idempotency-key"), str(export.export_id))

    @patch("apps.process_mining.services.logger")
    @patch("apps.process_mining.services.send_csv_to_process_mining", side_effect=TimeoutError("secret-token"))
    def test_authorization_header_is_not_logged_by_export(self, mocked, logger):
        self.create_events(1)
        export_pending_events_to_process_mining()
        logger.exception.assert_not_called()


class ProcessMiningDashboardTests(TestCase):
    def setUp(self):
        self.admin = create_user(username="pm-ui-admin", role=UserProfile.Role.ADMIN, password="pass")
        self.operator = create_user(username="pm-ui-operator", role=UserProfile.Role.MIXING_OPERATOR, password="pass")

    def test_anonymous_user_is_redirected_from_dashboard(self):
        response = self.client.get(reverse("process_mining:dashboard"))
        self.assertEqual(response.status_code, 302)

    def test_operator_cannot_open_dashboard(self):
        self.client.login(username="pm-ui-operator", password="pass")
        response = self.client.get(reverse("process_mining:dashboard"))
        self.assertEqual(response.status_code, 403)

    def test_admin_can_open_dashboard(self):
        self.client.login(username="pm-ui-admin", password="pass")
        response = self.client.get(reverse("process_mining:dashboard"))
        self.assertEqual(response.status_code, 200)

    @patch("apps.process_mining.views.export_pending_events_to_process_mining")
    def test_export_now_button_runs_export(self, mocked):
        mocked.return_value = {"events_count": 0}
        self.client.login(username="pm-ui-admin", password="pass")
        response = self.client.post(reverse("process_mining:dashboard"), {"action": "export_now"})
        self.assertEqual(response.status_code, 302)
        mocked.assert_called_once()

    def test_download_last_csv_returns_404_when_empty(self):
        self.client.login(username="pm-ui-admin", password="pass")
        response = self.client.get(reverse("process_mining:download_last_csv"))
        self.assertEqual(response.status_code, 404)

    def test_download_last_csv_returns_file(self):
        ProcessEventExport.objects.create(file_name="last.csv", csv_content="event_id,case_id\n1,B-1\n")
        self.client.login(username="pm-ui-admin", password="pass")
        response = self.client.get(reverse("process_mining:download_last_csv"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")


class ProcessMiningFullScenarioTests(TestCase):
    def setUp(self):
        self.user = create_user(username="pm-flow", role=UserProfile.Role.ADMIN)
        self.batch = create_manual_batch(user=self.user)

    @patch("apps.process_mining.services.send_csv_to_process_mining")
    def test_full_batch_move_to_csv_to_sent(self, mocked):
        mocked.return_value = (200, {"status": "accepted", "received": 1, "accepted": 1, "duplicates": 0, "rejected": 0, "errors": []})
        ProcessEvent.objects.all().delete()
        move_batch(self.batch, "mixing", self.user, "старт замеса")
        self.assertEqual(ProcessEvent.objects.count(), 1)
        export_pending_events_to_process_mining()
        event = ProcessEvent.objects.get()
        self.assertEqual(event.export_status, ProcessEvent.ExportStatus.SENT)
        self.assertTrue(event.export.checksum)

    @patch("apps.process_mining.services.send_csv_to_process_mining")
    def test_repeated_export_does_not_resend_sent_event(self, mocked):
        mocked.return_value = (200, {"status": "accepted", "errors": []})
        record_process_event(case_id="B-1", case_type="batch", activity="Начало замеса")
        export_pending_events_to_process_mining()
        export_pending_events_to_process_mining()
        self.assertEqual(mocked.call_count, 1)

    @patch("apps.process_mining.services.send_csv_to_process_mining", side_effect=TimeoutError("offline"))
    def test_business_batch_move_survives_unavailable_process_mining(self, mocked):
        move_batch(self.batch, "mixing", self.user, "замес")
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_stage, stage("mixing"))
