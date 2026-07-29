# Справочник API

Базовый префикс: `/api/v1`. Авторизация: `X-API-Key: <ключ>` или `Authorization: Bearer <ключ>`.
Интерактивная версия всегда актуальна: `/docs` (Swagger) и `/redoc`.

## Формат ошибок

```json
{
  "error": {
    "code": "validation_error",
    "message": "Could not detect required columns: timestamp",
    "details": { "available_columns": ["a", "b"] },
    "request_id": "7f3c1a9b2e4d5061"
  }
}
```

`request_id` возвращается в заголовке `X-Request-ID` и попадает в логи — по нему
находится любой запрос.

| Код | Когда |
|---|---|
| `unauthorized` | нет или неверный API-ключ |
| `not_found` | лог или задача не найдены |
| `validation_error` | битые данные, не определились колонки |
| `payload_too_large` | файл больше `PM_MAX_UPLOAD_MB` |
| `unsupported_format` | неизвестное расширение файла |
| `mining_failed` | pm4py не смог построить модель (обычно слишком мало событий) |
| `rendering_unavailable` | нет бинаря graphviz или таймаут рендера |
| `feature_disabled` | голосовой модуль выключен |

---

## Логи

### `POST /logs` — создать из JSON

```json
{
  "name": "Линия L1",
  "tenant": "openegiz",
  "mapping_profile": "bakery",
  "events": [
    {"case_id": "B-1", "activity": "начали замес", "timestamp": "2026-06-01T05:00:00Z", "resource": "Айгуль"}
  ]
}
```

`timestamp` можно не передавать — подставится текущее время сервера (UTC).
`activity` можно писать свободным текстом: профиль приведёт его к канонической активности,
а исходная строка сохранится в `activity_raw`.

### `POST /logs/upload` — создать из файла

`multipart/form-data`: `file` (CSV / TSV / XES / XES.GZ / JSON / JSONL) плюс необязательные
`name`, `tenant`, `mapping_profile`, `columns`.

`columns` — JSON-строка, нужна только если автоопределение ошиблось:

```json
{"case_id": "batch_id", "activity": "step", "timestamp": "event_time",
 "resource": "operator", "timestamp_format": "%d.%m.%Y %H:%M", "separator": ";"}
```

Ответ содержит `detected_columns` (что сервис распознал) и `warnings`
(например, сколько строк отброшено из-за нечитаемых дат).

### `POST /logs/preview` — посмотреть колонки, ничего не импортируя

Возвращает список колонок, предложенный маппинг и первые строки. Полезно для мастера импорта.

### Остальное

| Метод | Путь | Что делает |
|---|---|---|
| `GET` | `/logs` | список (`tenant`, `limit`, `offset`) |
| `GET` | `/logs/{id}` | сводка |
| `GET` | `/logs/{id}/events` | постраничный просмотр событий |
| `POST` | `/logs/{id}/events` | дописать события |
| `DELETE` | `/logs/{id}` | удалить |

---

## Дискавери

### `POST /logs/{id}/discover`

```json
{
  "algorithm": "dfg_performance",
  "format": "json",
  "noise_threshold": 0.2,
  "filters": {
    "date_from": "2026-06-01T00:00:00Z",
    "activities_exclude": ["other_activity"],
    "variant_coverage": 0.8,
    "min_case_length": 3
  },
  "render": { "rankdir": "LR", "font_size": 12, "dpi": 200 }
}
```

`algorithm`: `dfg_frequency`, `dfg_performance`, `petri_net_inductive`,
`petri_net_heuristics`, `process_tree`, `bpmn`.

`format`: `json` (граф), `svg`, `png` (base64), `dot`.
С `?raw=true` сервис вернёт саму картинку с правильным `Content-Type`.

Ответ:

```json
{
  "algorithm": "dfg_performance",
  "cached": false,
  "computed_in_ms": 184.3,
  "graph": {
    "nodes": [{"id": "proving", "label": "proving", "frequency": 60, "metrics": {"cases": 60}}],
    "edges": [{"source": "proving", "target": "load_oven", "frequency": 60,
               "mean_duration_seconds": 3948.0, "median_duration_seconds": 3900.0,
               "metrics": {"p95_seconds": 5820.0, "total_seconds": 236880.0}}],
    "start_activities": {"start_mixing": 60},
    "end_activities": {"shipment": 60}
  },
  "image": "<svg ...>",
  "content_type": "image/svg+xml"
}
```

### `GET /logs/{id}/map` — картинка одной ссылкой

`?algorithm=dfg_frequency&format=svg&variant_coverage=0.8&rankdir=LR`
Возвращает готовый SVG/PNG — можно вставлять прямо в `<img>`.

### `POST /logs/{id}/discover/async` — для больших логов

Сразу отдаёт `202` и `job_id`; результат забирается через `GET /jobs/{job_id}`.

---

## Аналитика

| Метод | Путь | Что возвращает |
|---|---|---|
| `GET` | `/logs/{id}/statistics` | события, кейсы, активности, ресурсы, варианты, время цикла (mean/median/p90/p95), топ активностей и ресурсов, кейсы по дням |
| `GET` | `/logs/{id}/variants?limit=20` | частые маршруты с долей и средним временем |
| `GET` | `/logs/{id}/bottlenecks?limit=10` | переходы, отсортированные по суммарному потерянному времени, плюс переделки и самопетли |
| `POST` | `/logs/{id}/conformance` | fitness (token replay) и precision |

---

## Stateless

### `POST /mine`

`multipart/form-data`: `file`, `algorithm`, `format`, `mapping_profile`, `columns`,
`filters`, `noise_threshold`, `include_statistics`.

Возвращает модель, статистику и топ-5 узких мест за один вызов. Ничего не сохраняет.
Это основной способ интеграции для соседних проектов.

---

## Служебное

| Метод | Путь | Что |
|---|---|---|
| `GET` | `/health/live` | жив ли процесс |
| `GET` | `/health/ready` | готов ли: хранилище, кеш, graphviz, задачи, профили |
| `GET` | `/api/v1/mapping-profiles` | список профилей |
| `POST` | `/api/v1/mapping-profiles/reload` | перечитать YAML |
| `GET` | `/api/v1/jobs` · `/api/v1/jobs/{id}` | фоновые задачи |
| `POST` | `/api/v1/voice/transcribe` | аудио → текст → активность (если включён голос) |
| `POST` | `/api/v1/voice/logs/{id}/events` | распознать и сразу дописать событие |
