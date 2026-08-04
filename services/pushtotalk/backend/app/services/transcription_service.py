"""Speech-to-text, delegated to the analytics service.

This module used to load its own faster-whisper model. That gave the stack two
Whispers: one in the `stt` container answering the web console, one in this
process answering the phone - two sets of weights in RAM, two places to tune,
and two answers to the same recording. They are one now: this posts the audio
to the analytics service, which owns the speech container and already knows how
to decode a phone recording into something the model accepts.

What is lost by delegating: the local model was given an `initial_prompt`
listing batch code shapes, and the OVOS speech server takes no prompt over
HTTP. Batch numbers therefore come back less reliably punctuated - which the
QMS side already tolerates, because it compares letters and digits only
(`_squash` in voice_process_mining.py).

The two exception types are unchanged, so `app/api/speech.py` does not care
that the model moved out of the process.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from app.config import Settings, settings

logger = logging.getLogger(__name__)


class TranscriptionUnavailableError(RuntimeError):
    """The speech service is not configured, or is not answering."""


class TranscriptionError(RuntimeError):
    """Audio reached the model and did not come back as text."""


def _multipart(path: Path, boundary: str) -> bytes:
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="audio_file"; filename="{path.name}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
    return head + path.read_bytes() + tail


def transcribe_audio(audio_path: Path, config: Settings = settings) -> str:
    """Send an audio file to the analytics service and return the text."""
    if not audio_path.exists() or audio_path.stat().st_size == 0:
        raise TranscriptionError("empty audio file")

    if not config.transcribe_url or not config.transcribe_token:
        raise TranscriptionUnavailableError(
            "Speech recognition is not configured. Set PTT_TRANSCRIBE_URL and "
            "PTT_TRANSCRIBE_TOKEN to the analytics service and its API key."
        )

    boundary = f"----ptt{uuid.uuid4().hex}"
    request = urllib.request.Request(
        config.transcribe_url,
        data=_multipart(audio_path, boundary),
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "X-API-Key": config.transcribe_token,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=config.transcribe_timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:300]
        # 5xx is the service having a bad day and is worth retrying; anything
        # else is this request being wrong and will fail again identically.
        if exc.code >= 500:
            raise TranscriptionUnavailableError(f"speech service HTTP {exc.code}: {body}") from exc
        raise TranscriptionError(f"speech service rejected the audio: HTTP {exc.code} {body}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise TranscriptionUnavailableError(f"speech service unreachable: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise TranscriptionError(f"speech service returned no JSON: {exc}") from exc

    text = str(data.get("text") or data.get("transcript") or "").strip()
    if not text:
        raise TranscriptionError("empty transcription")

    logger.info(
        "Transcribed via analytics service chars=%s took_ms=%s",
        len(text),
        data.get("took_ms"),
    )
    return text
