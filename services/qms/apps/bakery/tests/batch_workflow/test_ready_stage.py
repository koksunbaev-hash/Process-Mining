from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from apps.bakery.models import BatchStageHistory, ProductionBatch

from .factories import create_user
from .helpers import assert_move_rejected, create_batch_at_stage, complete_full_workflow, move_batch


class ReadyStageTests(TestCase):
    def setUp(self):
        self.user = create_user()

    def test_warehouse_to_done_works(self):
        batch = create_batch_at_stage("warehouse", self.user)
        move_batch(batch, "done", self.user, "finish")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "done")

    def test_done_status_is_completed(self):
        batch = create_batch_at_stage("warehouse", self.user)
        move_batch(batch, "done", self.user, "finish")
        batch.refresh_from_db()
        self.assertEqual(batch.status, ProductionBatch.Status.COMPLETED)

    def test_actual_finish_is_set(self):
        batch = create_batch_at_stage("warehouse", self.user)
        move_batch(batch, "done", self.user, "finish")
        batch.refresh_from_db()
        self.assertIsNotNone(batch.actual_finish)

    def test_completed_batch_cannot_move_back(self):
        batch = create_batch_at_stage("done", self.user)
        assert_move_rejected(self, batch, "warehouse", self.user, ValidationError, "return")

    def test_completed_batch_cannot_finish_again(self):
        assert_move_rejected(self, create_batch_at_stage("done", self.user), "done", self.user)

    def test_done_batch_appears_in_kanban_done_column(self):
        batch = create_batch_at_stage("done", self.user)
        self.client.force_login(self.user)
        response = self.client.get(reverse("bakery:kanban"))
        self.assertContains(response, batch.batch_number)

    def test_final_history_record_is_created(self):
        batch = create_batch_at_stage("warehouse", self.user)
        before = batch.stage_history.count()
        move_batch(batch, "done", self.user, "finish")
        self.assertEqual(batch.stage_history.count(), before + 1)

    def test_full_route_contains_six_transitions_after_initial_queue_record(self):
        batch = create_batch_at_stage("queue", self.user)
        complete_full_workflow(batch, self.user)
        self.assertEqual(BatchStageHistory.objects.filter(batch=batch).count(), 7)

    def test_full_duration_is_non_negative(self):
        batch = create_batch_at_stage("queue", self.user)
        complete_full_workflow(batch, self.user)
        batch.refresh_from_db()
        self.assertGreaterEqual((batch.actual_finish - batch.actual_start).total_seconds(), 0)
