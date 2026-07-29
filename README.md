# Process Mining Service

Микросервис для process mining. Принимает журнал событий (CSV / TSV / XES / JSON) или
поток событий по HTTP и возвращает модели процесса, метрики, варианты, узкие места и
оценку соответствия (conformance).

Это переработка прототипа на Streamlit (`main.py`, 965 строк в одном файле) в сервис,
который можно подключить к любому количеству ваших проектов через API.

---

## 1. Что изменилось по сравнению с прототипом

| Было (Streamlit) | Стало (микросервис) |
|---|---|
| Один файл на 965 строк: UI + CSS + бизнес-логика вперемешку | Слои: `api` → `services` → `core` → `storage`, каждый заменяем отдельно |
| Работает только через браузер, руками | HTTP API + OpenAPI-схема + готовые клиенты на Python и TypeScript |
| Лог живёт в `st.session_state` и умирает при рестарте | SQLite (или in-memory для тестов), интерфейс репозитория готов под Postgres |
| Whisper грузится всегда, ~1–6 ГБ RAM | Голос — отдельный модуль за флагом `PM_VOICE_ENABLED`, по умолчанию выключен |
| Ключевые слова пекарни зашиты в код | YAML-профили активностей, горячая перезагрузка без деплоя |
| Только DFG + Petri Net | DFG (частоты и длительности), Petri Net (inductive / heuristics), Process Tree, BPMN, conformance |
| Только картинка | И картинка (SVG / PNG / DOT), **и JSON-граф** — рисуйте чем хотите |
| Ошибка `PermissionError` при рендере | Рендер во временный каталог + таймаут |
| Нет авторизации, лимитов, логов | API-ключи, лимиты размера, structured JSON-логи, request-id, health-проб |
| Тестов нет | pytest: маппинг, парсинг, метрики, полный жизненный цикл API |

---

## 2. Быстрый старт

### Docker (рекомендуется)

```bash
cp .env.example .env          # поменяйте PM_API_KEYS
docker compose up -d --build

open http://localhost:8000/docs   # интерактивная документация
open http://localhost:8000/       # демо-интерфейс
```

### Локально

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

# нужен системный graphviz (бинарь dot):
#   Windows: choco install graphviz     macOS: brew install graphviz
#   Ubuntu:  sudo apt install graphviz

cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

### Проверка за один вызов

```bash
curl -X POST http://localhost:8000/api/v1/mine \
  -H "X-API-Key: dev-key-change-me" \
  -F "file=@examples/sample_log.csv" \
  -F "algorithm=dfg_performance" \
  -F "format=svg" | jq -r '.result.image' > map.svg
```

Или полный смоук-тест:

```bash
python clients/python/pm_client.py --base-url http://localhost:8000 --api-key dev-key-change-me
```

---

## 3. Два способа использования

**Stateless — один запрос, полный ответ, ничего не хранится.**
Подходит большинству проектов: загрузили файл, получили модель и метрики.

```
POST /api/v1/mine     (multipart: file + параметры)
```

**Stateful — лог живёт на сервере, события можно дописывать.**
Подходит, когда данные приходят потоком (голос, ERP, IoT, конвейер).

```
POST   /api/v1/logs                  создать лог
POST   /api/v1/logs/{id}/events      дописать события
POST   /api/v1/logs/{id}/discover    построить модель
GET    /api/v1/logs/{id}/statistics  KPI
GET    /api/v1/logs/{id}/bottlenecks узкие места
GET    /api/v1/logs/{id}/variants    частые маршруты
POST   /api/v1/logs/{id}/conformance fitness / precision
GET    /api/v1/logs/{id}/map         картинка прямо в <img>
```

---

## 4. Что за что отвечает

```
app/
├── main.py              сборка приложения: здесь и только здесь всё связывается воедино
├── config.py            все настройки из переменных окружения PM_*, никаких os.environ по коду
├── deps.py              зависимости FastAPI: проверка API-ключа, доступ к сервисам
├── errors.py            доменные исключения и единственное место, где они станут HTTP-ответом
├── middleware.py        request-id, лог доступа, ранняя отбраковка слишком больших тел
├── logging_config.py    JSON-логи с корреляцией запросов
│
├── api/v1/              HTTP-слой. Тонкий: провалидировать → вызвать сервис → отдать
│   ├── logs.py          создание/чтение/дополнение/удаление логов
│   ├── mining.py        discovery, статистика, варианты, узкие места, conformance, /mine
│   ├── jobs.py          опрос фоновых задач
│   ├── profiles.py      список профилей активностей и их перезагрузка
│   ├── voice.py         опциональный голосовой ввод (Whisper)
│   └── health.py        /health/live и /health/ready для Docker и Kubernetes
│
├── schemas/             контракты API (Pydantic). Меняете здесь — меняется и OpenAPI
│
├── services/            сценарии использования, не знают ничего про HTTP
│   ├── log_service.py   жизненный цикл лога
│   ├── mining_service.py дискавери + аналитика + кеш
│   └── transcription.py  аудио → текст → активность (ленивая загрузка Whisper)
│
├── core/                чистая предметная логика, ни FastAPI, ни БД
│   ├── model.py         канонический формат лога и починка таймзон
│   ├── ingestion.py     CSV / XES / JSON → канонический формат, автоопределение колонок
│   ├── mapping.py       нормализация названий активностей по YAML-профилям
│   ├── filtering.py     фильтры лога на чистом pandas
│   ├── mining.py        единственное место во всём коде, где вызывается pm4py
│   ├── metrics.py       KPI, варианты, узкие места, переделки (rework)
│   ├── rendering.py     graphviz → SVG / PNG / DOT, с таймаутом и без блокировок файлов
│   └── cache.py         LRU + TTL кеш результатов по отпечатку входных данных
│
├── storage/             хранение
│   ├── base.py          интерфейс репозитория
│   ├── memory.py        для тестов и stateless-режима
│   └── sqlite.py        для продакшена одного контейнера; на Postgres меняется URL
│
├── jobs/manager.py      пул потоков: тяжёлый pm4py никогда не блокирует event loop
└── static/index.html    демо-клиент: тёмная тема, работает поверх того же API
```

Правило простое: **зависимости идут только внутрь**. `api` знает про `services`,
`services` знают про `core` и `storage`, а `core` не знает ни про кого. Поэтому логику
можно вызывать из CLI, воркера или тестов без поднятия HTTP.

---

## 5. Идеи, которые здесь реализованы (и почему они полезны)

**JSON-граф рядом с картинкой.** Любой ответ discovery содержит `graph` — узлы и рёбра
с частотами и длительностями. Ваш фронтенд может нарисовать это в D3 / Cytoscape /
React Flow, сделать интерактив, зум и подсветку. SVG остаётся для отчётов и писем.

**Узкие места считаются по суммарному времени, а не по среднему.** Сортировка по
среднему выносит наверх единичные аномалии. Сортировка по `среднее × количество`
показывает, где на самом деле теряются часы. Плюс отдельно считаются переделки
(один и тот же шаг повторяется в кейсе) и самопетли — это классические источники потерь.

**Фильтры до дискавери, а не после.** `variant_coverage: 0.8` оставит варианты,
покрывающие 80% кейсов, и «спагетти-диаграмма» превратится в читаемую схему.
Это самый дешёвый способ сделать карту процесса понятной.

**Кеш по отпечатку.** Ключ = (лог + время его последнего изменения + параметры).
Дашборд может опрашивать сервис хоть каждую секунду: повторный расчёт Petri Net
вернётся из кеша за миллисекунды, а после дописывания событий кеш сам инвалидируется.

**Профили активностей в YAML.** «замес» → `start_mixing` больше не живёт в коде.
Новый проект = новый профиль в конфиге; файл перечитывается на лету.

**Асинхронный режим для больших логов.** `POST /logs/{id}/discover/async` сразу
возвращает `job_id`, клиент опрашивает `GET /jobs/{id}`. Никаких таймаутов шлюза.

**Conformance.** Fitness и precision показывают, насколько реальность расходится
с моделью. Это то, ради чего process mining обычно и внедряют.

---

## 6. Конфигурация

Все переменные с префиксом `PM_`, полный список — в `.env.example`.

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `PM_API_KEYS` | пусто | Ключи через запятую. Пусто = авторизация выключена (только для локальной разработки) |
| `PM_STORAGE_BACKEND` | `sqlite` | `sqlite` или `memory` |
| `PM_SQLITE_PATH` | `./data/pm.db` | Файл базы |
| `PM_MAX_UPLOAD_MB` | `64` | Лимит размера файла |
| `PM_MAX_EVENTS_PER_LOG` | `2000000` | Защита от случайного гигабайта |
| `PM_MAPPING_CONFIG` | `./config/activities.yaml` | Профили активностей |
| `PM_MAX_CONCURRENT_JOBS` | `4` | Размер пула потоков под pm4py |
| `PM_RENDER_TIMEOUT_SECONDS` | `60` | Таймаут graphviz |
| `PM_VOICE_ENABLED` | `false` | Включает Whisper-эндпоинты |
| `PM_LOG_JSON` | `true` | JSON-логи (удобно для Loki / ELK) |

---

## 7. Профили активностей

`config/activities.yaml`:

```yaml
profiles:
  bakery:
    description: "Линия выпечки"
    fallback: other_activity
    passthrough: false        # true = неопознанный текст остаётся как есть
    rules:
      - activity: start_mixing
        keywords: ["замес", "меси"]
      - activity: proving
        keywords: ["расстой", "брожен"]
        patterns: ["на\\s+расстой\\w*"]
```

Правила проверяются сверху вниз, первое совпадение выигрывает:
`exact` (точное совпадение) → `patterns` (регулярки) → `keywords` (подстроки).
Файл перечитывается автоматически при изменении; можно и вручную:
`POST /api/v1/mapping-profiles/reload`.

---

## 8. Примеры интеграции

### Python

```python
from pm_client import ProcessMiningClient

pm = ProcessMiningClient("http://process-mining:8000", api_key="...")

# без хранения
answer = pm.mine_file("orders.csv", algorithm="dfg_performance", output_format="svg")
open("map.svg", "w").write(answer["result"]["image"])
print(answer["bottlenecks"]["bottlenecks"][0])

# с хранением и дописыванием
log_id = pm.upload_log("orders.csv", mapping_profile="bakery")["log"]["log_id"]
pm.append_events(log_id, [{"case_id": "B-1", "activity": "упаковали"}])
print(pm.statistics(log_id)["throughput_seconds"]["median"])
```

### JavaScript / TypeScript

```ts
import { ProcessMiningClient } from './pmClient';

const pm = new ProcessMiningClient('http://localhost:8000', apiKey);
const { result, statistics } = await pm.mineFile(file, {
  algorithm: 'dfg_frequency',
  filters: { variant_coverage: 0.8 },
});
// result.graph.nodes / result.graph.edges → рисуем сами
```

### Просто картинка в вёрстке

```html
<img src="http://localhost:8000/api/v1/logs/LOG_ID/map?algorithm=dfg_performance&format=svg">
```

---

## 9. Разработка

```bash
make install     # зависимости
make dev         # автоперезагрузка
make test        # pytest
make lint        # ruff
make up / down   # docker compose
```

Тесты используют `storage_backend=memory`, поэтому ничего не оставляют после себя.

---

## 10. Продакшен: короткий чек-лист

1. Задайте `PM_API_KEYS` — без них API открыт всем.
2. `PM_CORS_ORIGINS` — перечислите свои домены вместо `*`.
3. Терминируйте TLS на nginx / ingress (пример в `deploy/nginx.conf`).
4. Воркеров uvicorn ≈ числу ядер; pm4py упирается в CPU.
5. Больше одной реплики → вынесите хранилище в Postgres, а задачи в Celery/RQ
   (интерфейсы под это уже разделены).
6. Собирайте `/health/ready` — там состояние хранилища, кеша, graphviz и задач.
7. Голосовой модуль включайте отдельным деплоем: у него другой профиль по памяти.

---

## 11. Известные подводные камни (унаследованные и решённые)

| Проблема | Как решено |
|---|---|
| `PermissionError [Errno 13]` при рендере graphviz | Рендер в приватный `tempfile.mkdtemp()`, после чтения каталог удаляется |
| `ValueError: Cannot mix tz-aware with tz-naive` | Все таймстемпы приводятся к tz-naive UTC один раз, в `core/model.py` |
| `'UploadedFile' object has no attribute 'decode'` для XES | Загрузка сохраняется во временный файл, затем `pm4py.read_xes(path)` |
| Импорты из внутренностей pm4py ломаются между версиями | Только публичный API pm4py, и он изолирован в `core/mining.py` |
| Плохое качество картинок | По умолчанию SVG (вектор), PNG — с настраиваемым DPI |
| Долгий расчёт вешает сервер | Пул потоков + асинхронные задачи + таймаут рендера |
