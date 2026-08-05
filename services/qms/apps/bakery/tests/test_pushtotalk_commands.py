from django.test import TestCase, override_settings
from django.test import Client
from rest_framework.test import APIClient

from apps.accounts.models import UserProfile
from apps.bakery.models import VoiceCommand, VoiceMessage
from apps.bakery.tests.batch_workflow.factories import create_user
from apps.bakery.tests.batch_workflow.helpers import create_batch_at_stage


@override_settings(
    PUSHTOTALK_API_TOKEN="ptt-secret",
    PUSHTOTALK_DEFAULT_USERNAME="ptt-dispatcher",
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class PushToTalkCommandApiTests(TestCase):
    def setUp(self):
        self.user = create_user("ptt-dispatcher", UserProfile.Role.PRODUCTION_DISPATCHER)
        self.client = APIClient()

    def post_command(self, payload, token="ptt-secret"):
        return self.client.post(
            "/api/pushtotalk/commands/",
            payload,
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

    def move_to_forming_text(self, batch):
        return (
            b"\xcf\xe0\xf0\xf2\xe8\xff ".decode("cp1251")
            + batch.batch_number
            + b" \xe7\xe0\xea\xee\xed\xf7\xe8\xeb\xe0 \xe7\xe0\xec\xe5\xf1, "
            b"\xef\xe5\xf0\xe5\xe4\xe0\xf2\xfc \xed\xe0 \xf4\xee\xf0\xec\xee\xe2\xea\xf3".decode("cp1251")
        )

    def test_pushtotalk_text_executes_command_immediately(self):
        batch = create_batch_at_stage("mixing", self.user)

        response = self.post_command(
            {
                "text": self.move_to_forming_text(batch),
                "client_request_id": "ptt-1",
            }
        )

        self.assertEqual(response.status_code, 201, response.data)
        voice = VoiceMessage.objects.get(client_request_id="ptt-1")
        self.assertEqual(voice.transcription_status, VoiceMessage.TranscriptionStatus.COMPLETED)
        self.assertEqual(voice.created_by, self.user)
        self.assertEqual(voice.audio_file.name, "")
        self.assertTrue(VoiceCommand.objects.filter(voice_message=voice).exists())
        self.assertEqual(response.data["command_id"], voice.command.pk)
        self.assertTrue(response.data["executed"])
        voice.command.refresh_from_db()
        self.assertEqual(voice.command.status, VoiceCommand.Status.EXECUTED)
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "forming")

    def test_pushtotalk_accepts_server_to_server_post_without_csrf_token(self):
        batch = create_batch_at_stage("mixing", self.user)
        csrf_client = Client(enforce_csrf_checks=True)

        response = csrf_client.post(
            "/api/pushtotalk/commands/",
            data={
                "text": self.move_to_forming_text(batch),
                "client_request_id": "ptt-no-csrf",
            },
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer ptt-secret",
        )

        self.assertEqual(response.status_code, 201, response.content)
        voice = VoiceMessage.objects.get(client_request_id="ptt-no-csrf")
        self.assertEqual(voice.command.status, VoiceCommand.Status.EXECUTED)

    @override_settings(PUSHTOTALK_DEFAULT_USERNAME="missing-dispatcher")
    def test_pushtotalk_uses_admin_fallback_for_immediate_execution(self):
        admin = create_user(
            "fallback-admin",
            UserProfile.Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        batch = create_batch_at_stage("mixing", admin)

        response = self.post_command(
            {
                "text": self.move_to_forming_text(batch),
                "client_request_id": "ptt-admin-fallback",
            }
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data["executed"])
        voice = VoiceMessage.objects.get(client_request_id="ptt-admin-fallback")
        self.assertEqual(voice.created_by, admin)
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "forming")

    def test_pushtotalk_text_is_idempotent_by_client_request_id(self):
        batch = create_batch_at_stage("mixing", self.user)
        payload = {"text": self.move_to_forming_text(batch), "client_request_id": "ptt-same"}

        first = self.post_command(payload)
        second = self.post_command(payload)

        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertTrue(second.data["duplicate"])
        self.assertEqual(VoiceMessage.objects.filter(client_request_id="ptt-same").count(), 1)
        self.assertEqual(VoiceCommand.objects.count(), 1)

    def test_pushtotalk_text_rejects_bad_token(self):
        response = self.post_command({"text": "noop"}, token="wrong")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(VoiceMessage.objects.count(), 0)

    @override_settings(PUSHTOTALK_API_TOKEN="")
    def test_pushtotalk_text_requires_configured_token(self):
        response = self.post_command({"text": "noop"})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(VoiceMessage.objects.count(), 0)

    def test_voice_list_renders_pushtotalk_text_command(self):
        batch = create_batch_at_stage("mixing", self.user)
        self.post_command(
            {
                "text": self.move_to_forming_text(batch),
                "client_request_id": "ptt-ui",
            }
        )
        self.client.force_login(self.user)

        response = self.client.get("/bakery/voice/")

        self.assertEqual(response.status_code, 200)
        voice = VoiceMessage.objects.get(client_request_id="ptt-ui")
        voice.command.refresh_from_db()
        self.assertEqual(voice.command.status, VoiceCommand.Status.EXECUTED)

    def test_text_command_has_no_public_audio_file(self):
        batch = create_batch_at_stage("mixing", self.user)
        self.post_command(
            {
                "text": self.move_to_forming_text(batch),
                "client_request_id": "ptt-no-audio",
            }
        )
        voice = VoiceMessage.objects.get(client_request_id="ptt-no-audio")
        self.client.force_login(self.user)

        response = self.client.get(f"/bakery/voice/{voice.pk}/audio/")

        self.assertEqual(response.status_code, 404)
