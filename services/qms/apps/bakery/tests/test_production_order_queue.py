from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.bakery.models import (
    Product,
    ProductionBatch,
    ProductionOrder,
    ProductionPlan,
    ProductionStage,
)


class ProductionOrderQueueTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("dispatcher-sheet", password="x")
        self.user.profile.role = UserProfile.Role.MANAGER
        self.user.profile.save(update_fields=["role"])
        self.client.force_login(self.user)
        self.queue = ProductionStage.objects.create(code="queue", name="Очередь", sequence=1)
        self.product = Product.objects.create(code="SHEET-BREAD", name="Хлеб из листа", unit="шт")
        self.second_product = Product.objects.create(code="SHEET-BUN", name="Булочка из листа", unit="шт")

    def test_sheet_has_queue_selection_and_ready_column(self):
        response = self.client.get(reverse("bakery:production_sheet"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'name="queue_quantity_{self.product.pk}"')
        self.assertContains(response, f'value="{self.product.pk}">Добавить</button>')
        self.assertContains(response, "Готово")
        self.assertContains(response, "Уже в канбан")
        self.assertContains(response, "Новая партия")

    def test_selected_quantity_creates_exact_queued_batch(self):
        today = timezone.localdate()
        response = self.client.post(
            reverse("bakery:production_sheet"),
            {
                "date": today.isoformat(),
                f"plan_{self.product.pk}": "125",
                f"queue_quantity_{self.product.pk}": "40",
                "queue_product": str(self.product.pk),
            },
        )

        self.assertRedirects(response, f"{reverse('bakery:production_sheet')}?date={today.isoformat()}")
        plan = ProductionPlan.objects.get(date=today, product=self.product)
        self.assertEqual(plan.quantity, Decimal("125"))
        order = ProductionOrder.objects.get()
        self.assertEqual(order.status, ProductionOrder.Status.QUEUED)
        batch = ProductionBatch.objects.get(order_item__order=order)
        self.assertEqual(batch.planned_quantity, Decimal("40"))
        self.assertEqual(batch.current_stage, self.queue)

    def test_checked_products_create_one_grouped_kanban_block(self):
        today = timezone.localdate()
        response = self.client.post(
            reverse("bakery:production_sheet"),
            {
                "date": today.isoformat(),
                f"plan_{self.product.pk}": "125",
                f"plan_{self.second_product.pk}": "80",
                f"queue_quantity_{self.product.pk}": "40",
                f"queue_quantity_{self.second_product.pk}": "25",
                "selected_products": [str(self.product.pk), str(self.second_product.pk)],
                "queue_selected": "1",
            },
        )

        self.assertRedirects(response, f"{reverse('bakery:production_sheet')}?date={today.isoformat()}")
        order = ProductionOrder.objects.get()
        self.assertTrue(order.kanban_grouped)
        self.assertEqual(order.items.count(), 2)
        self.assertEqual(ProductionBatch.objects.filter(order_item__order=order).count(), 2)

        board = self.client.get(reverse("bakery:kanban"))
        self.assertEqual(board.context["columns"][0]["count"], 1)
        self.assertContains(board, f"Заказ №{order.order_number}")
        self.assertContains(board, self.product.name)
        self.assertContains(board, self.second_product.name)

    def test_grouped_kanban_block_moves_all_batches_together(self):
        mixing = ProductionStage.objects.create(code="mixing", name="Замес", sequence=2)
        today = timezone.localdate()
        self.client.post(
            reverse("bakery:production_sheet"),
            {
                "date": today.isoformat(),
                f"plan_{self.product.pk}": "40",
                f"plan_{self.second_product.pk}": "25",
                "selected_products": [str(self.product.pk), str(self.second_product.pk)],
                "queue_selected": "1",
            },
        )
        order = ProductionOrder.objects.get()

        response = self.client.post(
            reverse("bakery:move_order_group", args=[order.pk]),
            {"from_stage": self.queue.pk, "stage": mixing.pk},
        )

        self.assertRedirects(response, reverse("bakery:kanban"))
        self.assertFalse(
            ProductionBatch.objects.filter(order_item__order=order).exclude(current_stage=mixing).exists()
        )

    def test_orders_page_has_history_and_add_fallback(self):
        response = self.client.get(reverse("bakery:orders"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "История заказов")
        self.assertNotContains(response, ">Новый заказ<")
        self.assertContains(response, "Добавить заказ")
        self.assertContains(response, reverse("bakery:production_sheet"))
