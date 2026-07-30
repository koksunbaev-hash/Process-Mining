from django.test import TestCase
from django.urls import reverse

from apps.bakery.models import BatchStageHistory, ProductionBatch

from .factories import create_queued_batch, create_user
from .helpers import assert_move_rejected, move_batch


class QueueStageTests(TestCase):
    def setUp(self):
        self.user = create_user()
        self.batch = create_queued_batch(self.user)

    def test_new_batch_is_in_queue(self):
        self.assertEqual(self.batch.current_stage.code, "queue")

    def test_new_batch_is_not_in_mixing(self):
        self.assertNotEqual(self.batch.current_stage.code, "mixing")

    def test_queue_status_is_queued(self):
        self.assertEqual(self.batch.status, ProductionBatch.Status.QUEUED)

    def test_queue_to_mixing_is_allowed(self):
        move_batch(self.batch, "mixing", self.user, "start")
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_stage.code, "mixing")

    def test_queue_to_forming_is_forbidden(self):
        assert_move_rejected(self, self.batch, "forming", self.user)

    def test_queue_to_oven_is_forbidden(self):
        assert_move_rejected(self, self.batch, "oven", self.user)

    def test_queue_to_warehouse_is_forbidden(self):
        assert_move_rejected(self, self.batch, "warehouse", self.user)

    def test_queue_to_done_is_forbidden(self):
        assert_move_rejected(self, self.batch, "done", self.user)

    def test_history_is_created_when_leaving_queue(self):
        before = BatchStageHistory.objects.filter(batch=self.batch).count()
        move_batch(self.batch, "mixing", self.user, "queue done")
        self.assertEqual(BatchStageHistory.objects.filter(batch=self.batch).count(), before + 1)

    def test_history_keeps_user_and_comment(self):
        move_batch(self.batch, "mixing", self.user, "operator note")
        row = self.batch.stage_history.order_by("-created_at").first()
        self.assertEqual(row.changed_by, self.user)
        self.assertEqual(row.comment, "operator note")

    def test_kanban_page_contains_queue_batch(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("bakery:kanban"))
        self.assertContains(response, self.batch.batch_number)
