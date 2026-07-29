from __future__ import annotations

from pathlib import Path

from app.core.mapping import MappingRegistry


def test_bakery_profile_normalizes_russian_speech():
    registry = MappingRegistry(Path("config/activities.yaml"))
    profile = registry.get("bakery")

    assert profile.normalize("начали замес теста")[0] == "start_mixing"
    assert profile.normalize("поставили на расстой")[0] == "proving"
    assert profile.normalize("вынимаем готовый хлеб")[0] == "unload_oven"


def test_unknown_text_falls_back():
    registry = MappingRegistry(Path("config/activities.yaml"))
    profile = registry.get("bakery")
    activity, rule, confidence = profile.normalize("кто-то уронил поднос")
    assert activity == "other_activity"
    assert rule is None
    assert confidence == 0.0


def test_generic_profile_is_passthrough():
    registry = MappingRegistry(Path("config/activities.yaml"))
    profile = registry.get("generic")
    assert profile.normalize("Anything At All")[0] == "Anything At All"
