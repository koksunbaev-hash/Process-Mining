from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.bakery.models import BatchStageHistory, ProductionBatch
from apps.bakery.services import pause_batch, resume_batch

from .factories import create_user
from .helpers import assert_move_rejected, create_batch_at_stage, move_batch


class MixingStageTests(TestCase):
    def setUp(self):
        self.user = create_user()

    def test_queue_to_mixing_works(self):
        batch = create_batch_at_stage("queue", self.user)
        move_batch(batch, "mixing", self.user, "start")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "mixing")

    def test_mixing_sets_in_progress(self):
        batch = create_batch_at_stage("queue", self.user)
        move_batch(batch, "mixing", self.user, "start")
        batch.refresh_from_db()
        self.assertEqual(batch.status, ProductionBatch.Status.IN_PROGRESS)

    def test_actual_start_exists_after_mixing(self):
        batch = create_batch_at_stage("queue", self.user)
        move_batch(batch, "mixing", self.user, "start")
        batch.refresh_from_db()
        self.assertIsNotNone(batch.actual_start)

    def test_repeated_mixing_is_forbidden(self):
        batch = create_batch_at_stage("mixing", self.user)
        assert_move_rejected(self, batch, "mixing", self.user)

    def test_mixing_to_forming_works(self):
        batch = create_batch_at_stage("mixing", self.user)
        move_batch(batch, "forming", self.user, "done")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "forming")

    def test_mixing_to_proofing_forbidden(self):
        assert_move_rejected(self, create_batch_at_stage("mixing", self.user), "proofing", self.user)

    def test_mixing_to_oven_forbidden(self):
        assert_move_rejected(self, create_batch_at_stage("mixing", self.user), "oven", self.user)

    def test_mixing_to_warehouse_forbidden(self):
        assert_move_rejected(self, create_batch_at_stage("mixing", self.user), "warehouse", self.user)

    def test_mixing_to_done_forbidden(self):
        assert_move_rejected(self, create_batch_at_stage("mixing", self.user), "done", self.user)

    def test_mixing_can_pause(self):
        batch = create_batch_at_stage("mixing", self.user)
        pause_batch(batch, self.user, "water correction")
        batch.refresh_from_db()
        self.assertEqual(batch.status, ProductionBatch.Status.PAUSED)

    def test_paused_mixing_cannot_move(self):
        batch = create_batch_at_stage("mixing", self.user)
        pause_batch(batch, self.user, "wait")
        assert_move_rejected(self, batch, "forming", self.user, ValidationError)

    def test_resume_allows_moving_again(self):
        batch = create_batch_at_stage("mixing", self.user)
        pause_batch(batch, self.user, "wait")
        resume_batch(batch, self.user, "go")
        move_batch(batch, "forming", self.user, "done")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "forming")

    def test_history_queue_to_mixing_is_recorded(self):
        batch = create_batch_at_stage("mixing", self.user)
        self.assertTrue(BatchStageHistory.objects.filter(batch=batch, from_stage__code="queue", to_stage__code="mixing").exists())

    def test_history_mixing_to_forming_is_recorded(self):
        batch = create_batch_at_stage("mixing", self.user)
        move_batch(batch, "forming", self.user, "done")
        self.assertTrue(BatchStageHistory.objects.filter(batch=batch, from_stage__code="mixing", to_stage__code="forming").exists())
