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
        """Названия этапов - записи в базе, а не подписи интерфейса.

        На них завязано голосовое управление: оператор говорит «печь три»,
        и разбор ищет ровно то слово, что написано на доске. Переведённая
        колонка развела бы экран с командой, которую человек произносит.
        По той же причине не переводятся названия машин - «Печь 3» написана
        по-русски и на самом оборудовании.
        """
        source = (Path(settings.BASE_DIR) / "static/js/ui-i18n.js").read_text(encoding="utf-8")
        stages = ("Очередь", "Замес", "Формовка", "Расстойка", "Печь", "Склад", "Готово")
        for stage in stages:
            self.assertNotIn(f'"{stage}":', source, f"этап «{stage}» попал в словарь")

    def test_the_dictionary_stays_parseable(self):
        """Словарь правят руками и скриптами, и потерянная запятая роняет
        весь перевод молча: страница просто остаётся русской."""
        source = (Path(settings.BASE_DIR) / "static/js/ui-i18n.js").read_text(encoding="utf-8")
        body = source[source.index("const translations = {"):]
        body = body[: body.index("\n  };")]
        entries = [line for line in body.splitlines() if line.startswith('    "')]
        self.assertGreater(len(entries), 300, "словарь подозрительно похудел")
        # Каждая запись - пара [казахский, английский]; пустой перевод хуже
        # отсутствующего: он подменяет подпись пустотой.
        self.assertNotIn('""', body, "в словаре есть пустой перевод")
