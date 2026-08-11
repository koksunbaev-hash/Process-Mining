from django.core.exceptions import PermissionDenied
from django.test import Client, TestCase
from rest_framework.test import APIClient

from apps.accounts.models import UserProfile
from apps.bakery.kanban_demo import create_demo_run, demo_status, reset_demo, start_demo, tick_demo
from apps.bakery.models import (
    BatchStageHistory,
    FinishedGoodsStock,
    KanbanDemoRun,
    ProductionBatch,
    ProductionOrder,
    ProductionOrderItem,
)
from apps.bakery.tests.batch_workflow.factories import create_user
from apps.bakery.tests.batch_workflow.helpers import create_batch_at_stage
from apps.notifications.models import Notification


class KanbanDemoTests(TestCase):
    def setUp(self):
        self.user = create_user("demo-admin", UserProfile.Role.ADMIN)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def create_run(self, count=100, **kwargs):
        return create_demo_run(user=self.user, count=count, speed_seconds=0.1, mode=KanbanDemoRun.Mode.FAST, **kwargs)

    def test_create_demo_run(self):
        run = self.create_run(count=5)
        self.assertEqual(run.status, KanbanDemoRun.Status.CREATED)
        self.assertEqual(run.total_batches, 5)

    def test_create_100_batches(self):
        run = self.create_run()
        self.assertEqual(run.batches.count(), 100)

    def test_all_batches_are_demo(self):
        run = self.create_run(count=7)
        self.assertEqual(run.batches.filter(is_demo=True).count(), 7)

    def test_all_batches_linked_to_demo_run(self):
        run = self.create_run(count=7)
        self.assertFalse(ProductionBatch.objects.filter(is_demo=True, demo_run__isnull=True).exists())

    def test_demo_batch_numbers_are_unique(self):
        run = self.create_run(count=12)
        numbers = list(run.batches.values_list("batch_number", flat=True))
        self.assertEqual(len(numbers), len(set(numbers)))
        self.assertIn("DEMO-B-0001", numbers)

    def test_all_batches_start_in_queue(self):
        run = self.create_run(count=4)
        self.assertEqual(run.batches.filter(current_stage__code="queue").count(), 4)

    def test_tick_moves_only_to_next_stage(self):
        run = self.create_run(count=1)
        start_demo(run, self.user)
        result = tick_demo(run, self.user)
        self.assertEqual(result["changed_batches"][0]["stage"], "mixing")
        batch = run.batches.get()
        self.assertEqual(batch.current_stage.code, "mixing")

    def test_demo_tick_does_not_create_user_notifications(self):
        run = self.create_run(count=1)
        start_demo(run, self.user)
        before = Notification.objects.count()
        tick_demo(run, self.user)
        self.assertEqual(Notification.objects.count(), before)

    def test_tick_does_not_skip_stage(self):
        run = self.create_run(count=1)
        start_demo(run, self.user)
        tick_demo(run, self.user)
        history = BatchStageHistory.objects.filter(batch=run.batches.get(), from_stage__code="queue", to_stage__code="mixing")
        self.assertEqual(history.count(), 1)

    def test_pause_blocks_tick(self):
        run = self.create_run(count=2)
        start_demo(run, self.user)
        response = self.client.post(f"/api/kanban-demo/{run.pk}/pause/")
        self.assertEqual(response.status_code, 200)
        before = list(run.batches.values_list("current_stage__code", flat=True))
        tick_demo(run, self.user)
        after = list(run.batches.values_list("current_stage__code", flat=True))
        self.assertEqual(before, after)

    def test_resume_allows_tick(self):
        run = self.create_run(count=1)
        self.client.post(f"/api/kanban-demo/{run.pk}/start/")
        self.client.post(f"/api/kanban-demo/{run.pk}/pause/")
        self.client.post(f"/api/kanban-demo/{run.pk}/resume/")
        self.client.post(f"/api/kanban-demo/{run.pk}/tick/")
        self.assertEqual(run.batches.get().current_stage.code, "mixing")

    def test_stop_blocks_new_transitions(self):
        run = self.create_run(count=1)
        self.client.post(f"/api/kanban-demo/{run.pk}/start/")
        self.client.post(f"/api/kanban-demo/{run.pk}/stop/")
        self.client.post(f"/api/kanban-demo/{run.pk}/tick/")
        self.assertEqual(run.batches.get().current_stage.code, "queue")

    def test_reset_deletes_only_demo(self):
        run = self.create_run(count=3)
        work_batch = create_batch_at_stage("queue", self.user)
        reset_demo(run, self.user)
        self.assertTrue(ProductionBatch.objects.filter(pk=work_batch.pk).exists())
        self.assertFalse(ProductionBatch.objects.filter(batch_number__startswith="DEMO-B-").exists())

    def test_reset_deletes_demo_orders_and_items(self):
        run = self.create_run(count=3)
        reset_demo(run, self.user)
        self.assertFalse(ProductionOrder.objects.filter(is_demo=True).exists())
        self.assertFalse(ProductionOrderItem.objects.filter(is_demo=True).exists())

    def test_repeated_tick_does_not_duplicate_same_history(self):
        run = self.create_run(count=1)
        start_demo(run, self.user)
        tick_demo(run, self.user)
        tick_demo(run, self.user)
        batch = run.batches.get()
        self.assertEqual(BatchStageHistory.objects.filter(batch=batch, from_stage__code="queue", to_stage__code="mixing").count(), 1)

    def test_warehouse_transition_creates_one_stock_record(self):
        run = self.create_run(count=1)
        start_demo(run, self.user)
        for _ in range(5):
            tick_demo(run, self.user)
        batch = run.batches.get()
        self.assertEqual(batch.current_stage.code, "warehouse")
        self.assertEqual(FinishedGoodsStock.objects.filter(batch=batch, is_demo=True, demo_run=run).count(), 1)

    def test_full_completion_sets_completed(self):
        run = self.create_run(count=3)
        start_demo(run, self.user)
        for _ in range(7):
            tick_demo(run, self.user)
        run.refresh_from_db()
        self.assertEqual(run.status, KanbanDemoRun.Status.COMPLETED)
        self.assertEqual(run.batches.filter(status=ProductionBatch.Status.COMPLETED).count(), 3)

    def test_progress_reaches_100(self):
        run = self.create_run(count=2)
        start_demo(run, self.user)
        for _ in range(7):
            result = tick_demo(run, self.user)
        self.assertEqual(result["progress_percent"], 100)

    def test_user_without_permission_gets_403(self):
        auditor = create_user("demo-auditor", UserProfile.Role.USER)
        self.client.force_authenticate(auditor)
        response = self.client.post("/api/kanban-demo/create/", {"count": 1}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_service_rejects_user_without_permission(self):
        auditor = create_user("demo-auditor-service", UserProfile.Role.USER)
        with self.assertRaises(PermissionDenied):
            create_demo_run(user=auditor, count=1)

    def test_repeated_create_with_client_request_id_returns_same_run(self):
        one = create_demo_run(user=self.user, count=2, client_request_id="same-demo-request")
        two = create_demo_run(user=self.user, count=2, client_request_id="same-demo-request")
        self.assertEqual(one.pk, two.pk)
        self.assertEqual(ProductionBatch.objects.filter(is_demo=True).count(), 2)

    def test_api_status_shape(self):
        run = self.create_run(count=2)
        response = self.client.get(f"/api/kanban-demo/{run.pk}/status/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["stages"]["queue"], 2)

    def test_kanban_page_has_demo_controls_for_admin(self):
        web = Client()
        web.force_login(self.user)
        response = web.get("/bakery/board/")
        self.assertContains(response, "Демо процесса")

    def test_kanban_page_hides_demo_controls_for_auditor(self):
        auditor = create_user("demo-auditor-ui", UserProfile.Role.USER)
        web = Client()
        web.force_login(auditor)
        response = web.get("/bakery/board/")
        self.assertNotContains(response, "Демо процесса")
