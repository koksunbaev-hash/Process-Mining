from decimal import Decimal
from datetime import timedelta

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
from apps.bakery.voice_process_mining import resolve_batch


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
        self.assertEqual(order.display_batch_number, "01")
        self.assertEqual(order.items.count(), 2)
        self.assertEqual(ProductionBatch.objects.filter(order_item__order=order).count(), 2)
        self.assertEqual(
            set(ProductionBatch.objects.filter(order_item__order=order).values_list("daily_card_number", flat=True)),
            {1},
        )

        board = self.client.get(reverse("bakery:kanban"))
        self.assertEqual(board.context["columns"][0]["count"], 1)
        self.assertContains(board, f"Заказ №{order.order_number}")
        self.assertContains(board, self.product.name)
        self.assertContains(board, self.second_product.name)
        self.assertEqual(resolve_batch({"batch_number": "01"}).order_item.order, order)

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

    def queue_for(self, production_date):
        self.client.post(
            reverse("bakery:production_sheet"),
            {
                "date": production_date.isoformat(),
                f"plan_{self.product.pk}": "20",
                f"queue_quantity_{self.product.pk}": "20",
                "queue_product": str(self.product.pk),
            },
        )

    def test_visible_batch_number_restarts_for_each_production_day(self):
        """Вчера закрыто - завтрашний день снова начинается с 01.

        Ради этого нумерация и дневная: номер называют вслух и пишут мелом,
        и он должен оставаться двузначным.
        """
        today = timezone.localdate()
        tomorrow = today + timedelta(days=1)

        self.queue_for(today)
        # Смена закончена: партии ушли с доски и освободили свои числа.
        ProductionBatch.objects.update(status=ProductionBatch.Status.COMPLETED)
        self.queue_for(tomorrow)

        orders = list(ProductionOrder.objects.order_by("batch_number_date"))
        self.assertEqual([order.display_batch_number for order in orders], ["01", "01"])
        self.assertNotEqual(orders[0].batch_number_date, orders[1].batch_number_date)

    def test_a_carried_over_batch_keeps_its_number_and_the_next_day_steps_over(self):
        """Компромисс: счёт дневной, но занятые доской числа пропускаются.

        Партия, не закрытая вчера, лежит на доске и сегодня - её «01»
        написано мелом на тележке. Если завтрашняя нумерация начнёт с того
        же «01», на доске окажутся два одинаковых числа: путается и смена,
        и разбор голосовых команд. Такой день начинается с 02.
        """
        today = timezone.localdate()
        tomorrow = today + timedelta(days=1)

        self.queue_for(today)          # вчерашняя партия остаётся в очереди
        self.queue_for(tomorrow)

        orders = list(ProductionOrder.objects.order_by("batch_number_date"))
        self.assertEqual([order.display_batch_number for order in orders], ["01", "02"])

        active = ProductionBatch.objects.exclude(status__in=("completed", "cancelled"))
        numbers = [batch.daily_card_number for batch in active]
        self.assertEqual(len(numbers), len(set(numbers)), f"на доске повторился номер: {numbers}")

    def test_board_and_lists_name_the_batch_by_its_visible_number_and_day(self):
        """Один номер на всех страницах, и рядом с ним - его день.

        Нумерация начинается заново каждый производственный день, поэтому «01»
        в отрыве от даты называет столько партий, сколько дней в базе. А
        технический номер (B-1000 -> «1000») не должен попадаться человеку
        нигде: раньше он оставался в списке партий и на складе, и рядом с
        двузначными номерами доски выглядел номером другой партии.
        """
        today = timezone.localdate()
        self.client.post(
            reverse("bakery:production_sheet"),
            {
                "date": today.isoformat(),
                f"plan_{self.product.pk}": "20",
                f"queue_quantity_{self.product.pk}": "20",
                "queue_product": str(self.product.pk),
            },
        )
        batch = ProductionBatch.objects.get()
        self.assertEqual(batch.display_batch_number, "01")
        self.assertEqual(batch.display_batch_date, today)

        board = self.client.get(reverse("bakery:kanban"))
        self.assertContains(board, "<b>01</b>")
        self.assertContains(board, f"<i>{today:%d.%m}</i>")

        listing = self.client.get(reverse("bakery:batches"))
        self.assertContains(listing, ">01</a>")
        self.assertContains(listing, f"{today:%d.%m.%Y}")

        detail = self.client.get(reverse("bakery:batch_detail", args=[batch.pk]))
        self.assertContains(detail, f"Партия 01 от {today:%d.%m.%Y}")

    def test_orders_page_has_history_and_add_fallback(self):
        response = self.client.get(reverse("bakery:orders"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "История заказов")
        self.assertNotContains(response, ">Новый заказ<")
        self.assertContains(response, "Добавить заказ")
        self.assertContains(response, reverse("bakery:production_sheet"))
