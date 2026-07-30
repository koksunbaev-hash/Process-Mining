from django.test import TestCase

from apps.bakery.services import next_stage_for, previous_stage_for, stock_expiration_for

from .factories import create_user
from .helpers import create_batch_at_stage


class ModelMethodWorkflowTests(TestCase):
    def setUp(self):
        self.user = create_user()

    def test_next_stage_for_queue_is_mixing(self):
        self.assertEqual(next_stage_for(create_batch_at_stage("queue", self.user)).code, "mixing")

    def test_next_stage_for_warehouse_is_done(self):
        self.assertEqual(next_stage_for(create_batch_at_stage("warehouse", self.user)).code, "done")

    def test_next_stage_for_done_is_none(self):
        self.assertIsNone(next_stage_for(create_batch_at_stage("done", self.user)))

    def test_previous_stage_for_mixing_is_queue(self):
        self.assertEqual(previous_stage_for(create_batch_at_stage("mixing", self.user)).code, "queue")

    def test_previous_stage_for_queue_is_none(self):
        self.assertIsNone(previous_stage_for(create_batch_at_stage("queue", self.user)))

    def test_previous_stage_for_done_is_warehouse(self):
        self.assertEqual(previous_stage_for(create_batch_at_stage("done", self.user)).code, "warehouse")

    def test_stage_duration_property_returns_value(self):
        self.assertIsNotNone(create_batch_at_stage("mixing", self.user).stage_duration)

    def test_has_blocking_problem_false_without_problem(self):
        self.assertFalse(create_batch_at_stage("mixing", self.user).has_blocking_problem)

    def test_stock_expiration_uses_product_shelf_life(self):
        batch = create_batch_at_stage("oven", self.user)
        expiration = stock_expiration_for(batch)
        self.assertGreater(expiration, batch.created_at)
