"""Activity normalization.

The old Streamlit prototype hardcoded Russian bakery keywords inside the UI
code. Here the same idea becomes data: YAML *profiles* with ordered rules
(exact / regex / keyword), so a new project only ships a new profile - no code
change, no redeploy of business logic.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.logging_config import get_logger

log = get_logger(__name__)


@dataclass(slots=True)
class Rule:
    activity: str
    keywords: tuple[str, ...] = ()
    patterns: tuple[re.Pattern[str], ...] = ()
    exact: tuple[str, ...] = ()

    def match(self, text: str) -> tuple[bool, str | None, float]:
        lowered = text.strip().lower()
        if lowered in self.exact:
            return True, "exact", 1.0
        for pattern in self.patterns:
            if pattern.search(text):
                return True, "regex:" + pattern.pattern, 0.9
        for keyword in self.keywords:
            if keyword in lowered:
                return True, "keyword:" + keyword, 0.75
        return False, None, 0.0


@dataclass(slots=True)
class MappingProfile:
    id: str
    description: str = ""
    fallback: str = "other_activity"
    passthrough: bool = False
    rules: list[Rule] = field(default_factory=list)

    def normalize(self, raw: str | None) -> tuple[str, str | None, float]:
        """Returns ``(activity, matched_rule, confidence)``."""
        if raw is None or not str(raw).strip():
            return self.fallback, None, 0.0
        text = str(raw)
        for rule in self.rules:
            matched, how, confidence = rule.match(text)
            if matched:
                return rule.activity, how, confidence
        if self.passthrough:
            return text.strip(), "passthrough", 0.5
        return self.fallback, None, 0.0

    @property
    def activities(self) -> list[str]:
        return sorted({rule.activity for rule in self.rules})


GENERIC = MappingProfile(
    id="generic",
    description="No normalization: activity labels are used as-is.",
    fallback="unknown",
    passthrough=True,
)


class MappingRegistry:
    """Thread-safe registry of profiles, hot-reloaded when the YAML file changes."""

    def __init__(self, config_path: Path, default_profile: str = "generic") -> None:
        self._path = Path(config_path)
        self._default = default_profile
        self._lock = threading.RLock()
        self._profiles: dict[str, MappingProfile] = {"generic": GENERIC}
        self._mtime: float | None = None
        self.reload()

    def reload(self) -> None:
        with self._lock:
            if not self._path.exists():
                log.warning("mapping_config_missing", extra={"path": str(self._path)})
                return
            try:
                raw = yaml.safe_load(self._path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as exc:
                log.error("mapping_config_invalid", extra={"error": str(exc)})
                return

            profiles: dict[str, MappingProfile] = {"generic": GENERIC}
            for profile_id, body in (raw.get("profiles") or {}).items():
                profiles[profile_id] = self._build_profile(profile_id, body or {})
            self._profiles = profiles
            self._mtime = self._path.stat().st_mtime
            log.info("mapping_config_loaded", extra={"profiles": list(profiles)})

    def _maybe_reload(self) -> None:
        if not self._path.exists():
            return
        mtime = self._path.stat().st_mtime
        if self._mtime is None or mtime > self._mtime:
            self.reload()

    @staticmethod
    def _build_profile(profile_id: str, body: dict[str, Any]) -> MappingProfile:
        rules: list[Rule] = []
        for entry in body.get("rules") or []:
            activity = entry.get("activity")
            if not activity:
                continue
            rules.append(
                Rule(
                    activity=str(activity),
                    keywords=tuple(str(k).lower() for k in entry.get("keywords") or ()),
                    patterns=tuple(
                        re.compile(str(p), re.IGNORECASE) for p in entry.get("patterns") or ()
                    ),
                    exact=tuple(str(e).lower() for e in entry.get("exact") or ()),
                )
            )
        return MappingProfile(
            id=profile_id,
            description=str(body.get("description") or ""),
            fallback=str(body.get("fallback") or "other_activity"),
            passthrough=bool(body.get("passthrough", False)),
            rules=rules,
        )

    def get(self, profile_id: str | None) -> MappingProfile:
        self._maybe_reload()
        with self._lock:
            key = profile_id or self._default
            return self._profiles.get(key) or self._profiles.get("generic") or GENERIC

    def list(self) -> list[MappingProfile]:
        self._maybe_reload()
        with self._lock:
            return sorted(self._profiles.values(), key=lambda p: p.id)
