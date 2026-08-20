"""Аналитик: выводы из журнала и сводка по-русски.

Проверяется не «функция вернула словарь», а то, ради чего она написана:
застрявший кейс должен попасть в аномалии, спокойный журнал - не должен
рождать выдуманных находок, а текст - говорить о том, что видно в числах.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from app.core import analyst, model


def frame_from(rows: list[tuple[str, str, datetime]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {model.CASE: case, model.ACTIVITY: activity, model.TIMESTAMP: stamp, model.RESOURCE: "смена"}
            for case, activity, stamp in rows
        ]
    )


STEPS = ["Очередь", "Замес", "Формовка", "Печь", "Готово"]


def steady_log(cases: int = 12, *, stuck_case: int | None = None, stuck_seconds: int = 7200):
    """Ровный поток, в котором один кейс может застрять перед печью."""
    base = datetime(2026, 8, 1, 8, 0)
    rows: list[tuple[str, str, datetime]] = []
    for index in range(cases):
        moment = base + timedelta(days=index % 10, minutes=index)
        for step_no, activity in enumerate(STEPS):
            waited = 600
            if stuck_case is not None and index == stuck_case and step_no == 3:
                waited = stuck_seconds
            moment = moment + timedelta(seconds=waited)
            rows.append((f"B-{1100 + index}", activity, moment))
    return frame_from(rows)


class TestAnomalies:
    def test_a_stuck_case_is_found(self):
        """Кейс, простоявший перед печью два часа при обычных десяти минутах."""
        found = analyst.find_anomalies(steady_log(stuck_case=5))

        assert found, "застрявший кейс должен попасть в аномалии"
        assert found[0]["case_id"] == "B-1105"
        assert found[0]["target"] == "Печь"
        assert found[0]["ratio"] >= analyst.ANOMALY_RATIO

    def test_a_steady_log_has_none(self):
        """Ровный поток не должен рождать находок: пустой раздел честнее
        натянутого вывода."""
        assert analyst.find_anomalies(steady_log()) == []

    def test_short_waits_are_not_anomalies(self):
        """Пятикратное отклонение от медианы в полминуты - шум, а не событие."""
        base = datetime(2026, 8, 1, 8, 0)
        rows = []
        for index in range(10):
            moment = base + timedelta(hours=index)
            for step_no, activity in enumerate(STEPS):
                moment += timedelta(seconds=120 if not (index == 3 and step_no == 2) else 240)
                rows.append((f"C-{index}", activity, moment))

        assert analyst.find_anomalies(frame_from(rows)) == []

    def test_rare_transitions_are_left_alone(self):
        """По одному наблюдению нельзя судить о «типичном» времени."""
        base = datetime(2026, 8, 1, 8, 0)
        rows = [
            ("X-1", "Начало", base),
            ("X-1", "Редкий шаг", base + timedelta(hours=9)),
        ]
        assert analyst.find_anomalies(frame_from(rows)) == []

    def test_an_empty_log_is_handled(self):
        assert analyst.find_anomalies(pd.DataFrame()) == []


class TestDigest:
    def test_it_names_the_stuck_case_and_the_bottleneck(self):
        analysis = analyst.analyze(steady_log(stuck_case=5))
        digest = analyst.compose_digest(analysis)
        text = " ".join(digest)

        assert "B-1105" in text, "сводка должна назвать застрявший кейс"
        assert "12 кейсов" in text
        assert "времени" in text, "должна быть фраза про узкое место"

    def test_a_calm_log_says_so_plainly(self):
        digest = analyst.compose_digest(analyst.analyze(steady_log()))
        text = " ".join(digest)

        assert "Застрявших кейсов нет" in text
        assert "B-11" not in text, "не выдумывать кейсы там, где их нет"

    def test_too_little_data_is_admitted(self):
        """Три кейса - не статистика, и делать вид, что это она, нельзя."""
        digest = analyst.compose_digest(analyst.analyze(steady_log(cases=2)))

        assert len(digest) == 1
        assert "мало" in digest[0]

    def test_every_paragraph_is_a_finished_sentence(self):
        digest = analyst.compose_digest(analyst.analyze(steady_log(stuck_case=5)))

        assert digest
        for paragraph in digest:
            assert paragraph.strip().endswith("."), paragraph


class TestHumanize:
    @pytest.mark.parametrize(
        "seconds,expected",
        [(45, "45 с"), (600, "10 мин"), (7200, "2 ч"), (9000, "2 ч 30 мин"), (None, "—")],
    )
    def test_durations_read_like_speech(self, seconds, expected):
        assert analyst.humanize_seconds(seconds) == expected

    def test_plural_follows_russian_grammar(self):
        cases = [(1, "кейс"), (2, "кейса"), (5, "кейсов"), (11, "кейсов"), (21, "кейс")]
        for count, expected in cases:
            assert analyst._plural(count, "кейс", "кейса", "кейсов") == expected


class TestEndpoint:
    def test_the_route_returns_digest_and_analysis(self, client, sample_events):
        created = client.post(
            "/api/v1/logs",
            json={"name": "bakery", "events": sample_events, "mapping_profile": "bakery"},
        )
        assert created.status_code == 201, created.text
        log_id = created.json()["log_id"]

        response = client.get(f"/api/v1/logs/{log_id}/analyst")
        assert response.status_code == 200, response.text

        payload = response.json()
        assert payload["log_id"] == log_id
        assert isinstance(payload["digest"], list) and payload["digest"]
        assert "anomalies" in payload["analysis"]
        assert "bottlenecks" in payload["analysis"]

    def test_it_needs_the_api_key(self, client):
        bare = client.get("/api/v1/logs/nope/analyst", headers={"X-API-Key": "wrong"})
        assert bare.status_code in (401, 403)
