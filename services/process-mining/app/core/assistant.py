"""Ассистент: вопрос по-русски - ответ.

Вопросов бывает два рода, и помощник отвечает на оба.

Про **загруженный журнал** - «где теряем время», «что с делом 1042» - он
отвечает через инструменты. Модель журнала не видит и читать его не умеет;
она умеет спросить: покажи узкие места, покажи путь дела. Каждый такой
вопрос - функция ниже, обычный запрос к таблице. Почему так, а не «отдать
журнал целиком»: журнал не влезет, а если резать его на куски, модель
начнёт считать сама - и ошибётся. Пусть считает pandas.

Про **сам предмет** - что такое process mining, что значит fitness, чем
DFG отличается от сети Петри - он отвечает своими знаниями, без всяких
инструментов. Это не отступление от правила «числа считает сервис»:
определение - не число, и ходить за ним в журнал некуда.

Инструменты только читают. Ни один из них ничего не меняет, не удаляет и не
ходит наружу: худшее, что может сделать модель, - задать неудачный вопрос и
получить пустой ответ.
"""

from __future__ import annotations

import difflib
import json
import logging
import statistics
from typing import Any, Callable

import pandas as pd

from . import analyst as analyst_mod
from . import llm
from . import metrics as metrics_mod
from . import model

logger = logging.getLogger(__name__)

# Сколько раз модель может сходить к данным за один вопрос. Хватает на
# «посмотри общее - потом уточни деталь - потом сравни»; дальше начинается
# хождение по кругу, за которое платит ожидающий человек.
MAX_STEPS = 5

# Сколько строк отдавать наружу в списках. Не ограничение модели, а защита от
# журнала на сто тысяч дел: длинный ответ она всё равно пересказывает первыми
# пятью строками.
MAX_ROWS = 20

SYSTEM = (
    "Ты помощник в консоли анализа процессов (process mining). Вопросы бывают "
    "двух родов, и путать их не надо.\n"
    "\n"
    "ПРО ЗАГРУЖЕННЫЙ ЖУРНАЛ - «где теряем время», «что с делом 1042», «какой "
    "этап повторяется». Числа для таких ответов бери функциями. Не помнишь, "
    "не видел, не уверен - спроси данные, а не выдумывай. Чего в журнале не "
    "видно, о том так и скажи: это нормальный ответ, лучше выдуманного.\n"
    "\n"
    "ПРО САМ ПРЕДМЕТ - что такое process mining, что значит fitness, чем DFG "
    "отличается от сети Петри, как читать узкое место, зачем нужны варианты "
    "маршрутов, что делать с найденными возвратами. Отвечай своими знаниями, "
    "спокойно и по существу. Функции тут не нужны, и приплетать числа этого "
    "журнала к определению не надо, если о них не спросили. Где уместно, "
    "поясняй на том, что человек видит в консоли.\n"
    "\n"
    "СЛОВАРЬ КОНСОЛИ - так эти вещи называются на экране, объясняй их этими "
    "же словами:\n"
    "- дело (кейс) - один проход процесса от начала до конца, со своим номером;\n"
    "- этап (активность) - шаг процесса, одна строка журнала;\n"
    "- маршрут (вариант) - последовательность этапов, которой прошло дело;\n"
    "- DFG, directly-follows graph - карта «что за чем шло» по журналу;\n"
    "- узкое место - переход между этапами, съедающий больше всего времени;\n"
    "- возврат (rework) - повторное прохождение этапа внутри одного дела;\n"
    "- fitness - насколько журнал укладывается в модель, precision - насколько "
    "модель не разрешает лишнего.\n"
    "\n"
    "ЧТО УМЕЕТ КОНСОЛЬ - на случай вопросов «а где это посмотреть»: строит "
    "модель по журналу (DFG, сеть Петри, дерево процесса, BPMN), считает "
    "показатели и маршруты, ищет узкие места, возвраты и застрявшие дела, "
    "проверяет соответствие журнала построенной модели (fitness и precision). "
    "Модель она выводит из журнала сама - загрузить в неё чужую эталонную "
    "схему для сравнения нельзя.\n"
    "\n"
    "ОБЩЕЕ:\n"
    "- Отвечай {language}, о чём бы ни спрашивали и на каком бы языке ни "
    "спросили. Коротко, но не в ущерб делу: определение - два-три "
    "предложения, разбор - несколько абзацев. Без разметки и списков-звёздочек.\n"
    "- Длительности пиши так, как их вернула функция.\n"
    "- Названия этапов, машин и номера дел не переводи: это надписи на "
    "оборудовании, человек ищет их глазами на экране.\n"
    "- Функции отвечают по-русски - это внутренний язык данных, а не язык "
    "ответа. Пересказывай их содержимое {language}.\n"
    "- Не выдумывай возможностей консоли, которых не знаешь: лучше сказать, "
    "что не уверен, где это искать."
)

# Без журнала инструменты не из чего вызывать, и модель надо об этом
# предупредить: иначе она пообещает посмотреть данные, которых нет.
NO_LOG = (
    "\n\nСЕЙЧАС ЖУРНАЛ НЕ ЗАГРУЖЕН: функций к данным нет. На вопросы о "
    "предмете отвечай как обычно, а если спрашивают про цифры - скажи, что "
    "для этого нужно загрузить журнал событий."
)


# --------------------------------------------------------------- инструменты

def _fmt(seconds: float | None) -> str | None:
    return analyst_mod.humanize_seconds(seconds) if seconds is not None else None


def _match_activity(frame: pd.DataFrame, name: str) -> str | None:
    """Название этапа на глазок: человек пишет «печь», в журнале «Выпечка».

    Сначала точное совпадение, потом вхождение, потом близость по буквам.
    Не нашли - честное None: чужой этап хуже, чем «такого этапа нет».
    """
    known = [str(v) for v in frame[model.ACTIVITY].dropna().unique()]
    if not known:
        return None
    wanted = (name or "").strip().lower()
    if not wanted:
        return None
    for item in known:
        if item.lower() == wanted:
            return item
    contains = [item for item in known if wanted in item.lower()]
    if len(contains) == 1:
        return contains[0]
    close = difflib.get_close_matches(wanted, [i.lower() for i in known], n=1, cutoff=0.7)
    if close:
        return next(item for item in known if item.lower() == close[0])
    return contains[0] if contains else None


def tool_overview(frame: pd.DataFrame) -> dict[str, Any]:
    stats = metrics_mod.statistics_overview(frame, top_n=10)
    throughput = stats.get("throughput_seconds") or {}
    return {
        "события": stats.get("events", 0),
        "дела": stats.get("cases", 0),
        "этапы": stats.get("activities", 0),
        "исполнители": stats.get("resources", 0),
        "маршруты": stats.get("variants", 0),
        "время_дела": {
            "медиана": _fmt(throughput.get("median")),
            "среднее": _fmt(throughput.get("mean")),
            "самое_быстрое": _fmt(throughput.get("min")),
            "самое_долгое": _fmt(throughput.get("max")),
            "95_процентиль": _fmt(throughput.get("p95")),
        },
        "самые_частые_этапы": [
            {"этап": row["activity"], "событий": row["occurrences"], "дел": row["cases"]}
            for row in (stats.get("activity_stats") or [])[:10]
        ],
    }


def tool_bottlenecks(frame: pd.DataFrame, limit: int = 5) -> dict[str, Any]:
    found = metrics_mod.bottlenecks(frame, top_n=min(int(limit or 5), MAX_ROWS))
    return {
        "переходы": [
            {
                "откуда": row.get("source"),
                "куда": row.get("target"),
                "обычно": _fmt(row.get("median_duration_seconds")),
                "доля_времени_процесса": f"{round((row.get('share_of_total_time') or 0) * 100)}%",
                "случаев": row.get("occurrences"),
            }
            for row in (found.get("bottlenecks") or [])
        ],
        "повторы_этапов": [
            {"этап": row.get("activity"), "дел_с_повтором": row.get("cases_with_rework")}
            for row in (found.get("rework") or [])[:MAX_ROWS]
        ],
    }


def tool_anomalies(frame: pd.DataFrame, limit: int = 5) -> dict[str, Any]:
    found = analyst_mod.find_anomalies(frame, limit=min(int(limit or 5), MAX_ROWS))
    if not found:
        return {
            "застрявшие_дела": [],
            "пояснение": "никто не ждал дольше тройной медианы перехода",
        }
    return {
        "застрявшие_дела": [
            {
                "дело": row["case_id"],
                "перед_этапом": row["target"],
                "ждало": _fmt(row["waited_seconds"]),
                "обычно": _fmt(row["typical_seconds"]),
                "во_сколько_раз_дольше": row["ratio"],
                "когда": row["when"][:16],
            }
            for row in found
        ]
    }


def tool_activity(frame: pd.DataFrame, name: str) -> dict[str, Any]:
    matched = _match_activity(frame, name)
    if matched is None:
        known = [str(v) for v in frame[model.ACTIVITY].dropna().unique()][:MAX_ROWS]
        return {"ошибка": f"этапа «{name}» в журнале нет", "известные_этапы": known}
    stats = metrics_mod.statistics_overview(frame, top_n=1000)
    row = next(
        (item for item in stats.get("activity_stats", []) if item["activity"] == matched), None
    )
    if row is None:
        return {"ошибка": f"по этапу «{matched}» нет статистики"}
    subset = frame[frame[model.ACTIVITY] == matched]
    resources = (
        subset[model.RESOURCE].dropna().value_counts().head(10).to_dict()
        if subset[model.RESOURCE].notna().any()
        else {}
    )
    return {
        "этап": matched,
        "событий": row["occurrences"],
        "дел": row["cases"],
        "доля_событий": f"{round(row['share_of_events'] * 100)}%",
        "среднее_ожидание_после": _fmt(row.get("mean_waiting_after_seconds")),
        "впервые": row["first_seen"][:16],
        "последний_раз": row["last_seen"][:16],
        "исполнители": {str(k): int(v) for k, v in resources.items()},
    }


def tool_resources(frame: pd.DataFrame, limit: int = 10) -> dict[str, Any]:
    stats = metrics_mod.statistics_overview(frame, top_n=MAX_ROWS)
    rows = [
        row
        for row in stats.get("resource_stats", [])
        if row.get("resource") not in ("", None, "nan")
    ]
    if not rows:
        return {"исполнители": [], "пояснение": "в журнале не указаны исполнители"}
    return {
        "исполнители": [
            {
                "исполнитель": row["resource"],
                "событий": row["events"],
                "дел": row["cases"],
                "этапов": row["activities"],
            }
            for row in rows[: min(int(limit or 10), MAX_ROWS)]
        ]
    }


def tool_case(frame: pd.DataFrame, case_id: str) -> dict[str, Any]:
    wanted = str(case_id).strip()
    subset = frame[frame[model.CASE].astype(str) == wanted]
    if subset.empty:
        # Часто промахиваются в форматировании номера, а не в самом номере.
        similar = difflib.get_close_matches(
            wanted, [str(v) for v in frame[model.CASE].astype(str).unique()], n=5, cutoff=0.6
        )
        return {"ошибка": f"дела «{case_id}» в журнале нет", "похожие_номера": similar}
    subset = subset.sort_values(model.TIMESTAMP, kind="stable")
    started = subset[model.TIMESTAMP].min()
    finished = subset[model.TIMESTAMP].max()
    steps = []
    previous = None
    for row in subset.head(50).itertuples(index=False):
        stamp = getattr(row, model.TIMESTAMP)
        resource = getattr(row, model.RESOURCE, None)
        steps.append(
            {
                "этап": str(getattr(row, model.ACTIVITY)),
                "когда": stamp.isoformat()[:16],
                "исполнитель": None if pd.isna(resource) else str(resource),
                "ждало_до_этого": _fmt((stamp - previous).total_seconds()) if previous else None,
            }
        )
        previous = stamp
    return {
        "дело": wanted,
        "событий": int(len(subset)),
        "начало": started.isoformat()[:16],
        "конец": finished.isoformat()[:16],
        "всего_заняло": _fmt((finished - started).total_seconds()),
        "путь": steps,
        "путь_обрезан": bool(len(subset) > 50),
    }


def tool_variants(frame: pd.DataFrame, limit: int = 5) -> dict[str, Any]:
    found = metrics_mod.variants(frame, limit=min(int(limit or 5), MAX_ROWS))
    return {
        "всего_маршрутов": found.get("total_variants", 0),
        "маршруты": [
            {
                "путь": " → ".join(item["sequence"]),
                "дел": item["cases"],
                "доля": f"{round(item['share'] * 100)}%",
                "обычно_занимает": _fmt(item.get("median_duration_seconds")),
                "например_дела": item.get("example_case_ids", [])[:3],
            }
            for item in found.get("items", [])
        ],
    }


def tool_slowest_cases(frame: pd.DataFrame, limit: int = 5) -> dict[str, Any]:
    durations = metrics_mod.case_durations(frame)
    if durations.empty:
        return {"дела": []}
    count = min(int(limit or 5), MAX_ROWS)
    ordered = durations.sort_values(ascending=False).head(count)
    median = float(statistics.median(durations.tolist()))
    return {
        "медиана_по_журналу": _fmt(median),
        "дела": [
            {"дело": str(case), "заняло": _fmt(float(value))} for case, value in ordered.items()
        ],
    }


TOOLS: dict[str, Callable[..., dict[str, Any]]] = {
    "overview": tool_overview,
    "bottlenecks": tool_bottlenecks,
    "anomalies": tool_anomalies,
    "activity": tool_activity,
    "resources": tool_resources,
    "case": tool_case,
    "variants": tool_variants,
    "slowest_cases": tool_slowest_cases,
}

# Описания видит модель и по ним решает, куда идти. Поэтому они по-русски и
# написаны как подсказка коллеге, а не как строка документации.
TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "overview",
            "description": "Общая картина по журналу: сколько дел и событий, "
            "сколько занимает типичное дело, какие этапы встречаются чаще.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bottlenecks",
            "description": "Самые долгие переходы между этапами и повторы этапов. "
            "Отсюда начинают, когда спрашивают «где теряем время».",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "сколько строк, по умолчанию 5"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "anomalies",
            "description": "Дела, которые ждали на переходе несравнимо дольше обычного - "
            "то есть застряли. Пустой ответ означает, что застрявших нет.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "сколько дел, по умолчанию 5"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "activity",
            "description": "Всё про один этап: сколько раз проходили, в скольких делах, "
            "сколько ждут после него, кто выполнял. Название можно неточное.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "название этапа"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resources",
            "description": "Исполнители и машины: кто сколько событий и дел провёл.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "сколько строк, по умолчанию 10"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "case",
            "description": "Путь одного дела: этапы по порядку, время каждого, "
            "исполнители и сколько ждали перед каждым шагом.",
            "parameters": {
                "type": "object",
                "properties": {"case_id": {"type": "string", "description": "номер дела"}},
                "required": ["case_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "variants",
            "description": "Частые маршруты: какими путями дела проходят процесс и "
            "как часто каждый путь встречается.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "сколько маршрутов, по умолчанию 5"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "slowest_cases",
            "description": "Самые долгие дела журнала с их длительностью и медианой для сравнения.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "сколько дел, по умолчанию 5"}
                },
            },
        },
    },
]


# Что говорит сам сервис, когда модель не при чём: она не настроена, молчит
# или ходит по кругу. Это не её текст, и переводить его ей незачем.
SERVICE_TEXT: dict[str, dict[str, str]] = {
    "not_configured": {
        "ru": "Помощник не настроен: в сервисе не указана языковая модель.",
        "kk": "Көмекші бапталмаған: сервисте тілдік модель көрсетілмеген.",
        "en": "The assistant is not configured: no language model is set for the service.",
    },
    "ask_something": {
        "ru": "Задайте вопрос по журналу.",
        "kk": "Журнал бойынша сұрақ қойыңыз.",
        "en": "Ask a question about the log.",
    },
    "unavailable": {
        "ru": "Модель сейчас недоступна. Числа и графики на других вкладках работают.",
        "kk": "Модель қазір қолжетімсіз. Басқа беттердегі сандар мен графиктер жұмыс істеп тұр.",
        "en": "The model is unavailable right now. Numbers and charts on the other tabs still work.",
    },
    "empty": {
        "ru": "Не удалось составить ответ - попробуйте спросить иначе.",
        "kk": "Жауап құрастыру мүмкін болмады - басқаша сұрап көріңіз.",
        "en": "Could not put together an answer — try asking differently.",
    },
    "looped": {
        "ru": "Не получилось собрать ответ за отведённые шаги. Попробуйте спросить конкретнее.",
        "kk": "Берілген қадамдарда жауап жинақталмады. Нақтырақ сұрап көріңіз.",
        "en": "Could not assemble an answer within the allowed steps. Try asking more precisely.",
    },
}


def call_tool(frame: pd.DataFrame, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Выполнить один инструмент. Любая осечка - это данные, а не исключение.

    Модель ошибается в имени или в аргументах примерно так же часто, как
    человек, и точно так же поправляется, увидев ответ «такого нет». Ронять
    из-за этого весь запрос незачем.
    """
    handler = TOOLS.get(name)
    if handler is None:
        return {"ошибка": f"нет такого инструмента: {name}", "доступные": sorted(TOOLS)}
    try:
        return handler(frame, **(arguments or {}))
    except TypeError as exc:
        return {"ошибка": f"неверные аргументы для {name}: {exc}"}
    except Exception as exc:  # pragma: no cover - защита от неожиданного
        logger.warning("Ассистент: инструмент %s упал (%s)", name, exc)
        return {"ошибка": f"инструмент {name} не смог ответить"}


def _arguments_of(call: dict[str, Any]) -> dict[str, Any]:
    raw = (call.get("function") or {}).get("arguments")
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw or "{}")
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def ask(
    settings,
    frame: pd.DataFrame | None,
    question: str,
    history: list[dict[str, str]] | None = None,
    lang: str = "ru",
) -> dict[str, Any]:
    """Ответ на вопрос. Журнала может и не быть - тогда отвечаем по предмету.

    Возвращает и сам ответ, и список сделанных запросов к данным: человеку
    полезно видеть, откуда взялось число, а нам - что модель вообще ходила за
    данными, а не сочиняла. Пустой список у вопроса про цифры - повод не
    верить ответу; у вопроса «что такое process mining» - норма.
    """
    lang = analyst_mod.normalize_lang(lang)
    told = lambda key: SERVICE_TEXT[key][lang]

    if not llm.configured(settings):
        return {"available": False, "answer": told("not_configured"), "steps": []}
    if not (question or "").strip():
        return {"available": True, "answer": told("ask_something"), "steps": []}

    has_log = frame is not None and not frame.empty
    system = SYSTEM.format(language=analyst_mod.ANSWER_IN[lang])
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system if has_log else system + NO_LOG}
    ]
    for turn in (history or [])[-6:]:
        role = turn.get("role")
        content = (turn.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": question.strip()})

    steps: list[dict[str, Any]] = []
    for _ in range(MAX_STEPS):
        # Размышление выключено намеренно: у Qwen в vLLM включённое съедает
        # лимит вывода и возвращает пустой ответ. Проверено на живой модели.
        message = llm.chat(
            settings, messages, tools=TOOL_SPECS if has_log else None, thinking=False
        )
        if message is None:
            return {"available": False, "answer": told("unavailable"), "steps": steps}
        calls = message.get("tool_calls") or []
        if not calls:
            answer = (message.get("content") or "").strip()
            return {"available": True, "answer": answer or told("empty"), "steps": steps}

        messages.append(message)
        for call in calls:
            name = (call.get("function") or {}).get("name") or ""
            arguments = _arguments_of(call)
            result = call_tool(frame, name, arguments)
            steps.append({"tool": name, "arguments": arguments})
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id") or name,
                    "name": name,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                }
            )

    # Круг замкнулся: модель ходит за данными и не переходит к ответу.
    # Честнее сказать об этом, чем показывать пустое поле.
    return {"available": True, "answer": told("looped"), "steps": steps}
