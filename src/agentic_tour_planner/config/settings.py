from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "development"
    app_name: str = "Agentic Travel Planner"
    log_level: str = "INFO"
    enable_trace_logs: bool = False

    langsmith_tracing: bool = False
    langsmith_api_key: str | None = None
    langsmith_project: str = "agentic-travel-planner"
    langsmith_endpoint: str | None = None

    default_llm_provider: str = "openai"
    default_llm_model: str = "gpt-4o-mini"
    ollama_base_url: str = "http://localhost:11434"
    openai_api_key: str | None = None
    google_api_key: str | None = None
    openrouter_api_key: str | None = None
    xai_api_key: str | None = None
    api_base_url: str = "http://localhost:8000"
    streamlit_server_port: int = 8501

    web_search_backend: str = "duckduckgo"
    tavily_api_key: str | None = None
    serpapi_api_key: str | None = None
    youtube_api_key: str | None = None
    openweather_api_key: str | None = None
    google_maps_api_key: str | None = None

    vector_store_dir: Path = Field(default=Path("data/chroma"))
    knowledge_base_dir: Path = Field(default=Path("data/knowledge"))
    operations_db_path: Path = Field(default=Path("data/operations/plans.db"))
    request_timeout_seconds: float = 20.0
    crawl_max_concurrency: int = 4
    web_crawl_backend: str = "trafilatura"
    proxy_routing_strategy: str = "direct"
    outbound_proxy_urls: list[str] = Field(default_factory=list)
    crawl_user_agents: list[str] = Field(
        default_factory=lambda: [
            "Mozilla/5.0 (compatible; AgenticTravelPlanner/0.1; +https://example.local/bot)"
        ]
    )

    retrieval_top_k: int = 8
    rerank_top_k: int = 4
    chunk_size: int = 850
    chunk_overlap: int = 120
    embedding_model_name: str = "BAAI/bge-small-en-v1.5"
    collection_name: str = "travel_knowledge"
    enable_prometheus_metrics: bool = True
    evaluation_dir: Path = Field(default=Path("data/evaluation"))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.vector_store_dir.mkdir(parents=True, exist_ok=True)
    settings.knowledge_base_dir.mkdir(parents=True, exist_ok=True)
    (settings.knowledge_base_dir / "raw").mkdir(parents=True, exist_ok=True)
    (settings.knowledge_base_dir / "processed").mkdir(parents=True, exist_ok=True)
    settings.operations_db_path.parent.mkdir(parents=True, exist_ok=True)
    settings.evaluation_dir.mkdir(parents=True, exist_ok=True)
    return settings
