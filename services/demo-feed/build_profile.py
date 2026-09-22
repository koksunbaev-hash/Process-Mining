"""Снимает профиль реального журнала: из чего потом генерировать демо.

Ничего не выдумывает - только считает распределения по выгруженным событиям.
Результат кладётся в profile.json рядом.
"""
import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
BATCH_LOG = "b5e7c062801e20a0e9a4"
ORDER_LOG = "3bf7465d64740a32ca08"


def load(log_id):
    with open(HERE / f"raw_{log_id}.json", encoding="utf-8") as fh:
        return json.load(fh)["items"]


def ts(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def profile_log(events, label):
    by_case = defaultdict(list)
    for ev in events:
        by_case[ev["case_id"]].append(ev)
    for case in by_case.values():
        case.sort(key=lambda e: ts(e["timestamp"]))

    activities = Counter(ev["activity"] for ev in events)
    resources = Counter(ev.get("resource") or "" for ev in events)
    # Ресурс зависит от действия: замес делает Миксер, выпечку - Печь. Общий
    # список сюда не годится, иначе в печи окажется формовщик.
    activity_resources = defaultdict(Counter)
    for ev in events:
        activity_resources[ev["activity"]][ev.get("resource") or ""] += 1
    products = Counter(
        ev["attributes"].get("product_name", "") for ev in events if ev["attributes"].get("product_name")
    )
    units = Counter(ev["attributes"].get("unit", "") for ev in events if ev["attributes"].get("unit"))

    # Атрибуты, которые сопровождают конкретное действие: from_stage, to_stage,
    # status, direction. Берём самый частый набор - генератор будет ставить его,
    # чтобы событие выглядело как настоящее, а не голой парой (case, activity).
    activity_attrs = {}
    for ev in events:
        a = ev["activity"]
        attrs = ev["attributes"]
        key = (
            attrs.get("from_stage", ""),
            attrs.get("to_stage", ""),
            attrs.get("status", ""),
            attrs.get("direction", ""),
        )
        activity_attrs.setdefault(a, Counter())[key] += 1

    # Маршруты: последовательность действий внутри кейса.
    variants = Counter(tuple(ev["activity"] for ev in case) for case in by_case.values())

    # Переходы и паузы между соседними событиями кейса.
    gaps = defaultdict(list)
    for case in by_case.values():
        for prev, nxt in zip(case, case[1:]):
            delta = (ts(nxt["timestamp"]) - ts(prev["timestamp"])).total_seconds()
            if delta >= 0:
                gaps[f"{prev['activity']} -> {nxt['activity']}"].append(delta)

    durations = []
    starts = []
    for case in by_case.values():
        first, last = ts(case[0]["timestamp"]), ts(case[-1]["timestamp"])
        durations.append((last - first).total_seconds())
        starts.append(first)

    # Ритм: сколько кейсов начинается в какой день недели и в какой час.
    dow = Counter(s.weekday() for s in starts)
    hour = Counter(s.hour for s in starts)
    per_day = Counter(s.date().isoformat() for s in starts)

    quantities = [
        float(ev["attributes"]["quantity"])
        for ev in events
        if ev["attributes"].get("quantity")
    ]

    def dist(values):
        if not values:
            return {}
        ordered = sorted(values)
        return {
            "n": len(ordered),
            "min": round(ordered[0], 2),
            "p25": round(ordered[len(ordered) // 4], 2),
            "median": round(statistics.median(ordered), 2),
            "p75": round(ordered[len(ordered) * 3 // 4], 2),
            "p90": round(ordered[int(len(ordered) * 0.90)], 2),
            "p95": round(ordered[int(len(ordered) * 0.95)], 2),
            "max": round(ordered[-1], 2),
            "mean": round(statistics.fmean(ordered), 2),
        }

    return {
        "label": label,
        "events": len(events),
        "cases": len(by_case),
        "span": [min(starts).isoformat(), max(ts(e["timestamp"]) for e in events).isoformat()],
        "activities": activities.most_common(),
        "activity_attrs": {
            a: [{"from_stage": k[0], "to_stage": k[1], "status": k[2], "direction": k[3], "n": n}
                for k, n in c.most_common(3)]
            for a, c in activity_attrs.items()
        },
        "resources": resources.most_common(),
        "activity_resources": {a: c.most_common() for a, c in activity_resources.items()},
        "products": products.most_common(),
        "units": units.most_common(),
        "variants": [{"trace": list(t), "n": n} for t, n in variants.most_common()],
        "variant_count": len(variants),
        "gaps": {k: dist(v) for k, v in sorted(gaps.items(), key=lambda kv: -len(kv[1]))},
        # Сами наблюдения, а не сводка: генератор берёт паузу бутстрэпом из
        # реальных значений. По сводке пришлось бы предполагать форму
        # распределения, а она тут заведомо не нормальная - половина переходов
        # мгновенная, у остальных длинный хвост.
        "gap_samples": {k: [round(x, 1) for x in v[:400]] for k, v in gaps.items()},
        "case_duration": dist(durations),
        "quantity": dist(quantities),
        "quantity_samples": [round(q, 1) for q in quantities[:600]],
        "cases_per_weekday": {str(d): dow.get(d, 0) for d in range(7)},
        "case_start_hour": {str(h): hour.get(h, 0) for h in range(24)},
        "cases_per_day": dict(sorted(per_day.items())),
    }


def main():
    out = {
        "batch": profile_log(load(BATCH_LOG), "batch"),
        "order": profile_log(load(ORDER_LOG), "order"),
    }
    (HERE / "profile.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    for key in ("batch", "order"):
        p = out[key]
        print(f"===== {key}: {p['events']} событий, {p['cases']} кейсов, {p['variant_count']} маршрутов")
        print(f"  период        {p['span'][0][:16]} .. {p['span'][1][:16]}")
        print(f"  длительность  медиана {p['case_duration']['median']/3600:.2f} ч, "
              f"p90 {p['case_duration']['p90']/3600:.2f} ч, max {p['case_duration']['max']/3600:.1f} ч")
        print("  по дням недели (0=пн):", p["cases_per_weekday"])
        busy = {h: n for h, n in p["case_start_hour"].items() if n}
        print("  часы старта:", busy)
        print("  действия:")
        for a, n in p["activities"]:
            print(f"    {n:5d}  {a}")
        print("  топ-5 маршрутов:")
        for v in p["variants"][:5]:
            print(f"    {v['n']:4d}x  {' -> '.join(v['trace'])[:110]}")
        print("  ресурсы:", p["resources"][:8])
        print("  продукты:", p["products"][:8])
        print()


if __name__ == "__main__":
    main()
