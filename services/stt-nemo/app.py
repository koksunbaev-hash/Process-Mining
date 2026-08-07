"""Speech recognition on NeMo FastConformer, wearing the OVOS server's contract.

The service it replaces exposed exactly one useful endpoint - POST /stt?lang=xx
with a WAV body, answering with the text as a bare string. Everything that
calls speech recognition in this repository speaks that, so this speaks it too:
switching is one environment variable, and so is switching back.

Why the model changed, measured on eight recordings from the floor:

    batch number recognised   Whisper large-v3  2/8      NeMo kk+ru  7/8
    23.3s of audio took       Whisper (2 cores) 256s     NeMo (4)    0.7s

The second number is the surprise: FastConformer labels the audio in one pass
instead of generating text token by token, so it does not need a GPU to be
faster than real time. The first is the reason to bother. The third reason has
no number: an RNN-T decoder returns nothing when it hears nothing, where
Whisper invents a plausible sentence - and a plausible sentence is exactly what
a countdown-to-execute command must never be handed.

The model is bilingual Kazakh/Russian and picks the language itself, which is
what the shop floor actually speaks: "үш жүз қырық бір на расстойку".
"""

from __future__ import annotations

import io
import os
import time
import wave
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

MODEL_NAME = os.getenv("NEMO_MODEL", "nvidia/stt_kk_ru_fastconformer_hybrid_large")
THREADS = int(os.getenv("NEMO_THREADS", "4"))
MAX_BYTES = int(os.getenv("NEMO_MAX_UPLOAD_MB", "32")) * 1024 * 1024

_model = None


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Weights before the first caller, unless told otherwise.

    Loading on startup costs a few seconds once; loading on first request costs
    them to whoever spoke first, which on a shop floor is somebody holding a
    button and wondering whether it is broken.
    """
    if os.getenv("NEMO_PRELOAD", "true").lower() in {"1", "true", "yes"}:
        _load()
    yield


app = FastAPI(title="STT (NeMo FastConformer)", version="1.0.0", lifespan=lifespan)


def _load():
    """Loaded once, on the first request rather than at import.

    Import time matters: uvicorn's healthcheck should be able to answer while
    the weights are still coming off disk, and a container that is unhealthy
    for three seconds is easier to reason about than one that is unhealthy for
    a minute.
    """
    global _model
    if _model is None:
        import torch

        torch.set_num_threads(THREADS)
        import nemo.collections.asr as nemo_asr

        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = nemo_asr.models.ASRModel.from_pretrained(MODEL_NAME, map_location=device)
        model.eval()
        _model = model
    return _model


def _duration_seconds(payload: bytes) -> float:
    """Length of the recording, for the log line. Zero if it is not a WAV."""
    try:
        with wave.open(io.BytesIO(payload)) as handle:
            return handle.getnframes() / handle.getframerate()
    except Exception:  # noqa: BLE001 - a log line is never worth an exception
        return 0.0


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": MODEL_NAME, "loaded": _model is not None}


@app.post("/stt")
async def stt(request: Request, lang: str = "") -> Response:
    """WAV in, text out.

    `lang` is accepted and ignored: this model is bilingual and decides for
    itself. The parameter stays in the signature because every caller sends it,
    and rejecting it would make the drop-in not drop in.
    """
    payload = await request.body()
    if not payload:
        return JSONResponse({"error": "empty body"}, status_code=400)
    if len(payload) > MAX_BYTES:
        return JSONResponse({"error": "audio too large"}, status_code=413)

    import tempfile
    from pathlib import Path

    handle = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    try:
        handle.write(payload)
        handle.close()
        started = time.perf_counter()
        result = _load().transcribe([handle.name], batch_size=1, verbose=False)
        took_ms = round((time.perf_counter() - started) * 1000, 1)
    except Exception as error:  # noqa: BLE001 - the caller gets a 500, not a hang
        return JSONResponse({"error": f"{type(error).__name__}: {error}"}, status_code=500)
    finally:
        Path(handle.name).unlink(missing_ok=True)

    # Hybrid models can answer with a (rnnt, ctc) pair; the first is the better one.
    if isinstance(result, tuple):
        result = result[0]
    item = result[0]
    text = (getattr(item, "text", item) if not isinstance(item, str) else item).strip()

    seconds = _duration_seconds(payload)
    print(
        f"stt chars={len(text)} audio={seconds:.1f}s took={took_ms}ms "
        f"rtf={took_ms / 1000 / seconds:.3f}" if seconds else f"stt chars={len(text)} took={took_ms}ms",
        flush=True,
    )

    # A bare string, exactly as the OVOS server answers - the caller parses
    # either that or a JSON object, and matching the old shape keeps the
    # rollback honest.
    return PlainTextResponse(text)
