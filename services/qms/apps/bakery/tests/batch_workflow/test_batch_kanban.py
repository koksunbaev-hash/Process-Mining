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
