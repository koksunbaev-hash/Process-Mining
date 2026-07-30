from django.test import TestCase
from django.utils import timezone

from apps.bakery.models import ProductionBatch
from apps.bakery.services import pause_batch, resume_batch

from .factories import create_user
from .helpers import assert_move_rejected, create_batch_at_stage, move_batch


class ProofingStageTests(TestCase):
    def setUp(self):
        self.user = create_user()

    def test_forming_to_proofing_works(self):
        batch = create_batch_at_stage("forming", self.user)
        move_batch(batch, "proofing", self.user, "proof")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "proofing")

    def test_current_stage_is_proofing(self):
        self.assertEqual(create_batch_at_stage("proofing", self.user).current_stage.code, "proofing")

    def test_proofing_to_oven_works(self):
        batch = create_batch_at_stage("proofing", self.user)
        move_batch(batch, "oven", self.user, "bake")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "oven")

    def test_proofing_to_warehouse_forbidden(self):
        assert_move_rejected(self, create_batch_at_stage("proofing", self.user), "warehouse", self.user)

    def test_proofing_to_done_forbidden(self):
        assert_move_rejected(self, create_batch_at_stage("proofing", self.user), "done", self.user)

    def test_repeated_proofing_forbidden(self):
        assert_move_rejected(self, create_batch_at_stage("proofing", self.user), "proofing", self.user)

    def test_pause_on_proofing_works(self):
        batch = create_batch_at_stage("proofing", self.user)
        pause_batch(batch, self.user, "slow rise")
        batch.refresh_from_db()
        self.assertEqual(batch.status, ProductionBatch.Status.PAUSED)

    def test_resume_on_proofing_works(self):
        batch = create_batch_at_stage("proofing", self.user)
        pause_batch(batch, self.user, "slow rise")
        resume_batch(batch, self.user, "ready")
        batch.refresh_from_db()
        self.assertEqual(batch.status, ProductionBatch.Status.IN_PROGRESS)

    def test_history_created_on_proofing_exit(self):
        batch = create_batch_at_stage("proofing", self.user)
        before = batch.stage_history.count()
        move_batch(batch, "oven", self.user, "bake")
        self.assertEqual(batch.stage_history.count(), before + 1)

    def test_stage_duration_is_timedelta(self):
        self.assertGreaterEqual(create_batch_at_stage("proofing", self.user).stage_duration.total_seconds(), 0)

    def test_planned_finish_can_be_overdue(self):
        batch = create_batch_at_stage("proofing", self.user)
        batch.planned_finish = timezone.now() - timezone.timedelta(minutes=1)
        batch.save(update_fields=["planned_finish", "updated_at"])
        self.assertLess(batch.planned_finish, timezone.now())
