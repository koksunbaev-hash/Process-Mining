import hashlib
import hmac
import json
from decimal import Decimal
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import UserProfile
from apps.audit.models import AuditLog
from apps.bakery.models import BatchStageHistory, VoiceCommand, VoiceMessage
from apps.bakery.services import move_batch
from apps.bakery.voice_process_mining import parse_voice_command
from apps.bakery.tests.batch_workflow.factories import create_user
from apps.bakery.tests.batch_workflow.helpers import create_batch_at_stage, stage
from apps.notifications.models import Notification


def audio_file(name="voice.webm", content_type="audio/webm", size=10):
    return SimpleUploadedFile(name, b"a" * size, content_type=content_type)


def signed_callback(payload, secret="callback-secret"):
    raw = json.dumps(payload).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    return raw, f"sha256={digest}"


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
    PROCESS_MINING_CALLBACK_SECRET="callback-secret",
)
class VoiceProcessMiningTests(TestCase):
    def setUp(self):
        self.user = create_user("voice-dispatcher", UserProfile.Role.PRODUCTION_DISPATCHER)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def upload_voice(self, client_request_id="req-1", file=None):
        with patch("apps.bakery.api.send_voice_to_process_mining") as mocked:
            response = self.client.post(
                "/api/voice-messages/",
                {"audio_file": file or audio_file(), "client_request_id": client_request_id},
                format="multipart",
            )
        return response, mocked

    def callback(self, voice, transcript, confidence=0.96, status="completed"):
        payload = {
            "external_id": voice.pk,
            "task_id": "tr-8821",
            "status": status,
            "transcript": transcript,
            "confidence": confidence,
        }
        raw, signature = signed_callback(payload)
        return self.client.post("/api/process-mining/callback/", data=raw, content_type="application/json", HTTP_X_PROCESS_MINING_SIGNATURE=signature)

    def test_upload_webm(self):
        response, _ = self.upload_voice()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(VoiceMessage.objects.count(), 1)
        self.assertEqual(VoiceMessage.objects.get().mime_type, "audio/webm")

    def test_unauthorized_upload_forbidden(self):
        self.client.force_authenticate(user=None)
        response = self.client.post("/api/voice-messages/", {"audio_file": audio_file()}, format="multipart")
        self.assertIn(response.status_code, [401, 403])

    def test_rejects_wrong_format(self):
        response, _ = self.upload_voice(file=audio_file("bad.exe", "application/x-msdownload"))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(VoiceMessage.objects.count(), 0)

    @override_settings(MAX_VOICE_MESSAGE_SIZE_MB=1)
    def test_rejects_large_file(self):
        response, _ = self.upload_voice(file=audio_file("big.webm", "audio/webm", 2 * 1024 * 1024))
        self.assertEqual(response.status_code, 400)

    def test_client_request_id_prevents_duplicates(self):
        self.upload_voice(client_request_id="same-request")
        self.upload_voice(client_request_id="same-request")
        self.assertEqual(VoiceMessage.objects.filter(client_request_id="same-request").count(), 1)

    def test_upload_calls_process_mining_service(self):
        _, mocked = self.upload_voice(client_request_id="send-service")
        self.assertTrue(mocked.called)

    def test_callback_saves_transcript(self):
        self.upload_voice()
        voice = VoiceMessage.objects.get()
        response = self.callback(voice, "Партия B-154 закончила замес, передать на формовку")
        voice.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(voice.transcription_status, VoiceMessage.TranscriptionStatus.COMPLETED)
        self.assertIn("закончила замес", voice.transcript)

    def test_invalid_callback_signature_rejected(self):
        self.upload_voice()
        voice = VoiceMessage.objects.get()
        payload = {"external_id": voice.pk, "status": "completed"}
        response = self.client.post("/api/process-mining/callback/", data=json.dumps(payload).encode("utf-8"), content_type="application/json", HTTP_X_PROCESS_MINING_SIGNATURE="bad")
        self.assertEqual(response.status_code, 403)

    def test_repeated_callback_does_not_create_duplicate_command(self):
        batch = create_batch_at_stage("mixing", self.user)
        self.upload_voice()
        voice = VoiceMessage.objects.get()
        text = f"Партия {batch.batch_number} закончила замес, передать на формовку"
        self.callback(voice, text)
        self.callback(voice, text)
        self.assertEqual(VoiceCommand.objects.filter(voice_message=voice).count(), 1)

    def test_status_api_returns_processing(self):
        self.upload_voice()
        voice = VoiceMessage.objects.get()
        voice.transcription_status = VoiceMessage.TranscriptionStatus.PROCESSING
        voice.save(update_fields=["transcription_status", "updated_at"])
        response = self.client.get(f"/api/voice-messages/{voice.pk}/status/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "processing")

    def test_status_api_returns_completed_command(self):
        batch = create_batch_at_stage("mixing", self.user)
        self.upload_voice()
        voice = VoiceMessage.objects.get()
        self.callback(voice, f"Партия {batch.batch_number} закончила замес")
        response = self.client.get(f"/api/voice-messages/{voice.pk}/status/")
        self.assertEqual(response.data["status"], "completed")
        self.assertEqual(response.data["command"]["intent"], "move_batch")

    def test_callback_creates_voice_command(self):
        batch = create_batch_at_stage("mixing", self.user)
        self.upload_voice()
        voice = VoiceMessage.objects.get()
        self.callback(voice, f"Партия {batch.batch_number} закончила замес")
        self.assertTrue(VoiceCommand.objects.filter(voice_message=voice).exists())

    def test_low_confidence_requires_review(self):
        batch = create_batch_at_stage("mixing", self.user)
        self.upload_voice()
        voice = VoiceMessage.objects.get()
        self.callback(voice, f"Партия {batch.batch_number} закончила замес", confidence=0.55)
        self.assertEqual(voice.command.status, VoiceCommand.Status.NEEDS_REVIEW)

    def test_confirm_calls_existing_batch_service(self):
        batch = create_batch_at_stage("mixing", self.user)
        self.upload_voice()
        voice = VoiceMessage.objects.get()
        self.callback(voice, f"Партия {batch.batch_number} закончила замес")
        response = self.client.post(f"/api/voice-commands/{voice.command.pk}/confirm/")
        batch.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(batch.current_stage.code, "forming")

    def test_repeated_confirm_does_not_execute_twice(self):
        batch = create_batch_at_stage("mixing", self.user)
        self.upload_voice()
        voice = VoiceMessage.objects.get()
        self.callback(voice, f"Партия {batch.batch_number} закончила замес")
        self.client.post(f"/api/voice-commands/{voice.command.pk}/confirm/")
        before = BatchStageHistory.objects.filter(batch=batch).count()
        response = self.client.post(f"/api/voice-commands/{voice.command.pk}/confirm/")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(BatchStageHistory.objects.filter(batch=batch).count(), before)

    def _move_command(self, batch, to_stage, comment="bad", from_stage="mixing"):
        voice = VoiceMessage.objects.create(audio_file=audio_file(), original_filename="voice.webm", mime_type="audio/webm", file_size=10, created_by=self.user)
        return VoiceCommand.objects.create(
            voice_message=voice,
            intent="move_batch",
            extracted_data={"batch_number": batch.batch_number, "from_stage": from_stage, "to_stage": to_stage, "comment": comment},
            confidence=Decimal("0.96"),
        )

    def test_voice_may_send_a_batch_straight_past_intermediate_stages(self):
        # A spoken order names a destination, not a step: "закончил замес,
        # отправить в склад" skips three stages and is a reasonable thing to say.
        batch = create_batch_at_stage("mixing", self.user)
        command = self._move_command(batch, "warehouse", comment="Забраковали, сразу на склад")
        response = self.client.post(f"/api/voice-commands/{command.pk}/confirm/")
        self.assertEqual(response.status_code, 200)
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "warehouse")

    def test_a_skip_names_the_stages_it_stepped_over(self):
        batch = create_batch_at_stage("mixing", self.user)
        command = self._move_command(batch, "oven", comment="Печь освободилась")
        self.client.post(f"/api/voice-commands/{command.pk}/confirm/")
        history = BatchStageHistory.objects.filter(batch=batch, to_stage__code="oven").latest("created_at")
        self.assertIn("Печь освободилась", history.comment)
        self.assertIn("Формовка", history.comment)
        self.assertIn("Расстойка", history.comment)

    def test_a_skip_without_a_reason_is_refused(self):
        batch = create_batch_at_stage("mixing", self.user)
        command = self._move_command(batch, "oven", comment="")
        response = self.client.post(f"/api/voice-commands/{command.pk}/confirm/")
        self.assertEqual(response.status_code, 400)
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "mixing")

    def test_moving_to_the_stage_it_is_already_on_is_refused(self):
        batch = create_batch_at_stage("mixing", self.user)
        command = self._move_command(batch, "mixing", comment="никуда")
        response = self.client.post(f"/api/voice-commands/{command.pk}/confirm/")
        self.assertEqual(response.status_code, 400)

    def test_an_unrecognised_stage_is_refused_instead_of_crashing(self):
        batch = create_batch_at_stage("mixing", self.user)
        command = self._move_command(batch, "", comment="что-то невнятное")
        response = self.client.post(f"/api/voice-commands/{command.pk}/confirm/")
        self.assertEqual(response.status_code, 400)

    def test_insufficient_permissions_return_403(self):
        batch = create_batch_at_stage("mixing", self.user)
        auditor = create_user("voice-auditor", UserProfile.Role.AUDITOR)
        voice = VoiceMessage.objects.create(audio_file=audio_file(), original_filename="voice.webm", mime_type="audio/webm", file_size=10, created_by=auditor)
        command = VoiceCommand.objects.create(voice_message=voice, intent="move_batch", extracted_data={"batch_number": batch.batch_number, "from_stage": "mixing", "to_stage": "forming"}, confidence=Decimal("0.96"))
        self.client.force_authenticate(auditor)
        self.assertEqual(self.client.post(f"/api/voice-commands/{command.pk}/confirm/").status_code, 403)

    def test_changed_stage_returns_409(self):
        batch = create_batch_at_stage("mixing", self.user)
        voice = VoiceMessage.objects.create(audio_file=audio_file(), original_filename="voice.webm", mime_type="audio/webm", file_size=10, created_by=self.user)
        command = VoiceCommand.objects.create(voice_message=voice, intent="move_batch", extracted_data={"batch_number": batch.batch_number, "from_stage": "mixing", "to_stage": "forming"}, confidence=Decimal("0.96"))
        move_batch(batch, stage("forming"), self.user, "manual")
        response = self.client.post(f"/api/voice-commands/{command.pk}/confirm/")
        self.assertEqual(response.status_code, 409)

    def test_confirm_creates_history_audit_and_notification(self):
        batch = create_batch_at_stage("mixing", self.user)
        self.upload_voice()
        voice = VoiceMessage.objects.get()
        self.callback(voice, f"Партия {batch.batch_number} закончила замес")
        self.client.post(f"/api/voice-commands/{voice.command.pk}/confirm/")
        self.assertTrue(BatchStageHistory.objects.filter(batch=batch, to_stage__code="forming").exists())
        self.assertTrue(AuditLog.objects.filter(action="voice_command_executed").exists())
        self.assertTrue(Notification.objects.filter(notification_type="stage_changed").exists())

    def test_process_mining_failed_callback_saves_error(self):
        self.upload_voice()
        voice = VoiceMessage.objects.get()
        payload = {"external_id": voice.pk, "task_id": "tr-failed", "status": "failed", "error": "Не удалось распознать голос"}
        raw, signature = signed_callback(payload)
        response = self.client.post("/api/process-mining/callback/", data=raw, content_type="application/json", HTTP_X_PROCESS_MINING_SIGNATURE=signature)
        voice.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(voice.transcription_status, "failed")
        self.assertIn("Не удалось", voice.processing_error)

    def test_user_cannot_see_other_voice_status(self):
        other = create_user("other-voice", UserProfile.Role.MIXING_OPERATOR)
        voice = VoiceMessage.objects.create(audio_file=audio_file(), original_filename="voice.webm", mime_type="audio/webm", file_size=10, created_by=other)
        current = create_user("current-voice", UserProfile.Role.MIXING_OPERATOR)
        self.client.force_authenticate(current)
        self.assertEqual(self.client.get(f"/api/voice-messages/{voice.pk}/status/").status_code, 404)

    def test_full_upload_callback_confirm_moves_batch(self):
        batch = create_batch_at_stage("mixing", self.user)
        self.upload_voice(client_request_id="full-flow")
        voice = VoiceMessage.objects.get(client_request_id="full-flow")
        self.callback(voice, f"Партия {batch.batch_number} закончила замес, передать на формовку")
        status_response = self.client.get(f"/api/voice-messages/{voice.pk}/status/")
        self.assertEqual(status_response.data["command"]["extracted_data"]["next_stage"], "Формовка")
        confirm_response = self.client.post(f"/api/voice-commands/{voice.command.pk}/confirm/")
        batch.refresh_from_db()
        self.assertEqual(confirm_response.status_code, 200)
        self.assertEqual(batch.current_stage.code, "forming")


class VoiceStageParsingTests(TestCase):
    """Which stage a spoken sentence is asking for. No database, no audio."""

    def target(self, text):
        return parse_voice_command(text)["to_stage"]

    def test_a_named_destination_beats_an_implied_one(self):
        # Both halves are meaningful: "закончил замес" implies Формовка, while
        # "в склад" states Склад. The stated one is the instruction.
        self.assertEqual(self.target("B-102 закончил замес, отправить в склад"), "warehouse")
        self.assertEqual(self.target("B-110 закончила формовку, отправить в печь"), "oven")

    def test_a_finished_stage_implies_the_next_one(self):
        self.assertEqual(self.target("Партия B-107 закончила замес"), "forming")
        self.assertEqual(self.target("B-108 завершили расстойку"), "oven")

    def test_gender_and_number_do_not_matter(self):
        for text in ("B-101 закончил замес", "B-101 закончила замес", "B-101 закончили замес"):
            self.assertEqual(self.target(text), "forming", text)

    def test_plain_directions(self):
        self.assertEqual(self.target("B-103 передать на формовку"), "forming")
        self.assertEqual(self.target("B-104 отправить в печь"), "oven")
        self.assertEqual(self.target("B-109 перевести в очередь"), "queue")
        self.assertEqual(self.target("B-105 отправь его сразу в готово"), "done")

    def test_a_sentence_naming_no_stage_asks_for_nothing(self):
        self.assertEqual(self.target("B-101 что-то не так"), "")
