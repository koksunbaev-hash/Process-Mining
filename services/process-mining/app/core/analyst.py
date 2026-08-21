"""Аналитик: превращает журнал событий в выводы и русский текст.

Всё считается и пишется на месте, без внешних сервисов и без токенов - это
осознанное требование: сводка должна быть бесплатной и работать в контуре
завода. Числа берутся из тех же метрик, что и остальные экраны, аномалии -
устойчивой статистикой (медианы и квантили, не среднее: одно застрявшее
дело не должно сдвигать порог), а текст собирается из шаблонов.

Языковая модель, если она настроена, меняет только изложение: ``narrate``
пересказывает ту же выжимку живее, чем ``compose_digest`` собирает её из
шаблонов. Числа она получает готовыми и журнала не видит - соврать про
партию ей не на чем. Модели нет или молчит - остаются шаблоны, и экран
выглядит ровно так же, как до неё.
"""

from __future__ import annotations

import statistics
from typing import Any

import pandas as pd

from . import llm
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

def humanize_seconds(value: float | None, lang: str = "ru") -> str:
    if value is None:
        return "—"
    units = UNITS.get(lang, UNITS["ru"])
    seconds = float(value)
    if seconds < 90:
        return f"{seconds:.0f} {units['s']}"
    minutes = seconds / 60
    if minutes < 90:
        return f"{minutes:.0f} {units['min']}"
    hours = minutes / 60
    if hours < 36:
        whole = int(hours)
        rest = int(round((hours - whole) * 60))
        return f"{whole} {units['h']} {rest:02d} {units['min']}" if rest else f"{whole} {units['h']}"
    days = hours / 24
    return f"{days:.1f} {units['d']}"


def _plural(count: int, one: str, few: str, many: str) -> str:
    tail, teen = count % 10, count % 100
    if teen in range(11, 15):
        return many
    if tail == 1:
        return one
    if tail in (2, 3, 4):
        return few
    return many


# Языки, на которых умеет говорить сервис. Всё, чего нет, - русский.
LANGUAGES = ("ru", "kk", "en")


def normalize_lang(value: str | None) -> str:
    """Код языка от консоли. Непонятное - русский, а не ошибка."""
    code = (value or "").strip().lower()[:2]
    return code if code in LANGUAGES else "ru"


# Шаблонная сводка на трёх языках. Ключ - роль предложения, а не его
# русский текст: у казахского другой порядок слов, и «перевод фразы»
# здесь превратился бы в перевод обрывков.
PHRASES: dict[str, dict[str, str]] = {
    "thin": {
        "ru": "Данных пока мало: меньше трёх кейсов в журнале. Сводка появится, "
              "когда наберётся история, по которой можно судить о типичных временах.",
        "kk": "Дерек әзірге аз: журналда үш кейстен де кем. Әдеттегі уақыттар туралы "
              "пікір айтуға болатын тарих жиналғанда түйіндеме пайда болады.",
        "en": "There is too little data: fewer than three cases in the log. The summary "
              "will appear once there is enough history to judge typical timings by.",
    },
    "opening": {
        "ru": "В журнале {cases} {word}. Типичный проходит путь за {median}",
        "kk": "Журналда {cases} {word}. Әдеттегісі жолды {median} ішінде өтеді",
        "en": "The log holds {cases} {word}. A typical one runs the path in {median}",
    },
    "opening_tail": {
        "ru": ", но каждый двадцатый растягивается до {p95}",
        "kk": ", бірақ жиырмадан біреуі {p95} дейін созылады",
        "en": ", but one in twenty stretches to {p95}",
    },
    "neck": {
        "ru": "Больше всего времени съедает переход «{source} → {target}»: {share}% всего "
              "времени процесса, обычно {median} на кейс",
        "kk": "Ең көп уақытты «{source} → {target}» ауысуы алады: процестің жалпы уақытының "
              "{share}%, әдетте бір кейске {median}",
        "en": "The transition “{source} → {target}” eats the most time: {share}% of the whole "
              "process, usually {median} per case",
    },
    "neck_second": {
        "ru": ". Следом - «{source} → {target}» ({share}%)",
        "kk": ". Одан кейін - «{source} → {target}» ({share}%)",
        "en": ". Next comes “{source} → {target}” ({share}%)",
    },
    "neck_advice": {
        "ru": ". Если ускорять процесс, начинать стоит отсюда.",
        "kk": ". Процесті жеделдететін болса, осы жерден бастаған жөн.",
        "en": ". If the process is to be sped up, this is where to start.",
    },
    "anomalies": {
        "ru": "{count} {word} несравнимо дольше обычного. Хуже всех - «{case}»: перед "
              "«{target}» он простоял {waited} при обычных {typical} - в {ratio} раза дольше.",
        "kk": "{count} {word} әдеттегіден өлшеусіз ұзақ күтті. Ең нашары - «{case}»: "
              "«{target}» алдында ол әдеттегі {typical} орнына {waited} тұрып қалды - {ratio} есе ұзақ.",
        "en": "{count} {word} waited far longer than usual. The worst is “{case}”: before "
              "“{target}” it stood {waited} against the usual {typical} — {ratio} times longer.",
    },
    "no_anomalies": {
        "ru": "Застрявших кейсов нет: никто не ждал на переходах дольше тройной медианы. "
              "Хороший знак.",
        "kk": "Кептеліп қалған кейс жоқ: ауысуларда ешкім үш медианадан ұзақ күткен жоқ. "
              "Бұл жақсы белгі.",
        "en": "Nothing is stuck: no case waited on a transition longer than three times the "
              "median. A good sign.",
    },
    "rework": {
        "ru": "Этап «{activity}» повторялся: {count} {word} его больше одного раза. Возвраты - "
              "обычно следствие брака или спешки, стоит посмотреть причины.",
        "kk": "«{activity}» кезеңі қайталанды: {count} {word} одан бірден көп рет өтті. "
              "Қайтарымдар әдетте ақау немесе асығыстықтан болады, себебін қараған жөн.",
        "en": "The stage “{activity}” repeated: {count} {word} went through it more than once. "
              "Rework usually follows defects or haste — the causes are worth a look.",
    },
    "trend_up": {
        "ru": "Поток растёт: {last} кейсов за последнюю неделю против {prev} за предыдущую (+{change}%).",
        "kk": "Ағын өсуде: соңғы аптада {last} кейс, алдыңғысында {prev} (+{change}%).",
        "en": "The flow is growing: {last} cases last week against {prev} the week before (+{change}%).",
    },
    "trend_down": {
        "ru": "Поток просел: {last} кейсов за последнюю неделю против {prev} за предыдущую ({change}%).",
        "kk": "Ағын төмендеді: соңғы аптада {last} кейс, алдыңғысында {prev} ({change}%).",
        "en": "The flow has dropped: {last} cases last week against {prev} the week before ({change}%).",
    },
    "busiest": {
        "ru": "Самый нагруженный исполнитель - {resource}: {events} {word}.",
        "kk": "Ең жүктелген орындаушы - {resource}: {events} {word}.",
        "en": "The busiest resource is {resource}: {events} {word}.",
    },
}

# Формы существительных при числе. В казахском форма одна - после
# числительного слово не меняется.
WORDS: dict[str, dict[str, tuple[str, ...]]] = {
    "case": {"ru": ("кейс", "кейса", "кейсов"), "kk": ("кейс",), "en": ("case", "cases")},
    "event": {"ru": ("событие", "события", "событий"), "kk": ("оқиға",), "en": ("event", "events")},
    "waited": {
        "ru": ("кейс ждал", "кейса ждали", "кейсов ждали"),
        "kk": ("кейс",),
        "en": ("case", "cases"),
    },
    "passed": {
        "ru": ("кейс проходил", "кейса проходили", "кейсов проходили"),
        "kk": ("кейс",),
        "en": ("case", "cases"),
    },
}

# Единицы длительности рядом с числом.
UNITS: dict[str, dict[str, str]] = {
    "ru": {"s": "с", "min": "мин", "h": "ч", "d": "дн"},
    "kk": {"s": "с", "min": "мин", "h": "сағ", "d": "күн"},
    "en": {"s": "s", "min": "min", "h": "h", "d": "d"},
}


def say(key: str, lang: str, **params) -> str:
    return PHRASES[key][lang].format(**params)


def word(key: str, count: int, lang: str) -> str:
    forms = WORDS[key][lang]
    if len(forms) == 1:
        return forms[0]
    if lang == "en":
        return forms[0] if abs(count) == 1 else forms[1]
    return _plural(count, *forms)


def compose_digest(analysis: dict[str, Any], lang: str = "ru") -> list[str]:
    """Сводка словами: несколько абзацев, каждый - одна мысль.

    Пишет только о том, что видно в числах, и говорит «всё спокойно», когда
    это правда: пустой раздел честнее натянутого вывода.
    """
    lang = normalize_lang(lang)
    cases = analysis.get("cases", 0)
    if cases < 3:
        return [say("thin", lang)]

    parts: list[str] = []

    throughput = analysis.get("throughput_seconds") or {}
    median = throughput.get("median")
    p95 = throughput.get("p95")
    opening = say(
        "opening", lang,
        cases=cases, word=word("case", cases, lang),
        median=humanize_seconds(median, lang),
    )
    if p95 and median and p95 > median * 1.3:
        opening += say("opening_tail", lang, p95=humanize_seconds(p95, lang))
    parts.append(opening + ".")

    necks = analysis.get("bottlenecks") or []
    if necks:
        top = necks[0]
        sentence = say(
            "neck", lang,
            source=top.get("source"), target=top.get("target"),
            share=round((top.get("share_of_total_time") or 0) * 100),
            median=humanize_seconds(top.get("median_duration_seconds"), lang),
        )
        if len(necks) > 1:
            second = necks[1]
            sentence += say(
                "neck_second", lang,
                source=second.get("source"), target=second.get("target"),
                share=round((second.get("share_of_total_time") or 0) * 100),
            )
        parts.append(sentence + say("neck_advice", lang))

    anomalies = analysis.get("anomalies") or []
    if anomalies:
        worst = anomalies[0]
        count = len(anomalies)
        parts.append(say(
            "anomalies", lang,
            count=count, word=word("waited", count, lang),
            case=worst["case_id"], target=worst["target"],
            waited=humanize_seconds(worst["waited_seconds"], lang),
            typical=humanize_seconds(worst["typical_seconds"], lang),
            ratio=f"{worst['ratio']:g}",
        ))
    else:
        parts.append(say("no_anomalies", lang))

    rework = analysis.get("rework") or []
    if rework:
        top = rework[0]
        count = top.get("cases_with_rework", 0)
        parts.append(say(
            "rework", lang,
            activity=top.get("activity"), count=count, word=word("passed", count, lang),
        ))

    trend = analysis.get("trend")
    if trend:
        change = trend["change_pct"]
        if change >= 15:
            parts.append(say("trend_up", lang, last=trend["last_week"],
                             prev=trend["prev_week"], change=change))
        elif change <= -15:
            parts.append(say("trend_down", lang, last=trend["last_week"],
                             prev=trend["prev_week"], change=change))

    busiest = analysis.get("busiest_resource")
    if busiest and busiest.get("events"):
        events = busiest["events"]
        parts.append(say("busiest", lang, resource=busiest["resource"],
                         events=events, word=word("event", events, lang)))

    return parts


# ------------------------------------------- тот же текст, но словами модели

# На каком языке просят ответ. Модель охотнее слушается, когда язык назван
# её же словами, а не кодом.
ANSWER_IN = {
    "ru": "по-русски",
    "kk": "по-казахски (қазақ тілінде)",
    "en": "in English",
}

NARRATOR_SYSTEM = (
    "Ты аналитик производства. Тебе дают готовую сводку показателей по журналу "
    "событий и просят изложить её {language} для сменного мастера.\n"
    "Правила:\n"
    "1. Используй только те числа, что даны. Ничего не досчитывай и не округляй "
    "заново - пиши длительности ровно так, как они записаны в сводке.\n"
    "2. Не выдумывай причин, которых не видно в данных. Можно осторожно "
    "предположить, но тогда так и скажи: «похоже», «стоит проверить».\n"
    "3. От трёх до пяти абзацев, каждый - одна мысль. Без списков, без "
    "заголовков, без разметки, без вступлений вроде «вот сводка».\n"
    "4. Спокойный рабочий тон. Если всё в порядке - так и напиши, "
    "не выдавливай тревогу из ровных чисел.\n"
    "5. Названия этапов, машин и номера дел не переводи: это надписи на "
    "оборудовании, человек ищет их глазами на экране."
)

# Модель может замолчать, поперхнуться разметкой или выдать пару слов. Всё это
# для нас одно и то же - «не получилось», и тогда работают шаблоны.
MIN_NARRATION_CHARS = 120


def brief(analysis: dict[str, Any], lang: str = "ru") -> str:
    """Выжимка для модели: только показатели, уже посчитанные и оформленные.

    Журнал модели не отдаём - ни целиком, ни кусками. Во-первых, он не влезет;
    во-вторых, пересказывая готовые числа, ошибиться в них труднее, чем
    считая их самой.
    """
    lines = [
        f"Кейсов в журнале: {analysis.get('cases', 0)}",
        f"Событий: {analysis.get('events', 0)}",
    ]
    period = analysis.get("period") or {}
    if period.get("from") and period.get("to"):
        lines.append(f"Период: с {period['from'][:16]} по {period['to'][:16]}")

    throughput = analysis.get("throughput_seconds") or {}
    if throughput.get("median") is not None:
        lines.append(
            f"Время прохождения кейса: медиана {humanize_seconds(throughput.get('median'), lang)}, "
            f"95-й процентиль {humanize_seconds(throughput.get('p95'), lang)}"
        )

    necks = analysis.get("bottlenecks") or []
    if necks:
        lines.append("Самые долгие переходы:")
        for item in necks[:3]:
            lines.append(
                f"  - «{item.get('source')} → {item.get('target')}»: "
                f"обычно {humanize_seconds(item.get('median_duration_seconds'), lang)} на кейс, "
                f"{round((item.get('share_of_total_time') or 0) * 100)}% всего времени процесса"
            )

    anomalies = analysis.get("anomalies") or []
    if anomalies:
        lines.append(f"Кейсов, ждавших ненормально долго: {len(anomalies)}. Худшие:")
        for item in anomalies[:3]:
            lines.append(
                f"  - кейс «{item['case_id']}» перед «{item['target']}» простоял "
                f"{humanize_seconds(item['waited_seconds'], lang)} при обычных "
                f"{humanize_seconds(item['typical_seconds'], lang)} (в {item['ratio']:g} раза дольше)"
            )
    else:
        lines.append("Застрявших кейсов нет: никто не ждал дольше тройной медианы перехода.")

    rework = analysis.get("rework") or []
    if rework:
        lines.append("Повторы этапов:")
        for item in rework[:3]:
            lines.append(
                f"  - «{item.get('activity')}» проходили больше одного раза "
                f"{item.get('cases_with_rework', 0)} кейсов"
            )
    else:
        lines.append("Повторных прохождений этапов не зафиксировано.")

    trend = analysis.get("trend")
    if trend:
        lines.append(
            f"Поток: {trend['last_week']} кейсов за последнюю неделю против "
            f"{trend['prev_week']} за предыдущую ({trend['change_pct']:+d}%)"
        )

    busiest = analysis.get("busiest_resource")
    if busiest and busiest.get("events"):
        lines.append(
            f"Самый нагруженный исполнитель: {busiest['resource']}, {busiest['events']} событий"
        )

    return "\n".join(lines)


def narrate(settings, analysis: dict[str, Any], lang: str = "ru") -> list[str] | None:
    """Сводка словами модели. None - значит модель не помогла, берём шаблоны."""
    if analysis.get("cases", 0) < 3:
        # Про два кейса и шаблону сказать нечего, и модели тем более.
        return None

    lang = normalize_lang(lang)
    text = llm.say(
        settings,
        NARRATOR_SYSTEM.format(language=ANSWER_IN[lang]),
        "Сводка показателей:\n\n" + brief(analysis, lang)
        + "\n\nИзложи это для сменного мастера " + ANSWER_IN[lang] + ".",
    )
    if not text or len(text) < MIN_NARRATION_CHARS:
        return None
    paragraphs = [line.strip(" \t*#-") for line in text.split("\n")]
    return [line for line in paragraphs if line] or None
