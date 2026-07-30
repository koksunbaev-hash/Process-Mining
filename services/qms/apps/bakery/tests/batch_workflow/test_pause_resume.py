from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.bakery.models import ProductionBatch
from apps.bakery.services import pause_batch, resume_batch

from .factories import create_user
from .helpers import assert_move_rejected, create_batch_at_stage, move_batch


class PauseResumeTests(TestCase):
    def setUp(self):
        self.user = create_user()

    def test_active_batch_can_pause(self):
        batch = create_batch_at_stage("mixing", self.user)
        pause_batch(batch, self.user, "wait")
        batch.refresh_from_db()
        self.assertEqual(batch.status, ProductionBatch.Status.PAUSED)

    def test_paused_batch_cannot_move_forward(self):
        batch = create_batch_at_stage("mixing", self.user)
        pause_batch(batch, self.user, "wait")
        assert_move_rejected(self, batch, "forming", self.user, ValidationError)

    def test_paused_batch_cannot_finish(self):
        batch = create_batch_at_stage("warehouse", self.user)
        pause_batch(batch, self.user, "wait")
        assert_move_rejected(self, batch, "done", self.user, ValidationError)

    def test_resume_returns_to_in_progress(self):
        batch = create_batch_at_stage("mixing", self.user)
        pause_batch(batch, self.user, "wait")
        resume_batch(batch, self.user, "go")
        batch.refresh_from_db()
        self.assertEqual(batch.status, ProductionBatch.Status.IN_PROGRESS)

    def test_resume_allows_next_transition(self):
        batch = create_batch_at_stage("mixing", self.user)
        pause_batch(batch, self.user, "wait")
        resume_batch(batch, self.user, "go")
        move_batch(batch, "forming", self.user, "form")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "forming")

    def test_repeated_pause_rejected(self):
        batch = create_batch_at_stage("mixing", self.user)
        pause_batch(batch, self.user, "wait")
        with self.assertRaises(ValidationError):
            pause_batch(batch, self.user, "again")

    def test_resume_active_batch_rejected(self):
        with self.assertRaises(ValidationError):
            resume_batch(create_batch_at_stage("mixing", self.user), self.user, "go")

    def test_cancelled_batch_cannot_resume(self):
        batch = create_batch_at_stage("mixing", self.user)
        batch.status = ProductionBatch.Status.CANCELLED
        batch.save(update_fields=["status", "updated_at"])
        with self.assertRaises(ValidationError):
            resume_batch(batch, self.user, "go")

    def test_completed_batch_cannot_pause(self):
        with self.assertRaises(ValidationError):
            pause_batch(create_batch_at_stage("done", self.user), self.user, "stop")

    def test_pause_creates_order_event(self):
        batch = create_batch_at_stage("mixing", self.user)
        before = batch.events.count()
        pause_batch(batch, self.user, "wait")
        self.assertEqual(batch.events.count(), before + 1)

    def test_resume_creates_order_event(self):
        batch = create_batch_at_stage("mixing", self.user)
        pause_batch(batch, self.user, "wait")
        before = batch.events.count()
        resume_batch(batch, self.user, "go")
        self.assertEqual(batch.events.count(), before + 1)
