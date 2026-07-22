from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class CallMetrics:
    provider: str
    model: str
    role: str
    latency_s: float
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    ok: bool = True
    error_type: str | None = None


class TokenCounterHook:
    """Accumulates token usage across all LLM calls."""

    def __init__(self) -> None:
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0

    def record(self, m: CallMetrics) -> None:
        self.calls += 1
        self.prompt_tokens += m.prompt_tokens
        self.completion_tokens += m.completion_tokens
        self.total_tokens += m.total_tokens
        logger.debug("TokenCounterHook.record provider={} model={} ok={}", m.provider, m.model, m.ok)

    def summary(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


class TimeEstimateHook:
    """Accumulates wall-clock time spent in LLM calls, per provider."""

    def __init__(self) -> None:
        self.calls = 0
        self.total_llm_s = 0.0
        self.per_provider: dict[str, float] = {}

    def record(self, m: CallMetrics) -> None:
        self.calls += 1
        self.total_llm_s += m.latency_s
        self.per_provider[m.provider] = self.per_provider.get(m.provider, 0.0) + m.latency_s
        logger.debug("TimeEstimateHook.record provider={} latency_s={:.3f}", m.provider, m.latency_s)

    def summary(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "total_llm_s": round(self.total_llm_s, 2),
            "per_provider_s": {k: round(v, 2) for k, v in self.per_provider.items()},
        }


class MetricsBus:
    """Shared bus that the two hooks write to; readable by the CLI/API."""

    def __init__(self) -> None:
        self.token_hook = TokenCounterHook()
        self.time_hook = TimeEstimateHook()
        self.call_log: list[CallMetrics] = []

    def record(self, m: CallMetrics) -> None:
        self.token_hook.record(m)
        self.time_hook.record(m)
        self.call_log.append(m)
        logger.info("MetricsBus.record total_calls={} total_tokens={}", len(self.call_log), self.token_hook.total_tokens)

    def summary(self) -> dict[str, Any]:
        return {
            "tokens": self.token_hook.summary(),
            "time": self.time_hook.summary(),
        }

    def reset(self) -> None:
        self.token_hook = TokenCounterHook()
        self.time_hook = TimeEstimateHook()
        self.call_log = []


metrics_bus = MetricsBus()
