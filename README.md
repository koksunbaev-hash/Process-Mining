# Bakery QMS + Process Mining

Two services that ship together: the **QMS** that runs the bakery, and the
**process-mining** service that shows how it actually ran.

```bash
cp .env.example .env             # set SECRET_KEY and PM_API_KEYS
sh services/nginx/make-cert.sh   # the proxy will not start without this
docker compose up -d --build
```

The certificate step is not optional. Certificates are generated per host and
never committed, so on a fresh clone `services/nginx/certs/` does not exist;
the `proxy` container mounts it, fails to load the key and — being
`restart: unless-stopped` — retries forever. Pass the host's IP or domain if
the stack is reached by anything other than `localhost`
(`sh services/nginx/make-cert.sh 192.168.0.137`).

| | URL | What it is |
|---|---|---|
| QMS | <http://localhost:8000> | Django app: orders, production batches, stages, quality, stock |
| Process mining | <http://localhost:8001> | FastAPI + pm4py: process maps, KPIs, variants, bottlenecks |
| API docs | <http://localhost:8001/docs> | OpenAPI for the analytics service |

---

## Why two services and not one

They share a repository, not a process. QMS owns the business data and must
keep taking orders even when a discovery job on a large log is chewing through
a CPU core; the analytics service holds nothing that cannot be recomputed and
can restart whenever it likes. Merging them into one application would trade
that isolation for nothing — they already talk over a clean HTTP contract.

So what is merged is the **lifecycle**: one clone, one `.env`, one
`docker compose up`, one place to read the code.

```
.
├── docker-compose.yml       the whole stack
├── .env.example             one file for both services
└── services/
    ├── qms/                 Django 5 + Postgres  (bakery QMS)
    └── process-mining/      FastAPI + pm4py      (analytics)
```

Each service keeps its own `Dockerfile`, dependencies and README —
[services/qms/README.md](services/qms/README.md) and
[services/process-mining/README.md](services/process-mining/README.md)
([по-русски](services/process-mining/README.ru.md)).

---

## How the two are wired

QMS records business events as they happen — a batch moves from `Замес` to
`Формовка`, an order is confirmed, a nonconformity is opened — into a local
outbox table (`apps/process_mining/models.py`). A background command batches
them into CSV and posts them to the analytics service:

```
POST http://process-mining:8000/api/event-logs/import/
```

The URL is set by compose from the container name, so there are no IP
addresses to maintain and nothing to change when the stack moves to another
host. The token is the same `PM_API_KEYS` value both services read from `.env`.

Delivery is idempotent from both ends, which is what makes retries safe: an
event whose `event_id` was already stored counts as a duplicate instead of
being imported twice, and a whole batch replayed with the same
`Idempotency-Key` returns the original answer. Events are filed into a separate
log per `case_type`, because production orders and production batches are
different processes and one map covering both would describe a process nobody
runs.

Contract and limits: [services/process-mining/docs/EVENT-LOG-INTAKE.md](services/process-mining/docs/EVENT-LOG-INTAKE.md).

---

## Configuration

Everything lives in one root `.env`. Two values must be set before the stack
will start — compose refuses rather than booting with an empty secret:

```bash
openssl rand -hex 32     # SECRET_KEY  (Django)
openssl rand -hex 32     # PM_API_KEYS (analytics API token, shared by both)
```

| Variable | Default | Meaning |
|---|---|---|
| `QMS_PORT` | `8000` | Host port for the QMS |
| `PM_PORT` | `8001` | Host port for the analytics console |
| `DB_NAME` / `DB_USER` / `DB_PASSWORD` | `qms` / `qms` / — | Postgres credentials |
| `RUN_SEED` | `False` | Fill the database with demo bakery data on first start |
| `DEBUG` | `False` | Django debug mode |
| `PROCESS_MINING_SOURCE` | `kms_bakery` | Name this deployment reports as; keep it stable |

Both containers listen on 8000 internally; only the published host ports
differ.

---

## Development

The stack is the fastest way to run everything, but each service also runs on
its own. For the analytics service:

```bash
cd services/process-mining
pip install -r requirements-dev.txt
pytest -q
uvicorn app.main:app --reload --port 8001
```

It needs the `graphviz` binary on PATH (`apt install graphviz`,
`brew install graphviz`, `choco install graphviz`). For the QMS:

```bash
cd services/qms
pip install -r requirements.txt
python manage.py migrate && python manage.py runserver
```

---

## Deployment

Same command as locally:

```bash
docker compose up -d --build
```

Before exposing it: set real secrets, put `DEBUG=False`, list your domains in
`ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`, and terminate TLS in front —
there is a working reverse-proxy config in
[services/process-mining/deploy/nginx.conf](services/process-mining/deploy/nginx.conf).

The analytics image is ~1 GB because pm4py pulls in scipy and matplotlib. On a
host without internet, `docker save | gzip` gives you ~400 MB to copy.

---

## Limitations

- **The analytics store is SQLite**, so run one replica of that service. The
  repository interface is ready for Postgres but the implementation is not
  written. QMS itself is on Postgres and has no such limit.
- **`tenant` is a filter, not isolation** in the analytics service — it scopes
  queries, it does not stop one key reading another tenant's data.
- **No rate limiting**, only a request body size cap.
- **Discovery is CPU-bound.** Large logs should go through
  `/discover/async` + `/jobs/{id}` rather than holding a connection open.
- **Voice transcription is not deployed here.** QMS can send recordings to a
  transcription endpoint and the analytics service has a Whisper module, but it
  is off by default: it wants gigabytes of RAM and belongs in its own deployment.

---

## Picking this up

[docs/HANDOFF.md](docs/HANDOFF.md) carries the context a newcomer would
otherwise spend a day re-deriving: why the two services stay separate, which
traps have already been stepped on, what the 1C data can and cannot support,
and what is deliberately unfinished. Read it before the first change.

Showing the system to someone: [docs/DEMO-CHECKLIST.md](docs/DEMO-CHECKLIST.md)
for the deploy and the checks worth doing beforehand,
[docs/VOICE-DEMO.md](docs/VOICE-DEMO.md) for the voice walkthrough.
