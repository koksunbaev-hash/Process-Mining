from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import UserProfile

from .factories import create_user
from .helpers import create_batch_at_stage, stage


class BatchViewEndpointTests(TestCase):
    def setUp(self):
        self.user = create_user()
        self.batch = create_batch_at_stage("mixing", self.user)
        self.client.force_login(self.user)

    def test_batch_detail_opens(self):
        self.assertEqual(self.client.get(reverse("bakery:batch_detail", args=[self.batch.pk])).status_code, 200)

    def test_move_view_post_moves_batch(self):
        response = self.client.post(reverse("bakery:move_batch", args=[self.batch.pk]), {"stage": stage("forming").pk, "comment": "form"})
        self.assertEqual(response.status_code, 302)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_stage.code, "forming")

    def test_move_view_rejects_invalid_transition(self):
        response = self.client.post(reverse("bakery:move_batch", args=[self.batch.pk]), {"stage": stage("oven").pk})
        self.assertEqual(response.status_code, 302)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_stage.code, "mixing")

    def test_pause_view_sets_paused(self):
        self.client.post(reverse("bakery:batch_action", args=[self.batch.pk, "pause"]), {"comment": "pause"})
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.status, "paused")

    def test_resume_view_sets_in_progress(self):
        self.client.post(reverse("bakery:batch_action", args=[self.batch.pk, "pause"]), {"comment": "pause"})
        self.client.post(reverse("bakery:batch_action", args=[self.batch.pk, "resume"]), {"comment": "resume"})
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.status, "in_progress")

    def test_prev_view_requires_comment(self):
        batch = create_batch_at_stage("forming", self.user)
        self.client.post(reverse("bakery:batch_action", args=[batch.pk, "prev"]), {"comment": ""})
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "forming")

    def test_prev_view_with_comment_returns(self):
        batch = create_batch_at_stage("forming", self.user)
        self.client.post(reverse("bakery:batch_action", args=[batch.pk, "prev"]), {"comment": "return"})
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "mixing")

    def test_auditor_move_view_does_not_move(self):
        auditor = create_user("view-auditor", UserProfile.Role.AUDITOR)
        self.client.force_login(auditor)
        self.client.post(reverse("bakery:move_batch", args=[self.batch.pk]), {"stage": stage("forming").pk})
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_stage.code, "mixing")
