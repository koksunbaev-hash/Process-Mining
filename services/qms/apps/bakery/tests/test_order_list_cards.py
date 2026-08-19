"""Список заказов: карточка должна оставаться карточкой.

Крупный заказ на заводе - это три десятка позиций. Пока карточка росла под
них, она вытягивала весь ряд: соседние карточки растягивались следом и стояли
с щелями между заголовком, датами и товарами.

Высота ограничена показом, а не разметкой: все позиции остаются на странице,
и поиск по ней их находит.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.bakery.models import (
    Customer,
    Product,
    ProductionOrder,
    ProductionOrderItem,
)


class OrderCardTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("orders-list", password="x")
        self.user.profile.role = UserProfile.Role.MANAGER
        self.user.profile.save(update_fields=["role"])
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(name="Сеть магазинов")

    def make_order(self, positions):
        order = ProductionOrder.objects.create(
            customer=self.customer, required_date=timezone.now() + timedelta(days=1)
        )
        for index in range(positions):
            product = Product.objects.create(
                code=f"P{order.pk}-{index}", name=f"Хлеб номер {index}", unit="шт"
            )
            ProductionOrderItem.objects.create(
                order=order, product=product, quantity=10 + index, unit="шт"
            )
        return order

    def card_of(self, order):
        html = self.client.get(reverse("bakery:orders")).content.decode()
        start = html.index(f"№{order.order_number}")
        return html[start:html.index("</article>", start)]

    def test_a_big_order_keeps_all_its_positions_in_the_page(self):
        """Обрезано только показом. Выбрось позиции из разметки - и поиск по
        странице перестанет их находить, а ищут по ней постоянно."""
        self.make_order(30)
        card = self.card_of(ProductionOrder.objects.first())

        self.assertIn("Хлеб номер 0", card)
        self.assertIn("Хлеб номер 29", card)

    def test_a_big_order_can_be_opened_in_place(self):
        """Прятать состав нельзя - за ним сюда и заходят. Кнопка разворачивает
        список прямо в карточке, не уводя со страницы."""
        self.make_order(30)
        card = self.card_of(ProductionOrder.objects.first())

        self.assertIn("Все позиции (30)", card)
        self.assertIn("data-products-toggle", card)
        self.assertNotIn("is-whole", card)

    def test_a_small_order_is_not_clipped(self):
        """Три позиции помещаются целиком - обрывать нечего, и подпись про
        количество была бы шумом."""
        self.make_order(3)
        card = self.card_of(ProductionOrder.objects.first())

        self.assertIn("is-whole", card)
        self.assertNotIn("data-products-toggle", card)

    def test_an_empty_order_says_so(self):
        self.make_order(0)
        card = self.card_of(ProductionOrder.objects.first())

        self.assertIn("Нет позиций", card)
