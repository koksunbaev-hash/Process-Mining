from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import UserProfile
from apps.bakery.models import FinishedGoodsStock, ProductionBatch

from .factories import create_user
from .helpers import assert_move_rejected, create_batch_at_stage, move_batch


class WarehouseStageTests(TestCase):
    def setUp(self):
        self.user = create_user()

    def test_oven_to_warehouse_works(self):
        batch = create_batch_at_stage("oven", self.user)
        move_batch(batch, "warehouse", self.user, "receive")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "warehouse")

    def test_stock_record_created_on_warehouse(self):
        batch = create_batch_at_stage("oven", self.user)
        move_batch(batch, "warehouse", self.user, "receive")
        self.assertTrue(FinishedGoodsStock.objects.filter(batch=batch).exists())

    def test_stock_record_is_linked_to_batch(self):
        batch = create_batch_at_stage("oven", self.user)
        move_batch(batch, "warehouse", self.user, "receive")
        self.assertEqual(batch.stock_record.batch, batch)

    def test_stock_record_is_linked_to_product(self):
        batch = create_batch_at_stage("oven", self.user)
        move_batch(batch, "warehouse", self.user, "receive")
        self.assertEqual(batch.stock_record.product, batch.product)

    def test_stock_uses_actual_quantity_when_present(self):
        batch = create_batch_at_stage("oven", self.user)
        batch.actual_quantity = Decimal("91.000")
        batch.save(update_fields=["actual_quantity", "updated_at"])
        move_batch(batch, "warehouse", self.user, "receive")
        self.assertEqual(batch.stock_record.quantity, Decimal("91.000"))

    def test_stock_uses_planned_quantity_when_actual_empty(self):
        batch = create_batch_at_stage("oven", self.user)
        move_batch(batch, "warehouse", self.user, "receive")
        self.assertEqual(batch.stock_record.quantity, batch.planned_quantity)

    def test_repeated_warehouse_move_is_rejected_without_duplicate_stock(self):
        batch = create_batch_at_stage("warehouse", self.user)
        before = FinishedGoodsStock.objects.filter(batch=batch).count()
        assert_move_rejected(self, batch, "warehouse", self.user)
        self.assertEqual(FinishedGoodsStock.objects.filter(batch=batch).count(), before)

    def test_warehouse_batch_is_not_completed_yet(self):
        batch = create_batch_at_stage("warehouse", self.user)
        self.assertNotEqual(batch.status, ProductionBatch.Status.COMPLETED)

    def test_warehouse_to_done_works(self):
        batch = create_batch_at_stage("warehouse", self.user)
        move_batch(batch, "done", self.user, "ready")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "done")

    def test_warehouse_to_oven_requires_comment(self):
        batch = create_batch_at_stage("warehouse", self.user)
        assert_move_rejected(self, batch, "oven", self.user)

    def test_warehouse_to_oven_with_comment_works(self):
        batch = create_batch_at_stage("warehouse", self.user)
        move_batch(batch, "oven", self.user, "return for baking")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "oven")

    def test_warehouse_worker_can_finish(self):
        worker = create_user("warehouse-worker", UserProfile.Role.USER)
        batch = create_batch_at_stage("warehouse", self.user)
        move_batch(batch, "done", worker, "ready")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "done")

    def test_employee_closes_a_batch_from_the_warehouse(self):
        # Раньше склад закрывал только кладовщик. Отдельной роли кладовщика
        # больше нет - закрывает тот, кто принял продукцию.
        worker = create_user("stock-worker", UserProfile.Role.USER)
        batch = create_batch_at_stage("warehouse", self.user)
        move_batch(batch, "done", worker, "принято")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "done")

    def test_stock_status_is_available(self):
        batch = create_batch_at_stage("oven", self.user)
        move_batch(batch, "warehouse", self.user, "receive")
        self.assertEqual(batch.stock_record.status, FinishedGoodsStock.Status.AVAILABLE)

    def test_stock_received_by_is_user(self):
        batch = create_batch_at_stage("oven", self.user)
        move_batch(batch, "warehouse", self.user, "receive")
        self.assertEqual(batch.stock_record.received_by, self.user)

    def test_stock_received_at_is_set(self):
        batch = create_batch_at_stage("oven", self.user)
        move_batch(batch, "warehouse", self.user, "receive")
        self.assertIsNotNone(batch.stock_record.received_at)
