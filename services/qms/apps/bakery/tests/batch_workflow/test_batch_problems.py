from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.bakery.models import ProductionBatch

from .factories import create_problem, create_user
from .helpers import assert_move_rejected, create_batch_at_stage, move_batch


class BatchProblemTests(TestCase):
    def setUp(self):
        self.user = create_user()


def make_problem_stage_test(stage_code):
    def test(self):
        batch = create_batch_at_stage(stage_code, self.user)
        problem = create_problem(batch, code=f"P-{stage_code}")
        self.assertEqual(problem.bakery_stage.code, stage_code)
        self.assertTrue(batch.has_blocking_problem)
    return test


for code in ["mixing", "forming", "proofing", "oven", "warehouse"]:
    setattr(BatchProblemTests, f"test_create_problem_on_{code}", make_problem_stage_test(code))


class BatchProblemBehaviorTests(TestCase):
    def setUp(self):
        self.user = create_user()

    def test_critical_problem_marks_manual_status_problem(self):
        batch = create_batch_at_stage("mixing", self.user)
        create_problem(batch)
        batch.status = ProductionBatch.Status.PROBLEM
        batch.save(update_fields=["status", "updated_at"])
        batch.refresh_from_db()
        self.assertEqual(batch.status, ProductionBatch.Status.PROBLEM)

    def test_critical_problem_blocks_forward(self):
        batch = create_batch_at_stage("mixing", self.user)
        create_problem(batch)
        assert_move_rejected(self, batch, "forming", self.user, ValidationError)

    def test_noncritical_problem_does_not_block(self):
        batch = create_batch_at_stage("mixing", self.user)
        create_problem(batch, criticality="medium", code="MEDIUM-PROBLEM")
        move_batch(batch, "forming", self.user, "ok")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "forming")

    def test_closed_critical_problem_removes_block(self):
        batch = create_batch_at_stage("mixing", self.user)
        problem = create_problem(batch, code="CLOSED-PROBLEM")
        problem.status = "closed"
        problem.save(update_fields=["status", "updated_at"])
        move_batch(batch, "forming", self.user, "fixed")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "forming")

    def test_rejected_critical_problem_removes_block(self):
        batch = create_batch_at_stage("mixing", self.user)
        problem = create_problem(batch, code="REJECTED-PROBLEM")
        problem.status = "rejected"
        problem.save(update_fields=["status", "updated_at"])
        move_batch(batch, "forming", self.user, "fixed")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "forming")

    def test_one_open_critical_problem_keeps_block(self):
        batch = create_batch_at_stage("mixing", self.user)
        closed = create_problem(batch, code="CLOSED-ONE")
        closed.status = "closed"
        closed.save(update_fields=["status", "updated_at"])
        create_problem(batch, code="OPEN-ONE")
        assert_move_rejected(self, batch, "forming", self.user, ValidationError)

    def test_problem_responsible_department_saved(self):
        self.assertIsNotNone(create_problem(create_batch_at_stage("mixing", self.user)).responsible_department)

    def test_problem_links_to_order_batch_product(self):
        batch = create_batch_at_stage("mixing", self.user)
        problem = create_problem(batch, code="LINKED-P")
        self.assertEqual(problem.bakery_batch, batch)
        self.assertEqual(problem.bakery_product, batch.product)
        self.assertEqual(problem.bakery_order, batch.order_item.order)

    def test_failed_move_with_problem_creates_no_history(self):
        batch = create_batch_at_stage("mixing", self.user)
        create_problem(batch, code="NO-HIST")
        before = batch.stage_history.count()
        assert_move_rejected(self, batch, "forming", self.user, ValidationError)
        self.assertEqual(batch.stage_history.count(), before)
