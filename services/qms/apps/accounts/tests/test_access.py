"""Скрытый пункт меню должен быть ещё и закрыт по прямой ссылке."""

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import UserProfile
from apps.bakery.tests.batch_workflow.factories import create_stage_list, create_user


class SectionAccessTests(TestCase):
    def setUp(self):
        create_stage_list()

    def login(self, username, role):
        create_user(username, role, password="pass12345")
        self.client.login(username=username, password="pass12345")

    def test_operator_is_sent_home_from_the_orders_page(self):
        self.login("operator", UserProfile.Role.USER)
        response = self.client.get(reverse("bakery:orders"), follow=True)
        self.assertRedirects(response, reverse("bakery:kanban"))
        self.assertContains(response, "недоступен для вашей роли")

    def test_operator_landing_on_the_dashboard_ends_up_on_the_board(self):
        # LOGIN_REDIRECT_URL ведёт на панель, а цех её не видит: без этого
        # первым экраном после входа была бы страница отказа.
        self.login("operator2", UserProfile.Role.USER)
        response = self.client.get(reverse("dashboard:index"), follow=True)
        self.assertRedirects(response, reverse("bakery:kanban"))

    def test_operator_keeps_the_board_and_the_recipes(self):
        self.login("operator3", UserProfile.Role.USER)
        self.assertEqual(self.client.get(reverse("bakery:kanban")).status_code, 200)
        self.assertEqual(self.client.get(reverse("bakery:recipes")).status_code, 200)

    def test_manager_opens_everything_the_office_needs(self):
        self.login("manager", UserProfile.Role.MANAGER)
        for name in ["bakery:ingredients", "bakery:production_sheet", "bakery:orders", "audit:logs"]:
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_guard_covers_pages_of_single_records_too(self):
        # Раздел - это не один адрес: форма нового продукта закрыта тем же
        # правилом, что и список.
        self.login("operator4", UserProfile.Role.USER)
        self.assertRedirects(self.client.get(reverse("bakery:product_new")), reverse("bakery:kanban"))

    def test_anonymous_goes_to_the_login_form_keeping_the_address(self):
        target = reverse("bakery:orders")
        response = self.client.get(target)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])
        self.assertIn(target, response["Location"])

    def test_api_is_left_to_its_own_permissions(self):
        # У API свои разрешения DRF, и посредник в них не вмешивается: иначе
        # мобильное приложение оператора получало бы перенаправление на HTML.
        self.login("operator5", UserProfile.Role.USER)
        response = self.client.get("/api/orders/")
        self.assertEqual(response.status_code, 200)
