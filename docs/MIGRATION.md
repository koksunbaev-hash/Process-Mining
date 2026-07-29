# Миграция с прототипа на Streamlit

## Куда переехал код

| Было в `main.py` | Стало |
|---|---|
| строки 1–27, `render_svg()` | `app/core/rendering.py` (+ таймаут, PNG/DOT, чистка временных файлов) |
| строки 29–637, CSS | `app/static/index.html` (демо-клиент, необязателен) |
| строки 661–698, запись и распознавание | `app/services/transcription.py` + `app/api/v1/voice.py` |
| строки 702–768, загрузка CSV/XES | `app/core/ingestion.py` (+ JSON/JSONL, автоопределение колонок, форматы дат) |
| строки 784–789, словарь ключевых слов | `config/activities.yaml`, движок в `app/core/mapping.py` |
| строки 827–867, статистика лога | `app/core/metrics.py` (+ время цикла, ресурсы, переделки) |
| строки 869–965, DFG и Petri Net | `app/core/mining.py` (+ heuristics, process tree, BPMN, conformance) |
| `st.session_state.event_log` | `app/storage/` (SQLite или память) |

## Соответствие действий

| В Streamlit | В сервисе |
|---|---|
| загрузить CSV в сайдбаре | `POST /api/v1/logs/upload` |
| выбрать колонки в четырёх селектах | поле `columns` (нужно только если автоопределение ошиблось) |
| сказать фразу и нажать «Добавить событие» | `POST /api/v1/voice/logs/{id}/events` |
| нажать «Launch Process Mining» | `POST /api/v1/logs/{id}/discover` |
| три картинки на странице | три вызова с разным `algorithm`, либо `GET /logs/{id}/map` |

## Что делать со старым интерфейсом

Вариант 1 (быстрый): оставить Streamlit как есть, но вместо pm4py дёргать сервис.
Весь блок дискавери заменяется на пару строк:

```python
import requests

response = requests.post(
    "http://process-mining:8000/api/v1/mine",
    headers={"X-API-Key": API_KEY},
    files={"file": open(path, "rb")},
    data={"algorithm": "dfg_frequency", "format": "svg", "mapping_profile": "bakery"},
    timeout=300,
).json()

st.markdown(response["result"]["image"], unsafe_allow_html=True)
st.json(response["statistics"])
```

После этого Streamlit-приложение перестаёт зависеть от pm4py, graphviz и Whisper —
всё это остаётся в контейнере сервиса.

Вариант 2 (правильный): взять `app/static/index.html` как основу и сделать нормальный
фронтенд, который рисует `graph.nodes` / `graph.edges` интерактивно.

## Чего в сервисе намеренно нет

- Записи звука с микрофона: `sounddevice` работает только на машине с устройством ввода.
  Записывать должен клиент (браузер умеет через `MediaRecorder`), сервис принимает готовый файл.
- Глобального состояния «текущий лог»: у каждого клиента свой `log_id`.
