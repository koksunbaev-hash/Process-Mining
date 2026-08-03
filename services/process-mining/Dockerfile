# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

# graphviz renders the process maps; ffmpeg decodes browser recordings
# (webm/opus, mp4) into the raw PCM the speech service expects
RUN apt-get update && apt-get install -y --no-install-recommends \
        graphviz curl ffmpeg \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY app ./app
COPY config ./config

RUN useradd -m -u 10001 appuser && mkdir -p /srv/data && chown -R appuser /srv
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:8000/health/live || exit 1

# One worker, deliberately. The job registry (app/jobs/manager.py) and the
# result cache (app/main.py) are plain dicts in process memory, so a second
# worker gets its own copy: /discover/async hands back a job_id minted in one
# process and /jobs/{id} then misses it about half the time. Two workers also
# doubled PM_MAX_CONCURRENT_JOBS into four parallel discoveries and pointed a
# second writer at the same SQLite file.
#
# Throughput barely needs them: discovery already runs in a thread pool capped
# by PM_MAX_CONCURRENT_JOBS. Log upload is the exception - upload_log and
# import_events parse and write inline, so a large XES blocks this process
# while pm4py reads it. That is a fair trade against job_ids that go missing,
# but it is the thing to fix before raising the count, along with moving job
# state and the cache out of process memory.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
