from django.test import TestCase

from apps.bakery.models import ProductionBatch, ProductionOrder
from apps.bakery.services import confirm_order

from .factories import create_order_with_two_items, create_stage_list, create_user
from .helpers import WORKFLOW, move_batch


def walk_to_done(batch, user):
    for code in WORKFLOW[WORKFLOW.index(batch.current_stage.code) + 1 :]:
        move_batch(batch, code, user, f"to {code}")
    batch.refresh_from_db()
    return batch


class OrderStatusTests(TestCase):
    """An order carries one batch per order item, so it is only ready when all of
    them are. Finishing the first used to mark the whole order ready while the
    rest were still in the mixer."""

    def setUp(self):
        create_stage_list()
        self.user = create_user()
        self.order, _, _ = create_order_with_two_items(user=self.user)
        self.first, self.second = confirm_order(self.order, user=self.user, assignee=self.user)

    def test_order_stays_in_production_while_the_second_batch_is_unfinished(self):
        walk_to_done(self.first, self.user)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, ProductionOrder.Status.IN_PRODUCTION)

    def test_order_becomes_ready_once_every_batch_is_done(self):
        walk_to_done(self.first, self.user)
        walk_to_done(self.second, self.user)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, ProductionOrder.Status.READY)

    def test_a_cancelled_batch_does_not_hold_the_order_open(self):
        self.second.status = ProductionBatch.Status.CANCELLED
        self.second.save(update_fields=["status"])
        walk_to_done(self.first, self.user)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, ProductionOrder.Status.READY)

    def test_the_order_stays_open_while_the_second_batch_walks_the_line(self):
        # A finished batch is COMPLETED and move_batch refuses to move it, so
        # "done" is terminal per batch; the order can only be reopened by another
        # batch of the same order still moving.
        walk_to_done(self.first, self.user)
        for code in ("mixing", "forming", "proofing"):
            move_batch(self.second, code, self.user, f"to {code}")
            self.order.refresh_from_db()
            self.assertEqual(self.order.status, ProductionOrder.Status.IN_PRODUCTION)

    def test_confirm_order_creates_one_batch_per_item(self):
        self.assertEqual(ProductionBatch.objects.filter(order_item__order=self.order).count(), 2)


class SingleItemOrderStatusTests(TestCase):
    """Every seeded and demo order has one item, so this is the path the
    demonstration actually walks - it must be unchanged."""

    def setUp(self):
        create_stage_list()
        self.user = create_user()

    def test_single_batch_order_still_becomes_ready(self):
        from .factories import create_queued_batch

        batch = create_queued_batch(user=self.user)
        walk_to_done(batch, self.user)
        order = batch.order_item.order
        order.refresh_from_db()
        self.assertEqual(order.status, ProductionOrder.Status.READY)
