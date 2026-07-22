from __future__ import annotations

from typing import Any

from agentic_tour_planner.domain.models import (
    CostEstimate,
    CostLineItem,
    DailyCost,
    OverallCost,
    PlanningRequest,
)
from agentic_tour_planner.llm.provider import CALCULATOR_TOOL, LLMProvider
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)

COST_SYSTEM_PROMPT = (
    "You are a travel cost estimator for Indian destinations. Use the calculator tool for all math. "
    "BE REALISTIC - use these exact price ranges, never exceed them:\n"
    "HOTEL (per room per night):\n"
    "- Budget: ₹800-1200, Mid: ₹1500-2500, Premium: ₹3000-5000\n"
    "- SAME PRICE for 1-2 people sharing (do NOT multiply by members)\n"
    "- For 3+ people: rent enough rooms, total cost = room_rate × rooms_needed\n"
    "FOOD (per person per day):\n"
    "- Budget: ₹250, Mid: ₹600, Premium: ₹1200\n"
    "TRANSPORT (per leg):\n"
    "- Local auto/rickshaw: ₹80-150, Cab: ₹150-300, Bus: ₹30-80\n"
    "- Inter-city train/bus: ₹200-400\n"
    "TICKETS/ENTRIES:\n"
    "- Local sites: ₹100, Popular attractions: ₹300, Major sites: ₹600\n"
    "MAXIMUM DAILY TOTAL: ₹8000 per person (even premium)\n"
    "OUTPUT: Every amount must be a string like '3500 rupees'.\n"
    "JSON: {\"daily\": [{\"day\": int, \"items\": [{\"label\": str, \"amount\": str}], "
    "\"subtotal\": str, \"steps\": [str]}], "
    "\"overall\": {\"per_person_total\": str, \"members\": int, "
    "\"grand_total\": str, \"steps\": [str]}}."
)


class CostEstimator:
    def __init__(self) -> None:
        self.llm = LLMProvider()
        logger.debug("CostEstimator initialized")

    def _build_prompt(self, request: PlanningRequest, plan_json: dict[str, Any]) -> str:
        logger.debug("_build_prompt destination={} members={} days={}", request.destination, request.travelers, len(plan_json.get("itinerary", []) or []))
        members = request.travelers
        transport = request.transport_mode or "unspecified"
        days = plan_json.get("itinerary", []) or []

        day_summaries = []
        for d in days:
            spots = d.get("spots") or []
            activities = (
                (d.get("morning") or [])
                + (d.get("afternoon") or [])
                + (d.get("evening") or [])
            )
            day_summaries.append(
                f"Day {d.get('day')} ({d.get('theme','')}): "
                f"{len(activities)} activities, notable places: {[s.get('name') for s in spots]}"
            )
        plan_text = "\n".join(day_summaries)

        currency = self._guess_currency(request.destination)
        rooms = 1 if members <= 2 else (members + 1) // 2

        return (
            f"Destination: {request.destination}\n"
            f"Trip length: {request.trip_length_days} days\n"
            f"Number of members: {members}\n"
            f"Budget level: {request.budget_level}\n"
            f"Currency: {currency}\n"
            f"Rooms needed: {rooms} (max 2 people per room)\n\n"
            f"Plan summary:\n{plan_text}\n\n"
            "Estimate costs using the exact price ranges in the system prompt. "
            "Be conservative - use lower-end prices if uncertain. "
            "Hotel cost is PER ROOM, not per person. "
            "Food/transport/tickets are per person. "
            "Every amount must be a string like '3500 rupees'."
        )

    @staticmethod
    def _guess_currency(destination: str) -> str:
        dest_lower = (destination or "").lower()
        if any(w in dest_lower for w in ("andaman", "india", "kerala", "rajasthan", "goa", "kashmir")):
            return "rupees"
        if any(w in dest_lower for w in ("bali", "indonesia")):
            return "Indonesian rupiah"
        if any(w in dest_lower for w in ("thailand", "bangkok", "phuket")):
            return "Thai baht"
        return "rupees"

    @staticmethod
    def _parse(data: dict[str, Any], records: list[dict[str, Any]], request: PlanningRequest) -> CostEstimate:
        logger.debug("_parse daily_count={} has_error={}", len(data.get("daily", []) or []), ("error" in data or "raw" in data))
        if "error" in data or "raw" in data:
            return CostEstimate(calculations=records)
        daily: list[DailyCost] = []
        for d in data.get("daily", []) or []:
            items = [
                CostLineItem(label=i.get("label", ""), amount=float(i.get("amount", 0) if not isinstance(i.get("amount"), str) else _amount_to_num(i.get("amount", "0"))))
                for i in (d.get("items") or [])
            ]
            subtotal = d.get("subtotal")
            if isinstance(subtotal, str):
                subtotal = _amount_to_num(subtotal)
            daily.append(
                DailyCost(
                    day=int(d.get("day", 0)),
                    items=items,
                    subtotal=subtotal,
                    steps=d.get("steps") or [],
                )
            )
        overall_data = data.get("overall") or {}
        ppt = overall_data.get("per_person_total")
        if isinstance(ppt, str):
            ppt = _amount_to_num(ppt)
        grand = overall_data.get("grand_total")
        if isinstance(grand, str):
            grand = _amount_to_num(grand)
        overall = OverallCost(
            per_person_total=ppt,
            members=int(overall_data.get("members", request.travelers)),
            grand_total=grand,
            steps=overall_data.get("steps") or [],
        )
        return CostEstimate(daily=daily, overall=overall, calculations=records)

    async def estimate(self, request: PlanningRequest, plan_json: dict[str, Any]) -> CostEstimate:
        logger.info("estimate start destination={} provider_override={}", request.destination, request.provider)
        prompt = self._build_prompt(request, plan_json)

        # Single pass: produce the structured JSON (daily + overall breakdown) with the
        # calculator tool available so the model does its arithmetic. We intentionally do
        # NOT run a second forced-proof phase — the step-by-step math is not shown to the
        # user, so generating it would only waste time and tokens.
        logger.info("estimate: requesting structured cost JSON (single pass)")
        data, _ = await self.llm.complete_with_tools(
            prompt,
            COST_SYSTEM_PROMPT,
            [CALCULATOR_TOOL],
            role="worker",
            provider_override=request.provider,
            model_override=request.worker_model,
            max_tool_rounds=3,
        )

        result = self._parse(data, [], request)
        logger.info("estimate done daily_count={}", len(result.daily))
        return result


def _amount_to_num(text: str) -> float:
    """Extract numeric value from a string like '3500 rupees' or '₹5,000'."""
    import re
    cleaned = re.sub(r"[₹$€£,]", "", str(text))
    nums = re.findall(r"\d+(?:\.\d+)?", cleaned)
    return float(nums[0]) if nums else 0.0
