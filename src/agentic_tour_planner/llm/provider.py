from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from tenacity import retry, stop_after_attempt, wait_exponential

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.domain.models import PlanningRequest
from agentic_tour_planner.observability.langsmith import configure_langsmith

try:
    from langchain_google_genai import ChatGoogleGenerativeAI
except Exception:  # pragma: no cover
    ChatGoogleGenerativeAI = None
try:
    from langchain_ollama import ChatOllama
except Exception:  # pragma: no cover
    ChatOllama = None
try:
    from langchain_openai import ChatOpenAI
except Exception:  # pragma: no cover
    ChatOpenAI = None


class LLMProvider:
    def __init__(self) -> None:
        self.settings = get_settings()
        configure_langsmith(self.settings)

    def resolve_provider(self, request: PlanningRequest) -> tuple[str, str]:
        provider = request.provider or self.settings.default_llm_provider
        model = request.model or self.settings.default_llm_model
        return provider, model

    def _api_key_for(self, provider: str) -> str | None:
        return {
            "openai": self.settings.openai_api_key,
            "google": self.settings.google_api_key,
            "openrouter": self.settings.openrouter_api_key,
            "xai": self.settings.xai_api_key,
        }.get(provider)

    def _base_url_for(self, provider: str) -> str | None:
        if provider == "ollama":
            return self.settings.ollama_base_url
        if provider == "openrouter":
            return "https://openrouter.ai/api/v1"
        if provider == "xai":
            return "https://api.x.ai/v1"
        return None

    def _build_chat_model(self, provider: str, model: str):
        if provider in {"openai", "openrouter", "xai"} and ChatOpenAI:
            if not self._api_key_for(provider):
                return None
            kwargs: dict[str, Any] = {"model": model, "api_key": self._api_key_for(provider)}
            base_url = self._base_url_for(provider)
            if base_url:
                kwargs["base_url"] = base_url
            return ChatOpenAI(**kwargs)
        if provider == "google" and ChatGoogleGenerativeAI:
            if not self.settings.google_api_key:
                return None
            return ChatGoogleGenerativeAI(model=model, google_api_key=self.settings.google_api_key)
        if provider == "ollama" and ChatOllama:
            return ChatOllama(model=model, base_url=self.settings.ollama_base_url)
        return None

    def _langchain_config(self) -> dict[str, Any]:
        return {"tags": ["travel-planner"], "metadata": {"app_env": self.settings.app_env}}

    @staticmethod
    def _coerce_content(result: Any) -> str:
        content = getattr(result, "content", result)
        if isinstance(content, list):
            return "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
        return str(content)

    @retry(wait=wait_exponential(min=1, max=8), stop=stop_after_attempt(3))
    async def complete_json(self, prompt: str, request: PlanningRequest) -> dict[str, Any]:
        provider, model = self.resolve_provider(request)
        chat_model = self._build_chat_model(provider, model)
        if not chat_model:
            return self._fallback_json(prompt, request)
        parser = JsonOutputParser()
        try:
            result = await chat_model.ainvoke(
                [
                    SystemMessage(content="Return strict JSON only. Do not wrap in markdown."),
                    HumanMessage(content=prompt),
                ],
                config=self._langchain_config(),
            )
            text = self._coerce_content(result)
            return parser.parse(text)
        except Exception:
            return self._fallback_json(prompt, request)

    def _fallback_json(self, prompt: str, request: PlanningRequest) -> dict[str, Any]:
        days = []
        interests = request.interests or ["landmarks", "food", "walks"]
        for day in range(1, request.trip_length_days + 1):
            theme = interests[(day - 1) % len(interests)].title()
            days.append(
                {
                    "day": day,
                    "theme": f"{theme} in {request.destination}",
                    "morning": [f"Explore a {theme.lower()} anchor area."],
                    "afternoon": [f"Visit a second {theme.lower()} venue and lunch nearby."],
                    "evening": ["Wrap with a scenic walk and local dinner."],
                    "meals": ["Breakfast near hotel", "Lunch in activity zone", "Dinner in lively district"],
                    "logistics": ["Use one neighborhood cluster per half day."],
                }
            )
        return {
            "overview": f"A {request.trip_length_days}-day {request.destination} itinerary balanced around {', '.join(interests)}.",
            "itinerary": days,
            "practical_tips": [
                "Reconfirm hours for reservation-heavy attractions.",
                "Keep weather-flexible indoor alternatives ready.",
            ],
            "citations": [],
        }
