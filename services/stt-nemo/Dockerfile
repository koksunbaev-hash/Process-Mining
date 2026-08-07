# syntax=docker/dockerfile:1
#
# Speech recognition, CPU only. Measured on the eight recordings from the floor:
# 23.3 seconds of audio in 0.7 seconds on four threads, which is why there is no
# CUDA in this image and no GPU in the requirements. FastConformer labels the
# audio in a single pass rather than generating it token by token.
#
# The weights are not baked in - they land in the cache volume on first start,
# the same arrangement the image this replaces used.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/cache/huggingface

# libsndfile is what soundfile reads WAV through; NeMo pulls the rest itself.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libsndfile1 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU wheels on purpose: the CUDA build of torch is several gigabytes and buys
# nothing here. Installed before NeMo so NeMo does not drag the GPU one in.
RUN pip install torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY app.py ./

RUN mkdir -p /cache/huggingface

EXPOSE 8080

# Generous start period: the first run downloads ~600 MB of weights.
HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=300s \
    CMD curl -fsS http://127.0.0.1:8080/health || exit 1

CMD ["sh", "-c", "exec uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1"]
