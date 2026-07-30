"""Optional voice-to-event module.

Kept behind ``PM_VOICE_ENABLED`` and imported lazily: a Whisper model is ~1-6 GB
of RAM, and most consumers of this microservice will never touch it. Disabled,
the service stays small and starts in under a second.

Contract: audio in -> text + normalized activity out. The caller decides what
to do with it (usually POST it to ``/logs/{id}/events``).
"""

from __future__ import annotations

import tempfile
import threading
from pathlib import Path
from typing import Any

from app.config import Settings
from app.core.mapping import MappingRegistry
from app.errors import FeatureDisabledError, ValidationError
from app.logging_config import get_logger

log = get_logger(__name__)

SUPPORTED_SUFFIXES = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".webm", ".mp4"}


class TranscriptionService:
    def __init__(self, settings: Settings, mappings: MappingRegistry) -> None:
        self.settings = settings
        self.mappings = mappings
        self._model: Any = None
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.settings.voice_enabled

    def _ensure_model(self) -> Any:
        if not self.enabled:
            raise FeatureDisabledError(
                "Voice module is disabled. Start the service with PM_VOICE_ENABLED=true "
                "and install extras: pip install '.[voice]'"
            )
        if self._model is None:
            with self._lock:
                if self._model is None:
                    try:
                        import whisper
                    except ImportError as exc:
                        raise FeatureDisabledError(
                            "openai-whisper is not installed. pip install '.[voice]'"
                        ) from exc
                    log.info("whisper_loading", extra={"model": self.settings.whisper_model})
                    self._model = whisper.load_model(self.settings.whisper_model)
                    log.info("whisper_loaded")
        return self._model

    def transcribe(
        self,
        payload: bytes,
        filename: str,
        *,
        language: str | None = None,
        mapping_profile: str | None = None,
    ) -> dict[str, Any]:
        suffix = Path(filename or "audio.wav").suffix.lower() or ".wav"
        if suffix not in SUPPORTED_SUFFIXES:
            raise ValidationError(
                f"Unsupported audio format '{suffix}'. Allowed: {sorted(SUPPORTED_SUFFIXES)}"
            )

        model_obj = self._ensure_model()
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
            handle.write(payload)
            tmp_path = Path(handle.name)
        try:
            result = model_obj.transcribe(
                str(tmp_path),
                language=language or self.settings.whisper_language,
                fp16=False,
            )
        finally:
            tmp_path.unlink(missing_ok=True)

        text = str(result.get("text", "")).strip()
        segments = result.get("segments") or []
        duration = float(segments[-1]["end"]) if segments else 0.0

        profile = self.mappings.get(mapping_profile)
        activity, matched_rule, confidence = profile.normalize(text)

        return {
            "text": text,
            "language": str(result.get("language") or language or self.settings.whisper_language),
            "duration_seconds": round(duration, 3),
            "activity": activity if text else None,
            "activity_confidence": confidence if text else None,
            "matched_rule": matched_rule,
        }
