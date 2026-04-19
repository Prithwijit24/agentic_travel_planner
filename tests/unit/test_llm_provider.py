from agentic_tour_planner.domain.models import PlanningRequest
from agentic_tour_planner.llm.provider import LLMProvider


def test_resolve_provider_prefers_request_values():
    provider = LLMProvider()
    request = PlanningRequest(
        destination="Kyoto",
        trip_length_days=3,
        provider="openai",
        model="gpt-4o-mini",
    )

    resolved_provider, resolved_model = provider.resolve_provider(request)

    assert resolved_provider == "openai"
    assert resolved_model == "gpt-4o-mini"


def test_openrouter_uses_openai_compatible_base_url():
    provider = LLMProvider()

    assert provider._base_url_for("openrouter") == "https://openrouter.ai/api/v1"

