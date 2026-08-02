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
    # A model without an openai/ prefix gets one added for the OpenAI-compatible gateway.
    import asyncio

    async def run():
        return provider._normalize_model("agnes-2.0-flash")

    assert asyncio.run(run()) == "openai/agnes-2.0-flash"


def test_native_gemini_model_routing_strips_vendor_prefix(monkeypatch):
    provider = LLMProvider()
    monkeypatch.setattr(provider, "providers", {"gemini": {"api_type": "gemini"}})
    lm_model, base = provider._litellm_model_and_base("gemini", "google/gemini-4-31b-it:free")
    assert lm_model == "gemini/gemini-4-31b-it:free"
    assert base is None


def test_native_groq_model_routing_strips_vendor_prefix(monkeypatch):
    provider = LLMProvider()
    monkeypatch.setattr(provider, "providers", {"grokai": {"api_type": "groq"}})
    lm_model, base = provider._litellm_model_and_base("grokai", "openai/gpt-oss-120b")
    assert lm_model == "groq/gpt-oss-120b"
    assert base is None


def test_openai_gateway_uses_api_base(monkeypatch):
    provider = LLMProvider()
    monkeypatch.setattr(
        provider,
        "providers",
        {"openrouter": {"api_type": "openai", "base_url": "https://openrouter.ai/api/v1"}},
    )
    # openrouter model already carries the openai/ prefix, so it is passed through.
    lm_model, base = provider._litellm_model_and_base("openrouter", "openai/gpt-oss-20b:free")
    assert lm_model == "openai/gpt-oss-20b:free"
    assert base == "https://openrouter.ai/api/v1"
    # A bare model name gets the openai/ prefix added.
    lm_model2, _ = provider._litellm_model_and_base("agnes", "agnes-2.0-flash")
    assert lm_model2 == "openai/agnes-2.0-flash"
