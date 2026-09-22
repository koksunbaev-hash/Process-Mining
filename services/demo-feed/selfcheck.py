"""Сравнивает сгенерированный журнал с настоящим.

Критерий приёмки у генератора необычный: числа должны сойтись, но **не
совпасть**. Совпадение до третьего знака означало бы, что вместо распределения
копируются сами наблюдения, а такое видно в консоли с первого взгляда - карта
процесса и есть инструмент поиска повторов.

    python selfcheck.py <real_log_id> <demo_log_id>
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

PM_URL = os.environ.get("DEMO_FEED_PM_URL", "http://127.0.0.1:8001")
API_KEY = os.environ.get("DEMO_FEED_API_KEY", "")

# Во сколько раз демо может отличаться от оригинала, чтобы это считалось
# нормой. Хвост (p95, max) гуляет сильнее середины - это свойство самого
# распределения, а не генератора: на нём стоят единицы наблюдений.
TOLERANCE = {"median": 0.20, "mean": 0.20, "p90": 0.25, "p95": 0.40, "max": 0.50}
# Слишком точное совпадение - тоже отказ. Ниже этого порога расхождение
# подозрительно: значит генератор перестал сэмплировать и начал копировать.
TOO_EXACT = 0.002


def get(path):
    request = urllib.request.Request(PM_URL.rstrip("/") + path, headers={"X-API-Key": API_KEY})
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.load(response)


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    real, demo = (get(f"/api/v1/logs/{log_id}/statistics") for log_id in sys.argv[1:3])

    print(f"{'':<24} {'РЕАЛЬНЫЙ':>11} {'ДЕМО':>11}")
    print("-" * 48)
    for key in ("events", "cases", "activities", "variants", "resources"):
        print(f"{key:<24} {real[key]:>11} {demo[key]:>11}")

    print("-" * 48)
    problems = []
    for key, limit in TOLERANCE.items():
        a, b = real["throughput_seconds"][key], demo["throughput_seconds"][key]
        drift = abs(b - a) / a if a else 0.0
        mark = "ok"
        if drift > limit:
            mark, _ = "ВЕЛИКО", problems.append(f"{key}: разошлось на {drift*100:.0f}%")
        elif drift < TOO_EXACT:
            mark, _ = "СЛИШКОМ ТОЧНО", problems.append(f"{key}: совпало до {drift*100:.2f}%")
        print(f"{key + ', ч':<24} {a/3600:>11.2f} {b/3600:>11.2f}  {drift*100:+6.1f}%  {mark}")

    print("-" * 48)
    real_share = {a["activity"]: a["share_of_events"] for a in real["activity_stats"]}
    demo_share = {a["activity"]: a["share_of_events"] for a in demo["activity_stats"]}
    for activity in sorted(real_share, key=lambda x: -real_share[x]):
        gap = abs(demo_share.get(activity, 0) - real_share[activity]) * 100
        print(f"  {activity[:34]:<34} {real_share[activity]*100:>6.1f}% "
              f"{demo_share.get(activity, 0)*100:>7.1f}%  {gap:+5.1f}пп")
        if gap > 3:
            problems.append(f"доля «{activity}» разошлась на {gap:.1f} пп")

    unknown = set(demo_share) - set(real_share)
    if unknown:
        problems.append(f"в демо есть действия, которых нет в оригинале: {sorted(unknown)}")

    print()
    if problems:
        print("РАСХОЖДЕНИЯ:")
        for line in problems:
            print("  -", line)
        return 1
    print("Профиль воспроизводится: близко, но не дословно.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
