from __future__ import annotations

import os

from agentic_tour_planner.config.settings import Settings


def configure_langsmith(settings: Settings) -> None:
    if not settings.langsmith_api_key:
        return
    os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    if settings.langsmith_endpoint:
        os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint
    os.environ["LANGSMITH_TRACING"] = "true" if settings.langsmith_tracing else "false"

