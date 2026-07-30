from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.bakery.models import FinishedGoodsStock

from .factories import create_user
from .helpers import assert_move_rejected, create_batch_at_stage, move_batch


class BatchConcurrencyTests(TestCase):
    def setUp(self):
        self.user = create_user()

    def test_second_same_transition_is_rejected_after_refresh(self):
        batch = create_batch_at_stage("mixing", self.user)
        move_batch(batch, "forming", self.user, "first")
        batch.refresh_from_db()
        assert_move_rejected(self, batch, "forming", self.user, ValidationError)

    def test_two_requests_do_not_create_duplicate_history_for_same_stage(self):
        batch = create_batch_at_stage("mixing", self.user)
        move_batch(batch, "forming", self.user, "first")
        before = batch.stage_history.count()
        assert_move_rejected(self, batch, "forming", self.user, ValidationError)
        self.assertEqual(batch.stage_history.count(), before)

    def test_two_warehouse_requests_do_not_create_two_stock_records(self):
        batch = create_batch_at_stage("oven", self.user)
        move_batch(batch, "warehouse", self.user, "first")
        assert_move_rejected(self, batch, "warehouse", self.user, ValidationError)
        self.assertEqual(FinishedGoodsStock.objects.filter(batch=batch).count(), 1)

    def test_second_request_sees_actual_state(self):
        batch = create_batch_at_stage("mixing", self.user)
        move_batch(batch, "forming", self.user, "first")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "forming")

    def test_repeated_done_request_keeps_completed(self):
        batch = create_batch_at_stage("done", self.user)
        assert_move_rejected(self, batch, "done", self.user, ValidationError)
        batch.refresh_from_db()
        self.assertEqual(batch.status, "completed")

    def test_stale_instance_is_locked_and_refreshed_inside_service(self):
        batch = create_batch_at_stage("mixing", self.user)
        stale = type(batch).objects.get(pk=batch.pk)
        move_batch(batch, "forming", self.user, "first")
        assert_move_rejected(self, stale, "forming", self.user, ValidationError)

    def test_duplicate_stock_prevented_by_one_to_one(self):
        batch = create_batch_at_stage("oven", self.user)
        move_batch(batch, "warehouse", self.user, "first")
        self.assertTrue(hasattr(batch, "stock_record"))

    def test_consecutive_valid_requests_advance_one_stage_each(self):
        batch = create_batch_at_stage("mixing", self.user)
        move_batch(batch, "forming", self.user, "one")
        move_batch(batch, "proofing", self.user, "two")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "proofing")
