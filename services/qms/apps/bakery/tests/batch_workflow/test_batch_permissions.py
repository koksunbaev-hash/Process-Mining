from django.core.exceptions import PermissionDenied
from django.test import TestCase

from apps.accounts.models import UserProfile

from .factories import create_user
from .helpers import assert_move_rejected, create_batch_at_stage, move_batch


class BatchPermissionTests(TestCase):
    def test_admin_can_move_any_batch(self):
        user = create_user("admin-flow", UserProfile.Role.ADMIN, is_superuser=True, is_staff=True)
        batch = create_batch_at_stage("oven", user)
        move_batch(batch, "warehouse", user, "ok")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "warehouse")

    def test_dispatcher_can_move_batch(self):
        user = create_user("dispatcher-flow", UserProfile.Role.PRODUCTION_DISPATCHER)
        batch = create_batch_at_stage("queue", user)
        move_batch(batch, "mixing", user, "ok")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "mixing")

    def test_mixing_operator_can_start_mixing(self):
        dispatcher = create_user("disp-perm", UserProfile.Role.PRODUCTION_DISPATCHER)
        user = create_user("mix-perm", UserProfile.Role.MIXING_OPERATOR)
        batch = create_batch_at_stage("queue", dispatcher)
        move_batch(batch, "mixing", user, "take")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "mixing")

    def test_mixing_operator_cannot_complete_forming(self):
        user = create_user("mix-no-form", UserProfile.Role.MIXING_OPERATOR)
        assert_move_rejected(self, create_batch_at_stage("forming", create_user()), "proofing", user, PermissionDenied)

    def test_forming_operator_can_move_to_forming(self):
        dispatcher = create_user("disp-form", UserProfile.Role.PRODUCTION_DISPATCHER)
        user = create_user("form-perm", UserProfile.Role.FORMING_OPERATOR)
        batch = create_batch_at_stage("mixing", dispatcher)
        move_batch(batch, "forming", user, "take")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "forming")

    def test_proofing_operator_can_move_to_proofing(self):
        dispatcher = create_user("disp-proof", UserProfile.Role.PRODUCTION_DISPATCHER)
        user = create_user("proof-perm", UserProfile.Role.PROOFING_OPERATOR)
        batch = create_batch_at_stage("forming", dispatcher)
        move_batch(batch, "proofing", user, "take")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "proofing")

    def test_oven_operator_can_move_to_oven(self):
        dispatcher = create_user("disp-oven", UserProfile.Role.PRODUCTION_DISPATCHER)
        user = create_user("oven-perm", UserProfile.Role.OVEN_OPERATOR)
        batch = create_batch_at_stage("proofing", dispatcher)
        move_batch(batch, "oven", user, "take")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "oven")

    def test_warehouse_worker_can_receive(self):
        dispatcher = create_user("disp-stock", UserProfile.Role.PRODUCTION_DISPATCHER)
        user = create_user("stock-perm", UserProfile.Role.WAREHOUSE_WORKER)
        batch = create_batch_at_stage("oven", dispatcher)
        move_batch(batch, "warehouse", user, "take")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "warehouse")

    def test_auditor_cannot_move(self):
        user = create_user("auditor-perm", UserProfile.Role.AUDITOR)
        assert_move_rejected(self, create_batch_at_stage("queue", create_user()), "mixing", user, PermissionDenied)

    def test_backend_blocks_hidden_button_bypass(self):
        user = create_user("auditor-bypass", UserProfile.Role.AUDITOR)
        assert_move_rejected(self, create_batch_at_stage("mixing", create_user()), "forming", user, PermissionDenied)
