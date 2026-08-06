from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values
from loguru import logger

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(__file__).resolve().parents[3]

_PATH_FIELDS = frozenset(
    {
        "operations_db_path",
    }
)

_API_KEY_FIELDS = frozenset(
    {
        "openweather_api_key",
        "google_maps_api_key",
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

    Every attribute is populated from YAML config files with optional
    env-var overrides. The annotations below document the settings that
    are accessed across the codebase so static type checkers can verify
    attribute access; instance attributes set from YAML always win.
    """

    # ── General / server ───────────────────────────────────────────
    app_name: str = "Agentic Travel Planner"
    app_env: str = "development"
    log_level: str = "INFO"
    api_host: str = "127.0.0.1"
    enable_prometheus_metrics: bool = True
    default_llm_provider: str | None = None

    # ── Storage / knowledge paths (resolved to absolute Path at load) ─
    operations_db_path: Path | None = None

    # Gates the AI Infra Stack /cache endpoints for image results (legacy name).
    redis_cache_enabled: bool = False

    # ── Context gathering ─────────────────────────────────────────
    retrieval_top_k: int = 8
    request_timeout_seconds: float = 20.0

    # ── External API keys (env-overridable, may be unset) ──────────
    google_maps_api_key: str | None = None
    openweather_api_key: str | None = None
    unsplash_access_key: str | None = None
    pexels_api_key: str | None = None

    # ── Image pipeline ─────────────────────────────────────────────
    image_openverse_enabled: bool = True
    image_mapillary_token: str | None = None
    image_cache_ttl_seconds: int = 2592000

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
        try:
            with yaml_file.open() as f:
                data = yaml.safe_load(f)
                if data:
                    merged.update(data)
        except yaml.YAMLError as e:
            logger.error(f"Failed to parse YAML file {yaml_file}: {e}")
            raise
    return merged


def _load_env_variables() -> dict[str, Any]:
    env_file = PROJECT_ROOT / ".env"
    env_values = dotenv_values(dotenv_path=env_file) if env_file.exists() else {}
    env_dict = {**env_values, **os.environ}

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
        try:
            if isinstance(default, bool):
                coerced[key] = str(value).strip().lower() in {"1", "true", "yes", "on"}
            elif isinstance(default, int) and not isinstance(default, bool):
                coerced[key] = int(value)
            elif isinstance(default, float):
                coerced[key] = float(value)
            elif isinstance(default, list) and isinstance(value, str):
                coerced[key] = [item.strip() for item in value.split(",") if item.strip()]
            elif isinstance(default, dict):
                # A scalar env var must never clobber a structured config block
                # (e.g. an LLM provider dict). This guards against accidental
                # collisions such as `OPENCODE=1` overwriting the `opencode`
                # provider in llm.yml.
                continue
            else:
                coerced[key] = value
        except (ValueError, TypeError):
            logger.warning(f"Failed to coerce env var {key}={value!r} to type {type(default).__name__}, using default")
            coerced[key] = default
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

    # ── Image pipeline defaults ─────────────────────────────────────
    merged.setdefault("image_clip_threshold", 0.22)
    merged.setdefault("image_min_resolution", 800)
    merged.setdefault("image_max_aspect_ratio", 2.5)
    merged.setdefault("image_cache_ttl_seconds", 2592000)  # 30 days
    merged.setdefault("image_dedup_threshold", 5)
    merged.setdefault("image_nsfw_threshold", 0.5)
    merged.setdefault("image_smart_crop_enabled", True)
    merged.setdefault("image_mapillary_token", None)
    merged.setdefault("image_openverse_enabled", True)
    merged.setdefault("llm_provider_cooldown_seconds", 30)
    merged.setdefault("llm_call_timeout_seconds", 120)
    merged.setdefault("llm_planner_timeout_seconds", 180)

    applied_overrides = [
        key
        for key in env_data
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

    db_path: Path | None = getattr(settings, "operations_db_path", None)
    if db_path is not None:
        db_path.parent.mkdir(parents=True, exist_ok=True)

    return settings


def clear_config():
    get_settings.cache_clear()
