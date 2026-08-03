from django.test import TestCase
from django.urls import reverse

from apps.bakery.tests.batch_workflow.factories import (
    create_manual_batch,
    create_problem,
    create_user,
)


class DashboardDemoFilterTests(TestCase):
    """The board defaults to work batches and this page has no switch, so a demo
    run must not be able to replace the shop-floor numbers shown here."""

    def setUp(self):
        self.user = create_user()
        self.client.force_login(self.user)

    def test_stage_counter_ignores_demo_batches(self):
        create_manual_batch("mixing", self.user)
        create_manual_batch("mixing", self.user, is_demo=True)
        response = self.client.get(reverse("dashboard:index"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["mixing"], 1)

    def test_stage_breakdown_ignores_demo_batches(self):
        create_manual_batch("oven", self.user)
        create_manual_batch("oven", self.user, is_demo=True)
        create_manual_batch("oven", self.user, is_demo=True)
        response = self.client.get(reverse("dashboard:index"))
        totals = {row["current_stage__name"]: row["total"] for row in response.context["stage_counts"]}
        self.assertEqual(totals.get("Печь"), 1)

    def test_problem_counter_ignores_demo_batches(self):
        create_manual_batch("oven", self.user, status="problem", is_demo=True)
        response = self.client.get(reverse("dashboard:index"))
        self.assertEqual(response.context["problem_batches"], 0)

    def test_latest_nonconformities_ignore_demo_batches(self):
        # Nonconformities carry no is_demo of their own - the batch they were
        # raised against is what marks them synthetic.
        demo_batch = create_manual_batch("oven", self.user, is_demo=True)
        create_problem(demo_batch)
        response = self.client.get(reverse("dashboard:index"))
        self.assertEqual(list(response.context["latest_nc"]), [])
