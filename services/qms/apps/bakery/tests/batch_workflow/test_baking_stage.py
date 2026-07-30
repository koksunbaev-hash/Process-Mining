from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.bakery.models import BatchStageHistory, ProductionBatch
from apps.bakery.services import pause_batch, resume_batch

from .factories import create_problem, create_user
from .helpers import assert_move_rejected, create_batch_at_stage, move_batch


class BakingStageTests(TestCase):
    def setUp(self):
        self.user = create_user()

    def test_proofing_to_oven_works(self):
        batch = create_batch_at_stage("proofing", self.user)
        move_batch(batch, "oven", self.user, "bake")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "oven")

    def test_current_stage_is_oven(self):
        self.assertEqual(create_batch_at_stage("oven", self.user).current_stage.code, "oven")

    def test_oven_to_warehouse_works(self):
        batch = create_batch_at_stage("oven", self.user)
        move_batch(batch, "warehouse", self.user, "stock")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "warehouse")

    def test_oven_to_done_directly_forbidden(self):
        assert_move_rejected(self, create_batch_at_stage("oven", self.user), "done", self.user)

    def test_repeated_oven_forbidden(self):
        assert_move_rejected(self, create_batch_at_stage("oven", self.user), "oven", self.user)

    def test_pause_in_oven_works(self):
        batch = create_batch_at_stage("oven", self.user)
        pause_batch(batch, self.user, "temperature")
        batch.refresh_from_db()
        self.assertEqual(batch.status, ProductionBatch.Status.PAUSED)

    def test_resume_in_oven_works(self):
        batch = create_batch_at_stage("oven", self.user)
        pause_batch(batch, self.user, "temperature")
        resume_batch(batch, self.user, "stable")
        batch.refresh_from_db()
        self.assertEqual(batch.status, ProductionBatch.Status.IN_PROGRESS)

    def test_oven_exit_has_started_and_finished_times(self):
        batch = create_batch_at_stage("oven", self.user)
        move_batch(batch, "warehouse", self.user, "stock")
        row = batch.stage_history.order_by("-created_at").first()
        self.assertIsNotNone(row.started_at)
        self.assertIsNotNone(row.finished_at)

    def test_oven_duration_is_non_negative(self):
        batch = create_batch_at_stage("oven", self.user)
        move_batch(batch, "warehouse", self.user, "stock")
        self.assertGreaterEqual(batch.stage_history.order_by("-created_at").first().duration_minutes, 0)

    def test_burn_problem_blocks_forward_move(self):
        batch = create_batch_at_stage("oven", self.user)
        create_problem(batch, criticality="critical", code="BURNING")
        batch.status = ProductionBatch.Status.PROBLEM
        batch.save(update_fields=["status", "updated_at"])
        assert_move_rejected(self, batch, "warehouse", self.user, ValidationError)

    def test_underbaked_problem_blocks_forward_move(self):
        batch = create_batch_at_stage("oven", self.user)
        create_problem(batch, criticality="critical", code="UNDERBAKED")
        batch.status = ProductionBatch.Status.PROBLEM
        batch.save(update_fields=["status", "updated_at"])
        assert_move_rejected(self, batch, "warehouse", self.user, ValidationError)

    def test_closed_problem_allows_forward_move(self):
        batch = create_batch_at_stage("oven", self.user)
        problem = create_problem(batch, criticality="critical", code="OVEN-CLOSED")
        problem.status = "closed"
        problem.save(update_fields=["status", "updated_at"])
        move_batch(batch, "warehouse", self.user, "fixed")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "warehouse")

    def test_history_contains_oven_to_warehouse(self):
        batch = create_batch_at_stage("oven", self.user)
        move_batch(batch, "warehouse", self.user, "stock")
        self.assertTrue(BatchStageHistory.objects.filter(batch=batch, from_stage__code="oven", to_stage__code="warehouse").exists())
