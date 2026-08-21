"""Язык серверного текста: сводка и служебные ответы помощника.

Консоль переводится сама, а вот сводку и реплики помощника пишет сервер.
Проверяется не «перевод дословный» - это дело словаря, - а то, что язык
вообще доходит: от запроса до текста, включая единицы времени и формы
существительных при числе.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.core import analyst, assistant, llm

from tests.test_assistant import Model, bakery_log


@pytest.fixture
def analysis():
    return analyst.analyze(bakery_log())


class TestTemplateDigest:
    def test_every_language_gets_its_own_words(self, analysis):
        digests = {lang: analyst.compose_digest(analysis, lang) for lang in ("ru", "kk", "en")}
        assert "В журнале" in digests["ru"][0]
        assert "Журналда" in digests["kk"][0]
        assert "The log holds" in digests["en"][0]
        # Абзацев одинаково: языки различаются словами, а не наполнением.
        assert len({len(d) for d in digests.values()}) == 1

    def test_units_follow_the_language(self):
        """«4 ч 09 мин» на английском - это «4 h 09 min», а не перевод цифр."""
        assert analyst.humanize_seconds(14_940, "ru") == "4 ч 09 мин"
        assert analyst.humanize_seconds(14_940, "kk") == "4 сағ 09 мин"
        assert analyst.humanize_seconds(14_940, "en") == "4 h 09 min"

    def test_the_russian_plural_still_has_three_forms(self, analysis):
        """Русскому нужны «кейс / кейса / кейсов», английскому - две формы,
        казахскому - одна: после числительного слово не меняется."""
        assert analyst.word("case", 1, "ru") == "кейс"
        assert analyst.word("case", 3, "ru") == "кейса"
        assert analyst.word("case", 12, "ru") == "кейсов"
        assert analyst.word("case", 12, "kk") == "кейс"
        assert analyst.word("case", 1, "en") == "case"
        assert analyst.word("case", 12, "en") == "cases"

    def test_an_unknown_language_is_russian_not_a_crash(self, analysis):
        """С фронта может прийти что угодно - «uk», «ru-RU», пустая строка.
        Ронять сводку из-за этого нельзя."""
        assert analyst.normalize_lang("ru-RU") == "ru"
        assert analyst.normalize_lang("kk-KZ") == "kk"
        for junk in ("", None, "uk", "zz", "«»"):
            assert analyst.normalize_lang(junk) == "ru"
        assert analyst.compose_digest(analysis, "zz") == analyst.compose_digest(analysis, "ru")

    def test_a_thin_log_speaks_the_language_too(self):
        """Даже отказ «данных мало» человек читает на своём языке."""
        thin = analyst.analyze(bakery_log(cases=2))
        assert "жиналғанда" in analyst.compose_digest(thin, "kk")[0]
        assert "too little data" in analyst.compose_digest(thin, "en")[0]


class TestModelPrompts:
    def test_the_narrator_is_told_which_language_to_use(self, analysis, monkeypatch):
        seen = {}
        monkeypatch.setattr(
            llm, "say",
            lambda settings, system, user, **k: seen.update(system=system, user=user) or "x" * 300,
        )
        wired = Settings(
            llm_enabled=True, llm_base_url="http://model.invalid/v1", llm_model="q",
            mapping_config="config/activities.yaml",
        )
        analyst.narrate(wired, analysis, "en")
        assert "in English" in seen["system"]
        assert "in English" in seen["user"]

    def test_the_assistant_is_told_too(self, monkeypatch):
        fake = Model({"role": "assistant", "content": "The log looks steady."})
        monkeypatch.setattr(llm, "chat", fake)
        wired = Settings(
            llm_enabled=True, llm_base_url="http://model.invalid/v1", llm_model="q",
            mapping_config="config/activities.yaml",
        )
        assistant.ask(wired, bakery_log(), "how are we doing?", lang="en")
        assert "in English" in fake.sent[0][0]["content"]

    def test_stage_names_are_left_alone(self, monkeypatch):
        """Названия этапов - надписи на оборудовании. Переведённая «Формовка»
        в английском ответе не найдётся глазами на экране."""
        fake = Model({"role": "assistant", "content": "ok"})
        monkeypatch.setattr(llm, "chat", fake)
        wired = Settings(
            llm_enabled=True, llm_base_url="http://model.invalid/v1", llm_model="q",
            mapping_config="config/activities.yaml",
        )
        assistant.ask(wired, bakery_log(), "what is slow?", lang="en")
        assert "не переводи" in fake.sent[0][0]["content"]


class TestServiceReplies:
    def test_silence_is_reported_in_the_asked_language(self, monkeypatch):
        """Модель молчит - это говорит сервис, а не она. Значит, и текст
        должен быть на языке консоли, без похода к модели."""
        monkeypatch.setattr(llm, "chat", Model())
        wired = Settings(
            llm_enabled=True, llm_base_url="http://model.invalid/v1", llm_model="q",
            mapping_config="config/activities.yaml",
        )
        assert "unavailable" in assistant.ask(wired, bakery_log(), "?", lang="en")["answer"]
        assert "қолжетімсіз" in assistant.ask(wired, bakery_log(), "?", lang="kk")["answer"]

    def test_an_unconfigured_model_says_so_in_the_asked_language(self):
        bare = Settings(mapping_config="config/activities.yaml")
        assert "not configured" in assistant.ask(bare, None, "hi", lang="en")["answer"]
        assert "бапталмаған" in assistant.ask(bare, None, "hi", lang="kk")["answer"]


class TestEndpoints:
    @pytest.fixture
    def log_id(self, client, sample_events) -> str:
        created = client.post(
            "/api/v1/logs",
            json={"name": "bakery", "events": sample_events, "mapping_profile": "bakery"},
        )
        assert created.status_code == 201, created.text
        return created.json()["log_id"]

    def test_the_digest_route_takes_a_language(self, client, log_id):
        english = client.get(f"/api/v1/logs/{log_id}/analyst?lang=en").json()["digest"]
        russian = client.get(f"/api/v1/logs/{log_id}/analyst?lang=ru").json()["digest"]
        assert english != russian
        assert "The log holds" in english[0]

    def test_the_cache_does_not_serve_the_wrong_language(self, client, log_id):
        """Сводка кэшируется. Ключ обязан включать язык - иначе первый
        спросивший по-русски определит язык для всех следующих."""
        first = client.get(f"/api/v1/logs/{log_id}/analyst?lang=ru").json()["digest"][0]
        second = client.get(f"/api/v1/logs/{log_id}/analyst?lang=kk").json()["digest"][0]
        assert first != second
        assert "Журналда" in second

    def test_the_assistant_route_takes_a_language(self, client, log_id):
        answer = client.post(
            f"/api/v1/logs/{log_id}/assistant",
            json={"question": "how are we doing?", "lang": "en"},
        ).json()
        assert answer["available"] is False
        assert "not configured" in answer["answer"]
