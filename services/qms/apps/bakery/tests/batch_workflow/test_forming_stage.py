from django.test import TestCase

from apps.bakery.models import ProductionBatch
from apps.bakery.services import pause_batch, resume_batch

from .factories import create_user
from .helpers import assert_move_rejected, create_batch_at_stage, move_batch


class FormingStageTests(TestCase):
    def setUp(self):
        self.user = create_user()

    def test_mixing_to_forming_works(self):
        batch = create_batch_at_stage("mixing", self.user)
        move_batch(batch, "forming", self.user, "shape")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "forming")

    def test_current_stage_is_forming(self):
        self.assertEqual(create_batch_at_stage("forming", self.user).current_stage.code, "forming")

    def test_forming_to_proofing_works(self):
        batch = create_batch_at_stage("forming", self.user)
        move_batch(batch, "proofing", self.user, "proof")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "proofing")

    def test_forming_to_oven_directly_forbidden(self):
        assert_move_rejected(self, create_batch_at_stage("forming", self.user), "oven", self.user)

    def test_forming_to_warehouse_forbidden(self):
        assert_move_rejected(self, create_batch_at_stage("forming", self.user), "warehouse", self.user)

    def test_forming_to_done_forbidden(self):
        assert_move_rejected(self, create_batch_at_stage("forming", self.user), "done", self.user)

    def test_repeated_forming_forbidden(self):
        assert_move_rejected(self, create_batch_at_stage("forming", self.user), "forming", self.user)

    def test_pause_on_forming_works(self):
        batch = create_batch_at_stage("forming", self.user)
        pause_batch(batch, self.user, "form issue")
        batch.refresh_from_db()
        self.assertEqual(batch.status, ProductionBatch.Status.PAUSED)

    def test_resume_on_forming_works(self):
        batch = create_batch_at_stage("forming", self.user)
        pause_batch(batch, self.user, "form issue")
        resume_batch(batch, self.user, "ok")
        batch.refresh_from_db()
        self.assertEqual(batch.status, ProductionBatch.Status.IN_PROGRESS)

    def test_history_keeps_forming_comment(self):
        batch = create_batch_at_stage("forming", self.user)
        move_batch(batch, "proofing", self.user, "forms ready")
        self.assertEqual(batch.stage_history.order_by("-created_at").first().comment, "forms ready")

    def test_history_keeps_forming_user(self):
        batch = create_batch_at_stage("forming", self.user)
        move_batch(batch, "proofing", self.user, "forms ready")
        self.assertEqual(batch.stage_history.order_by("-created_at").first().changed_by, self.user)

    def test_forming_exit_has_finished_time(self):
        batch = create_batch_at_stage("forming", self.user)
        move_batch(batch, "proofing", self.user, "forms ready")
        self.assertIsNotNone(batch.stage_history.order_by("-created_at").first().finished_at)
