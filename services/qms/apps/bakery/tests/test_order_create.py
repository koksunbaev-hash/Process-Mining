from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.bakery.models import Customer, Product, ProductionOrder


class OrderCreateTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("order-manager", password="x")
        self.user.profile.role = UserProfile.Role.MANAGER
        self.user.profile.save(update_fields=["role"])
        self.client.force_login(self.user)
        self.product = Product.objects.create(code="ORDER-TEST", name="Тестовый хлеб", unit="шт", is_active=True)

    def test_new_order_page_starts_with_products(self):
        response = self.client.get(reverse("bakery:order_new"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Добавьте продукцию и количество")
        self.assertContains(response, "items-0-product")
        self.assertNotContains(response, "Клиент:")
        self.assertNotContains(response, "Плановый срок:")
        self.assertNotContains(response, "Приоритет:")

    def test_creates_same_day_order_with_hidden_defaults_and_item(self):
        response = self.client.post(reverse("bakery:order_new"), {
            "items-TOTAL_FORMS": "1", "items-INITIAL_FORMS": "0",
            "items-MIN_NUM_FORMS": "0", "items-MAX_NUM_FORMS": "100",
            "items-0-product": str(self.product.pk), "items-0-quantity": "125",
        })
        order = ProductionOrder.objects.get()
        self.assertRedirects(response, reverse("bakery:order_detail", args=[order.pk]))
        self.assertEqual(order.customer.name, "Производство")
        self.assertEqual(order.priority, ProductionOrder.Priority.NORMAL)
        self.assertEqual(timezone.localdate(order.required_date), timezone.localdate())
        self.assertEqual(order.items.get().product, self.product)
        self.assertEqual(order.items.get().unit, self.product.unit)

    def test_requires_at_least_one_product(self):
        response = self.client.post(reverse("bakery:order_new"), {
            "items-TOTAL_FORMS": "1", "items-INITIAL_FORMS": "0",
            "items-MIN_NUM_FORMS": "0", "items-MAX_NUM_FORMS": "100",
            "items-0-product": "", "items-0-quantity": "",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Добавьте хотя бы один продукт")
        self.assertFalse(ProductionOrder.objects.exists())
        self.assertFalse(Customer.objects.filter(name="Производство").exists())

    def test_manager_can_delete_draft_order_from_detail(self):
        customer = Customer.objects.create(name="Системный клиент")
        order = ProductionOrder.objects.create(
            customer=customer,
            required_date=timezone.now(),
            created_by=self.user,
        )

        response = self.client.post(
            reverse("bakery:order_detail", args=[order.pk]),
            {"action": "delete"},
        )

        self.assertRedirects(response, reverse("bakery:orders"))
        self.assertFalse(ProductionOrder.objects.filter(pk=order.pk).exists())
