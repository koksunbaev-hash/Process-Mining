# Process Mining Service

HTTP API around [pm4py](https://pm4py.fit.fraunhofer.de/). Feed it an event log, get back a
process map, KPIs, path variants, bottlenecks and conformance scores.

*[Русская версия](README.ru.md)*

Process mining answers three questions about a business process: how it **actually** runs
(not how the flowchart says it does), where reality diverges from the intended model, and
where the time is going. This service does all three over HTTP so that any number of your
projects can use it without embedding pm4py themselves.

Every model comes back **twice**: as a rendered SVG/PNG for reports, and as a
renderer-agnostic JSON graph (nodes + edges + metrics) you can draw with D3, Cytoscape or
React Flow.

---

## Quick start

```bash
cp .env.example .env          # set PM_API_KEYS
docker compose up -d --build
```

Then open <http://localhost:8000/> for the web console, or <http://localhost:8000/docs>
for the OpenAPI browser.

Without Docker you need the `graphviz` binary on PATH (`apt install graphviz`,
`brew install graphviz`, `choco install graphviz`) and then:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

One call to check everything works end to end:

```bash
curl -X POST http://localhost:8000/api/v1/mine \
  -H "X-API-Key: dev-key-change-me" \
  -F "file=@examples/sample_log.csv" \
  -F "algorithm=dfg_performance" \
  -F "format=svg" | jq -r '.result.image' > map.svg
```

Or the full smoke test, which exercises upload → stats → bottlenecks → render → delete:

```bash
python clients/python/pm_client.py --api-key dev-key-change-me
```

---

## Input format

Three columns are mandatory: **case id**, **activity**, **timestamp**. Everything else is
optional. Column names are auto-detected (`batch_id`, `order`, `ticket` → case id;
`step`, `action`, `task` → activity; and so on), and you can override the guess explicitly.

```csv
batch_id,step,event_time,operator
B-0001,start_mixing,2026-06-01 07:00:00,Danijar
B-0001,add_ingredients,2026-06-01 07:07:00,Danijar
```

Accepted: CSV, TSV, XES (plain or `.gz`), JSON, JSONL.

---

## Two ways to use it

**Stateless** — one request in, full answer out, nothing is stored. This is what most
callers want.

```
POST /api/v1/mine        multipart: file + parameters
```

**Stateful** — the log lives on the server and events are appended as they happen. Use this
when data arrives as a stream (ERP, IoT, a conveyor line, voice input).

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/logs` | create a log from a JSON event list |
| `POST /api/v1/logs/upload` | create a log from a file |
| `POST /api/v1/logs/{id}/events` | append events |
| `POST /api/v1/logs/{id}/discover` | build a model |
| `POST /api/v1/logs/{id}/discover/async` | same, returns a `job_id` immediately |
| `GET /api/v1/logs/{id}/statistics` | throughput, activity and resource stats |
| `GET /api/v1/logs/{id}/variants` | most frequent end-to-end paths |
| `GET /api/v1/logs/{id}/bottlenecks` | where the time actually goes |
| `POST /api/v1/logs/{id}/conformance` | fitness / precision against a discovered model |
| `GET /api/v1/logs/{id}/map` | the image itself, embeddable in `<img src=...>` |

**Automated intake** — a source system pushes its own business events in, in batches, and
nobody uploads anything by hand.

```
POST /api/event-logs/import/     multipart CSV + export_id + checksum
```

Delivery is idempotent in two independent ways: an event whose `event_id` is already
stored is counted as a duplicate rather than imported again, and replaying a batch with
the same `Idempotency-Key` returns the original response. That is what makes a retry after
a timeout safe. Events are routed into separate logs per `case_type`, because orders and
production batches are different processes and one map over both would describe a process
that does not exist. Contract and limits: [docs/EVENT-LOG-INTAKE.md](docs/EVENT-LOG-INTAKE.md).

Auth is `X-API-Key: <key>` or `Authorization: Bearer <key>`. Leave `PM_API_KEYS` empty to
disable auth — local development only.

Full endpoint reference: [docs/API.md](docs/API.md).

---

## Algorithms

| `algorithm` | Output |
|---|---|
| `dfg_frequency` | directly-follows graph, edges weighted by count |
| `dfg_performance` | directly-follows graph, edges weighted by waiting time |
| `petri_net_inductive` | Petri net, inductive miner (sound by construction) |
| `petri_net_heuristics` | Petri net, heuristics miner (handles noise) |
| `process_tree` | process tree |
| `bpmn` | BPMN diagram |

Start with `dfg_performance`: it is the one that shows you where the hours go.

Two knobs matter for readability. `noise_threshold` (0–1) drops rare behaviour in the
inductive and heuristics miners. `filters.variant_coverage: 0.8` keeps only the variants
covering 80% of cases — the cheapest way to turn a spaghetti diagram into something a
human can read.

---

## What you get back

```jsonc
{
  "result": {
    "algorithm": "dfg_performance",
    "graph": { "nodes": [...], "edges": [...] },   // draw it yourself
    "image": "<svg .../>",                          // or use this
    "computed_in_ms": 327
  },
  "statistics": { "events": 497, "cases": 60, "throughput_seconds": { "median": 8520 } },
  "bottlenecks": { "bottlenecks": [...], "rework": [...] },
  "variants":    { "items": [...] },
  "warnings": [], "detected_columns": { "case_id": "batch_id" }
}
```

Bottlenecks are ranked by **total** time consumed (`mean × occurrences`), not by mean
duration. Ranking by mean surfaces rare freak cases; ranking by total surfaces what
actually costs the business hours.

---

## Web console

The service ships a built-in UI at `/` — upload a log, pick an algorithm, get the map plus
tabs for variants, bottlenecks and activities. Interface language: English, Russian,
Kazakh. Light and dark themes.

It is a plain static page (`app/static/`) talking to the same public API, no build step and
no npm. If you want your own frontend, read `app/static/app.js` as the reference client.

---

## Activity profiles

Free-text activity names get normalized through YAML profiles, so `"замес"`, `"месим тесто"`
and `"start_mixing"` all collapse into one activity. Rules are checked top-down, first match
wins: `exact` → `patterns` (regex) → `keywords` (substring).

```yaml
profiles:
  bakery:
    fallback: other_activity
    passthrough: false        # true = keep unmatched text as-is
    rules:
      - activity: start_mixing
        exact: ["start_mixing"]
        keywords: ["замес", "меси"]
```

`config/activities.yaml` is re-read automatically when it changes; `POST
/api/v1/mapping-profiles/reload` forces it.

---

## Configuration

Environment variables, all prefixed `PM_`. Full list in `.env.example`.

| Variable | Default | Meaning |
|---|---|---|
| `PM_API_KEYS` | *empty* | Comma-separated. Empty disables auth |
| `PM_CORS_ORIGINS` | `*` | Set your real origins in production |
| `PM_STORAGE_BACKEND` | `sqlite` | `sqlite` or `memory` |
| `PM_SQLITE_PATH` | `./data/pm.db` | Database file |
| `PM_MAX_UPLOAD_MB` | `64` | Upload size limit |
| `PM_MAX_EVENTS_PER_LOG` | `2000000` | Guard against an accidental gigabyte |
| `PM_MAPPING_CONFIG` | `./config/activities.yaml` | Activity profiles |
| `PM_MAX_CONCURRENT_JOBS` | `4` | Thread-pool size for pm4py work |
| `PM_RENDER_TIMEOUT_SECONDS` | `60` | Graphviz timeout |
| `PM_VOICE_ENABLED` | `false` | Enables the Whisper endpoints |
| `PM_LOG_JSON` | `true` | JSON logs, for Loki / ELK |

---

## Layout

```
app/
├── main.py         composition root - everything is wired here, once
├── config.py       PM_* settings; nothing else reads os.environ
├── deps.py         FastAPI dependencies: API key, service accessors
├── api/v1/         HTTP layer. Thin: validate → call a service → serialize
├── schemas/        Pydantic contracts; edit here and OpenAPI follows
├── services/       use cases, no HTTP knowledge
├── core/           pure domain logic, no FastAPI, no DB
│   ├── ingestion.py   CSV/XES/JSON → canonical frame, column detection
│   ├── mining.py      discovery; imports pm4py (so does ingestion, for XES)
│   ├── metrics.py     KPIs, variants, bottlenecks, rework (plain pandas)
│   ├── rendering.py   graphviz → SVG/PNG/DOT, sandboxed + timed out
│   └── cache.py       LRU + TTL keyed by a fingerprint of the inputs
├── storage/        repository interface + memory and sqlite backends
└── jobs/manager.py thread pool: blocking pm4py never touches the event loop
```

Dependencies point inward only: `api` → `services` → `core`. `core` knows about nobody, so
the logic runs from a CLI, a worker or a test without starting HTTP.

Two decisions worth knowing about. **pm4py is confined to `core/mining.py` and one function in
`core/ingestion.py`** (`read_xes`, which nothing else can do) — its public API drifts between
minor versions, so an upgrade touches those two files and nothing else. **Rendering happens
in a private temp dir** with a timeout, because rendering into the project directory is how
you get `PermissionError` on Windows and a wedged worker on a pathological graph.

More detail in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Development

```bash
make install     # dependencies
make dev         # uvicorn with reload
make test        # pytest
make lint        # ruff
```

Tests run against `storage_backend=memory` and leave nothing behind.

---

## Deployment

`docker compose up -d --build` on a VM is the intended setup: no external dependencies,
SQLite in a named volume, `restart: unless-stopped`, healthcheck built in.

Before going to production: set real `PM_API_KEYS`, replace `PM_CORS_ORIGINS=*` with your
domains, set `PM_DEBUG=false`, and put TLS in front of it — there is a working reverse proxy
config in [deploy/nginx.conf](deploy/nginx.conf) with the long timeouts discovery needs.

The image is ~1 GB (pm4py pulls in scipy and matplotlib). For an air-gapped host,
`docker save | gzip` gives you ~400 MB to copy.

---

## Limitations

Read this section before building on top of it.

- **Deduplication needs an `event_id`.** Events that carry one can never be stored twice;
  events without one (plain file uploads) are always appended, because there is no honest
  way to tell a re-delivery from a genuine repeat of the same activity in the same case.
- **SQLite means one node.** The `LogRepository` interface is ready for Postgres but the
  implementation does not exist. Do not run multiple replicas against one database file —
  note that `deploy/k8s.yaml` ships `replicas: 2`, which you must fix before using it.
- **`tenant` is a filter, not isolation.** It scopes queries; it does not enforce that key A
  cannot read tenant B.
- **No rate limiting.** Only a request body size cap.
- **Discovery is CPU-bound and synchronous by default.** Large logs should go through
  `/discover/async` + `/jobs/{id}` rather than holding an HTTP connection open.
- **Voice input needs Whisper** (`PM_VOICE_ENABLED=true`, `pip install '.[voice]'`), which
  wants gigabytes of RAM. It is off by default and lazily imported for that reason.

---

## Docs

- [docs/API.md](docs/API.md) — endpoint reference
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — data flow and design decisions
- [docs/MIGRATION.md](docs/MIGRATION.md) — porting from the old Streamlit prototype
- `clients/python/pm_client.py`, `clients/js/pmClient.ts` — copy one file into your project
