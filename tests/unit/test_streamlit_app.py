"""Unit tests for the Streamlit display layer.

These only exercise the pure data-conversion helpers; they import the app
module but never run it in a Streamlit runtime (bare mode warnings are fine).
"""

from agentic_tour_planner.app.streamlit_app import _plan_to_display_dict


def _plan(spot: dict) -> dict:
    return {"itinerary": [{"day": 1, "spots": [spot]}]}


def test_null_fields_do_not_crash():
    """LLM JSON frequently contains explicit nulls for known keys. .get() defaults
    only apply to MISSING keys, so a null must be coerced, not sliced/subscripted."""
    plan = _plan({"name": "Gangtok", "description": None, "history": None})
    out = _plan_to_display_dict(plan, {})
    spot = out["itinerary"][0]["spots"][0]
    assert spot["name"] == "Gangtok"
    assert spot["description"] == ""
    assert spot["key_note"] == ""
    assert spot["hours"] == "Not available"
    assert spot["transport"] == "Local transport"


def test_null_in_detail_falls_back_to_spot_description():
    plan = {
        "itinerary": [{"day": 1, "spots": [{"name": "Gangtok", "description": "D a long city description"}]}],
        "detailed": {
            "days": [
                {
                    "day": 1,
                    "places": [{"name": "Gangtok", "key_note": None, "description": None}],
                }
            ]
        },
    }
    out = _plan_to_display_dict(plan, {})
    spot = out["itinerary"][0]["spots"][0]
    assert spot["description"] == "D a long city description"
    assert spot["key_note"] == "D a long city description"[:120]


def test_key_note_truncated_to_120_chars():
    plan = _plan({"name": "Gangtok", "description": "x" * 500})
    out = _plan_to_display_dict(plan, {})
    spot = out["itinerary"][0]["spots"][0]
    assert spot["key_note"][:120] == "x" * 120
    assert spot["key_note"][120:] == ""


def test_opening_hours_uses_dash_separated_range():
    plan = _plan({"name": "Gangtok", "opening_hours": "9:00 AM", "closing_hours": "6:00 PM"})
    out = _plan_to_display_dict(plan, {})
    spot = out["itinerary"][0]["spots"][0]
    assert spot["hours"] == "9:00 AM \u2013 6:00 PM"


def test_wall_time_and_llm_usage_flow_through():
    plan = {
        "itinerary": [{"day": 1, "spots": [{"name": "Gangtok"}]}],
        "wall_time_s": 137.4,
        "llm_usage": {"used": ["itinerary planner", "day realign"], "fallback": ["detailed places"]},
    }
    out = _plan_to_display_dict(plan, {})
    assert out["wall_time_s"] == 137.4
    assert out["llm_usage"]["used"] == ["itinerary planner", "day realign"]
    assert out["llm_usage"]["fallback"] == ["detailed places"]


def test_missing_telemetry_defaults_to_none_and_empty():
    out = _plan_to_display_dict(_plan({"name": "Gangtok"}), {})
    assert out["wall_time_s"] is None
    assert out["llm_usage"] == {}


def test_is_optional_flows_from_detailed_plan():
    plan = {
        "itinerary": [{"day": 1, "spots": [{"name": "Gangtok"}, {"name": "Tsomgo Lake"}]}],
        "detailed": {
            "days": [
                {
                    "day": 1,
                    "places": [
                        {"name": "Gangtok"},
                        {"name": "Tsomgo Lake", "is_optional": True},
                    ],
                }
            ]
        },
    }
    out = _plan_to_display_dict(plan, {})
    by_name = {s["name"]: s for s in out["itinerary"][0]["spots"]}
    assert by_name["Gangtok"]["is_optional"] is False
    assert by_name["Tsomgo Lake"]["is_optional"] is True


def test_is_optional_defaults_false_when_unknown():
    out = _plan_to_display_dict(_plan({"name": "Gangtok"}), {})
    assert out["itinerary"][0]["spots"][0]["is_optional"] is False
