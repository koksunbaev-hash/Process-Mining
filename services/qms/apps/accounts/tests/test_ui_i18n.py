from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class UiLanguageSwitcherTests(TestCase):
    def test_login_page_has_three_language_switcher(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, 'data-ui-language')
        self.assertContains(response, 'value="ru"')
        self.assertContains(response, 'value="kk"')
        self.assertContains(response, 'value="en"')
        self.assertContains(response, "ui-i18n.")

    def test_authenticated_page_has_language_switcher(self):
        user = get_user_model().objects.create_user("language-user", password="x")
        self.client.force_login(user)
        response = self.client.get(reverse("bakery:kanban"))
        self.assertContains(response, 'data-ui-language')

    def test_stage_and_catalog_values_are_not_translation_keys(self):
        source = (Path(settings.BASE_DIR) / "static/js/ui-i18n.js").read_text(encoding="utf-8")
        for protected_value in ('"Замес":', '"Формовка":', '"Расстойка":', '"Печь":'):
            self.assertNotIn(protected_value, source)
