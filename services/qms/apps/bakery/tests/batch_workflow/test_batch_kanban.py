from django.test import TestCase
from django.urls import reverse

from apps.bakery.models import ProductionBatch
from apps.bakery.services import pause_batch

from .factories import create_problem, create_user
from .helpers import WORKFLOW, create_batch_at_stage


class BatchKanbanTests(TestCase):
    def setUp(self):
        self.user = create_user()


def make_kanban_stage_test(code):
    def test(self):
        batch = create_batch_at_stage(code, self.user)
        self.client.force_login(self.user)
        response = self.client.get(reverse("bakery:kanban"))
        self.assertContains(response, batch.batch_number)
        self.assertEqual(ProductionBatch.objects.filter(pk=batch.pk, current_stage__code=code).count(), 1)
    return test


for code in WORKFLOW:
    setattr(BatchKanbanTests, f"test_batch_visible_in_{code}_column", make_kanban_stage_test(code))


class BatchKanbanFilterTests(TestCase):
    def setUp(self):
        self.user = create_user()
        self.batch = create_batch_at_stage("mixing", self.user)
        self.client.force_login(self.user)

    def test_search_by_batch_number(self):
        response = self.client.get(reverse("bakery:kanban"), {"q": self.batch.batch_number})
        self.assertContains(response, self.batch.batch_number)

    def test_filter_by_product(self):
        response = self.client.get(reverse("bakery:kanban"), {"product": self.batch.product_id})
        self.assertContains(response, self.batch.batch_number)

    def test_filter_by_assigned_status(self):
        response = self.client.get(reverse("bakery:kanban"), {"status": self.batch.status})
        self.assertContains(response, self.batch.batch_number)

    def test_filter_by_priority(self):
        response = self.client.get(reverse("bakery:kanban"), {"priority": self.batch.order_item.order.priority})
        self.assertContains(response, self.batch.batch_number)

    def test_column_search(self):
        response = self.client.get(reverse("bakery:kanban"), {"stage_q_mixing": self.batch.batch_number})
        self.assertContains(response, self.batch.batch_number)

    def test_paused_batch_visible_with_status(self):
        pause_batch(self.batch, self.user, "pause")
        response = self.client.get(reverse("bakery:kanban"))
        self.assertContains(response, "paused")

    def test_problem_batch_visible_with_status(self):
        create_problem(self.batch)
        self.batch.status = "problem"
        self.batch.save(update_fields=["status", "updated_at"])
        response = self.client.get(reverse("bakery:kanban"))
        self.assertContains(response, "problem")

    def test_batch_list_page_contains_batch(self):
        response = self.client.get(reverse("bakery:batches"))
        self.assertContains(response, self.batch.batch_number)


class KanbanCardActionsTests(TestCase):
    """The "Дальше →" button posts without naming a stage, so on a card in the
    last column it asked the view to move a batch that has nowhere left to go."""

    def setUp(self):
        self.user = create_user()
        self.client.force_login(self.user)

    def board(self):
        return self.client.get(reverse("bakery:kanban")).content.decode()

    def test_card_in_a_middle_column_offers_the_next_stage(self):
        create_batch_at_stage("mixing", self.user)
        self.assertEqual(self.board().count("Дальше"), 1)

    def test_card_in_the_last_column_does_not(self):
        batch = create_batch_at_stage("done", self.user)
        html = self.board()
        self.assertIn(batch.batch_number, html)
        self.assertNotIn("Дальше", html)

    def test_only_the_last_column_loses_the_button(self):
        for code in ("queue", "mixing", "oven"):
            create_batch_at_stage(code, create_user(username=f"op-{code}"))
        create_batch_at_stage("done", create_user(username="op-done"))
        self.assertEqual(self.board().count("Дальше"), 3)
