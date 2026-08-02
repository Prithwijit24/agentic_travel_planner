"""Per-provider connectivity test harness for the Agentic Travel Planner LLM layer.

Each provider in ``config/llm.yml`` gets a dedicated script that performs a real
litellm completion call through the fallback router and prints PASS/FAIL with the
latency and a short sample of the response.

Run an individual provider:
    uv run python scripts/test_provider_openrouter.py

Run everything (all providers, planner + worker probes, plus a live fallback test):
    uv run python scripts/test_all_providers.py

Run all models for every provider (slower):
    uv run python scripts/test_all_providers.py --all
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

# Make the project's ``src`` package importable when run as a standalone script.
_SRC = str(Path(__file__).resolve().parents[1] / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from agentic_tour_planner.domain.models import PlanningRequest  # noqa: E402 -- after sys.path bootstrap
from agentic_tour_planner.llm.provider import LLMProvider  # noqa: E402 -- after sys.path bootstrap


async def test_provider(
    provider_name: str,
    include_ollama: bool = False,
    all_models: bool = False,
) -> list[dict]:
    """Probe a single provider (its worker + planner model(s)) and report results."""
    provider = LLMProvider(include_ollama=include_ollama)
    if provider_name not in provider.providers:
        return [{"provider": provider_name, "status": "SKIP", "reason": "not configured in llm.yml"}]

    worker_models = provider._models_for(provider_name, "worker")
    planner_models = provider._models_for(provider_name, "planner")

    results: list[dict] = []
    for role, models in (("worker", worker_models), ("planner", planner_models)):
        if not models:
            continue
        to_test = models if all_models else models[:1]
        for model in to_test:
            r = await provider.test_provider_model(provider_name, model, role=role)
            results.append(r)
    if not results:
        return [{"provider": provider_name, "status": "SKIP", "reason": "no worker/planner models"}]
    return results


def _print_result(r: dict) -> None:
    status = r.get("status", "?")
    icon = {"ok": "✅", "unparsed": "🟡", "failed": "❌", "SKIP": "⚠️"}.get(status, "?")
    line = f"{icon} {r['provider']:12s} {status:8s} {r.get('role', r.get('litellm_model', ''))}"
    if r.get("model"):
        line += f"  model={r['model']}"
    if r.get("latency_s") is not None:
        line += f"  ({r['latency_s']}s)"
    if r.get("error_type"):
        line += f"  [{r['error_type']}]"
    if r.get("error"):
        line += f"  err={r['error']}"
    if r.get("sample"):
        line += f"  -> {r['sample']!r}"
    print(line)


async def test_fallback_chain(include_ollama: bool = False) -> None:
    """Exercise the real fallback router end-to-end and report what it produced."""
    provider = LLMProvider(include_ollama=include_ollama)
    print("\n--- Live fallback-chain test ---")
    print(f"preferred planner: {provider.get_planner_model()}")
    print(f"preferred worker : {provider.get_worker_model()}")

    # Worker (structured) call.
    start = time.perf_counter()
    worker_out = await provider.complete_structured(
        "Destination: Paris. Interests: art, food. Give route guidance as JSON.", "route"
    )
    w_elapsed = round(time.perf_counter() - start, 2)
    worker_ok = "error" not in worker_out
    print(
        f"{'✅' if worker_ok else '❌'} worker(route)  ({w_elapsed}s)  "
        f"{'OK' if worker_ok else 'FAILED'}: {str(worker_out)[:120]}"
    )

    # Planner (JSON itinerary) call.
    request = PlanningRequest(destination="Tokyo", trip_length_days=2, interests=["food", "walks"])
    prompt = "Create a 2-day Tokyo itinerary focused on food and walks. Respond with strict JSON only."
    start = time.perf_counter()
    plan = await provider.complete_json(prompt, request)
    p_elapsed = round(time.perf_counter() - start, 2)
    planner_ok = isinstance(plan, dict) and bool(plan.get("itinerary"))
    print(
        f"{'✅' if planner_ok else '❌'} planner(itinerary) ({p_elapsed}s)  "
        f"{'OK' if planner_ok else 'FAILED'}: days={len(plan.get('itinerary', []))}"
    )


async def main(provider_name: str | None = None, all_models: bool = False) -> int:
    include_ollama = "--ollama" in sys.argv
    provider = LLMProvider(include_ollama=include_ollama)

    targets = [provider_name] if provider_name else list(provider.providers.keys())

    print(f"Providers configured: {provider.list_providers()}")
    print(f"Fallback priority   : {provider._provider_chain()}")
    if not targets:
        print("No providers found.")
        return 0

    all_results: list[dict] = []
    for name in targets:
        res = await test_provider(name, include_ollama=include_ollama, all_models=all_models)
        for r in res:
            _print_result(r)
            all_results.append(r)

    ok = [r for r in all_results if r.get("status") == "ok"]
    unparsed = [r for r in all_results if r.get("status") == "unparsed"]
    failed = [r for r in all_results if r.get("status") == "failed"]
    skipped = [r for r in all_results if r.get("status") == "SKIP"]
    print(
        f"\nSummary: {len(all_results)} probes | "
        f"{len(ok)} ok | {len(unparsed)} unparsed | "
        f"{len(failed)} failed | {len(skipped)} skipped"
    )

    if not provider_name:
        await test_fallback_chain(include_ollama=include_ollama)

    return 1 if failed else 0


if __name__ == "__main__":
    name = None
    if len(sys.argv) > 1 and not sys.argv[1].startswith("--"):
        name = sys.argv[1]
    raise SystemExit(asyncio.run(main(name)))
