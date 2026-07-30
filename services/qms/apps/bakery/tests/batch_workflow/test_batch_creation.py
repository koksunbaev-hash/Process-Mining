from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.bakery.models import ProductionBatch

from .factories import create_manual_batch, create_queued_batch, create_stage_list, create_user


class BatchCreationTests(TestCase):
    def setUp(self):
        self.user = create_user()
        create_stage_list()

    def test_batch_is_created_from_confirmed_order(self):
        self.assertIsInstance(create_queued_batch(self.user), ProductionBatch)

    def test_batch_number_is_saved(self):
        self.assertTrue(create_queued_batch(self.user).batch_number)

    def test_batch_number_is_unique(self):
        first = create_queued_batch(self.user)
        second = create_manual_batch(user=self.user)
        self.assertNotEqual(first.batch_number, second.batch_number)

    def test_batch_number_is_generated_when_blank(self):
        batch = create_manual_batch(user=self.user, batch_number="")
        self.assertTrue(batch.batch_number.startswith("B-"))

    def test_planned_quantity_is_saved(self):
        self.assertEqual(create_queued_batch(self.user, quantity=Decimal("321.500")).planned_quantity, Decimal("321.500"))

    def test_actual_quantity_starts_empty(self):
        self.assertIsNone(create_queued_batch(self.user).actual_quantity)

    def test_unit_is_saved(self):
        self.assertEqual(create_queued_batch(self.user).unit, "шт")

    def test_product_is_saved(self):
        self.assertEqual(create_queued_batch(self.user).product.name, "Хлеб тестовый")

    def test_order_item_is_saved(self):
        self.assertIsNotNone(create_queued_batch(self.user).order_item_id)

    def test_initial_stage_is_queue(self):
        self.assertEqual(create_queued_batch(self.user).current_stage.code, "queue")

    def test_initial_status_is_queued(self):
        self.assertEqual(create_queued_batch(self.user).status, ProductionBatch.Status.QUEUED)

    def test_assigned_to_is_saved(self):
        assignee = create_user("mixing-user")
        self.assertEqual(create_queued_batch(self.user, assignee=assignee).assigned_to, assignee)

    def test_planned_dates_are_saved(self):
        start = timezone.now()
        finish = start + timezone.timedelta(hours=4)
        batch = create_manual_batch(user=self.user, planned_start=start, planned_finish=finish)
        self.assertEqual(batch.planned_start, start)
        self.assertEqual(batch.planned_finish, finish)

    def test_timestamps_are_filled(self):
        batch = create_queued_batch(self.user)
        self.assertIsNotNone(batch.created_at)
        self.assertIsNotNone(batch.updated_at)

    def test_negative_planned_quantity_is_rejected_by_model_validation(self):
        batch = create_manual_batch(user=self.user, quantity=Decimal("-1.000"))
        with self.assertRaises(ValidationError):
            batch.full_clean()

    def test_zero_planned_quantity_is_rejected_by_model_validation(self):
        batch = create_manual_batch(user=self.user, quantity=Decimal("0.000"))
        with self.assertRaises(ValidationError):
            batch.full_clean()

    def test_string_representation_returns_batch_number(self):
        batch = create_queued_batch(self.user)
        self.assertEqual(str(batch), batch.batch_number)
