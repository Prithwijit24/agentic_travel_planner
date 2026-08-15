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
    app_name: str
    app_env: str
    log_level: str
    api_host: str
    enable_prometheus_metrics: bool
    default_llm_provider: str | None

    # ── Storage / knowledge paths (resolved to absolute Path at load) ─
    operations_db_path: Path | None

    # ── Context gathering ─────────────────────────────────────────
    redis_cache_enabled: bool
    retrieval_top_k: int
    request_timeout_seconds: float

    # ── External API keys (env-overridable, may be unset) ──────────
    google_maps_api_key: str | None
    openweather_api_key: str | None
    unsplash_access_key: str | None
    pexels_api_key: str | None

    # ── Image pipeline ─────────────────────────────────────────────
    image_openverse_enabled: bool
    image_mapillary_token: str | None
    image_cache_ttl_seconds: int
    image_request_timeout: int
    image_search_timeout: int
    image_max_concurrency: int
    image_waterfall_timeout: int
    image_commons_category_limit: int
    image_openverse_page_size: int
    image_mapillary_radius: int
    image_mapillary_limit: int
    image_unsplash_per_page: int
    image_pexels_per_page: int
    image_stack_max_results: int
    image_ddgs_max_results: int
    image_clip_threshold: float
    image_min_resolution: int
    image_max_aspect_ratio: float
    image_dedup_threshold: int
    image_nsfw_threshold: float
    image_smart_crop_enabled: bool

    # ── Pipeline orchestration ─────────────────────────────────────
    pipeline_daily_hour_budget: float
    pipeline_plan_timeout_seconds: int
    pipeline_sse_timeout_seconds: int
    pipeline_max_revisions: int
    pipeline_target_description_words: int
    pipeline_word_count_tolerance: int
    pipeline_daily_transport_budget_budget: int
    pipeline_daily_transport_budget_midrange: int
    pipeline_daily_transport_budget_luxury: int

    # ── Sequencing ─────────────────────────────────────────────────
    sequencing_avg_visit_hrs: float
    sequencing_daily_hour_budget: float

    # ── Travel constraints ─────────────────────────────────────────
    constraints_far_apart_km: float
    constraints_far_apart_min: float
    constraints_daily_travel_budget_min: float

    # ── Freshness agent ────────────────────────────────────────────
    freshness_threshold_days: int
    freshness_min_description_length: int

    # ── Budget agent (INR / person / day) ──────────────────────────
    budget_threshold_budget: int
    budget_threshold_midrange: int
    budget_threshold_luxury: int

    # ── Cost estimator (INR) ───────────────────────────────────────
    cost_hotel_rate_budget: float
    cost_hotel_rate_midrange: float
    cost_hotel_rate_luxury: float
    cost_food_rate_budget: float
    cost_food_rate_midrange: float
    cost_food_rate_luxury: float
    cost_transport_rate_public: float
    cost_transport_rate_car: float
    cost_hotel_prompt_budget: str
    cost_hotel_prompt_midrange: str
    cost_hotel_prompt_luxury: str
    cost_food_prompt_budget: str
    cost_food_prompt_midrange: str
    cost_food_prompt_luxury: str
    cost_transport_prompt: str
    cost_max_daily_per_person: float

    # ── News service ───────────────────────────────────────────────
    news_cache_ttl_seconds: int

    # ── Geocoding / map tool ───────────────────────────────────────
    geocode_timeout_seconds: float
    geocode_retries: int
    geocode_backoff_base: float
    nominatim_rate_limit_seconds: float
    geocode_circuit_breaker_threshold: int
    autocomplete_limit: int

    # ── LLM provider tuning ────────────────────────────────────────
    llm_call_timeout_seconds: float
    llm_planner_timeout_seconds: float
    llm_cooldown_rate_limit_floor: float
    llm_cooldown_timeout_floor: float
    llm_cooldown_max_seconds: float
    llm_gateway_error_hint_prefix_length: int

    # ── Graph DB loading ───────────────────────────────────────────
    graph_near_threshold_km: float
    graph_load_batch_size: int

    # ── Geonames ───────────────────────────────────────────────────
    geonames_suggestion_limit: int

    # ── Vector DB ──────────────────────────────────────────────────
    vectordb_collection_name: str
    vectordb_batch_size: int

    # ── API server ─────────────────────────────────────────────────
    api_port: int
    api_cors_origins: list[str] | None

    # ── Retrieval ──────────────────────────────────────────────────
    retrieval_api_top_k: int
    retrieval_api_max_poi_names: int

    # ── Planning workers (heuristic fallbacks) ────────────────────
    worker_daily_budget_budget: float
    worker_daily_budget_midrange: float
    worker_daily_budget_luxury: float
    worker_high_season_months: list[str] | None

    # ── LLM provider core ────────────────────────────────────────────
    llm_provider_priority: list[str] | None
    llm_gateway_error_hints: list[str] | None
    llm_prompt_field_providers: list[str] | None

    # ── Map tool ────────────────────────────────────────────────────
    map_day_colors: list[str] | None
    map_tile_opentopomap_url: str
    map_tile_cartopositon_url: str

    # ── Image sources ───────────────────────────────────────────────
    image_user_agent: str
    image_wikidata_api_url: str
    image_commons_api_url: str
    image_wikipedia_rest_url: str
    image_openverse_api_url: str

    # ── Cost estimator ticket classification ─────────────────────────
    cost_major_markers: list[str] | None
    cost_popular_markers: list[str] | None

    # ── API client defaults ─────────────────────────────────────────
    api_client_base_url: str
    api_client_admin_user: str

    # ── Place type classification ───────────────────────────────────
    place_type_markers: dict[str, list[str]] | None

    # ── CLI display ─────────────────────────────────────────────────
    cli_category_colors: dict[str, str] | None

    # ── LLM provider API key env-var aliases ─────────────────────────
    llm_api_key_aliases: dict[str, list[str]] | None

    # ── Wikivoyage listing templates ────────────────────────────────
    listing_templates: dict[str, str] | None

    # ── Streamlit UI ────────────────────────────────────────────────
    streamlit_api_base_url: str
    streamlit_keyword_colors: dict[str, str] | None

    def __init__(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            if key in _PATH_FIELDS and isinstance(value, str):
                value = _resolve_path(value)
            setattr(self, key, value)
        self.package_root = PACKAGE_ROOT
        self.project_root = PROJECT_ROOT

    def __getattr__(self, name: str) -> Any:
        """Return None for any config key not present in YAML.

        This makes Settings resilient to missing keys — removing a key from
        a YAML file will not crash the app; it just becomes None.
        """
        return None


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


def _load_prompt_files() -> dict[str, Any]:
    """Load prompt templates from prompts/*.md files.

    Each file maps to a UPPER_CASE settings attribute:
    ``planner_system_prompt.md`` → ``PLANNER_SYSTEM_PROMPT``.
    """
    config_dir = Path(__file__).parent
    prompts_dir = config_dir / "prompts"
    merged: dict[str, Any] = {}
    if not prompts_dir.is_dir():
        return merged
    for md_file in sorted(prompts_dir.glob("*.md")):
        key = md_file.stem.upper()
        merged[key] = md_file.read_text(encoding="utf-8").strip()
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
    prompt_data = _load_prompt_files()
    env_data = _coerce_env_overrides(yaml_data, _load_env_variables())
    merged = {**yaml_data, **prompt_data, **env_data}

    for key in _API_KEY_FIELDS | _PATH_FIELDS:
        merged.setdefault(key, None)

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
