"""Помощник и языковая модель.

Ни один тест сюда не ходит в сеть: модель подменяется заглушкой, и это не
удобство, а условие - иначе набор тестов начнёт зависеть от того, включена
ли машина в соседней стойке.

Проверяется главное свойство всей затеи: числа считает сервис, модель их
только пересказывает. Поэтому инструменты проверяются на настоящем журнале,
а разговор - на том, что модель действительно сходила за данными, а её
молчание не погасило экран.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pandas as pd
import pytest

from app.config import Settings
from app.core import analyst, assistant, llm, model


# --------------------------------------------------------------- обстановка

STEPS = ["Очередь", "Замес", "Формовка", "Печь", "Готово"]


def bakery_log(cases: int = 12) -> pd.DataFrame:
    base = datetime(2026, 8, 1, 8, 0)
    rows = []
    for index in range(cases):
        moment = base + timedelta(days=index % 10, minutes=index)
        for step_no, activity in enumerate(STEPS):
            moment = moment + timedelta(seconds=7200 if index == 5 and step_no == 3 else 600)
            rows.append(
                {
                    model.CASE: f"B-{1100 + index}",
                    model.ACTIVITY: activity,
                    model.TIMESTAMP: moment,
                    model.RESOURCE: f"Печь {index % 3 + 1}",
                }
            )
    return pd.DataFrame(rows)


@pytest.fixture
def log() -> pd.DataFrame:
    return bakery_log()


@pytest.fixture
def wired() -> Settings:
    """Настройки с «включённой» моделью. Ходить по этому адресу никто не будет:
    сам вызов всегда подменяется."""
    return Settings(
        llm_enabled=True,
        llm_base_url="http://model.invalid/v1",
        llm_model="qwen-test",
        mapping_config="config/activities.yaml",
    )


class Model:
    """Заглушка модели: отдаёт заранее заготовленные ответы по одному.

    Запоминает отправленные сообщения - по ним видно, дошли ли до модели
    результаты инструментов и не утёк ли ей журнал целиком.
    """

    def __init__(self, *replies):
        self.replies = list(replies)
        self.sent: list[list[dict]] = []

    def __call__(self, settings, messages, **kwargs):
        self.sent.append([dict(m) for m in messages])
        return self.replies.pop(0) if self.replies else None


def tool_call(name: str, **arguments) -> dict:
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
        ],
    }


# ---------------------------------------------------------------- транспорт

class TestTransport:
    def test_an_unconfigured_model_is_silence_not_an_error(self):
        """Пустые настройки - обычное состояние сервиса без модели. Вызов
        обязан вернуть None молча, не пытаясь никуда пойти."""
        settings = Settings(mapping_config="config/activities.yaml")
        assert llm.configured(settings) is False
        assert llm.chat(settings, [{"role": "user", "content": "привет"}]) is None
        assert llm.say(settings, "система", "вопрос") is None

    def test_half_configured_counts_as_unconfigured(self, wired):
        """Адрес без имени модели - недонастройка. Идти по нему бессмысленно:
        vLLM ответит ошибкой, а человек получит непонятное сообщение."""
        assert llm.configured(wired.model_copy(update={"llm_model": ""})) is False
        assert llm.configured(wired.model_copy(update={"llm_base_url": ""})) is False

    def test_an_empty_answer_is_treated_as_no_answer(self, wired, monkeypatch):
        """Так выглядит модель, ушедшая в размышление: content пустой, всё
        ушло в reasoning. Для вызывающего это то же самое, что молчание."""
        monkeypatch.setattr(llm, "chat", lambda *a, **k: {"role": "assistant", "content": "   "})
        assert llm.say(wired, "система", "вопрос") is None


# ------------------------------------------------------------------- сводка

class TestNarration:
    def test_the_brief_carries_the_numbers_the_screen_shows(self, log):
        """Модель получает выжимку, а не журнал. Значит, в выжимке должно
        быть всё, о чём её потом спросят, - и ничего кроме."""
        text = analyst.brief(analyst.analyze(log))
        assert "Кейсов в журнале: 12" in text
        assert "Самые долгие переходы:" in text
        assert "Формовка → Печь" in text
        # Журнал целиком в выжимку не попадает: номера дел - только у аномалий.
        assert text.count("B-11") <= 3

    def test_the_model_words_replace_the_templates(self, wired, log, monkeypatch):
        told = "Смена прошла ровно.\n\nДольше всего ждут перед печью."
        monkeypatch.setattr(llm, "say", lambda *a, **k: told + " " * 200)
        digest = analyst.narrate(wired, analyst.analyze(log))
        assert digest is not None
        assert digest[0].startswith("Смена прошла ровно")

    def test_a_two_word_answer_is_not_a_digest(self, wired, log, monkeypatch):
        """Короткий ответ - признак того, что модель не поняла задачу.
        Шаблоны в этом случае честнее."""
        monkeypatch.setattr(llm, "say", lambda *a, **k: "Всё хорошо.")
        assert analyst.narrate(wired, analyst.analyze(log)) is None

    def test_silence_falls_back_to_templates(self, wired, log, monkeypatch):
        monkeypatch.setattr(llm, "say", lambda *a, **k: None)
        assert analyst.narrate(wired, analyst.analyze(log)) is None

    def test_a_thin_log_does_not_bother_the_model(self, wired, monkeypatch):
        """Про два кейса сказать нечего ни шаблону, ни модели. Ходить к ней
        за этим - тратить секунды на заведомо пустой ответ."""
        called = []
        monkeypatch.setattr(llm, "say", lambda *a, **k: called.append(1) or "x" * 300)
        assert analyst.narrate(wired, analyst.analyze(bakery_log(cases=2))) is None
        assert called == []


class TestDigestEndpoint:
    @pytest.fixture
    def log_id(self, client, sample_events) -> str:
        created = client.post(
            "/api/v1/logs",
            json={"name": "bakery", "events": sample_events, "mapping_profile": "bakery"},
        )
        assert created.status_code == 201, created.text
        return created.json()["log_id"]

    def test_without_a_model_the_digest_is_still_there(self, client, log_id):
        """Главное свойство: модель выключена - экран работает как раньше."""
        payload = client.get(f"/api/v1/logs/{log_id}/analyst").json()
        assert payload["narrator"] == "templates"
        assert payload["digest"]

    def test_the_model_is_not_asked_unless_asked_for(self, client, log_id, monkeypatch):
        """Пересказ идёт секунды, и экран открывается раньше него. Значит,
        обычный запрос сводки не должен трогать модель вообще."""
        visits = []
        monkeypatch.setattr(analyst, "narrate", lambda *a, **k: visits.append(1))
        assert client.get(f"/api/v1/logs/{log_id}/analyst").status_code == 200
        assert visits == []

    def test_the_flag_brings_the_model_words(self, client, log_id, monkeypatch):
        monkeypatch.setattr(analyst, "narrate", lambda *a, **k: ["Смена прошла ровно."])
        payload = client.get(f"/api/v1/logs/{log_id}/analyst?narrate=1").json()
        assert payload["narrator"] == "llm"
        assert payload["digest"] == ["Смена прошла ровно."]

    def test_a_silent_model_leaves_the_templates(self, client, log_id, monkeypatch):
        """Пересказ не получился - сводка всё равно на месте, и подписана
        честно. Пустой экран здесь был бы хуже шаблонного текста."""
        monkeypatch.setattr(analyst, "narrate", lambda *a, **k: None)
        payload = client.get(f"/api/v1/logs/{log_id}/analyst?narrate=1").json()
        assert payload["narrator"] == "templates"
        assert payload["digest"]


# --------------------------------------------------------------- инструменты

class TestTools:
    def test_overview_answers_in_human_units(self, log):
        result = assistant.call_tool(log, "overview", {})
        assert result["дела"] == 12
        assert result["события"] == 60
        # Секунды наружу не выходят: модель их всё равно перепишет неверно.
        assert "мин" in result["время_дела"]["медиана"] or "ч" in result["время_дела"]["медиана"]

    def test_bottlenecks_name_the_slowest_transition(self, log):
        result = assistant.call_tool(log, "bottlenecks", {"limit": 3})
        assert result["переходы"]
        assert len(result["переходы"]) <= 3

    def test_anomalies_say_plainly_when_there_are_none(self):
        """Пустой список легко прочитать как «не спросили». Пояснение рядом
        не даёт модели превратить тишину в тревогу."""
        result = assistant.call_tool(bakery_log(cases=12).query("case_id != 'B-1105'"), "anomalies", {})
        assert result["застрявшие_дела"] == []
        assert "пояснение" in result

    def test_the_stuck_case_is_found_by_name(self, log):
        result = assistant.call_tool(log, "anomalies", {})
        assert [row["дело"] for row in result["застрявшие_дела"]] == ["B-1105"]

    def test_an_activity_is_matched_loosely(self, log):
        """Человек спрашивает «печь», в журнале «Печь». Требовать точного
        совпадения значит отвечать «такого этапа нет» на верный вопрос."""
        assert assistant.call_tool(log, "activity", {"name": "печь"})["этап"] == "Печь"
        assert assistant.call_tool(log, "activity", {"name": "формов"})["этап"] == "Формовка"

    def test_an_unknown_activity_returns_the_real_ones(self, log):
        """Ошибка с подсказкой: модель по этому списку сама себя поправит."""
        result = assistant.call_tool(log, "activity", {"name": "гальваника"})
        assert "ошибка" in result
        assert "Печь" in result["известные_этапы"]

    def test_a_case_trace_reads_in_order(self, log):
        result = assistant.call_tool(log, "case", {"case_id": "B-1105"})
        assert [step["этап"] for step in result["путь"]] == STEPS
        assert result["путь"][0]["ждало_до_этого"] is None
        assert result["событий"] == 5

    def test_an_unknown_case_suggests_the_near_ones(self, log):
        result = assistant.call_tool(log, "case", {"case_id": "B-1106x"})
        assert "ошибка" in result
        assert "B-1106" in result["похожие_номера"]

    def test_resources_are_the_machines(self, log):
        result = assistant.call_tool(log, "resources", {})
        assert {row["исполнитель"] for row in result["исполнители"]} == {"Печь 1", "Печь 2", "Печь 3"}

    def test_variants_and_slowest_cases_answer(self, log):
        assert assistant.call_tool(log, "variants", {})["всего_маршрутов"] == 1
        slowest = assistant.call_tool(log, "slowest_cases", {"limit": 2})
        assert slowest["дела"][0]["дело"] == "B-1105"

    def test_a_wrong_tool_name_is_an_answer_not_a_crash(self, log):
        """Модель промахивается мимо имени примерно как человек. Ронять из-за
        этого весь запрос - значит терять и остальные её находки."""
        result = assistant.call_tool(log, "погода", {})
        assert "ошибка" in result and "overview" in result["доступные"]

    def test_wrong_arguments_are_an_answer_too(self, log):
        assert "ошибка" in assistant.call_tool(log, "case", {"дело": "B-1105"})
        assert "ошибка" in assistant.call_tool(log, "activity", {})


# ----------------------------------------------------------------- разговор

class TestConversation:
    def test_the_model_goes_to_the_data_before_answering(self, wired, log, monkeypatch):
        """Ради этого всё и затевалось: ответ собирается из настоящих чисел,
        а не из памяти модели. Проверяем, что результат инструмента реально
        доехал до неё следующим сообщением."""
        fake = Model(
            tool_call("anomalies", limit=3),
            {"role": "assistant", "content": "Застряло одно дело - B-1105 перед печью."},
        )
        monkeypatch.setattr(llm, "chat", fake)

        result = assistant.ask(wired, log, "какие дела застряли?")

        assert result["available"] is True
        assert "B-1105" in result["answer"]
        assert result["steps"] == [{"tool": "anomalies", "arguments": {"limit": 3}}]
        second_call = fake.sent[1]
        assert second_call[-1]["role"] == "tool"
        assert "B-1105" in second_call[-1]["content"]

    def test_a_silent_model_does_not_break_the_screen(self, wired, log, monkeypatch):
        monkeypatch.setattr(llm, "chat", Model())
        result = assistant.ask(wired, log, "что случилось вчера?")
        assert result["available"] is False
        assert "недоступна" in result["answer"]

    def test_without_settings_it_says_so_instead_of_pretending(self, log):
        settings = Settings(mapping_config="config/activities.yaml")
        result = assistant.ask(settings, log, "сколько дел?")
        assert result["available"] is False
        assert "не настроен" in result["answer"]

    def test_a_model_stuck_in_a_loop_is_cut_off(self, wired, log, monkeypatch):
        """Модель может ходить за данными бесконечно. Круг обрывается, и
        человек получает объяснение, а не пустое поле."""
        monkeypatch.setattr(llm, "chat", Model(*[tool_call("overview")] * 20))
        result = assistant.ask(wired, log, "расскажи всё")
        assert len(result["steps"]) == assistant.MAX_STEPS
        assert "конкретнее" in result["answer"]

    def test_history_reaches_the_model_but_stays_short(self, wired, log, monkeypatch):
        """Переписку хранит браузер, и прислать он может сколько угодно.
        В запрос уходит хвост: длинная история дороже, чем полезна."""
        fake = Model({"role": "assistant", "content": "Да, это та же печь."})
        monkeypatch.setattr(llm, "chat", fake)
        history = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"реплика {i}"}
            for i in range(20)
        ]
        assistant.ask(wired, log, "а это та же печь?", history)
        sent = fake.sent[0]
        assert sent[0]["role"] == "system"
        assert len(sent) == 1 + 6 + 1
        assert sent[-1]["content"] == "а это та же печь?"

    def test_an_empty_question_is_not_sent_anywhere(self, wired, log, monkeypatch):
        monkeypatch.setattr(llm, "chat", Model({"role": "assistant", "content": "не должно случиться"}))
        assert assistant.ask(wired, log, "   ")["answer"] == "Задайте вопрос по журналу."


class TestAssistantEndpoint:
    def test_the_route_answers_even_without_a_model(self, client, sample_events):
        """Модель не настроена - маршрут всё равно отвечает 200 и объясняет,
        почему помощник молчит. Ошибка сервера тут выглядела бы поломкой."""
        created = client.post(
            "/api/v1/logs",
            json={"name": "bakery", "events": sample_events, "mapping_profile": "bakery"},
        )
        response = client.post(
            f"/api/v1/logs/{created.json()['log_id']}/assistant",
            json={"question": "где теряем время?"},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["available"] is False
        assert payload["log_id"] == created.json()["log_id"]

    def test_an_empty_question_is_refused_by_the_schema(self, client, sample_events):
        created = client.post(
            "/api/v1/logs",
            json={"name": "bakery", "events": sample_events, "mapping_profile": "bakery"},
        )
        response = client.post(
            f"/api/v1/logs/{created.json()['log_id']}/assistant", json={"question": ""}
        )
        assert response.status_code == 422

    def test_it_needs_the_api_key(self, client):
        bare = client.post(
            "/api/v1/logs/nope/assistant",
            json={"question": "привет"},
            headers={"X-API-Key": "wrong"},
        )
        assert bare.status_code in (401, 403)
