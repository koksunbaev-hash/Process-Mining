"""Кто что видит в меню.

Проверяется список разделов, а не разметка: разметка меняется, а обещание
«оператор не видит заказы» - нет.
"""

from django.test import TestCase
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from apps.accounts.models import UserProfile
from apps.accounts.navigation import (
    GROUPS,
    ROUTE_SECTION,
    SECTIONS,
    can_view,
    grouped_sections,
    home_section,
    sections_for,
)
from apps.bakery.tests.batch_workflow.factories import create_user


def keys_for(user):
    return {section.key for section in sections_for(user)}


class RoleMenuTests(TestCase):
    def test_employee_sees_the_board_and_little_else(self):
        user = create_user("worker", UserProfile.Role.USER)
        self.assertEqual(
            keys_for(user),
            {"kanban", "batches", "voice", "stock", "recipes", "nonconformities", "notifications", "settings"},
        )

    def test_employee_menu_is_not_grouped(self):
        # Восемь пунктов - заголовки групп над ними были бы разлиновкой ради
        # разлиновки. Порог живёт в FLAT_MENU_LIMIT.
        user = create_user("worker2", UserProfile.Role.USER)
        self.assertLessEqual(len(sections_for(user)), 8)

    def test_employee_does_not_get_the_office_pages(self):
        keys = keys_for(create_user("worker3", UserProfile.Role.USER))
        for key in ["dashboard", "orders", "products", "ingredients", "production_sheet",
                    "forecast", "reports", "audit", "process_mining"]:
            self.assertNotIn(key, keys)

    def test_manager_sees_everything_except_the_django_admin(self):
        """«Всё, кроме админки»: сама админка живёт на is_staff, а не на роли."""
        manager = create_user("boss-lite", UserProfile.Role.MANAGER)
        self.assertEqual(keys_for(manager), {section.key for section in SECTIONS})
        self.assertFalse(manager.is_staff)

    def test_admin_sees_every_section(self):
        user = create_user("boss", UserProfile.Role.ADMIN)
        self.assertEqual(keys_for(user), {section.key for section in SECTIONS})

    def test_superuser_counts_as_admin_without_a_role(self):
        user = create_user("root", UserProfile.Role.USER)
        user.is_superuser = True
        user.save(update_fields=["is_superuser"])
        self.assertEqual(keys_for(user), {section.key for section in SECTIONS})

    def test_a_profile_without_a_role_falls_back_to_employee(self):
        # Профиль без роли не должен показывать пустое меню: это выглядит
        # поломкой. Самый узкий уровень - честнее.
        user = create_user("no-role-nav", UserProfile.Role.USER)
        user.profile.role = ""
        user.profile.save(update_fields=["role"])
        self.assertEqual(keys_for(user), keys_for(create_user("worker4", UserProfile.Role.USER)))

    def test_hidden_section_leaves_the_menu_but_keeps_its_guard(self):
        """Уведомления убраны из меню, но остаются разделом.

        Если бы раздел удалили совсем, его адреса выпали бы из ROUTE_SECTION и
        стали бы открыты любой роли - молча.
        """
        from apps.accounts.navigation import BY_KEY, menu_sections

        user = create_user("worker-hidden", UserProfile.Role.USER)
        self.assertTrue(BY_KEY["notifications"].hidden)
        self.assertNotIn("notifications", {s.key for s in menu_sections(user)})
        self.assertIn("notifications", keys_for(user))
        self.assertTrue(can_view(user, "notifications"))

    def test_anonymous_sees_nothing(self):
        from django.contrib.auth.models import AnonymousUser

        self.assertEqual(sections_for(AnonymousUser()), [])
        self.assertFalse(can_view(AnonymousUser(), "kanban"))

    def test_home_is_the_first_available_section(self):
        self.assertEqual(home_section(create_user("op3", UserProfile.Role.USER)).key, "kanban")
        self.assertEqual(home_section(create_user("mgr", UserProfile.Role.MANAGER)).key, "dashboard")

    def test_groups_keep_their_order_and_drop_the_empty_ones(self):
        groups = grouped_sections(create_user("op4", UserProfile.Role.USER))
        titles = [group["title"] for group in groups]
        self.assertEqual(titles, [title for title in GROUPS if title in titles])
        self.assertTrue(all(group["items"] for group in groups))


class SectionWiringTests(TestCase):
    """Ошибки, которые видно только в бою: опечатка в имени адреса и забытый вид."""

    def test_every_section_resolves(self):
        for section in SECTIONS:
            with self.subTest(section=section.key):
                self.assertTrue(reverse(section.url_name))

    def test_every_group_is_declared(self):
        for section in SECTIONS:
            self.assertIn(section.group, GROUPS)

    def test_no_route_belongs_to_two_sections(self):
        routes = [route for section in SECTIONS for route in section.all_routes]
        self.assertEqual(len(routes), len(set(routes)))

    def test_every_bakery_url_is_covered(self):
        """Новый вид в bakery без раздела остался бы открытым для всех.

        Раздел определяет и меню, и проверку посредника, поэтому адрес вне
        разделов виден любой роли - молча и до тех пор, пока кто-нибудь не
        заметит.
        """
        uncovered = sorted(name for name in url_names("bakery") if name not in ROUTE_SECTION)
        self.assertEqual(uncovered, [])


def url_names(namespace):
    """Все именованные адреса пространства имён, как `bakery:kanban`."""
    for entry in get_resolver().url_patterns:
        if isinstance(entry, URLResolver) and entry.namespace == namespace:
            for pattern in entry.url_patterns:
                if isinstance(pattern, URLPattern) and pattern.name:
                    yield f"{namespace}:{pattern.name}"
