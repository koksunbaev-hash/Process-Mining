"""Speech-to-text against an OVOS STT server, plus the signed callback.

The model does not live in this process. It runs in its own container and is
reached over HTTP, which is what keeps this service small enough to restart in
under a second and lets speech get a GPU without dragging analytics along.

The flow this implements is the one the source system was built against:
accept the audio, answer immediately with a task id, transcribe in the
background, then POST the result back signed with HMAC-SHA256.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any

from app.config import Settings
from app.errors import ValidationError
from app.logging_config import get_logger

log = get_logger(__name__)


class SttError(RuntimeError):
    """Raised when audio cannot be turned into text."""

    def __init__(self, message: str, code: str = "TRANSCRIPTION_FAILED") -> None:
        super().__init__(message)
        self.code = code


def new_task_id() -> str:
    return f"tr-{uuid.uuid4().hex[:12]}"


class SttService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    # ---- audio ----------------------------------------------------------
    def decode_to_pcm(self, payload: bytes) -> tuple[bytes, float]:
        """Any browser recording -> 16 kHz mono int16 PCM.

        The recorder in a browser produces webm/opus or mp4, and the STT
        server wants raw PCM. ffmpeg reads the container from the byte stream,
        so we never need to know or trust the file extension.

        Returns ``(pcm, duration_seconds)``.
        """
        if shutil.which("ffmpeg") is None:
            raise SttError(
                "ffmpeg is not installed in this image; audio cannot be decoded",
                code="AUDIO_DECODE_UNAVAILABLE",
            )
        if not payload:
            raise ValidationError("Audio file is empty")

        rate = self.settings.stt_sample_rate
        try:
            done = subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-i", "pipe:0",
                    "-f", "s16le", "-acodec", "pcm_s16le",
                    "-ac", "1", "-ar", str(rate),
                    "pipe:1",
                ],
                input=payload,
                capture_output=True,
                timeout=self.settings.stt_timeout_seconds,
                check=True,
            )
        except subprocess.TimeoutExpired as exc:
            raise SttError("Audio decoding timed out", code="AUDIO_DECODE_TIMEOUT") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or b"").decode("utf-8", errors="replace")[:300]
            raise SttError(f"Cannot decode audio: {detail}", code="UNSUPPORTED_AUDIO") from exc

        pcm = done.stdout
        if not pcm:
            raise SttError("Audio decoded to zero samples", code="EMPTY_AUDIO")
        duration = len(pcm) / (rate * 2)  # int16 mono
        return pcm, round(duration, 3)

    # ---- transcription --------------------------------------------------
    def transcribe(self, payload: bytes, *, language: str | None = None) -> dict[str, Any]:
        pcm, duration = self.decode_to_pcm(payload)
        lang = language or self.settings.stt_language

        query = urllib.parse.urlencode(
            {"lang": lang, "sample_rate": self.settings.stt_sample_rate, "sample_width": 2}
        )
        url = f"{self.settings.stt_url.rstrip('/')}/stt?{query}"
        request = urllib.request.Request(
            url,
            data=pcm,
            method="POST",
            headers={"Content-Type": "application/octet-stream"},
        )

        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self.settings.stt_timeout_seconds) as resp:
                raw = resp.read().decode("utf-8", errors="replace").strip()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:300]
            raise SttError(f"STT server returned HTTP {exc.code}: {body}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise SttError(
                f"STT server at {self.settings.stt_url} is unreachable: {exc}",
                code="STT_UNAVAILABLE",
            ) from exc

        # The native endpoint answers with a bare string; be tolerant of a
        # JSON-wrapped transcript so a different plugin does not break us.
        text = raw
        if raw.startswith("{") or raw.startswith('"'):
            try:
                parsed = json.loads(raw)
                text = parsed.get("transcript", parsed.get("text", "")) if isinstance(parsed, dict) else str(parsed)
            except json.JSONDecodeError:
                text = raw

        text = text.strip()
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        log.info(
            "stt_done",
            extra={"chars": len(text), "audio_seconds": duration, "took_ms": elapsed_ms},
        )
        if not text:
            raise SttError("Nothing was recognised in the recording", code="EMPTY_TRANSCRIPT")

        return {
            "transcript": text,
            "language": lang,
            "duration_ms": int(duration * 1000),
            "took_ms": elapsed_ms,
        }

    # ---- callback -------------------------------------------------------
    def sign(self, body: bytes) -> str:
        digest = hmac.new(
            self.settings.callback_secret.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()
        return f"sha256={digest}"

    def send_callback(self, callback_url: str, payload: dict[str, Any]) -> bool:
        """POSTs the result back, signed. Retries a few times, then gives up.

        Giving up is deliberate: the caller keeps its own record and can ask
        again, and an endless retry loop against a system that is down helps
        nobody.
        """
        if not callback_url:
            log.warning("callback_skipped_no_url", extra={"task": payload.get("task_id")})
            return False
        if not callback_url.lower().startswith(("http://", "https://")):
            log.error(
                "callback_url_not_absolute",
                extra={"url": callback_url, "task": payload.get("task_id")},
            )
            return False
        if not self.settings.callback_secret:
            log.error("callback_skipped_no_secret", extra={"task": payload.get("task_id")})
            return False

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "X-Process-Mining-Signature": self.sign(body),
        }

        for attempt in range(1, self.settings.callback_retries + 1):
            try:
                request = urllib.request.Request(
                    callback_url, data=body, headers=headers, method="POST"
                )
                with urllib.request.urlopen(
                    request, timeout=self.settings.callback_timeout_seconds
                ) as resp:
                    log.info(
                        "callback_delivered",
                        extra={"task": payload.get("task_id"), "status": resp.status},
                    )
                    return True
            except Exception as exc:  # noqa: BLE001 - any failure is retryable
                log.warning(
                    "callback_failed",
                    extra={
                        "task": payload.get("task_id"),
                        "attempt": attempt,
                        "error": str(exc)[:200],
                    },
                )
                if attempt < self.settings.callback_retries:
                    time.sleep(min(2**attempt, 8))

        log.error("callback_gave_up", extra={"task": payload.get("task_id")})
        return False
