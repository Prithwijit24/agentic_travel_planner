import asyncio

import httpx
import pytest

from agentic_tour_planner.llm import provider as provider_module
from agentic_tour_planner.llm.provider import LLMProvider


def test_providers_loaded_from_llm_yaml():
    provider = LLMProvider()
    names = provider.list_providers()
    # Providers defined in llm.yml must be discovered (by scanning dicts with base_url).
    assert "oraclellm" in names
    assert "agnes" in names
    assert "nararouter" in names
    assert "llm7io" in names
    assert "opencode" in names


def test_get_planner_and_worker_model_return_preferred():
    provider = LLMProvider()
    planner = provider.get_planner_model()
    worker = provider.get_worker_model()
    # The default provider is configured in llm.yml (oraclellm is the self-hosted default).
    assert planner[0] == "oraclellm"
    assert worker[0] == "oraclellm"
    assert planner[1]
    assert worker[1]


def test_explicit_request_provider_overrides_fallback_chain():
    provider = LLMProvider()
    chain = provider._chain_for("nararouter", "planner")
    # The explicit provider's models must come first (sticky), then the rest in priority order.
    assert chain[0][0] == "nararouter"
    first_rest_provider = next(p for p, _ in chain if p != "nararouter")
    assert first_rest_provider == "oraclellm"


def test_model_override_is_tried_before_provider_defaults():
    provider = LLMProvider()
    chain = provider._chain_for("nararouter", "worker", model_override="mistral-large")
    assert chain[0][0] == "nararouter"
    assert chain[0][1] == "mistral-large"


def test_unknown_provider_falls_back_to_default_chain():
    provider = LLMProvider()
    chain = provider._chain_for("nope-not-configured", "planner")
    assert chain[0][0] == "oraclellm"


def test_planner_model_override_only_includes_explicit_model_first():
    provider = LLMProvider()
    chain = provider._chain_for("nararouter", "planner", model_override="custom-model")
    assert chain[0][0] == "nararouter"
    assert chain[0][1] == "custom-model"


async def _run_post_ok(provider):
    return await provider._post_chat(
        "agnes",
        "agnes-2.0-flash",
        [{"role": "user", "content": "hi"}],
        timeout=10,
        role="planner",
    )


def test_llm_unavailable_when_no_providers_configured(monkeypatch):
    provider = LLMProvider()
    monkeypatch.setattr(provider, "providers", {})
    monkeypatch.setattr(provider, "_provider_chain", list)
    chain = provider._chain_for(None, "planner")
    assert chain == []


def test_marked_down_provider_is_filtered_out():
    import time

    provider = LLMProvider()
    provider._mark_down("agnes", "server_busy")
    chain = provider._available([("agnes", "agnes-2.0-flash"), ("nararouter", "agnes-2.5-flash")])
    assert all(p != "agnes" for p, _ in chain)
    provider._cooldown["nararouter"] = time.monotonic() - 1  # past expiry
    chain2 = provider._available([("nararouter", "m")])
    assert chain2  # expired cooldown is available again


def test_timeout_mark_down_gets_long_cooldown():
    import time

    provider = LLMProvider()
    provider._cooldown_seconds = 30
    provider._mark_down("agnes", "timeout")
    deadline = provider._cooldown["agnes"]
    assert deadline > time.monotonic() + 300 * 0.9  # default 300s floor


def test_timeout_mark_down_scales_with_min_long_cooldown():
    import time

    provider = LLMProvider()
    provider._cooldown_seconds = 5
    provider._mark_down("nararouter", "timeout")
    deadline = provider._cooldown["nararouter"]
    assert deadline > time.monotonic() + 300 * 0.9  # timeouts never below 300s


def test_gateway_error_content_is_detected():
    from agentic_tour_planner.llm.provider import _is_gateway_error_content

    assert _is_gateway_error_content("Streaming response failed: [503] The request queue is full.")
    assert _is_gateway_error_content("The upstream server is busy. Please retry.")
    assert not _is_gateway_error_content("Gangtok is a beautiful hill station.")


class _FakeResponse:
    def __init__(self, content: str, status: int = 200):
        self.content = content
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=httpx.Request("POST", "http://fake"), response=None)

    def json(self) -> dict:
        return {"choices": [{"message": {"content": self.content}}]}


class _FakeAsyncClient:
    """Minimal httpx.AsyncClient replacement. ``post`` may sleep to simulate a
    gateway that keeps the connection open but never finishes the body."""

    def __init__(self, response: _FakeResponse, delay: float = 0.0):
        self.response = response
        self.delay = delay

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def post(self, *args, **kwargs):
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.response


@pytest.mark.asyncio
async def test_hard_deadline_cuts_off_trickling_gateway(monkeypatch):
    """A gateway that accepts the request but never completes the body must be
    cut off at the deadline (httpx per-chunk timeouts would never fire)."""
    provider = LLMProvider()
    fake = _FakeAsyncClient(_FakeResponse("{}"), delay=5.0)
    monkeypatch.setattr(provider_module.httpx, "AsyncClient", lambda **_: fake)

    import time

    start = time.monotonic()
    result = await provider._post_chat("agnes", "agnes-2.0-flash", [{"role": "user", "content": "hi"}], timeout=0.3)
    elapsed = time.monotonic() - start
    assert result is None
    assert elapsed < 2.0  # far below the fake 5s sleep: the deadline cut it off
    assert not provider._provider_available("agnes")  # marked down


@pytest.mark.asyncio
async def test_empty_content_marks_provider_down(monkeypatch):
    """HTTP 200 with an empty body is a failure: fail over instead of wasting
    the next provider's patience on an unparseable response."""
    provider = LLMProvider()
    fake = _FakeAsyncClient(_FakeResponse(""))
    monkeypatch.setattr(provider_module.httpx, "AsyncClient", lambda **_: fake)
    result = await provider._post_chat("agnes", "agnes-2.0-flash", [{"role": "user", "content": "hi"}], timeout=5)
    assert result is None
    assert not provider._provider_available("agnes")
    assert provider._failures.get("agnes") == 1


def test_timeout_error_classified_as_timeout():
    assert LLMProvider._classify_error(TimeoutError()) == "timeout"
