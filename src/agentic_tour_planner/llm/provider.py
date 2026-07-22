from __future__ import annotations

import json
import re
import time
from typing import Any

from litellm import acompletion

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.domain.models import PlanningRequest
from agentic_tour_planner.llm.hooks import CallMetrics, metrics_bus
from agentic_tour_planner.tools.calculator import CALCULATOR_TOOL, run_calculator
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)

# System prompts for worker agents - concise JSON format
ROUTE_PROMPT = (
    'Return ONLY JSON: {"strategy": "string", "cluster_advice": ["string"], "transit_notes": ["string"]}'
)
BUDGET_PROMPT = (
    'Return ONLY JSON: {"estimated_daily_budget": number, "estimated_total_budget": number, '
    '"assumptions": ["string"], "saving_tips": ["string"]}'
)
TIMING_PROMPT = (
    'Return ONLY JSON: {"season_summary": "string", "booking_window": "string", "day_planning_notes": ["string"]}'
)

PLANNER_SYSTEM_PROMPT = (
    "You are a travel itinerary generator. Return strict JSON only, no markdown or code fences. "
    "The JSON must include: overview (string), monthly_weather (string, a 1-2 sentence estimate for the travel month), "
    "itinerary (list of day objects), practical_tips (list of strings), citations (list of objects with keys title and url, or a list of strings). "
    "Every morning/afternoon/evening/meals/logistics value must be a list of strings, never a single string.\n"
    "\n"
    "TIME WINDOWS: Prefix or embed a concrete time window in every activity string, e.g. "
    "'Visit Fushimi Inari Shrine (Morning 6:00-8:30): climb the vermilion torii gates before crowds'. "
    "Use realistic windows: Morning 6:00-8:30, Late Morning 8:30-11:00, Midday 11:00-13:00, "
    "Afternoon 14:00-16:30, Late Afternoon 16:30-18:30, Evening 19:00-21:30.\n"
    "\n"
    "RETURN DAY: The final day is the return/departure day. Do NOT schedule any attractions, meals, or activities on it. "
    "Set its morning/afternoon/evening to empty lists, theme to 'Departure / Return Travel', and put only a logistics note "
    "about checkout and airport/station transfer. Still include its weather block.\n"
    "\n"
    "Each itinerary day object must have keys: day (integer), theme (string), morning, afternoon, evening, meals, logistics "
    "(each a list of strings), weather, spots, needs_hotel_change, hotel_recommendation. "
    "weather is an object: {temperature_c (number, daytime), temperature_night_c (number, nighttime), "
    "sunrise (string like '06:12'), sunset (string like '18:45'), humidity_percent (integer), "
    "rainfall_chance_percent (integer)} estimated for the travel month. "
    "spots is a list of objects, one per notable place scheduled that day, each: "
    "{name (string), slot (one of 'morning'|'afternoon'|'evening'), history (1-2 sentence history), "
    "opening_hours (string like '09:00'), closing_hours (string like '17:00'), "
    "best_time (ideal visiting window, e.g. 'Morning 6:00-8:30'), "
    "description (1-2 sentence note on the scenic beauty)}. Use the exact same place name in the matching activity string. "
    "Include a top-level transport_options list (mode, description, fare, notes) when public transport is relevant.\n"
    "\n"
    "STRICT PLANNING RULES — you MUST obey these exactly on every plan:\n"
    "• PLACES PER DAY MINIMUM: Always schedule AT LEAST the number of places the user requested per day. "
    "If they request 6-7, every regular day MUST contain at least 6 distinct notable places — never fewer. "
    "Populate the 'spots' list with the same minimum count. (The final return/departure day is the only "
    "exception and stays attraction-free.)\n"
    "• TRIP-LENGTH ROUTING STRATEGY:\n"
    "  - 2-3 days: stay compact — wander the nearer places around a single base; minimise long transfers.\n"
    "  - 4-6 days: cover the main sights AND add 1-2 offbeat / lesser-known places in addition to the popular ones.\n"
    "  - 11-12+ days: split the stay across TWO OR MORE distinct regions/areas of the destination "
    "(e.g. Andaman: first 5-6 days in one area, then move to a different region such as the north for the rest). "
    "Apply this region-split principle to any long trip.\n"
    "  - Other lengths: follow the route strategy while keeping the trip coherent.\n"
)

# Provider fallback priority (first = preferred). Ollama is optional and skipped by default.
# Order is intentionally "most reliable cloud gateway first" so real generation succeeds fast;
# the local-only (omniroute) and placeholder (gemini) entries are tried later in the cascade.
PROVIDER_PRIORITY = [
    "openrouter",
    "agnes",
    "nvidia",
    "llm7io",
    "morphllm",
    "grokai",
    "omniroute",
    "gemini",
    "ollama",
]

# API-key env-var aliases per provider (handles typos / vendor naming in .env)
API_KEY_ALIASES = {
    "omniroute": ["omniroute_api_key", "omnirute_api_key"],
    "openrouter": ["openrouter_api_key"],
    "grokai": ["grokai_api_key", "groqai_api_key"],
    "agnes": ["agnes_api_key"],
    "nvidia": ["nvidia_api_key"],
    "llm7io": ["llm7io_api_key"],
    "morphllm": ["morphllm_api_key"],
    "gemini": ["gemini_api_key"],
    "ollama": ["ollama_api_key"],
}

# Vendor prefixes that should be stripped when a model is routed through a *native*
# (non OpenAI-compatible) litellm provider such as gemini or groq.
_NATIVE_VENDOR_PREFIXES = {
    "openai",
    "google",
    "qwen",
    "meta",
    "mistral",
    "anthropic",
    "deepseek",
    "nvidia",
}

_PING_PROMPT = (
    'Reply with strictly valid JSON only, no markdown: {"ok": true, "pong": "hello"}'
)


class LLMProvider:
    """Multi-provider LLM layer backed by litellm with automatic fallback routing.

    Reads the provider registry from ``llm.yml``. Each provider declares an
    ``api_type`` (``openai`` | ``gemini`` | ``groq``) and a ``base_url``. For
    ``openai``-type gateways we route through litellm's OpenAI-compatible client
    (``openai/<model>`` + ``api_base``). For ``gemini``/``groq`` we use litellm's
    native provider (``gemini/<model>`` / ``groq/<model>``) with the vendor API key.

    For planner/worker requests it tries each provider in ``PROVIDER_PRIORITY``
    order, and within a provider each candidate model, falling back to the next on
    any failure. Ollama is optional and skipped by default.
    """

    def __init__(self, include_ollama: bool = False) -> None:
        self.settings = get_settings()
        self.include_ollama = include_ollama
        self.providers = self._load_providers()
        self.timeout = 120
        # Provider/model that actually produced the most recent result, per role.
        self.last_planner: tuple[str, str] | None = None
        self.last_worker: tuple[str, str] | None = None
        logger.debug("LLMProvider initialized providers={} include_ollama={}", list(self.providers.keys()), include_ollama)

    # ------------------------------------------------------------------ config
    def _load_providers(self) -> dict[str, dict[str, Any]]:
        logger.debug("_load_providers start")
        # Discover provider configs from settings: any dict attribute that looks
        # like an LLM provider entry (has a base_url AND a planner/worker model).
        found: dict[str, dict[str, Any]] = {}
        for name, value in vars(self.settings).items():
            if not isinstance(value, dict):
                continue
            if "base_url" not in value:
                continue
            if "planner_model" not in value and "worker_model" not in value:
                continue
            found[name] = value

        # Order by PROVIDER_PRIORITY first, then any extra providers discovered.
        priority = [p for p in PROVIDER_PRIORITY if p in found]
        extras = [p for p in found if p not in PROVIDER_PRIORITY]
        ordered = priority + extras
        logger.debug("_load_providers found={}", ordered)
        return {p: found[p] for p in ordered}

    def _api_key_for(self, provider: str) -> str | None:
        for attr in API_KEY_ALIASES.get(provider, [f"{provider}_api_key"]):
            key = getattr(self.settings, attr, None)
            if key:
                logger.debug("_api_key_for provider={} key=<set>", provider)
                return str(key)
        logger.debug("_api_key_for provider={} key=<unset>", provider)
        return None

    def _provider_chain(self) -> list[str]:
        chain = [p for p in PROVIDER_PRIORITY if p in self.providers]
        # Honour the configured default provider (llm.yml `default_llm_provider`):
        # try it first so a reliable default isn't buried behind a flaky one.
        default = getattr(self.settings, "default_llm_provider", None)
        if default and default in chain:
            chain = [default] + [p for p in chain if p != default]
        if self.include_ollama and "ollama" not in chain:
            chain.append("ollama")
        return chain

    def _chain_for(self, provider_override: str | None, role: str, model_override: str | None = None) -> list[tuple[str, str]]:
        """Build the (provider, model) attempt order. An explicit provider selection is
        tried first (sticky), then the remaining providers in priority order as a
        fallback so a flaky provider does not break the pipeline. An unknown explicit
        provider falls back to the default chain (with a warning)."""
        logger.debug("_chain_for provider_override={} role={} model_override={}", provider_override, role, model_override)
        if provider_override and provider_override in self.providers:
            models = self._models_for(provider_override, role)
            if model_override:
                models = [m for m in models if m != model_override] 
                models = [model_override] + models
            rest = [p for p in self._provider_chain() if p != provider_override]
            return [(provider_override, m) for m in models] + \
                   [(p, m) for p in rest for m in self._models_for(p, role)]
        if provider_override:
            logger.warning(f"[LLM] Unknown provider {provider_override!r}; using default chain")
        return [(p, m) for p in self._provider_chain() for m in self._models_for(p, role)]

    def list_providers(self) -> list[str]:
        return list(self.providers.keys())

    def list_models(self, provider: str) -> list[str]:
        """All candidate models (planner + worker) declared for a provider, de-duplicated."""
        cfg = self.providers.get(provider, {})
        models: list[str] = []
        for role in ("planner_model", "worker_model"):
            value = cfg.get(role)
            if isinstance(value, str):
                models.append(value)
            elif isinstance(value, list):
                models.extend(m for m in value if m)
        seen: set[str] = set()
        out: list[str] = []
        for m in models:
            if m not in seen:
                seen.add(m)
                out.append(m)
        return out

    # --------------------------------------------------------------- resolution
    def get_planner_model(self) -> tuple[str, str]:
        """Return the primary (preferred) planner provider/model for display/logging."""
        for provider in self._provider_chain():
            cfg = self.providers[provider]
            model = cfg.get("planner_model")
            if isinstance(model, list):
                model = model[0]
            if model:
                return provider, model
        return "none", "none"

    def get_worker_model(self) -> tuple[str, str]:
        """Return the primary (preferred) worker provider/model for display/logging."""
        for provider in self._provider_chain():
            cfg = self.providers[provider]
            model = cfg.get("worker_model")
            if isinstance(model, list):
                model = model[0]
            if model:
                return provider, model
        return "none", "none"

    def _models_for(self, provider: str, role: str) -> list[str]:
        cfg = self.providers.get(provider, {})
        model = cfg.get(f"{role}_model")
        if model is None:
            return []
        if isinstance(model, str):
            return [model]
        if isinstance(model, list):
            return [m for m in model if m]
        return []

    # ------------------------------------------------------------- last-used meta
    def last_planner_used(self) -> tuple[str, str]:
        """Provider/model that actually generated the most recent planner result."""
        return self.last_planner or ("unknown", "unknown")

    def last_worker_used(self) -> tuple[str, str]:
        """Provider/model that actually generated the most recent worker result."""
        return self.last_worker or ("unknown", "unknown")

    # ------------------------------------------------------------------- helpers
    @staticmethod
    def _extract_json(text: str) -> str:
        """Extract JSON from text that may contain markdown or other content."""
        text = re.sub(r"```json\s*", "", text)
        text = re.sub(r"```\s*$", "", text)
        text = re.sub(r"```", "", text)
        return text.strip()

    @staticmethod
    def _strip_vendor(model: str) -> str:
        """Strip a leading ``<vendor>/`` prefix for native (gemini/groq) routing."""
        if "/" in model:
            head = model.split("/", 1)[0].lower()
            if head in _NATIVE_VENDOR_PREFIXES:
                return model.split("/", 1)[1]
        return model

    @staticmethod
    def _normalize_model(model: str) -> str:
        """Make a model name safe for litellm against a custom OpenAI-compatible base.

        Every ``openai``-type provider in llm.yml is an OpenAI-compatible gateway, so
        we always call litellm with the ``openai/<model>`` form and pass ``api_base``.
        If the model already carries an ``openai/`` prefix it is passed through
        unchanged; otherwise we prepend ``openai/`` so litellm routes it to the custom
        base (e.g. ``auto/best-chat`` becomes ``openai/auto/best-chat``).
        """
        if model.startswith("openai/"):
            return model
        return f"openai/{model}"

    @staticmethod
    def _coerce_list(value: Any) -> list[Any]:
        if isinstance(value, list):
            return value
        return [value]

    @staticmethod
    def _classify_error(exc: Exception) -> str:
        etype = type(exc).__name__
        msg = str(exc).lower()
        if "timeout" in msg or etype in ("Timeout", "APITimeoutError"):
            return "timeout"
        if "rate" in msg or "429" in msg or etype in ("RateLimitError", "BadRequestError"):
            return "rate_limit"
        if "auth" in msg or "401" in msg or "key" in msg:
            return "auth"
        if "connect" in msg or "connection" in msg or etype in ("APIConnectionError",):
            return "connection"
        return "error"


    def _litellm_model_and_base(self, provider: str, model: str) -> tuple[str, str | None]:
        cfg = self.providers.get(provider, {})
        api_type = (cfg.get("api_type") or "openai").lower()
        if api_type == "gemini":
            return f"gemini/{self._strip_vendor(model)}", None
        if api_type == "groq":
            return f"groq/{self._strip_vendor(model)}", None
        # openai (default) + any unknown type: route through OpenAI-compatible client.
        return self._normalize_model(model), cfg.get("base_url")

    # ------------------------------------------------------------ metrics + core liteLLM call
    def _record(
        self,
        provider: str,
        model: str,
        role: str,
        elapsed: float,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        ok: bool,
        error_type: str | None,
    ) -> None:
        logger.debug("_record provider={} model={} role={} ok={} total_tokens={}", provider, model, role, ok, total_tokens)
        metrics_bus.record(
            CallMetrics(
                provider=provider,
                model=model,
                role=role,
                latency_s=elapsed,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                ok=ok,
                error_type=error_type,
            )
        )

    async def _litellm_complete(
        self,
        *,
        provider: str,
        model: str,
        messages: list[dict[str, str]],
        timeout: int | None = None,
        role: str = "worker",
    ) -> str | None:
        lm_model, base_url = self._litellm_model_and_base(provider, model)
        api_key = self._api_key_for(provider)
        # OpenAI-compatible gateways need *some* api_key value even if the server
        # ignores it; pass a placeholder rather than None to avoid litellm errors.
        if base_url and not api_key:
            api_key = "sk-noauth"
        logger.info("[LLM] calling provider={} model={} role={} api_key=<set>", provider, lm_model, role)
        started = time.perf_counter()
        try:
            response = await acompletion(
                model=lm_model,
                messages=messages,
                api_base=base_url,
                api_key=api_key,
                timeout=timeout or self.timeout,
                temperature=0,
            )
            elapsed = time.perf_counter() - started
            usage = getattr(response, "usage", None)
            prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
            completion_tokens = getattr(usage, "completion_tokens", 0) or 0
            total_tokens = getattr(usage, "total_tokens", 0) or 0
            self._record(provider, model, role, elapsed, prompt_tokens, completion_tokens, total_tokens, True, None)
            content = response.choices[0].message.content
            logger.debug(f"[LLM] {provider}/{model} ok latency={elapsed:.3f}s tokens={total_tokens}")
            return content if isinstance(content, str) else (content or "")
        except Exception as exc:  # noqa: BLE001 - fallback routing handles all failures
            elapsed = time.perf_counter() - started
            self._record(provider, model, role, elapsed, 0, 0, 0, False, self._classify_error(exc))
            logger.warning(f"[LLM] {provider}/{model} failed: {exc}")
            return None

    # ------------------------------------------------------------- provider testing
    async def test_provider_model(
        self,
        provider: str,
        model: str,
        role: str = "worker",
        prompt: str | None = None,
        timeout: int = 45,
    ) -> dict[str, Any]:
        """Probe a single provider/model pair. Returns a status report dict."""
        logger.debug("test_provider_model start provider={} model={} role={}", provider, model, role)
        system_prompt = {
            "route": ROUTE_PROMPT,
            "budget": BUDGET_PROMPT,
            "timing": TIMING_PROMPT,
            "planner": PLANNER_SYSTEM_PROMPT,
        }.get(role, "Return strict JSON only. Do not wrap in markdown.")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt or _PING_PROMPT},
        ]
        lm_model, base_url = self._litellm_model_and_base(provider, model)
        api_key = self._api_key_for(provider)
        if base_url and not api_key:
            api_key = "sk-noauth"

        started = time.perf_counter()
        try:
            response = await acompletion(
                model=lm_model,
                messages=messages,
                api_base=base_url,
                api_key=api_key,
                timeout=timeout,
                temperature=0,
            )
            content = response.choices[0].message.content
            content = content if isinstance(content, str) else (content or "")
            elapsed = time.perf_counter() - started
            # Try to parse JSON to confirm it is usable output.
            parse_ok = False
            try:
                json.loads(self._extract_json(content))
                parse_ok = True
            except Exception:  # noqa: BLE001
                parse_ok = False
            return {
                "provider": provider,
                "model": model,
                "litellm_model": lm_model,
                "status": "ok" if parse_ok else "unparsed",
                "latency_s": round(elapsed, 2),
                "parse_ok": parse_ok,
                "error": None,
                "error_type": None,
                "sample": content[:200],
            }
        except Exception as exc:  # noqa: BLE001
            elapsed = time.perf_counter() - started
            logger.debug("test_provider_model failed provider={} model={} error_type={}", provider, model, self._classify_error(exc))
            return {
                "provider": provider,
                "model": model,
                "litellm_model": lm_model,
                "status": "failed",
                "latency_s": round(elapsed, 2),
                "parse_ok": False,
                "error": f"{type(exc).__name__}: {exc}"[:300],
                "error_type": self._classify_error(exc),
                "sample": None,
            }

    @staticmethod
    def _classify_error(exc: Exception) -> str:
        """Bucket a litellm failure into a human-readable cause category."""
        text = f"{type(exc).__name__}: {exc}".lower()
        if "ratelimit" in text or "429" in text or "quota" in text:
            return "rate_limited"
        if "authentication" in text or "401" in text or "auth" in text or "invalid api key" in text:
            return "auth"
        if "notfound" in text or "404" in text or "does not exist" in text or "not found" in text:
            return "not_found"
        if "connection" in text or "ssl" in text or "certificate" in text or "timeout" in text or "timed out" in text:
            return "unreachable"
        return "other"

    # ------------------------------------------------------- public completion APIs
    async def complete_json(
        self,
        prompt: str,
        request: PlanningRequest | None = None,
        system_prompt: str | None = None,
    ) -> dict[str, Any]:
        logger.info("complete_json start role=planner prompt_len={}", len(prompt))
        messages = [
            {"role": "system", "content": system_prompt or PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        # An explicit provider selection (from the CLI/UI) is tried first (sticky),
        # but if it fails we fall through the remaining providers in priority order
        # instead of dropping straight to the heuristic. Only if EVERY provider fails
        # do we use the heuristic fallback.
        explicit_provider = (
            request.provider if (request and getattr(request, "provider", None)) else None
        )
        model_override = (
            request.planner_model if (request and getattr(request, "planner_model", None)) else None
        )
        chain = [(p, m) for p in self._provider_chain() for m in self._models_for(p, "planner")]
        if explicit_provider:
            if explicit_provider in self.providers:
                rest = [p for p in self._provider_chain() if p != explicit_provider]
                models = self._models_for(explicit_provider, "planner")
                if model_override:
                    models = [m for m in models if m != model_override]
                    models = [model_override] + models
                chain = [(explicit_provider, m) for m in models] + \
                        [(p, m) for p in rest for m in self._models_for(p, "planner")]
            else:
                logger.warning(f"[LLM] Unknown provider {explicit_provider!r}; using default chain")

        for provider, model in chain:
            content = await self._litellm_complete(provider=provider, model=model, messages=messages, role="planner")
            if content is None:
                continue
            try:
                result = json.loads(self._extract_json(content))
                self.last_planner = (provider, model)
                logger.debug("complete_json success provider={} model={}", provider, model)
                return result
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[LLM] JSON parse failed for {provider}/{model}: {exc}")
                continue
        logger.error("[LLM] All planner providers failed (tried {}); using heuristic fallback", ", ".join(p for p, _ in chain))
        self.last_planner = ("fallback", "heuristic")
        return self._fallback_json(prompt, request)

    async def complete_structured(
        self,
        prompt: str,
        worker_type: str,
        provider_override: str | None = None,
        model_override: str | None = None,
    ) -> dict[str, Any]:
        logger.info("complete_structured start worker_type={} provider_override={} model_override={}", worker_type, provider_override, model_override)
        system_prompt = {
            "route": ROUTE_PROMPT,
            "budget": BUDGET_PROMPT,
            "timing": TIMING_PROMPT,
        }.get(worker_type, "Return strict JSON only. Do not wrap in markdown.")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        # An explicit provider selection is sticky: try only that provider's own
        # models and never spill over to other providers (e.g. openrouter).
        chain = self._chain_for(provider_override, "worker", model_override=model_override)

        for provider, model in chain:
            content = await self._litellm_complete(provider=provider, model=model, messages=messages, role="worker")
            if content is None:
                continue
            try:
                result = json.loads(self._extract_json(content))
                self.last_worker = (provider, model)
                logger.debug("complete_structured success provider={} model={}", provider, model)
                return result
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[LLM] structured parse failed {provider}/{model}: {exc}")
                continue
        logger.error(f"[LLM] All worker providers failed for {worker_type}")
        self.last_worker = ("fallback", "heuristic")
        return {"error": "All providers failed"}

    # --------------------------------------------------- generic text / json completion
    async def complete_text(
        self,
        prompt: str,
        system_prompt: str | None = None,
        role: str = "translator",
        provider_override: str | None = None,
    ) -> str | None:
        """Single free-text completion (no JSON parsing). Used for translation and
        similar free-form tasks. Provider selection is sticky via provider_override."""
        logger.debug("complete_text start role={} provider_override={}", role, provider_override)
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        chain = self._chain_for(provider_override, "worker")
        for provider, model in chain:
            content = await self._litellm_complete(provider=provider, model=model, messages=messages, role=role)
            if content:
                logger.debug("complete_text success provider={} model={}", provider, model)
                return content
        logger.warning("complete_text failed for all providers role={}", role)
        return None

    async def extract_json(
        self,
        prompt: str,
        system_prompt: str,
        role: str = "worker",
        provider_override: str | None = None,
    ) -> dict[str, Any]:
        """Single JSON completion with an explicit system prompt (no worker-type
        lookup). Used to structure crawled/translated text. Sticky provider."""
        logger.debug("extract_json start role={} provider_override={}", role, provider_override)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]
        chain = self._chain_for(provider_override, "worker")
        for provider, model in chain:
            content = await self._litellm_complete(provider=provider, model=model, messages=messages, role=role)
            if content is None:
                continue
            try:
                result = json.loads(self._extract_json(content))
                logger.debug("extract_json success provider={} model={}", provider, model)
                return result
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[LLM] extract_json parse failed {provider}/{model}: {exc}")
                continue
        logger.error("[LLM] extract_json failed for all providers")
        return {}

    # --------------------------------------------------------- tool-calling completion
    async def _litellm_complete_with_tools(
        self,
        provider: str,
        model: str,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        timeout: int | None = None,
        tool_choice: str | dict[str, Any] = "auto",
        role: str = "worker",
    ):
        lm_model, base_url = self._litellm_model_and_base(provider, model)
        api_key = self._api_key_for(provider)
        if base_url and not api_key:
            api_key = "sk-noauth"
        logger.info("[LLM] tool-call start provider={} model={} role={} api_key=<set>", provider, lm_model, role)
        started = time.perf_counter()
        try:
            response = await acompletion(
                model=lm_model,
                messages=messages,
                api_base=base_url,
                api_key=api_key,
                timeout=timeout or self.timeout,
                temperature=0,
                tools=tools,
                tool_choice=tool_choice,
            )
            elapsed = time.perf_counter() - started
            usage = getattr(response, "usage", None)
            self._record(
                provider,
                model,
                role,
                elapsed,
                getattr(usage, "prompt_tokens", 0) or 0,
                getattr(usage, "completion_tokens", 0) or 0,
                getattr(usage, "total_tokens", 0) or 0,
                True,
                None,
            )
            return response
        except Exception as exc:  # noqa: BLE001
            elapsed = time.perf_counter() - started
            self._record(provider, model, role, elapsed, 0, 0, 0, False, self._classify_error(exc))
            logger.warning(f"[LLM] {provider}/{model} tool-call failed: {exc}")
            return None

    async def complete_with_tools(
        self,
        prompt: str,
        system_prompt: str,
        tools: list[dict[str, Any]],
        role: str = "worker",
        provider_override: str | None = None,
        model_override: str | None = None,
        max_tool_rounds: int = 6,
        force_tool_first: bool = False,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Complete a prompt while letting the model call tools (e.g. calculator).

        Returns (parsed_result, tool_call_records). On total failure returns
        ({"error": "..."}, []).
        """
        logger.info("complete_with_tools start role={} provider_override={} model_override={} max_tool_rounds={} force_tool_first={}", role, provider_override, model_override, max_tool_rounds, force_tool_first)
        # Explicit provider selection is sticky: try only that provider's models.
        chain = self._chain_for(provider_override, role, model_override=model_override)

        for provider, model in chain:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ]
            records: list[dict[str, Any]] = []
            for round_idx in range(max_tool_rounds):
                # Force the model to actually invoke a tool on the first round so the
                # calculator is genuinely used and its steps are captured for trust.
                tool_choice = (
                    {"type": "function", "function": {"name": "calculator"}}
                    if (force_tool_first and round_idx == 0)
                    else "auto"
                )
                response = await self._litellm_complete_with_tools(
                    provider, model, messages, tools, tool_choice=tool_choice, role=role
                )
                if response is None:
                    break
                msg = response.choices[0].message
                tool_calls = getattr(msg, "tool_calls", None)
                if tool_calls:
                    messages.append(msg)
                    for tc in tool_calls:
                        fn = tc.function
                        try:
                            args = json.loads(fn.arguments) if isinstance(fn.arguments, str) else fn.arguments
                        except Exception:  # noqa: BLE001
                            args = {}
                        if fn.name == "calculator":
                            result = run_calculator(args)
                        else:
                            result = {"error": f"unknown tool {fn.name}"}
                        records.append(result)
                        messages.append(
                            {"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)}
                        )
                    logger.debug("complete_with_tools round={} tool_calls={} records={}", round_idx, len(tool_calls), len(records))
                    continue
                content = msg.content or ""
                self.last_worker = (provider, model)
                try:
                    parsed = json.loads(self._extract_json(content))
                    logger.debug("complete_with_tools success provider={} model={} records={}", provider, model, len(records))
                    return parsed, records
                except Exception:  # noqa: BLE001
                    return {"raw": content}, records
        logger.error(f"[LLM] All tool-calling providers failed for {role}")
        self.last_worker = ("fallback", "heuristic")
        return {"error": "All providers failed"}, []

    # --------------------------------------------------------------- heuristic fallback
    def _fallback_json(self, prompt: str, request: PlanningRequest | None) -> dict[str, Any]:
        logger.info("_fallback_json start destination={}", request.destination if request else None)
        interests = (request.interests if request else None) or ["landmarks", "food", "walks"]
        days = request.trip_length_days if request else 1
        itinerary = []
        for day in range(1, days + 1):
            theme = interests[(day - 1) % len(interests)].title()
            itinerary.append(
                {
                    "day": day,
                    "theme": f"{theme} in {request.destination if request else 'destination'}",
                    "morning": [f"Explore a {theme.lower()} anchor area."],
                    "afternoon": [f"Visit a second {theme.lower()} venue and lunch nearby."],
                    "evening": ["Wrap with a scenic walk and local dinner."],
                    "meals": ["Breakfast near hotel", "Lunch in activity zone", "Dinner in lively district"],
                    "logistics": ["Use one neighborhood cluster per half day."],
                }
            )
        return {
            "overview": f"A {days}-day {request.destination if request else ''} itinerary balanced around {', '.join(interests)}.",
            "itinerary": itinerary,
            "practical_tips": [
                "Reconfirm hours for reservation-heavy attractions.",
                "Keep weather-flexible indoor alternatives ready.",
            ],
            "citations": [],
        }
