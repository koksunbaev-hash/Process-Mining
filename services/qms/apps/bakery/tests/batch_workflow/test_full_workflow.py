from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import UserProfile
from apps.bakery.models import BatchStageHistory, FinishedGoodsStock, ProductionBatch
from apps.bakery.services import pause_batch, resume_batch

from .factories import create_problem, create_user
from .helpers import WORKFLOW, complete_full_workflow, create_batch_at_stage, move_batch


class FullWorkflowTests(TestCase):
    def setUp(self):
        self.user = create_user()

    def assert_completed(self, batch, min_history=7):
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "done")
        self.assertEqual(batch.status, ProductionBatch.Status.COMPLETED)
        self.assertIsNotNone(batch.actual_start)
        self.assertIsNotNone(batch.actual_finish)
        self.assertTrue(FinishedGoodsStock.objects.filter(batch=batch).exists())
        self.assertGreaterEqual(BatchStageHistory.objects.filter(batch=batch).count(), min_history)

    def test_full_successful_path(self):
        batch = create_batch_at_stage("queue", self.user)
        complete_full_workflow(batch, self.user)
        self.assert_completed(batch)

    def test_full_path_with_pause_on_mixing(self):
        batch = create_batch_at_stage("mixing", self.user)
        pause_batch(batch, self.user, "pause")
        resume_batch(batch, self.user, "resume")
        complete_full_workflow(batch, self.user)
        self.assert_completed(batch)

    def test_full_path_with_pause_on_proofing(self):
        batch = create_batch_at_stage("proofing", self.user)
        pause_batch(batch, self.user, "pause")
        resume_batch(batch, self.user, "resume")
        complete_full_workflow(batch, self.user)
        self.assert_completed(batch)

    def test_full_path_with_oven_problem_then_fix(self):
        batch = create_batch_at_stage("oven", self.user)
        problem = create_problem(batch, code="E2E-OVEN")
        problem.status = "closed"
        problem.save(update_fields=["status", "updated_at"])
        complete_full_workflow(batch, self.user)
        self.assert_completed(batch)

    def test_full_path_with_return_from_forming_to_mixing(self):
        batch = create_batch_at_stage("forming", self.user)
        move_batch(batch, "mixing", self.user, "return")
        complete_full_workflow(batch, self.user)
        self.assert_completed(batch)

    def test_full_path_with_return_from_oven_to_proofing(self):
        batch = create_batch_at_stage("oven", self.user)
        move_batch(batch, "proofing", self.user, "return")
        complete_full_workflow(batch, self.user)
        self.assert_completed(batch)

    def test_full_path_with_reduced_actual_quantity(self):
        batch = create_batch_at_stage("oven", self.user)
        batch.actual_quantity = Decimal("77.000")
        batch.save(update_fields=["actual_quantity", "updated_at"])
        complete_full_workflow(batch, self.user)
        self.assertEqual(batch.stock_record.quantity, Decimal("77.000"))

    def test_full_path_with_different_operators(self):
        dispatcher = self.user
        users = {
            "mixing": create_user("e2e-mix", UserProfile.Role.USER),
            "forming": create_user("e2e-form", UserProfile.Role.USER),
            "proofing": create_user("e2e-proof", UserProfile.Role.USER),
            "oven": create_user("e2e-oven", UserProfile.Role.USER),
            "warehouse": create_user("e2e-stock", UserProfile.Role.USER),
            "done": create_user("e2e-done", UserProfile.Role.USER),
        }
        batch = create_batch_at_stage("queue", dispatcher)
        for code in WORKFLOW[1:]:
            move_batch(batch, code, users[code], code)
            batch.refresh_from_db()
        self.assert_completed(batch)

    def test_full_path_through_api_next_stage(self):
        batch = create_batch_at_stage("queue", self.user)
        client = APIClient()
        client.force_authenticate(self.user)
        for code in WORKFLOW[1:]:
            response = client.post(f"/api/batches/{batch.pk}/next_stage/", {"comment": code})
            self.assertEqual(response.status_code, 200)
            batch.refresh_from_db()
        self.assert_completed(batch)

    def test_full_path_through_kanban_move_endpoint(self):
        batch = create_batch_at_stage("queue", self.user)
        self.client.force_login(self.user)
        from .helpers import stage
        for code in WORKFLOW[1:]:
            response = self.client.post(f"/bakery/batches/{batch.pk}/move/", {"stage": stage(code).pk, "comment": code})
            self.assertEqual(response.status_code, 302)
            batch.refresh_from_db()
        self.assert_completed(batch)

    def test_history_order_after_full_path(self):
        batch = create_batch_at_stage("queue", self.user)
        complete_full_workflow(batch, self.user)
        codes = list(batch.stage_history.order_by("created_at").values_list("to_stage__code", flat=True))
        self.assertEqual(codes[1:], WORKFLOW[1:])

    def test_no_duplicate_stock_after_full_path(self):
        batch = create_batch_at_stage("queue", self.user)
        complete_full_workflow(batch, self.user)
        self.assertEqual(FinishedGoodsStock.objects.filter(batch=batch).count(), 1)
