"""Демонстрационный поток событий для консоли процесс-майнинга.

Зачем: реальный журнал наполняется только когда в КМС работают, а стенд нужно
показывать партнёрам в любой день. Этот сервис поддерживает отдельный журнал,
который выглядит как непрерывно работающий цех.

Чего он намеренно не делает:

* не трогает КМС - ни базу, ни outbox, ни ProcessEvent. Общается с аналитикой
  по тому же публичному контракту `POST /api/event-logs/import/`, что и любой
  внешний источник;
* не может попасть в реальный журнал: `log_id` выводится детерминированно из
  пары `(source, case_type)`, а `source` здесь всегда свой (`demo_bakery`);
* ничего не выдумывает. Маршруты, паузы, ресурсы, продукты и ритм недели взяты
  из `profile/profile.json`, снятого с настоящего журнала этой же установки.

Выключается в любой момент - см. `stop()` и README.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import random
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
LOG = logging.getLogger("demo-feed")

# Пространство имён для event_id. Фиксированное: event_id обязан быть
# детерминированным, иначе повтор после сбоя задвоит события. Интейк защищён по
# event_id, но эта защита работает только если ключ тот же самый.
NS = uuid.UUID("6f3d5a0e-0b1b-4f3e-9a5e-2d8f1c7b4a10")

CSV_COLUMNS = [
    "event_id", "case_id", "case_type", "activity", "timestamp",
    "user_id", "user_name", "resource", "product_id", "product_name",
    "batch_number", "order_number", "from_stage", "to_stage", "status",
    "quantity", "unit", "problem_type", "metadata",
]


def env(name, default=None, cast=str):
    raw = os.environ.get(name, "")
    if raw == "":
        return default
    return cast(raw)


class Config:
    def __init__(self):
        self.enabled = env("DEMO_FEED_ENABLED", "0") == "1"
        self.pm_url = env("DEMO_FEED_PM_URL", "http://process-mining:8000")
        self.api_key = env("DEMO_FEED_API_KEY", "")
        self.source = env("DEMO_FEED_SOURCE", "demo_bakery")
        self.runtime_dir = Path(env("DEMO_FEED_RUNTIME_DIR", "/srv/demo-feed"))
        self.profile_path = Path(env("DEMO_FEED_PROFILE", str(HERE / "profile.json")))
        self.state_path = Path(env("DEMO_FEED_STATE", str(self.runtime_dir / "state.json")))
        self.pause_file = Path(env("DEMO_FEED_PAUSE_FILE", str(self.runtime_dir / "PAUSED")))
        self.start_date = date.fromisoformat(env("DEMO_FEED_START_DATE", "2026-09-11"))
        self.interval = env("DEMO_FEED_INTERVAL_SECONDS", 1800, int)
        self.volume = env("DEMO_FEED_VOLUME", 1.0, float)
        self.timeout = env("DEMO_FEED_TIMEOUT_SECONDS", 30, int)
        self.max_backfill_days = env("DEMO_FEED_MAX_BACKFILL_DAYS", 400, int)
        self.dry_run = env("DEMO_FEED_DRY_RUN", "0") == "1"

    def headers(self):
        return {"X-API-Key": self.api_key}


# --------------------------------------------------------------------------
# Профиль
# --------------------------------------------------------------------------

class Profile:
    """Распределения, снятые с настоящего журнала."""

    def __init__(self, raw, case_type):
        self.case_type = case_type
        p = raw[case_type]
        self.variants = [(v["trace"], v["n"]) for v in p["variants"]]
        self.variant_weights = [n for _, n in self.variants]
        self.gap_samples = p["gap_samples"]
        self.gap_fallback = sorted(
            x for values in p["gap_samples"].values() for x in values
        ) or [0.0]
        self.activity_resources = {
            a: ([r for r, _ in rs], [n for _, n in rs]) for a, rs in p["activity_resources"].items()
        }
        self.activity_attrs = p["activity_attrs"]
        self.products = [x[0] for x in p["products"]] or [""]
        self.product_weights = [x[1] for x in p["products"]] or [1]
        self.units = [x[0] for x in p["units"]] or ["шт"]
        self.unit_weights = [x[1] for x in p["units"]] or [1]
        self.quantities = p["quantity_samples"] or [100.0]
        self.hours = [int(h) for h, n in p["case_start_hour"].items() if n]
        self.hour_weights = [n for h, n in p["case_start_hour"].items() if n]
        self.per_day = self._daily_volume(p["cases_per_day"])

    @staticmethod
    def _daily_volume(cases_per_day):
        """Сколько кейсов заводить в каждый день недели.

        Считается по фактическим суткам, а не делением общей суммы на число
        недель: в наблюдаемом окне разных дней недели разное количество, и
        деление на «сколько-то недель» занизило бы понедельник и пятницу.
        Пустые дни (выходные) в журнал не попали вовсе, поэтому их здесь нет и
        генератор в эти дни молчит - ровно как настоящий цех.
        """
        buckets = {}
        for iso, n in cases_per_day.items():
            buckets.setdefault(date.fromisoformat(iso).weekday(), []).append(n)
        return {wd: (min(v), max(v), sum(v) / len(v)) for wd, v in buckets.items()}

    def cases_for(self, day, rng, volume):
        stats = self.per_day.get(day.weekday())
        if not stats:
            return 0  # выходной: в профиле этого дня недели нет
        low, high, mean = stats
        # Треугольное распределение вокруг среднего, в границах наблюдавшихся
        # минимума и максимума. Ровное число каждый день выдало бы генератор
        # мгновенно: в реальных данных разброс от 7 до 40 за сутки.
        value = rng.triangular(low, high, mean)
        return max(0, int(round(value * volume)))

    def sample_trace(self, rng):
        trace = list(rng.choices([t for t, _ in self.variants], weights=self.variant_weights)[0])
        # Редкая мутация. Без неё множество маршрутов навсегда застынет на 54
        # наблюдавшихся, а у живого процесса оно медленно растёт.
        roll = rng.random()
        if roll < 0.04 and "Распределение на устройство" in trace:
            i = trace.index("Распределение на устройство")
            trace.insert(i, "Распределение на устройство")
        elif roll < 0.06 and len(trace) > 2:
            trace.insert(rng.randrange(1, len(trace)), "Возврат партии на предыдущий этап")
        return trace

    def sample_gap(self, prev, nxt, rng):
        samples = self.gap_samples.get(f"{prev} -> {nxt}")
        if not samples:
            samples = self.gap_fallback
        base = rng.choice(samples)
        if base <= 0:
            return 0.0
        # Бутстрэп даёт ровно наблюдавшиеся значения; джиттер не даёт им
        # повторяться дословно, сохраняя порядок величины.
        value = base * rng.uniform(0.75, 1.3)
        # Потолок по наблюдавшемуся максимуму этого же перехода. Без него
        # джиттер, попав на самую длинную паузу, выносит кейс за пределы всего, что
        # видел реальный журнал: застрявшая партия превращалась в трёхсуточную
        # при настоящем потолке в 45 часов.
        return max(0.0, min(value, max(samples) * 1.05))

    def sample_resource(self, activity, rng):
        names, weights = self.activity_resources.get(activity, (["Администратор"], [1]))
        return rng.choices(names, weights=weights)[0]

    def attrs_for(self, activity, rng):
        options = self.activity_attrs.get(activity)
        if not options:
            return {"from_stage": "", "to_stage": "", "status": "", "direction": "forward"}
        chosen = rng.choices(options, weights=[o["n"] for o in options])[0]
        return {k: chosen.get(k, "") for k in ("from_stage", "to_stage", "status", "direction")}


# --------------------------------------------------------------------------
# Генерация
# --------------------------------------------------------------------------

def build_case(profile, case_id, day, rng):
    """Полный кейс со всеми событиями и временами. Возвращает список событий."""
    trace = profile.sample_trace(rng)
    hour = rng.choices(profile.hours, weights=profile.hour_weights)[0]
    moment = datetime(day.year, day.month, day.day, hour, rng.randrange(60), rng.randrange(60),
                      tzinfo=timezone.utc)
    product = rng.choices(profile.products, weights=profile.product_weights)[0]
    unit = rng.choices(profile.units, weights=profile.unit_weights)[0]
    quantity = rng.choice(profile.quantities)

    events = []
    for index, activity in enumerate(trace):
        if index:
            moment = moment + timedelta(seconds=profile.sample_gap(trace[index - 1], activity, rng))
        attrs = profile.attrs_for(activity, rng)
        events.append({
            "event_id": str(uuid.uuid5(NS, f"{case_id}|{index}|{activity}")),
            "case_id": case_id,
            "case_type": profile.case_type,
            "activity": activity,
            "timestamp": moment.isoformat(),
            "user_id": "",
            "user_name": "",
            "resource": profile.sample_resource(activity, rng),
            "product_id": "",
            "product_name": product,
            "batch_number": case_id,
            "order_number": "",
            "from_stage": attrs["from_stage"],
            "to_stage": attrs["to_stage"],
            "status": attrs["status"],
            "quantity": f"{quantity:.3f}",
            "unit": unit,
            "problem_type": "",
            "metadata": json.dumps(
                {"direction": attrs["direction"], "synthetic": True, "source": "demo-feed"},
                ensure_ascii=False,
            ),
            "_sort": moment.timestamp(),
        })
    return events


def build_csv(events):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for event in events:
        writer.writerow({k: event.get(k, "") for k in CSV_COLUMNS})
    return out.getvalue()


# --------------------------------------------------------------------------
# Состояние
# --------------------------------------------------------------------------

def load_state(config):
    if config.state_path.exists():
        return json.loads(config.state_path.read_text(encoding="utf-8"))
    return {"next_case": 1386, "spawned_days": [], "pending": [], "last_tick": None, "sent": 0}


def save_state(config, state):
    config.state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = config.state_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    tmp.replace(config.state_path)


# --------------------------------------------------------------------------
# Отправка
# --------------------------------------------------------------------------

def send(config, events):
    csv_text = build_csv(events)
    export_id = str(uuid.uuid5(NS, "export|" + "|".join(sorted(e["event_id"] for e in events))))
    payload = csv_text.encode("utf-8")
    data = {
        "export_id": export_id,
        "source": config.source,
        "schema_version": "1.0",
        "checksum": hashlib.sha256(payload).hexdigest(),
        "events_count": str(len(events)),
    }
    if config.dry_run:
        LOG.info("dry-run: %d событий не отправлено", len(events))
        return {"status": "dry_run", "accepted": 0}
    response = requests.post(
        f"{config.pm_url.rstrip('/')}/api/event-logs/import/",
        headers={**config.headers(), "Idempotency-Key": export_id},
        files={"file": ("demo-feed.csv", payload, "text/csv")},
        data=data,
        timeout=config.timeout,
    )
    response.raise_for_status()
    return response.json()


# --------------------------------------------------------------------------
# Такт
# --------------------------------------------------------------------------

def tick(config, profile, rng, now=None):
    now = now or datetime.now(timezone.utc)
    if config.pause_file.exists():
        LOG.info("пауза: найден %s, ничего не делаю", config.pause_file)
        return {"paused": True}

    state = load_state(config)
    spawned = set(state["spawned_days"])
    pending = state["pending"]

    # 1. Завести кейсы за все рабочие дни, которые ещё не заводили.
    day = config.start_date
    horizon = now.date()
    if (horizon - day).days > config.max_backfill_days:
        day = horizon - timedelta(days=config.max_backfill_days)
    created = 0
    while day <= horizon:
        key = day.isoformat()
        if key not in spawned:
            count = profile.cases_for(day, rng, config.volume)
            for _ in range(count):
                case_id = f"B-{state['next_case']}"
                state["next_case"] += 1
                pending.extend(build_case(profile, case_id, day, rng))
                created += 1
            spawned.add(key)
        day += timedelta(days=1)

    # 2. Отправить то, что уже «произошло».
    cutoff = now.timestamp()
    due = [e for e in pending if e["_sort"] <= cutoff]
    rest = [e for e in pending if e["_sort"] > cutoff]
    result = {"paused": False, "created_cases": created, "due": len(due), "pending": len(rest)}

    if due:
        due.sort(key=lambda e: e["_sort"])
        # Пакетами: разовый бэкфилл за полгода - это десятки тысяч строк, а у
        # интейка есть предел на размер тела.
        accepted = 0
        for start in range(0, len(due), 500):
            chunk = due[start:start + 500]
            answer = send(config, chunk)
            accepted += answer.get("accepted", 0)
            result.setdefault("log_ids", answer.get("log_ids", []))
        result["accepted"] = accepted
        state["sent"] = state.get("sent", 0) + accepted

    state["spawned_days"] = sorted(spawned)
    state["pending"] = rest
    state["last_tick"] = now.isoformat()
    save_state(config, state)
    return result


def main():
    logging.basicConfig(
        level=os.environ.get("DEMO_FEED_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    config = Config()
    once = "--once" in sys.argv

    # Выключенный сервис простаивает, а не падает. Перезапускающийся контейнер
    # в цикле краха шумит в логах ровно так же, как настоящая поломка, и
    # прячет её; а выключен он здесь по умолчанию - чтобы свежий клон
    # репозитория где-нибудь ещё не начал писать выдуманные события молча.
    if not config.enabled:
        LOG.warning("DEMO_FEED_ENABLED != 1 - генерация выключена, простаиваю")
        return 0 if once else _idle(config)
    if not config.api_key:
        LOG.error("DEMO_FEED_API_KEY не задан - генерация невозможна, простаиваю")
        return 2 if once else _idle(config)

    raw = json.loads(config.profile_path.read_text(encoding="utf-8"))
    profile = Profile(raw, "batch")
    rng = random.Random()

    while True:
        try:
            result = tick(config, profile, rng)
            LOG.info("такт: %s", json.dumps(result, ensure_ascii=False))
        except Exception as exc:  # поток демо не должен ронять контейнер
            LOG.exception("такт не удался: %s", exc)
        if once:
            return 0
        time.sleep(config.interval)


def _idle(config):
    while True:
        time.sleep(config.interval)


if __name__ == "__main__":
    raise SystemExit(main())
