from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import UserProfile

from .factories import create_problem, create_user
from .helpers import WORKFLOW, create_batch_at_stage, stage


class BatchApiTests(TestCase):
    def setUp(self):
        self.user = create_user()
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_get_batch_detail(self):
        batch = create_batch_at_stage("queue", self.user)
        self.assertEqual(self.client.get(f"/api/batches/{batch.pk}/").status_code, 200)

    def test_get_batch_list(self):
        create_batch_at_stage("queue", self.user)
        self.assertEqual(self.client.get("/api/batches/").status_code, 200)

    def test_unauthorized_request_forbidden(self):
        batch = create_batch_at_stage("queue", self.user)
        self.client.force_authenticate(user=None)
        self.assertIn(self.client.post(f"/api/batches/{batch.pk}/next_stage/").status_code, [401, 403])

    def test_auditor_post_forbidden(self):
        batch = create_batch_at_stage("queue", self.user)
        auditor = create_user("api-auditor", UserProfile.Role.AUDITOR)
        self.client.force_authenticate(auditor)
        self.assertEqual(self.client.post(f"/api/batches/{batch.pk}/next_stage/").status_code, 403)

    def test_invalid_transition_returns_400(self):
        batch = create_batch_at_stage("queue", self.user)
        response = self.client.post(f"/api/batches/{batch.pk}/move/", {"stage": stage("oven").pk})
        self.assertEqual(response.status_code, 400)

    def test_comment_is_saved(self):
        batch = create_batch_at_stage("queue", self.user)
        self.client.post(f"/api/batches/{batch.pk}/next_stage/", {"comment": "api comment"})
        self.assertEqual(batch.stage_history.order_by("-created_at").first().comment, "api comment")

    def test_changed_by_is_request_user(self):
        batch = create_batch_at_stage("queue", self.user)
        self.client.post(f"/api/batches/{batch.pk}/next_stage/", {"changed_by": 999})
        self.assertEqual(batch.stage_history.order_by("-created_at").first().changed_by, self.user)

    def test_paused_batch_returns_400(self):
        from apps.bakery.services import pause_batch
        batch = create_batch_at_stage("mixing", self.user)
        pause_batch(batch, self.user, "pause")
        self.assertEqual(self.client.post(f"/api/batches/{batch.pk}/next_stage/").status_code, 400)

    def test_blocked_batch_returns_400(self):
        batch = create_batch_at_stage("mixing", self.user)
        create_problem(batch)
        self.assertEqual(self.client.post(f"/api/batches/{batch.pk}/next_stage/").status_code, 400)

    def test_completed_batch_returns_400(self):
        batch = create_batch_at_stage("done", self.user)
        self.assertEqual(self.client.post(f"/api/batches/{batch.pk}/move/", {"stage": stage("warehouse").pk, "comment": "back"}).status_code, 400)


def make_api_next_test(from_code, to_code):
    def test(self):
        batch = create_batch_at_stage(from_code, self.user)
        response = self.client.post(f"/api/batches/{batch.pk}/next_stage/", {"comment": to_code})
        self.assertEqual(response.status_code, 200)
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, to_code)
        self.assertEqual(response.data["current_stage"], stage(to_code).pk)
    return test


for from_code, to_code in zip(WORKFLOW[:-1], WORKFLOW[1:]):
    setattr(BatchApiTests, f"test_api_next_{from_code}_to_{to_code}", make_api_next_test(from_code, to_code))
