"""Проверяется не «похоже ли на правду» - это меряет selfcheck.py на живом
журнале, - а то, что генератор не может навредить и не расходится сам с собой.
"""

import json
import random
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import feed  # noqa: E402


@pytest.fixture
def profile():
    raw = json.loads((Path(feed.HERE) / "profile.json").read_text(encoding="utf-8"))
    return feed.Profile(raw, "batch")


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_FEED_ENABLED", "1")
    monkeypatch.setenv("DEMO_FEED_API_KEY", "test-key")
    monkeypatch.setenv("DEMO_FEED_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("DEMO_FEED_DRY_RUN", "1")
    monkeypatch.setenv("DEMO_FEED_START_DATE", "2026-09-14")
    return feed.Config()


def test_event_id_is_deterministic(profile):
    """Повтор пакета после таймаута не должен задваивать события.

    Интейк отбрасывает дубликаты по event_id, но только если ключ тот же -
    случайный uuid4 превратил бы защиту в украшение.
    """
    first = feed.build_case(profile, "B-777", date(2026, 9, 14), random.Random(5))
    again = feed.build_case(profile, "B-777", date(2026, 9, 14), random.Random(5))
    assert [e["event_id"] for e in first] == [e["event_id"] for e in again]

    # Разные кейсы - разные ключи.
    neighbour = feed.build_case(profile, "B-778", date(2026, 9, 14), random.Random(5))
    assert not set(e["event_id"] for e in first) & set(e["event_id"] for e in neighbour)


def test_repeated_activity_keeps_separate_ids(profile):
    """Одно и то же действие законно повторяется внутри кейса.

    В настоящем журнале «Приём продукции на склад» идёт дважды подряд 37 раз, и
    мутация умеет вставить второе «Распределение на устройство». Ключ считается
    от (case_id, номер шага, действие) - без номера шага повтор схлопнулся бы в
    один event_id, интейк счёл бы второе событие дубликатом и молча его выбросил,
    а кейс на карте стал бы короче, чем на самом деле.
    """
    rng = random.Random(5)
    for _ in range(300):
        events = feed.build_case(profile, "B-900", date(2026, 9, 14), rng)
        activities = [e["activity"] for e in events]
        if len(activities) != len(set(activities)):  # нашёлся кейс с повтором
            ids = [e["event_id"] for e in events]
            assert len(ids) == len(set(ids))
            return
    pytest.skip("кейс с повторяющимся действием не выпал за 300 попыток")


def test_a_day_is_never_spawned_twice(config, profile):
    """Такт идёт каждые полчаса - день должен заводиться ровно один раз.

    Без этого каждый запуск досыпал бы в те же сутки новую партию кейсов, и
    объём рос бы линейно по числу тактов, а не по календарю.
    """
    rng = random.Random(3)
    # Раннее утро: события этого дня ещё не наступили и целиком лежат в pending,
    # поэтому их видно и можно пересчитать.
    first = feed.tick(config, profile, rng, now=datetime(2026, 9, 14, 3, 0, tzinfo=timezone.utc))
    state = json.loads(config.state_path.read_text(encoding="utf-8"))
    cases_after_first = {e["case_id"] for e in state["pending"]}
    assert first["created_cases"] == len(cases_after_first) > 0

    second = feed.tick(config, profile, rng, now=datetime(2026, 9, 14, 3, 30, tzinfo=timezone.utc))
    state = json.loads(config.state_path.read_text(encoding="utf-8"))
    assert second["created_cases"] == 0, "тот же день заведён повторно"
    assert {e["case_id"] for e in state["pending"]} == cases_after_first


def test_weekend_produces_nothing(profile):
    """В профиле суббот и воскресений нет вовсе - цех по ним не работает.

    Генератор обязан молчать в эти дни, иначе демо покажет производство в
    выходной, чего у заказчика не бывает.
    """
    rng = random.Random(7)
    saturday, sunday = date(2026, 9, 19), date(2026, 9, 20)
    assert saturday.weekday() == 5 and sunday.weekday() == 6
    assert profile.cases_for(saturday, rng, 1.0) == 0
    assert profile.cases_for(sunday, rng, 1.0) == 0
    assert profile.cases_for(date(2026, 9, 16), rng, 1.0) > 0


def test_nothing_is_dated_in_the_future(config, profile):
    now = datetime(2026, 9, 18, 9, 30, tzinfo=timezone.utc)
    result = feed.tick(config, profile, random.Random(11), now=now)
    state = json.loads(config.state_path.read_text(encoding="utf-8"))
    assert result["due"] > 0
    for event in state["pending"]:
        assert event["_sort"] > now.timestamp(), "отложенное событие не может быть в прошлом"


def test_gap_stays_within_what_was_observed(profile):
    """Джиттер не должен выносить паузу за пределы наблюдавшегося максимума.

    Иначе застрявшая партия превращается в трёхсуточную при реальном потолке
    около 45 часов - и хвост распределения перестаёт быть правдой.
    """
    rng = random.Random(13)
    for transition, samples in list(profile.gap_samples.items())[:20]:
        prev, nxt = transition.split(" -> ")
        ceiling = max(samples) * 1.05
        for _ in range(200):
            assert profile.sample_gap(prev, nxt, rng) <= ceiling + 1e-6


def test_pause_file_stops_everything(config, profile):
    config.pause_file.parent.mkdir(parents=True, exist_ok=True)
    config.pause_file.touch()
    result = feed.tick(config, profile, random.Random(17),
                       now=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc))
    assert result == {"paused": True}
    assert not config.state_path.exists(), "на паузе состояние не трогается"


def test_disabled_by_default(monkeypatch, tmp_path):
    """Свежий клон репозитория не должен начать писать выдуманные события."""
    monkeypatch.delenv("DEMO_FEED_ENABLED", raising=False)
    monkeypatch.setenv("DEMO_FEED_RUNTIME_DIR", str(tmp_path))
    assert feed.Config().enabled is False


def test_csv_carries_the_contract_columns(profile):
    events = feed.build_case(profile, "B-42", date(2026, 9, 14), random.Random(19))
    header = feed.build_csv(events).splitlines()[0].split(",")
    assert header == feed.CSV_COLUMNS
    for required in ("event_id", "case_id", "activity", "timestamp"):
        assert required in header


def test_metadata_marks_the_row_synthetic(profile):
    """Строка должна сама о себе говорить, что она сгенерирована.

    Журнал отделён по source, но событие может уехать в выгрузку или в чей-то
    анализ отдельно от журнала, и тогда происхождение надо читать из него.
    """
    events = feed.build_case(profile, "B-43", date(2026, 9, 14), random.Random(23))
    for event in events:
        assert json.loads(event["metadata"])["synthetic"] is True
