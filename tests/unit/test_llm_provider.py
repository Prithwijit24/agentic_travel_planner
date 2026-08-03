from agentic_tour_planner.llm.provider import LLMProvider


def test_providers_loaded_from_llm_yaml():
    provider = LLMProvider()
    names = provider.list_providers()
    # Providers defined in llm.yml must be discovered (by scanning dicts with base_url).
    assert "agnes" in names
    assert "nararouter" in names
    assert "llm7io" in names
    assert "opencode" in names


def test_get_planner_and_worker_model_return_preferred():
    provider = LLMProvider()
    planner = provider.get_planner_model()
    worker = provider.get_worker_model()
    # The default provider is configured in llm.yml (agnes is the reliable default).
    assert planner[0] == "agnes"
    assert worker[0] == "agnes"
    assert planner[1]
    assert worker[1]


def test_explicit_request_provider_overrides_fallback_chain():
    provider = LLMProvider()
    chain = provider._chain_for("nararouter", "planner")
    # The explicit provider's models must come first (sticky), then the rest in priority order.
    assert chain[0][0] == "nararouter"
    first_rest_provider = next(p for p, _ in chain if p != "nararouter")
    assert first_rest_provider == "agnes"


def test_model_override_is_tried_before_provider_defaults():
    provider = LLMProvider()
    chain = provider._chain_for("nararouter", "worker", model_override="mistral-large")
    assert chain[0][0] == "nararouter"
    assert chain[0][1] == "mistral-large"


def test_unknown_provider_falls_back_to_default_chain():
    provider = LLMProvider()
    chain = provider._chain_for("nope-not-configured", "planner")
    assert chain[0][0] == "agnes"


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
