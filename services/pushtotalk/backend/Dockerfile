# syntax=docker/dockerfile:1
#
# The phone's half of the voice loop: takes a recording, gets it transcribed,
# hands the text to the QMS as a command awaiting confirmation.
#
# No ffmpeg and no model weights in this image. Recognition belongs to the
# analytics service, which owns the one speech container in the stack - this
# one only has to move bytes, so it stays small enough for a free tier.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Writable state lives on a volume; the image itself stays read-only in
# practice. Both paths are derived from this one unless set explicitly.
ENV PTT_RUNTIME_DIR=/srv/ptt
RUN mkdir -p /srv/ptt/data /srv/ptt/logs

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
