"""Аналитик: превращает журнал событий в выводы и русский текст.

Всё считается и пишется на месте, без внешних сервисов и без токенов - это
осознанное требование: сводка должна быть бесплатной и работать в контуре
завода. Числа берутся из тех же метрик, что и остальные экраны, аномалии -
устойчивой статистикой (медианы и квантили, не среднее: одно застрявшее
дело не должно сдвигать порог), а текст собирается из шаблонов.

Если когда-нибудь захочется языковую модель - заменить нужно только
``compose_digest``: вся аналитика от способа изложения не зависит.
"""

from __future__ import annotations

import statistics
from typing import Any

import pandas as pd

from . import metrics as metrics_mod
from . import model
from .mining import edge_duration_stats

# Ниже этого ожидание не считается аномалией, каким бы «непохожим» оно ни
# было: пятикратное отклонение от медианы в полминуты - это шум, а не событие.
ANOMALY_FLOOR_SECONDS = 300.0

# Во сколько раз дольше медианы должно ждать дело, чтобы попасть в сводку.
ANOMALY_RATIO = 3.0

# По скольким наблюдениям перехода вообще можно судить о «типичном» времени.
MIN_EDGE_SAMPLES = 5


# ------------------------------------------------------------------ числа

def analyze(frame: pd.DataFrame, *, anomaly_limit: int = 10) -> dict[str, Any]:
    """Все выводы по журналу одним словарём. Текст - отдельно, в compose_digest."""
    stats = metrics_mod.statistics_overview(frame)
    necks = metrics_mod.bottlenecks(frame, top_n=3)
    analysis = {
        "events": stats.get("events", 0),
        "cases": stats.get("cases", 0),
        "period": _period(frame),
        "throughput_seconds": stats.get("throughput_seconds", {}),
        "bottlenecks": necks.get("bottlenecks", []),
        "rework": necks.get("rework", []),
        "anomalies": find_anomalies(frame, limit=anomaly_limit),
        "trend": throughput_trend(stats.get("cases_per_day", {})),
        "busiest_resource": _busiest_resource(stats.get("resource_stats", [])),
    }
    return analysis


def find_anomalies(frame: pd.DataFrame, *, limit: int = 10) -> list[dict[str, Any]]:
    """Дела, которые ждали на переходе несравнимо дольше обычного.

    Порог - от медианы конкретного перехода, а не общий по журналу: у печи
    свои нормальные полчаса, у очереди - свои две минуты, и общая планка
    прятала бы аномалии быстрых этапов за спиной медленных.
    """
    if frame.empty:
        return []

    edges = edge_duration_stats(frame)
    ordered = frame.sort_values([model.CASE, model.TIMESTAMP], kind="stable")
    ordered = ordered.assign(
        next_activity=ordered.groupby(model.CASE, sort=False)[model.ACTIVITY].shift(-1),
        next_timestamp=ordered.groupby(model.CASE, sort=False)[model.TIMESTAMP].shift(-1),
    ).dropna(subset=["next_activity", "next_timestamp"])
    if ordered.empty:
        return []
    ordered = ordered.assign(
        waited=(ordered["next_timestamp"] - ordered[model.TIMESTAMP]).dt.total_seconds()
    )

    anomalies: list[dict[str, Any]] = []
    for row in ordered.itertuples(index=False):
        edge = edges.get((str(getattr(row, model.ACTIVITY)), str(row.next_activity)))
        if not edge or edge["count"] < MIN_EDGE_SAMPLES:
            continue
        typical = edge["median"]
        waited = float(row.waited)
        threshold = max(typical * ANOMALY_RATIO, edge["p95"], ANOMALY_FLOOR_SECONDS)
        if waited <= threshold or typical <= 0:
            continue
        anomalies.append({
            "case_id": str(getattr(row, model.CASE)),
            "source": str(getattr(row, model.ACTIVITY)),
            "target": str(row.next_activity),
            "waited_seconds": round(waited, 1),
            "typical_seconds": round(typical, 1),
            "ratio": round(waited / typical, 1),
            "when": getattr(row, model.TIMESTAMP).isoformat(),
        })
    anomalies.sort(key=lambda item: -item["ratio"])
    return anomalies[:limit]


def throughput_trend(cases_per_day: dict[str, int]) -> dict[str, Any] | None:
    """Последняя неделя против предыдущей. Меньше двух недель данных - молчим."""
    if not cases_per_day or len(cases_per_day) < 8:
        return None
    days = sorted(cases_per_day)
    last_week = sum(cases_per_day[d] for d in days[-7:])
    prev_days = days[-14:-7]
    prev_week = sum(cases_per_day[d] for d in prev_days)
    if not prev_week:
        return None
    return {
        "last_week": last_week,
        "prev_week": prev_week,
        "change_pct": round((last_week - prev_week) / prev_week * 100),
    }


def _period(frame: pd.DataFrame) -> dict[str, str]:
    if frame.empty:
        return {}
    return {
        "from": frame[model.TIMESTAMP].min().isoformat(),
        "to": frame[model.TIMESTAMP].max().isoformat(),
    }


def _busiest_resource(resource_stats: list[dict[str, Any]]) -> dict[str, Any] | None:
    real = [row for row in resource_stats if row.get("resource") not in ("", None, "nan")]
    if not real:
        return None
    top = max(real, key=lambda row: row.get("events", 0))
    return {"resource": top.get("resource"), "events": top.get("events", 0)}


# ------------------------------------------------------------------ текст

def humanize_seconds(value: float | None) -> str:
    if value is None:
        return "—"
    seconds = float(value)
    if seconds < 90:
        return f"{seconds:.0f} с"
    minutes = seconds / 60
    if minutes < 90:
        return f"{minutes:.0f} мин"
    hours = minutes / 60
    if hours < 36:
        whole = int(hours)
        rest = int(round((hours - whole) * 60))
        return f"{whole} ч {rest:02d} мин" if rest else f"{whole} ч"
    days = hours / 24
    return f"{days:.1f} дн"


def _plural(count: int, one: str, few: str, many: str) -> str:
    tail, teen = count % 10, count % 100
    if teen in range(11, 15):
        return many
    if tail == 1:
        return one
    if tail in (2, 3, 4):
        return few
    return many


def compose_digest(analysis: dict[str, Any]) -> list[str]:
    """Сводка по-русски: несколько абзацев, каждый - одна мысль.

    Пишет только о том, что видно в числах, и говорит «всё спокойно», когда
    это правда: пустой раздел честнее натянутого вывода.
    """
    cases = analysis.get("cases", 0)
    if cases < 3:
        return [
            "Данных пока мало: меньше трёх кейсов в журнале. Сводка появится, "
            "когда наберётся история, по которой можно судить о типичных временах."
        ]

    parts: list[str] = []

    throughput = analysis.get("throughput_seconds") or {}
    median = throughput.get("median")
    p95 = throughput.get("p95")
    opening = (
        f"В журнале {cases} {_plural(cases, 'кейс', 'кейса', 'кейсов')}. "
        f"Типичный проходит путь за {humanize_seconds(median)}"
    )
    if p95 and median and p95 > median * 1.3:
        opening += f", но каждый двадцатый растягивается до {humanize_seconds(p95)}"
    parts.append(opening + ".")

    necks = analysis.get("bottlenecks") or []
    if necks:
        top = necks[0]
        share = round((top.get("share_of_total_time") or 0) * 100)
        sentence = (
            f"Больше всего времени съедает переход «{top.get('source')} → {top.get('target')}»: "
            f"{share}% всего времени процесса, обычно {humanize_seconds(top.get('median_duration_seconds'))} на кейс"
        )
        if len(necks) > 1:
            second = necks[1]
            sentence += (
                f". Следом - «{second.get('source')} → {second.get('target')}» "
                f"({round((second.get('share_of_total_time') or 0) * 100)}%)"
            )
        parts.append(sentence + ". Если ускорять процесс, начинать стоит отсюда.")

    anomalies = analysis.get("anomalies") or []
    if anomalies:
        worst = anomalies[0]
        count = len(anomalies)
        sentence = (
            f"{count} {_plural(count, 'кейс ждал', 'кейса ждали', 'кейсов ждали')} "
            f"несравнимо дольше обычного. Хуже всех - «{worst['case_id']}»: "
            f"перед «{worst['target']}» он простоял {humanize_seconds(worst['waited_seconds'])} "
            f"при обычных {humanize_seconds(worst['typical_seconds'])} - в {worst['ratio']:g} раза дольше."
        )
        parts.append(sentence)
    else:
        parts.append(
            "Застрявших кейсов нет: никто не ждал на переходах дольше тройной медианы. Хороший знак."
        )

    rework = analysis.get("rework") or []
    if rework:
        top = rework[0]
        count = top.get("cases_with_rework", 0)
        parts.append(
            f"Этап «{top.get('activity')}» повторялся: {count} "
            f"{_plural(count, 'кейс проходил', 'кейса проходили', 'кейсов проходили')} его "
            "больше одного раза. Возвраты - обычно следствие брака или спешки, стоит посмотреть причины."
        )

    trend = analysis.get("trend")
    if trend:
        change = trend["change_pct"]
        if change >= 15:
            parts.append(
                f"Поток растёт: {trend['last_week']} кейсов за последнюю неделю против "
                f"{trend['prev_week']} за предыдущую (+{change}%)."
            )
        elif change <= -15:
            parts.append(
                f"Поток просел: {trend['last_week']} кейсов за последнюю неделю против "
                f"{trend['prev_week']} за предыдущую ({change}%)."
            )

    busiest = analysis.get("busiest_resource")
    if busiest and busiest.get("events"):
        parts.append(
            f"Самый нагруженный исполнитель - {busiest['resource']}: "
            f"{busiest['events']} {_plural(busiest['events'], 'событие', 'события', 'событий')}."
        )

    return parts
