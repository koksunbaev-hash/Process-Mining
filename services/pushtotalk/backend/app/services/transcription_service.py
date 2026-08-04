"""Local speech-to-text using faster-whisper."""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_PROMPT = (
    "Р Р°СЃРїРѕР·РЅР°Р№ СЂСѓСЃСЃРєСѓСЋ РїСЂРѕРёР·РІРѕРґСЃС‚РІРµРЅРЅСѓСЋ СЂРµС‡СЊ. Р’ С‚РµРєСЃС‚Рµ РјРѕРіСѓС‚ РІСЃС‚СЂРµС‡Р°С‚СЊСЃСЏ "
    "Р»Р°С‚РёРЅСЃРєРёРµ РєРѕРґС‹ РїР°СЂС‚РёР№ РІСЂРѕРґРµ DEMO-B-0012, MOD-3321, QMS-100."
)


class TranscriptionUnavailableError(RuntimeError):
    """Whisper runtime is not installed or cannot load a model."""


class TranscriptionError(RuntimeError):
    """Audio could not be transcribed."""


@lru_cache(maxsize=1)
def _load_model():
    try:
        from faster_whisper import WhisperModel
    except ImportError as error:  # pragma: no cover - depends on optional package
        raise TranscriptionUnavailableError(
            "faster-whisper is not installed. Run: pip install -r requirements.txt"
        ) from error

    model_name = os.getenv("PTT_WHISPER_MODEL", "small")
    device = os.getenv("PTT_WHISPER_DEVICE", "cpu")
    compute_type = os.getenv("PTT_WHISPER_COMPUTE_TYPE", "int8")

    try:
        logger.info(
            "Loading faster-whisper model=%s device=%s compute_type=%s",
            model_name,
            device,
            compute_type,
        )
        return WhisperModel(model_name, device=device, compute_type=compute_type)
    except Exception as error:  # pragma: no cover - model/download environment
        raise TranscriptionUnavailableError(str(error)) from error


def transcribe_audio(audio_path: Path) -> str:
    """Transcribe an audio file and return normalized text."""
    if not audio_path.exists() or audio_path.stat().st_size == 0:
        raise TranscriptionError("empty audio file")

    model = _load_model()
    language = os.getenv("PTT_WHISPER_LANGUAGE", "ru") or None
    prompt = os.getenv("PTT_WHISPER_PROMPT", DEFAULT_PROMPT)

    try:
        segments, _info = model.transcribe(
            str(audio_path),
            language=language,
            initial_prompt=prompt,
            beam_size=5,
            vad_filter=True,
        )
        text = " ".join(segment.text.strip() for segment in segments if segment.text.strip()).strip()
    except Exception as error:  # pragma: no cover - decoder/audio environment
        raise TranscriptionError(str(error)) from error

    if not text:
        raise TranscriptionError("empty transcription")

    return text
