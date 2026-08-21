"""Разговор с языковой моделью по OpenAI-совместимому протоколу.

Модель здесь - рассказчик, а не источник истины. Числа считает сервис, ей
достаётся готовая выжимка и просьба изложить её по-русски. Поэтому и врать
ей не на чем: в тексте те же цифры, что на экране рядом.

Всё, что связано с моделью, необязательно. Не настроена, не отвечает,
отвечает мусором - вызывающий получает None и показывает то, что собрал сам.
Экран аналитики не должен гаснуть из-за чужой машины в соседней стойке.

Стандартной библиотеки достаточно: один POST на запрос, никаких зависимостей
ради двадцати строк.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)


def configured(settings) -> bool:
    return bool(settings.llm_enabled and settings.llm_base_url and settings.llm_model)


def chat(
    settings,
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    thinking: bool | None = None,
    max_tokens: int | None = None,
    temperature: float = 0.3,
) -> dict[str, Any] | None:
    """Один заход к модели. Возвращает message целиком или None.

    Message, а не текст: у ответа с инструментами содержимого нет вовсе - там
    tool_calls, - и вызывающий сам решает, что ему нужно.
    """
    if not configured(settings):
        return None

    payload: dict[str, Any] = {
        "model": settings.llm_model,
        "messages": messages,
        "max_tokens": max_tokens or settings.llm_max_tokens,
        "temperature": temperature,
        # Размышление отключается через шаблон чата - так это устроено у Qwen
        # в vLLM. Оставленное включённым, оно съедает весь лимит вывода и
        # возвращает пустой content: проверено на живой модели.
        "chat_template_kwargs": {
            "enable_thinking": settings.llm_thinking if thinking is None else thinking
        },
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if settings.llm_api_key:
        headers["Authorization"] = f"Bearer {settings.llm_api_key}"

    request = urllib.request.Request(
        url,
        # ensure_ascii=False и явный utf-8: кириллица иначе уезжает вопросами.
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.llm_timeout_seconds) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        logger.warning("LLM: запрос не удался (%s)", exc)
        return None

    choices = body.get("choices") or []
    if not choices:
        logger.warning("LLM: ответ без choices")
        return None
    return choices[0].get("message") or None


def say(settings, system: str, user: str, **kwargs) -> str | None:
    """Короткий путь: спросить и получить текст. Пусто - значит не сложилось."""
    message = chat(
        settings,
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        **kwargs,
    )
    if not message:
        return None
    text = (message.get("content") or "").strip()
    if not text:
        # Так выглядит модель, ушедшая в размышление: содержимое пустое, всё
        # ушло в reasoning. Для вызывающего это то же самое, что молчание.
        logger.warning("LLM: пустой ответ (размышление съело вывод?)")
        return None
    return text


def health(settings) -> dict[str, Any]:
    """Отвечает ли модель. Для страницы настроек и диагностики."""
    if not configured(settings):
        return {"enabled": False, "reachable": False, "reason": "не настроена"}
    url = settings.llm_base_url.rstrip("/") + "/models"
    headers = {}
    if settings.llm_api_key:
        headers["Authorization"] = f"Bearer {settings.llm_api_key}"
    try:
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=min(5, settings.llm_timeout_seconds)) as response:
            body = json.loads(response.read().decode("utf-8"))
        names = [item.get("id") for item in body.get("data", [])]
        return {
            "enabled": True,
            "reachable": True,
            "models": names,
            "configured_model": settings.llm_model,
            # Настроенной модели может не оказаться в списке - опечатка в
            # имени выглядит как «всё включено, но ответов нет».
            "model_present": settings.llm_model in names,
        }
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return {"enabled": True, "reachable": False, "reason": str(exc)[:200]}
