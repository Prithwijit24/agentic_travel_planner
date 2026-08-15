from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.domain.models import PlanningRequest
from agentic_tour_planner.llm.hooks import CallMetrics, metrics_bus
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)


def _planner_system_prompt():
    return get_settings().PLANNER_SYSTEM_PROMPT


def _worker_prompts():
    s = get_settings()
    return s.ROUTE_PROMPT, s.BUDGET_PROMPT, s.TIMING_PROMPT


def _provider_priority():
    priority = get_settings().llm_provider_priority
    return (
        list(priority) if priority else ["agnes", "grokai", "gemini", "nararouter", "llm7io", "opencode", "oraclellm"]
    )


def _api_key_aliases():
    aliases = get_settings().llm_api_key_aliases
    if aliases:
        return {k: list(v) for k, v in aliases.items()}
    return {
        "oraclellm": ["oraclellm_api_key"],
        "agnes": ["agnes_api_key"],
        "nararouter": ["nararouter_api_key"],
        "llm7io": ["llm7io_api_key"],
        "opencode": ["opencode_api_key"],
        "openrouter": ["openrouter_api_key"],
        "grokai": ["grokai_api_key", "groqai_api_key"],
        "nvidia": ["nvidia_api_key"],
        "morphllm": ["morphllm_api_key"],
        "gemini": ["gemini_api_key"],
        "ollama": ["ollama_api_key"],
        "omniroute": ["omniroute_api_key", "omnirute_api_key"],
    }


class LLMUnavailableError(RuntimeError):
    def __init__(self, message: str = "all LLMs are Busy right now") -> None:
        super().__init__(message)


def _extract_json(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


def _gateway_error_hints():
    hints = get_settings().llm_gateway_error_hints
    return tuple(hints) if hints else ()


def _is_gateway_error_content(content: str) -> bool:
    if not content:
        return False
    prefix_len = get_settings().llm_gateway_error_hint_prefix_length
    lowered = content.strip().lower()
    return any(lowered.startswith(hint) or hint in lowered[:prefix_len] for hint in _gateway_error_hints())


def _prompt_field_providers():
    providers = get_settings().llm_prompt_field_providers
    return frozenset(providers) if providers else frozenset({"oraclellm"})


def _payload_for(provider: str, model: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the request body for a provider, adapting non-OpenAI formats."""
    if provider in _prompt_field_providers():
        text = "\n\n".join(f"{m.get('role', 'user')}: {m.get('content', '')}" for m in messages)
        return {"model": model, "prompt": text, "temperature": 0}
    return {"model": model, "messages": messages, "temperature": 0}


def _content_of(provider: str, data: dict[str, Any]) -> str:
    """Extract the assistant text from a response body, adapting non-OpenAI formats."""
    if provider in _prompt_field_providers():
        return str(data.get("response") or "")
    return (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""


class LLMProvider:
    """Minimal OpenAI-compatible LLM provider with simple failure routing.

    Calls provider endpoints directly over HTTP (no litellm). On failure the
    request fails over to the next provider in priority order.
    """

    def __init__(self, include_ollama: bool = False) -> None:
        self.settings = get_settings()
        self.include_ollama = include_ollama
        self.providers = self._load_providers()
        self.last_planner: tuple[str, str] | None = None
        self.last_worker: tuple[str, str] | None = None
        self.timeout = float(self.settings.llm_call_timeout_seconds)
        self.planner_timeout = float(self.settings.llm_planner_timeout_seconds)
        self._cooldown: dict[str, float] = {}
        self._cooldown_seconds = float(getattr(self.settings, "llm_provider_cooldown_seconds", None) or 30.0)
        self._failures: dict[str, int] = {}  # consecutive failure streak per provider

    # ------------------------------------------------------------- health / cooldown
    def _mark_down(self, provider: str, error_type: str | None) -> None:
        """Put a hard-failing provider on cooldown so it is skipped promptly.

        Server-capacity errors (503/429/queue-full) indicate a gateway that is
        overloaded for MINUTES, not seconds, so the base cooldown is long and
        grows exponentially with each consecutive failure (backoff). Timeouts
        get the longest floor: a hung upstream usually stays hung for a while,
        so we must not re-try it on the next call (e.g. the next day's planner).
        """
        s = get_settings()
        if error_type in ("rate_limit", "server_busy"):
            base = max(self._cooldown_seconds * 2, s.llm_cooldown_rate_limit_floor)
        elif error_type in ("auth", "connection", "not_found"):
            base = self._cooldown_seconds
        elif error_type == "timeout":
            base = max(self._cooldown_seconds * 10, s.llm_cooldown_timeout_floor)
        else:
            return
        streak = self._failures.get(provider, 0)
        cooldown = min(base * (2 ** min(streak, 3)), s.llm_cooldown_max_seconds)
        self._failures[provider] = streak + 1
        self._cooldown[provider] = time.monotonic() + cooldown
        logger.warning(f"[LLM] provider {provider!r} marked down for {cooldown:.0f}s ({error_type})")

    def _mark_up(self, provider: str) -> None:
        """Reset the failure streak when a provider answers successfully."""
        self._failures.pop(provider, None)

    def _provider_available(self, provider: str) -> bool:
        return time.monotonic() >= self._cooldown.get(provider, 0.0)

    def _available(self, chain: list[tuple[str, str]]) -> list[tuple[str, str]]:
        """Filter a (provider, model) chain to only the providers not on cooldown."""
        return [(p, m) for p, m in chain if self._provider_available(p)]

    @staticmethod
    def _classify_error(exc: Exception) -> str:
        """Map an exception to a coarse error class for cooldown decisions."""
        if isinstance(exc, httpx.TimeoutException | TimeoutError):
            return "timeout"
        if isinstance(exc, httpx.ConnectError):
            return "connection"
        if isinstance(exc, httpx.HTTPStatusError):
            code = exc.response.status_code if exc.response is not None else 0
            if code == 429:
                return "rate_limit"
            if code == 503:
                return "server_busy"
            if code in (401, 403):
                return "auth"
            if code == 404:
                return "not_found"
            if code >= 500:
                return "server_busy"
            return "http"
        return "unknown"

    # ------------------------------------------------------------- config
    def _load_providers(self) -> dict[str, dict[str, Any]]:
        """Discover provider configs from settings: any dict attribute that looks
        like an LLM provider entry (has a base_url AND a planner/worker model)."""
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
        priority = [p for p in _provider_priority() if p in found]
        extras = [p for p in found if p not in _provider_priority()]
        ordered = priority + extras
        logger.debug("_load_providers found={}", ordered)
        return {p: found[p] for p in ordered}

    def _api_key_for(self, provider: str) -> str | None:
        for attr in _api_key_aliases().get(provider, [f"{provider}_api_key"]):
            key = getattr(self.settings, attr, None)
            if key:
                return str(key)
        return None

    def _provider_chain(self) -> list[str]:
        chain = [p for p in _provider_priority() if p in self.providers]
        # Honour the configured default provider (llm.yml `default_llm_provider`):
        # try it first so a reliable default isn't buried behind a flaky one.
        default = getattr(self.settings, "default_llm_provider", None)
        if default and default in chain:
            chain = [default] + [p for p in chain if p != default]
        if self.include_ollama and "ollama" not in chain:
            chain.append("ollama")
        return chain

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

    def _timeout_for(self, provider: str, role: str, default: float) -> float:
        """Per-provider timeout override from llm.yml (e.g. a slow self-hosted
        model gets more headroom), falling back to the global default."""
        cfg = self.providers.get(provider, {})
        value = cfg.get(f"{role}_timeout") or cfg.get("timeout")
        if value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _chain_for(
        self, provider_override: str | None, role: str, model_override: str | None = None
    ) -> list[tuple[str, str]]:
        """Build the (provider, model) attempt order. An explicit provider selection is
        tried first (sticky), then the remaining providers in priority order as a
        fallback so a flaky provider does not break the pipeline. An unknown explicit
        provider falls back to the default chain (with a warning)."""
        logger.debug(
            "_chain_for provider_override={} role={} model_override={}", provider_override, role, model_override
        )
        if provider_override and provider_override in self.providers:
            models = self._models_for(provider_override, role)
            if model_override:
                models = [m for m in models if m != model_override]
                models = [model_override, *models]
            rest = [p for p in self._provider_chain() if p != provider_override]
            return [(provider_override, m) for m in models] + [(p, m) for p in rest for m in self._models_for(p, role)]
        if provider_override:
            logger.warning(f"[LLM] Unknown provider {provider_override!r}; using default chain")
        return [(p, m) for p in self._provider_chain() for m in self._models_for(p, role)]

    # ------------------------------------------------------------- introspection
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

    def get_planner_model(self) -> tuple[str, str]:
        """Return the primary (preferred) planner provider/model for display/logging."""
        for provider in self._provider_chain():
            models = self._models_for(provider, "planner")
            if models:
                return provider, models[0]
        return "none", "none"

    def get_worker_model(self) -> tuple[str, str]:
        """Return the primary (preferred) worker provider/model for display/logging."""
        for provider in self._provider_chain():
            models = self._models_for(provider, "worker")
            if models:
                return provider, models[0]
        return "none", "none"

    def last_planner_used(self) -> tuple[str, str]:
        return self.last_planner or ("unknown", "unknown")

    def last_worker_used(self) -> tuple[str, str]:
        return self.last_worker or ("unknown", "unknown")

    # ------------------------------------------------------------- HTTP layer
    def _record(
        self,
        provider: str,
        model: str,
        role: str,
        elapsed: float,
        usage: dict[str, Any] | None,
        ok: bool,
        error_type: str | None,
    ) -> None:
        logger.debug("_record provider={} model={} role={} ok={}", provider, model, role, ok)
        metrics_bus.record(
            CallMetrics(
                provider=provider,
                model=model,
                role=role,
                latency_s=round(elapsed, 3),
                prompt_tokens=int(usage.get("prompt_tokens") or 0) if usage else 0,
                completion_tokens=int(usage.get("completion_tokens") or 0) if usage else 0,
                total_tokens=int(usage.get("total_tokens") or 0) if usage else 0,
                ok=ok,
                error_type=error_type,
            )
        )

    async def _post_chat(
        self,
        provider: str,
        model: str,
        messages: list[dict[str, Any]],
        *,
        timeout: float,
        role: str = "worker",
    ) -> dict[str, Any] | None:
        """POST /chat/completions to an OpenAI-compatible endpoint. Returns the
        parsed response body, or None on any failure (error already logged)."""
        cfg = self.providers.get(provider)
        if not cfg:
            logger.warning(f"[LLM] provider {provider!r} not in config")
            return None
        base_url = str(cfg["base_url"]).rstrip("/")
        api_key = self._api_key_for(provider) or "sk-noauth"
        payload = _payload_for(provider, model, messages)

        started = time.perf_counter()
        try:
            # Hard total deadline: httpx's own timeout resets on every received
            # chunk, so a gateway that trickles keepalive bytes but never finishes
            # the response body would run far past the deadline. wait_for caps the
            # whole exchange; the raised TimeoutError maps to "timeout" cooldown.
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:

                async def _post() -> httpx.Response:
                    return await client.post(
                        f"{base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )

                response = await asyncio.wait_for(_post(), timeout=timeout)
                response.raise_for_status()
                data: dict[str, Any] = response.json()
            elapsed = time.perf_counter() - started
            usage = data.get("usage") or {}
            content = _content_of(provider, data)
            # Some gateways (e.g. agnes) return HTTP 200 with an error message in
            # the content body when their request queue is full. Treat that as a
            # server-busy failure so we fail over instead of trying to parse it.
            if _is_gateway_error_content(content):
                self._record(provider, model, role, elapsed, usage, False, "server_busy")
                self._mark_down(provider, "server_busy")
                logger.warning(
                    f"[LLM] {provider}/{model} returned gateway error content in {elapsed:.1f}s: {content[:120]!r}"
                )
                return None
            if not content.strip():
                # HTTP 200 with an empty body: the gateway accepted the request
                # but returned nothing. Parsing it would fail anyway ("Expecting
                # value: line 1 column 1") AFTER burning the full timeout, so
                # treat it as a failure now and fail over to the next provider.
                self._record(provider, model, role, elapsed, usage, False, "server_busy")
                self._mark_down(provider, "server_busy")
                logger.warning(f"[LLM] {provider}/{model} returned EMPTY content in {elapsed:.1f}s; marking down")
                return None
            self._record(provider, model, role, elapsed, usage, True, None)
            self._mark_up(provider)
            logger.debug(f"[LLM] {provider}/{model} ok latency={elapsed:.3f}s")
            return data
        except Exception as exc:
            elapsed = time.perf_counter() - started
            error_type = self._classify_error(exc)
            self._record(provider, model, role, elapsed, None, False, error_type)
            self._mark_down(provider, error_type)
            logger.warning(f"[LLM] {provider}/{model} failed in {elapsed:.1f}s: {exc} ({error_type})")
            return None

    async def _complete(
        self,
        chain: list[tuple[str, str]],
        messages: list[dict[str, Any]],
        *,
        timeout: float,
        role: str = "worker",
    ) -> tuple[str, str, str] | None:
        """Try each (provider, model) in the chain until one returns a response.
        Returns (provider, model, content) or None if all fail."""
        for provider, model in chain:
            data = await self._post_chat(provider, model, messages, timeout=timeout, role=role)
            if data is not None:
                content = _content_of(provider, data)
                return provider, model, content
        return None

    # ------------------------------------------------------------- public API
    async def complete_json(
        self,
        prompt: str,
        request: PlanningRequest | None = None,
        system_prompt: str | None = None,
    ) -> dict[str, Any]:
        logger.info("complete_json start role=planner prompt_len={}", len(prompt))
        messages = [
            {"role": "system", "content": system_prompt or _planner_system_prompt()},
            {"role": "user", "content": prompt},
        ]
        # An explicit provider selection (from the CLI/UI) is tried first (sticky),
        # but if it fails we fall through the remaining providers in priority order.
        explicit_provider = request.provider if (request and getattr(request, "provider", None)) else None
        model_override = request.planner_model if (request and getattr(request, "planner_model", None)) else None
        chain = self._available(self._chain_for(explicit_provider, "planner", model_override=model_override))

        for provider, model in chain:
            data = await self._post_chat(
                provider,
                model,
                messages,
                timeout=self._timeout_for(provider, "planner", self.planner_timeout),
                role="planner",
            )
            if data is None:
                continue
            content = _content_of(provider, data)
            try:
                result: dict[str, Any] = json.loads(_extract_json(content))
                self.last_planner = (provider, model)
                logger.debug("complete_json success provider={} model={}", provider, model)
                return result
            except Exception as exc:
                logger.warning(f"[LLM] JSON parse failed for {provider}/{model}: {exc}")
                continue
        tried = ", ".join(p for p, _ in chain)
        logger.error("[LLM] All planner providers failed (tried {}); all LLMs are busy", tried)
        raise LLMUnavailableError()

    async def complete_structured(
        self,
        prompt: str,
        worker_type: str,
        provider_override: str | None = None,
        model_override: str | None = None,
    ) -> dict[str, Any]:
        logger.info(
            "complete_structured start worker_type={} provider_override={} model_override={}",
            worker_type,
            provider_override,
            model_override,
        )
        route_prompt, budget_prompt, timing_prompt = _worker_prompts()
        system_prompt = {
            "route": route_prompt,
            "budget": budget_prompt,
            "timing": timing_prompt,
        }.get(worker_type, "Return strict JSON only. Do not wrap in markdown.")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]
        chain = self._available(self._chain_for(provider_override, "worker", model_override=model_override))

        for provider, model in chain:
            data = await self._post_chat(
                provider,
                model,
                messages,
                timeout=self._timeout_for(provider, "worker", self.timeout),
                role="worker",
            )
            if data is None:
                continue
            content = _content_of(provider, data)
            try:
                result: dict[str, Any] = json.loads(_extract_json(content))
                self.last_worker = (provider, model)
                logger.debug("complete_structured success provider={} model={}", provider, model)
                return result
            except Exception as exc:
                logger.warning(f"[LLM] structured parse failed {provider}/{model}: {exc}")
                continue
        logger.error(f"[LLM] All worker providers failed for {worker_type}")
        self.last_worker = ("fallback", "heuristic")
        return {"error": "All providers failed"}

    async def complete_text(
        self,
        prompt: str,
        system_prompt: str | None = None,
        role: str = "translator",
        provider_override: str | None = None,
    ) -> str | None:
        """Single free-text completion (no JSON parsing). Used for translation and
        similar free-form tasks."""
        logger.debug("complete_text start role={} provider_override={}", role, provider_override)
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        chain = self._available(self._chain_for(provider_override, role))

        for provider, model in chain:
            data = await self._post_chat(
                provider,
                model,
                messages,
                timeout=self._timeout_for(provider, "worker", self.timeout),
                role=role,
            )
            if data is None:
                continue
            content = _content_of(provider, data)
            if content:
                logger.debug("complete_text success provider={} model={}", provider, model)
                return content
        logger.warning("complete_text failed for all providers role={}", role)
        return None
