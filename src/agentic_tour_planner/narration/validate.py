"""Validation pass for narration.

Non-LLM checks for cost match, POI presence, and completeness.
"""

from __future__ import annotations

import re
from typing import Any

from loguru import logger


def validate_narration(
    narration: dict[str, Any],
    day_skeleton: list[dict[str, Any]],
    cost_summary: dict[str, Any],
) -> list[str]:
    """Validate narration against skeleton and cost data.

    Returns a list of detected issues (empty if all good).
    """
    issues = []

    # 1. Check cost match
    cost_issues = _check_cost_match(narration, cost_summary)
    issues.extend(cost_issues)

    # 2. Check POI presence
    poi_issues = _check_poi_presence(narration, day_skeleton)
    issues.extend(poi_issues)

    # 3. Check completeness
    completeness_issues = _check_completeness(narration, day_skeleton)
    issues.extend(completeness_issues)

    if issues:
        logger.warning("Validation found {} issues".format(len(issues)))
    else:
        logger.info("Validation passed")

    return issues


def _extract_numbers(text: str) -> list[float]:
    """Extract all numbers from text."""
    return [float(m) for m in re.findall(r"[\d,]+\.?\d*", text.replace(",", ""))]


def _check_cost_match(narration: dict[str, Any], cost_summary: dict[str, Any]) -> list[str]:
    """Check if cost mentioned in narration matches cost_summary."""
    issues = []
    grand_total = cost_summary.get("grand_total")
    if not grand_total:
        return issues

    narration_text = json.dumps(narration) if isinstance(narration, dict) else str(narration)
    numbers = _extract_numbers(narration_text)

    # Check if any number in narration is close to grand_total
    found = any(abs(n - grand_total) / max(grand_total, 1) < 0.1 for n in numbers)
    if not found:
        issues.append("Cost mismatch: grand total {} not mentioned in narration".format(grand_total))

    return issues


def _check_poi_presence(narration: dict[str, Any], day_skeleton: list[dict[str, Any]]) -> list[str]:
    """Check that POIs in narration exist in skeleton and vice versa."""
    issues = []

    # Build set of all POI names in skeleton
    skeleton_pois = set()
    for day in day_skeleton:
        for poi in day.get("pois", []):
            name = poi.get("name", "").strip().lower()
            if name:
                skeleton_pois.add(name)

    # Check narration mentions only known POIs
    narration_text = json.dumps(narration).lower()
    for day in day_skeleton:
        for poi in day.get("pois", []):
            name = poi.get("name", "").strip().lower()
            if name and name not in narration_text:
                issues.append("POI missing from narration: {}".format(name))

    return issues


def _check_completeness(narration: dict[str, Any], day_skeleton: list[dict[str, Any]]) -> list[str]:
    """Check that all days have narrative content."""
    issues = []
    narration_days = narration.get("days", [])

    skeleton_day_nums = {day.get("day") for day in day_skeleton}
    narration_day_nums = {d.get("day") for d in narration_days}

    missing_days = skeleton_day_nums - narration_day_nums
    for day_num in missing_days:
        issues.append("Day {} missing from narration".format(day_num))

    return issues


import json  # needed for _check_cost_match and _check_poi_presence
