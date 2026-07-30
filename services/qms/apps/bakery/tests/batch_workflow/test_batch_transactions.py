from unittest.mock import patch

from django.test import TestCase

from apps.bakery.models import BatchStageHistory, FinishedGoodsStock

from .factories import create_user
from .helpers import create_batch_at_stage, move_batch


class BatchTransactionTests(TestCase):
    def setUp(self):
        self.user = create_user()

    def test_history_error_rolls_back_stage_change(self):
        batch = create_batch_at_stage("mixing", self.user)
        with patch("apps.bakery.services.BatchStageHistory.objects.create", side_effect=RuntimeError("history failed")):
            with self.assertRaises(RuntimeError):
                move_batch(batch, "forming", self.user, "form")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "mixing")

    def test_stock_error_rolls_back_history(self):
        batch = create_batch_at_stage("oven", self.user)
        before = BatchStageHistory.objects.filter(batch=batch).count()
        with patch("apps.bakery.services.FinishedGoodsStock.objects.get_or_create", side_effect=RuntimeError("stock failed")):
            with self.assertRaises(RuntimeError):
                move_batch(batch, "warehouse", self.user, "receive")
        self.assertEqual(BatchStageHistory.objects.filter(batch=batch).count(), before)

    def test_stock_error_rolls_back_stock_record(self):
        batch = create_batch_at_stage("oven", self.user)
        with patch("apps.bakery.services.FinishedGoodsStock.objects.get_or_create", side_effect=RuntimeError("stock failed")):
            with self.assertRaises(RuntimeError):
                move_batch(batch, "warehouse", self.user, "receive")
        self.assertFalse(FinishedGoodsStock.objects.filter(batch=batch).exists())

    def test_notification_error_rolls_back_transition(self):
        batch = create_batch_at_stage("mixing", self.user)
        with patch("apps.bakery.services.notify", side_effect=RuntimeError("notify failed")):
            with self.assertRaises(RuntimeError):
                move_batch(batch, "forming", self.user, "form")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "mixing")

    def test_half_transition_does_not_remain_after_error(self):
        batch = create_batch_at_stage("mixing", self.user)
        with patch("apps.bakery.services.notify", side_effect=RuntimeError("notify failed")):
            with self.assertRaises(RuntimeError):
                move_batch(batch, "forming", self.user, "form")
        self.assertFalse(BatchStageHistory.objects.filter(batch=batch, to_stage__code="forming").exists())

    def test_retry_after_error_works(self):
        batch = create_batch_at_stage("mixing", self.user)
        with patch("apps.bakery.services.notify", side_effect=RuntimeError("notify failed")):
            with self.assertRaises(RuntimeError):
                move_batch(batch, "forming", self.user, "form")
        move_batch(batch, "forming", self.user, "retry")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "forming")

    def test_move_batch_uses_atomic_behavior_for_stock(self):
        batch = create_batch_at_stage("oven", self.user)
        with patch("apps.bakery.services.FinishedGoodsStock.objects.get_or_create", side_effect=RuntimeError("stock failed")):
            with self.assertRaises(RuntimeError):
                move_batch(batch, "warehouse", self.user, "receive")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "oven")

    def test_failed_transition_preserves_status(self):
        batch = create_batch_at_stage("mixing", self.user)
        old_status = batch.status
        with patch("apps.bakery.services.notify", side_effect=RuntimeError("notify failed")):
            with self.assertRaises(RuntimeError):
                move_batch(batch, "forming", self.user, "form")
        batch.refresh_from_db()
        self.assertEqual(batch.status, old_status)
