from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any
from dotenv import dotenv_values

from loguru import logger

import yaml

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(__file__).resolve().parents[3]

_PATH_FIELDS = frozenset(
    {
        "vector_store_dir",
        "knowledge_base_dir",
        "operations_db_path",
        "evaluation_dir",
        "wikivoyage_dump_path",
    }
)

_API_KEY_FIELDS = frozenset(
    {
        "langsmith_api_key",
        "openai_api_key",
        "google_api_key",
        "openrouter_api_key",
        "xai_api_key",
        "tavily_api_key",
        "serp_api_key",
        "serpapi_api_key",
        "youtube_api_key",
        "openweather_api_key",
        "google_maps_api_key",
        "google_places_api_key",
        "unsplash_access_key",
        "pexels_api_key",
    }
)

_SECRET_NAME_FRAGMENTS = ("password", "secret", "token", "_api_key", "apikey", "api_key")


def _is_secret_field(name: str) -> bool:
    lowered = name.lower()
    return any(frag in lowered for frag in _SECRET_NAME_FRAGMENTS)


class Settings:
    """Configuration loaded entirely from per-module YAML files.

    No field declarations — every attribute is populated from YAML
    config files with optional env-var overrides.
    """

    def __init__(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            if key in _PATH_FIELDS and isinstance(value, str):
                value = _resolve_path(value)
            setattr(self, key, value)
        self.package_root = PACKAGE_ROOT
        self.project_root = PROJECT_ROOT


def _resolve_path(value: str | Path | None) -> Path | None:
    if value is None:
        return None
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _load_yaml_configs() -> dict[str, Any]:
    config_dir = Path(__file__).parent
    merged: dict[str, Any] = {}
    for yaml_file in sorted(config_dir.glob("*.yml")):
        with open(yaml_file) as f:
            data = yaml.safe_load(f)
            if data:
                merged.update(data)
    return merged


def _load_env_variables() -> dict[str, Any]:
    env_dict = {**dotenv_values(), **os.environ}

    overrides: dict[str, Any] = {}
    for env_key in env_dict:
        key_lower = env_key.lower().replace("-", "_")
        overrides[key_lower] = env_dict.get(env_key)

    return overrides


def _coerce_env_overrides(yaml_data: dict[str, Any], env_data: dict[str, Any]) -> dict[str, Any]:
    coerced: dict[str, Any] = {}
    for key, value in env_data.items():
        if key not in yaml_data:
            coerced[key] = value
            continue
        default = yaml_data[key]
        if isinstance(default, bool):
            coerced[key] = str(value).strip().lower() in {"1", "true", "yes", "on"}
        elif isinstance(default, int) and not isinstance(default, bool):
            coerced[key] = int(value)
        elif isinstance(default, float):
            coerced[key] = float(value)
        elif isinstance(default, list) and isinstance(value, str):
            coerced[key] = [item.strip() for item in value.split(",") if item.strip()]
        else:
            coerced[key] = value
    return coerced


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    logger.debug("Loading application configuration")
    yaml_data = _load_yaml_configs()
    env_data = _coerce_env_overrides(yaml_data, _load_env_variables())
    merged = {**yaml_data, **env_data}

    for key in _API_KEY_FIELDS | _PATH_FIELDS:
        merged.setdefault(key, None)
    merged.setdefault("image_provider", "unsplash")

    applied_overrides = [
        key for key in env_data
        if key in yaml_data
        and key not in _API_KEY_FIELDS
        and not _is_secret_field(key)
        and env_data.get(key) is not None
    ]
    for key in applied_overrides:
        logger.info(f"Env override applied for {key}")

    settings = Settings(**merged)

    logger.debug(
        f"Config loaded: app_env={getattr(settings, 'app_env', '<unset>')}, "
        f"default_llm_provider={getattr(settings, 'default_llm_provider', '<unset>')}"
    )

    settings.vector_store_dir.mkdir(parents=True, exist_ok=True)
    settings.knowledge_base_dir.mkdir(parents=True, exist_ok=True)
    (settings.knowledge_base_dir / "raw").mkdir(parents=True, exist_ok=True)
    (settings.knowledge_base_dir / "processed").mkdir(parents=True, exist_ok=True)
    settings.operations_db_path.parent.mkdir(parents=True, exist_ok=True)
    settings.evaluation_dir.mkdir(parents=True, exist_ok=True)

    return settings


def clear_config():
    get_settings.cache_clear()
