"""Список заказов: карточка должна оставаться карточкой.

Крупный заказ на заводе - это шесть десятков позиций. Пока в карточку попадали
все, она вырастала на весь экран, а соседние в том же ряду растягивались под
неё и стояли полупустыми: заголовок вверху, даты посередине, товары у самого
низа. Список читают, чтобы найти нужный заказ, а не изучить его состав.
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

PREVIEW_LIMIT = 8


class OrderCardPreviewTests(TestCase):
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

    def preview_of(self, html, order):
        """Кусок разметки одной карточки - от её номера до конца списка товаров."""
        start = html.index(f"№{order.order_number}")
        return html[start:html.index("</article>", start)]

    def test_a_big_order_shows_only_the_first_few(self):
        order = self.make_order(40)
        card = self.preview_of(self.client.get(reverse("bakery:orders")).content.decode(), order)

        self.assertIn("Хлеб номер 0", card)
        self.assertIn(f"Хлеб номер {PREVIEW_LIMIT - 1}", card)
        self.assertNotIn(f"Хлеб номер {PREVIEW_LIMIT}", card)

    def test_the_rest_are_counted_not_dropped(self):
        """Молча обрезать нельзя: по карточке не понять, весь заказ перед
        тобой или его начало."""
        order = self.make_order(40)
        card = self.preview_of(self.client.get(reverse("bakery:orders")).content.decode(), order)

        self.assertIn(f"ещё {40 - PREVIEW_LIMIT}", card)

    def test_a_small_order_is_shown_whole(self):
        order = self.make_order(3)
        card = self.preview_of(self.client.get(reverse("bakery:orders")).content.decode(), order)

        self.assertIn("Хлеб номер 2", card)
        self.assertNotIn("ещё", card)

    def test_exactly_the_limit_needs_no_counter(self):
        order = self.make_order(PREVIEW_LIMIT)
        card = self.preview_of(self.client.get(reverse("bakery:orders")).content.decode(), order)

        self.assertIn(f"Хлеб номер {PREVIEW_LIMIT - 1}", card)
        self.assertNotIn("ещё", card)

    def test_an_empty_order_says_so(self):
        order = self.make_order(0)
        card = self.preview_of(self.client.get(reverse("bakery:orders")).content.decode(), order)

        self.assertIn("Нет позиций", card)
