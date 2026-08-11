from django.test import TestCase, override_settings
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
        self.user = create_user("ptt-dispatcher", UserProfile.Role.MANAGER)
        self.client = APIClient()

    def post_command(self, payload, token="ptt-secret"):
        return self.client.post(
            "/api/pushtotalk/commands/",
            payload,
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

    def test_pushtotalk_text_executes_command_immediately(self):
        batch = create_batch_at_stage("mixing", self.user)

        response = self.post_command(
            {
                "text": f"Партия {batch.batch_number} закончила замес, передать на формовку",
                "client_request_id": "ptt-1",
            }
        )

        self.assertEqual(response.status_code, 201)
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

    def test_pushtotalk_text_returns_review_reason_for_unclear_command(self):
        response = self.post_command(
            {
                "text": "семь сакабан",
                "client_request_id": "ptt-unclear",
            }
        )

        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.data["executed"])
        self.assertEqual(response.data["command_status"], VoiceCommand.Status.NEEDS_REVIEW)
        self.assertTrue(response.data["reason"])
        voice = VoiceMessage.objects.get(client_request_id="ptt-unclear")
        voice.command.refresh_from_db()
        self.assertEqual(voice.command.status, VoiceCommand.Status.NEEDS_REVIEW)
        self.assertEqual(voice.command.error_message, response.data["reason"])

    @override_settings(PUSHTOTALK_DEFAULT_USERNAME="missing-ptt-user")
    def test_pushtotalk_text_returns_reason_when_actor_is_not_configured(self):
        batch = create_batch_at_stage("mixing", self.user)

        response = self.post_command(
            {
                "text": f"Партия {batch.batch_number} закончила замес, передать на формовку",
                "client_request_id": "ptt-no-actor",
            }
        )

        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.data["executed"])
        self.assertEqual(response.data["command_status"], VoiceCommand.Status.NEEDS_REVIEW)
        self.assertIn("не настроен", response.data["reason"])
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "mixing")
    def test_pushtotalk_text_is_idempotent_by_client_request_id(self):
        batch = create_batch_at_stage("mixing", self.user)
        payload = {"text": f"Партия {batch.batch_number} закончила замес", "client_request_id": "ptt-same"}

        first = self.post_command(payload)
        second = self.post_command(payload)

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.data["duplicate"])
        self.assertEqual(VoiceMessage.objects.filter(client_request_id="ptt-same").count(), 1)
        self.assertEqual(VoiceCommand.objects.count(), 1)

    def test_pushtotalk_text_rejects_bad_token(self):
        response = self.post_command({"text": "Партия B-1 закончила замес"}, token="wrong")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(VoiceMessage.objects.count(), 0)

    @override_settings(PUSHTOTALK_API_TOKEN="")
    def test_pushtotalk_text_requires_configured_token(self):
        response = self.post_command({"text": "Партия B-1 закончила замес"})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(VoiceMessage.objects.count(), 0)

    def test_voice_list_renders_pushtotalk_text_command(self):
        batch = create_batch_at_stage("mixing", self.user)
        self.post_command(
            {
                "text": f"Партия {batch.batch_number} закончила замес, передать на формовку",
                "client_request_id": "ptt-ui",
            }
        )
        self.client.force_login(self.user)

        response = self.client.get("/bakery/voice/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Партия")
        self.assertContains(response, "выполнена")

    def test_text_command_has_no_public_audio_file(self):
        self.post_command({"text": "Партия B-1 закончила замес", "client_request_id": "ptt-no-audio"})
        voice = VoiceMessage.objects.get(client_request_id="ptt-no-audio")
        self.client.force_login(self.user)

        response = self.client.get(f"/bakery/voice/{voice.pk}/audio/")

        self.assertEqual(response.status_code, 404)
