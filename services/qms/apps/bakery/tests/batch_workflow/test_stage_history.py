from django.test import TestCase

from apps.bakery.models import BatchStageHistory

from .factories import create_user
from .helpers import assert_move_rejected, create_batch_at_stage, complete_full_workflow, move_batch


class StageHistoryTests(TestCase):
    def setUp(self):
        self.user = create_user()

    def test_history_created_on_each_transition(self):
        batch = create_batch_at_stage("queue", self.user)
        move_batch(batch, "mixing", self.user, "mix")
        self.assertEqual(batch.stage_history.count(), 2)

    def test_from_stage_saved(self):
        batch = create_batch_at_stage("mixing", self.user)
        move_batch(batch, "forming", self.user, "form")
        self.assertEqual(batch.stage_history.order_by("-created_at").first().from_stage.code, "mixing")

    def test_to_stage_saved(self):
        batch = create_batch_at_stage("mixing", self.user)
        move_batch(batch, "forming", self.user, "form")
        self.assertEqual(batch.stage_history.order_by("-created_at").first().to_stage.code, "forming")

    def test_changed_by_saved(self):
        batch = create_batch_at_stage("mixing", self.user)
        move_batch(batch, "forming", self.user, "form")
        self.assertEqual(batch.stage_history.order_by("-created_at").first().changed_by, self.user)

    def test_comment_saved(self):
        batch = create_batch_at_stage("mixing", self.user)
        move_batch(batch, "forming", self.user, "comment")
        self.assertEqual(batch.stage_history.order_by("-created_at").first().comment, "comment")

    def test_created_at_saved(self):
        self.assertIsNotNone(create_batch_at_stage("mixing", self.user).stage_history.first().created_at)

    def test_started_at_saved(self):
        batch = create_batch_at_stage("mixing", self.user)
        move_batch(batch, "forming", self.user, "form")
        self.assertIsNotNone(batch.stage_history.order_by("-created_at").first().started_at)

    def test_finished_at_saved(self):
        batch = create_batch_at_stage("mixing", self.user)
        move_batch(batch, "forming", self.user, "form")
        self.assertIsNotNone(batch.stage_history.order_by("-created_at").first().finished_at)

    def test_history_ordering_is_newest_first_by_default(self):
        batch = create_batch_at_stage("forming", self.user)
        rows = list(batch.stage_history.all())
        self.assertGreaterEqual(rows[0].created_at, rows[-1].created_at)

    def test_full_process_creates_expected_history_count(self):
        batch = create_batch_at_stage("queue", self.user)
        complete_full_workflow(batch, self.user)
        self.assertEqual(BatchStageHistory.objects.filter(batch=batch).count(), 7)

    def test_failed_transition_creates_no_history(self):
        batch = create_batch_at_stage("queue", self.user)
        before = batch.stage_history.count()
        assert_move_rejected(self, batch, "oven", self.user)
        self.assertEqual(batch.stage_history.count(), before)

    def test_backward_transition_creates_history(self):
        batch = create_batch_at_stage("forming", self.user)
        before = batch.stage_history.count()
        move_batch(batch, "mixing", self.user, "return")
        self.assertEqual(batch.stage_history.count(), before + 1)

    def test_backward_reason_is_saved(self):
        batch = create_batch_at_stage("forming", self.user)
        move_batch(batch, "mixing", self.user, "return reason")
        self.assertEqual(batch.stage_history.order_by("-created_at").first().comment, "return reason")
