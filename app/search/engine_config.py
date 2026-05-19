from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from app.config import get_settings


DEFAULT_GROUPS = {
    "general": ["bing_web", "duckduckgo_lite", "google_web", "brave_web"],
    "news": ["google_news_rss"],
    "reference": ["wikipedia"],
    "academic": ["arxiv"],
    "code": ["stackoverflow", "github"],
    "site": ["google_web", "bing_web", "duckduckgo_lite"],
}


@dataclass(slots=True)
class EngineConfig:
    groups: dict[str, list[str]] = field(default_factory=dict)
    disabled: set[str] = field(default_factory=set)
    header_profiles: dict[str, list[dict[str, str]]] = field(default_factory=dict)

    def group(self, key: str) -> list[str]:
        return [name for name in self.groups.get(key, []) if name not in self.disabled]

    def headers_for(self, engine_name: str) -> list[dict[str, str]]:
        return [dict(profile) for profile in self.header_profiles.get(engine_name, [])]


def load_engine_config(config_path: str | None = None) -> EngineConfig:
    path = Path(config_path or get_settings().search_engine_config_path)
    return _load_engine_config_cached(str(path.resolve()))


@lru_cache(maxsize=16)
def _load_engine_config_cached(resolved_path: str) -> EngineConfig:
    path = Path(resolved_path)
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(payload, dict):
        payload = {}

    groups = payload.get("groups") if isinstance(payload.get("groups"), dict) else {}
    normalized_groups = {
        str(name): [str(item).strip() for item in values if str(item).strip()]
        for name, values in groups.items()
        if isinstance(values, list)
    }
    for name, values in DEFAULT_GROUPS.items():
        normalized_groups.setdefault(name, list(values))

    disabled_raw = payload.get("disabled_engines")
    disabled = {str(item).strip() for item in disabled_raw if str(item).strip()} if isinstance(disabled_raw, list) else set()

    header_profiles_raw = payload.get("engine_headers")
    header_profiles: dict[str, list[dict[str, str]]] = {}
    if isinstance(header_profiles_raw, dict):
        for engine_name, profiles in header_profiles_raw.items():
            if not isinstance(profiles, list):
                continue
            normalized_profiles: list[dict[str, str]] = []
            for profile in profiles:
                if not isinstance(profile, dict):
                    continue
                normalized = {
                    str(key).strip(): str(value).strip()
                    for key, value in profile.items()
                    if str(key).strip() and str(value).strip()
                }
                if normalized:
                    normalized_profiles.append(normalized)
            if normalized_profiles:
                header_profiles[str(engine_name).strip()] = normalized_profiles

    return EngineConfig(groups=normalized_groups, disabled=disabled, header_profiles=header_profiles)
