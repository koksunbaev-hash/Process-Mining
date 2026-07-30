from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from apps.bakery.models import FinishedGoodsStock

from .factories import create_problem, create_user
from .helpers import create_batch_at_stage, move_batch


class BatchStockTests(TestCase):
    def setUp(self):
        self.user = create_user()

    def test_only_oven_to_warehouse_creates_stock(self):
        batch = create_batch_at_stage("oven", self.user)
        move_batch(batch, "warehouse", self.user, "receive")
        self.assertTrue(FinishedGoodsStock.objects.filter(batch=batch).exists())

    def test_early_stage_does_not_create_stock(self):
        batch = create_batch_at_stage("mixing", self.user)
        move_batch(batch, "forming", self.user, "form")
        self.assertFalse(FinishedGoodsStock.objects.filter(batch=batch).exists())

    def test_stock_created_once(self):
        batch = create_batch_at_stage("oven", self.user)
        move_batch(batch, "warehouse", self.user, "receive")
        self.assertEqual(FinishedGoodsStock.objects.filter(batch=batch).count(), 1)

    def test_stock_quantity_matches_actual_quantity(self):
        batch = create_batch_at_stage("oven", self.user)
        batch.actual_quantity = Decimal("88.000")
        batch.save(update_fields=["actual_quantity", "updated_at"])
        move_batch(batch, "warehouse", self.user, "receive")
        self.assertEqual(batch.stock_record.quantity, Decimal("88.000"))

    def test_stock_product_matches_batch_product(self):
        batch = create_batch_at_stage("oven", self.user)
        move_batch(batch, "warehouse", self.user, "receive")
        self.assertEqual(batch.stock_record.product, batch.product)

    def test_stock_batch_matches_batch(self):
        batch = create_batch_at_stage("oven", self.user)
        move_batch(batch, "warehouse", self.user, "receive")
        self.assertEqual(batch.stock_record.batch, batch)

    def test_stock_received_by_matches_user(self):
        batch = create_batch_at_stage("oven", self.user)
        move_batch(batch, "warehouse", self.user, "receive")
        self.assertEqual(batch.stock_record.received_by, self.user)

    def test_blocking_problem_prevents_stock_creation(self):
        batch = create_batch_at_stage("oven", self.user)
        create_problem(batch)
        with self.assertRaises(Exception):
            move_batch(batch, "warehouse", self.user, "receive")
        self.assertFalse(FinishedGoodsStock.objects.filter(batch=batch).exists())

    def test_stock_error_rolls_back_transition(self):
        batch = create_batch_at_stage("oven", self.user)
        with patch("apps.bakery.services.FinishedGoodsStock.objects.get_or_create", side_effect=RuntimeError("stock failed")):
            with self.assertRaises(RuntimeError):
                move_batch(batch, "warehouse", self.user, "receive")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "oven")
