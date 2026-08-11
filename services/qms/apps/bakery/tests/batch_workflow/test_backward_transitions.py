from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from apps.accounts.models import UserProfile

from .factories import create_problem, create_user
from .helpers import assert_move_rejected, create_batch_at_stage, move_batch


class BackwardTransitionTests(TestCase):
    def setUp(self):
        self.user = create_user()

    def test_forming_to_mixing_with_comment(self):
        batch = create_batch_at_stage("forming", self.user)
        move_batch(batch, "mixing", self.user, "return")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "mixing")

    def test_proofing_to_forming_with_comment(self):
        batch = create_batch_at_stage("proofing", self.user)
        move_batch(batch, "forming", self.user, "return")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "forming")

    def test_oven_to_proofing_with_comment(self):
        batch = create_batch_at_stage("oven", self.user)
        move_batch(batch, "proofing", self.user, "return")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "proofing")

    def test_warehouse_to_oven_with_comment(self):
        batch = create_batch_at_stage("warehouse", self.user)
        move_batch(batch, "oven", self.user, "return")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "oven")

    def test_backward_without_comment_forbidden(self):
        assert_move_rejected(self, create_batch_at_stage("forming", self.user), "mixing", self.user, ValidationError)

    def test_backward_two_stages_forbidden(self):
        assert_move_rejected(self, create_batch_at_stage("proofing", self.user), "mixing", self.user, ValidationError, "return")

    def test_done_cannot_be_returned_by_dispatcher(self):
        assert_move_rejected(self, create_batch_at_stage("done", self.user), "warehouse", self.user, ValidationError, "return")

    def test_blocking_problem_forbids_backward_when_status_problem(self):
        batch = create_batch_at_stage("forming", self.user)
        create_problem(batch)
        batch.status = "problem"
        batch.save(update_fields=["status", "updated_at"])
        assert_move_rejected(self, batch, "mixing", self.user, ValidationError, "return")

    def test_employee_returns_a_batch_only_with_a_reason(self):
        """Возврат остался за объяснением, а не за ролью.

        Раньше здесь проверялось, что аудитор не вернёт партию назад. Роли
        аудитора нет, вернуть может любой - но по-прежнему только с
        комментарием: без него в истории останется движение без причины.
        """
        worker = create_user("worker-back", UserProfile.Role.USER)
        assert_move_rejected(self, create_batch_at_stage("forming", self.user), "mixing", worker, ValidationError)

        batch = create_batch_at_stage("forming", self.user)
        move_batch(batch, "mixing", worker, "тесто не подошло")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "mixing")

    def test_after_return_can_move_forward_again(self):
        batch = create_batch_at_stage("forming", self.user)
        move_batch(batch, "mixing", self.user, "return")
        move_batch(batch, "forming", self.user, "again")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "forming")
