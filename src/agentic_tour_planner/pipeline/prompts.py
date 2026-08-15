from __future__ import annotations

import re
from pathlib import Path
from textwrap import dedent
from typing import Any

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.domain.models import (
    LiveWebBrief,
    PlanningInsights,
    PlanningRequest,
    RetrievedContext,
    parse_place_range,
)
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Guard against logistics/day-phase labels masquerading as real places
# (e.g. "Arrive", "Depart Gangtok", "Early", "Transit"). These are day-phase
# or travel-logistics labels, not tourist places, and should never be given
# their own spot entry with hours/best_time/transport fields.
# ---------------------------------------------------------------------------
_LOGISTICS_NAME_PATTERNS = re.compile(
    r"^\s*(arrive|arrival|depart(ure)?|early|transit|check[- ]?in|check[- ]?out|"
    r"drive to|drive from|en route|free time|rest day|travel day|return|transfer|"
    r"flight|layover|breakfast|lunch|dinner)\b",
    re.IGNORECASE,
)


def _is_real_place_name(name: str) -> bool:
    """Heuristic guard against logistics/day-phase labels masquerading as spots.

    Returns False for names that look like travel logistics or day-phase
    labels (e.g. "Arrive", "Depart Gangtok", "Early", "Transit", "Check-in")
    rather than actual named tourist attractions.
    """
    if not name:
        return False
    stripped = name.strip()
    if len(stripped) < 3:
        return False
    return not _LOGISTICS_NAME_PATTERNS.match(stripped)


def strip_place_markdown(name: str) -> str:
    """Remove markdown emphasis from a route-place `name` (e.g. '**Nathula Pass**' -> 'Nathula Pass').

    Bold/italic markdown is allowed in narrative fields (description, key_note,
    transport, best_time) but must never leak into the `name` field itself, which
    the renderer treats as literal text.
    """
    if not name:
        return ""
    cleaned = re.sub(r"[*_`]+", " ", str(name)).strip()
    return re.sub(r"\s+", " ", cleaned)


def _format_live_brief(brief: LiveWebBrief) -> str:
    logger.debug(
        f"Formatting live brief (sections filled={sum(1 for _ in [brief.path_instructions, brief.fair_charges, brief.transport_availability, brief.place_reviews, brief.daywise_guide] if _)}, sources={len(brief.sources)})"
    )
    sections = [
        ("Path instructions", brief.path_instructions),
        ("Fair charges", brief.fair_charges),
        ("Public transport availability", brief.transport_availability),
        ("Place reviews", brief.place_reviews),
        ("Day-wise guide", brief.daywise_guide),
    ]
    lines = []
    for label, value in sections:
        text = (value or "").strip()
        if text:
            lines.append(f"### {label}\n{text}")
    return "\n\n".join(lines)


def build_itinerary_prompt(
    request: PlanningRequest,
    context: RetrievedContext,
    insights: PlanningInsights,
    live_web_brief: LiveWebBrief | None = None,
) -> str:
    logger.debug(
        f"Building itinerary prompt for destination={request.destination!r} "
        f"days={request.trip_length_days} docs={len(context.documents)} "
        f"live_brief={'yes' if live_web_brief else 'no'}"
    )
    evidence_blocks: list[str] = []
    for document in context.documents[:12]:
        evidence_blocks.append(f"[Document] {document.title}\nURL: {document.url}\nContent: {document.content[:1500]}")
    for result in context.search_results[:8]:
        evidence_blocks.append(f"[Search] {result.title}\nURL: {result.url}\nSnippet: {result.snippet}")
    for place in context.place_hours[:8]:
        evidence_blocks.append(
            f"[Place Hours] {place.venue}\nStatus: {place.status}\nHours: {' | '.join(place.opening_hours)}"
        )
    if context.weather:
        evidence_blocks.append(f"[Weather] {context.weather.summary}")

    live_block = ""
    if live_web_brief:
        live_block = _format_live_brief(live_web_brief)

    guidance = dedent(
        f"""
        Route strategy: {insights.route.strategy}
        Route clusters: {"; ".join(insights.route.cluster_advice)}
        Transit notes: {"; ".join(insights.route.transit_notes)}
        Daily budget: {insights.budget.estimated_daily_budget}
        Total budget: {insights.budget.estimated_total_budget}
        Budget assumptions: {"; ".join(insights.budget.assumptions)}
        Savings tips: {"; ".join(insights.budget.saving_tips)}
        Timing summary: {insights.timing.season_summary}
        Booking window: {insights.timing.booking_window}
        Timing notes: {"; ".join(insights.timing.day_planning_notes)}
        """
    ).strip()

    transport_mode = request.transport_mode or "unspecified"
    transport_rule = (
        "TRANSPORT: The traveller will use their OWN CAR. Include transport_options with realistic options "
        "(rental car, taxi, ride-hailing, parking, tolls). For each option provide: mode, description, "
        "fare (with currency), and notes about availability or restrictions."
        if transport_mode == "car"
        else (
            "TRANSPORT: The traveller will use PUBLIC TRANSPORT. Populate a top-level "
            "transport_options list with one entry per realistic option (train, bus, metro, taxi, pass), "
            "each: {mode, description, fare (with currency), notes}. Include all options with fares in detail."
        )
        if transport_mode == "public"
        else "TRANSPORT: transport_mode not specified. Populate transport_options with all realistic options "
        "(train, bus, metro, taxi, rental car, pass) with fares in local currency."
    )

    place_lo, place_hi = parse_place_range(request.places_per_day)
    places_rule = (
        f"PLACES PER DAY (SOFT TARGET): Aim for about {place_lo}-{place_hi} places on regular days "
        f"(user asked '{request.places_per_day}'). This is a preference, not a quota: fewer places are "
        f"fine on arrival/transfer/departure days or when a region is sparse, and never pad a day with "
        f"distant places just to reach the count."
        if place_lo != place_hi
        else f"PLACES PER DAY (SOFT TARGET): Aim for about {place_lo} places on regular days "
        f"(user asked '{request.places_per_day}'). This is a preference, not a quota: fewer places are "
        f"fine on arrival/transfer/departure days or when a region is sparse, and never pad a day with "
        f"distant places just to reach the count."
    )

    authority_rule = (
        "SOURCE OF TRUTH: The LIVE WEB INTELLIGENCE block below (blogs/videos crawled and "
        "translated just now) is the authoritative, up-to-date source. Prioritise it over the "
        "knowledge-base evidence. Use the knowledge-base evidence only to supplement where the "
        "live block is silent."
        if live_web_brief
        else "No live web intelligence available; rely on the knowledge-base evidence."
    )

    evidence_text = "\n\n".join(evidence_blocks) or "No external evidence available."

    prompt = dedent(
        f"""
        You are producing a precise travel plan for {request.destination}.
        Respect the following input:
        Origin: {request.origin or "Not specified"}
        Trip length: {request.trip_length_days} days
        Interests: {", ".join(request.interests) or "General sightseeing"}
        Budget level: {request.budget_level}
        Travel month: {request.travel_month or "Flexible"}
        Notes: {request.notes or "None"}
        Transport mode: {transport_mode}

        STRICT PLANNING RULES:
        - PLACES PER DAY (SOFT TARGET): {places_rule}  (do NOT default to 1-2 places; aim for this preference)
        - GEOGRAPHIC CLUSTERING FIRST (MANDATORY): Before assigning places to days, group selected places into
          clusters by realistic road/transit proximity, NOT input order and NOT the same name everywhere.
          Places in the same day MUST sit within a 1-2 hour travel radius.
        - ONE REGION PER DAY (MANDATORY): Every day MUST be built from places lying in a SINGLE, contiguous
          geographic region/direction of the destination. Never mix two distant directions (e.g. north AND
          south Sikkim, or east AND south) in the same day. If a destination is commonly divided into named
          regions (e.g. North/East/West/South Sikkim, districts, valleys), tag each place with its region and
          assign the entire day to one region. Move a place to a neighbouring day rather than mixing regions
          in one day. The itinerary as a whole should sweep through regions in a sensible route order (one
          region per day, visiting them sequentially), not hop back and forth.
        - DAILY TRAVEL BUDGET: Keep each day's total local transit around 3-4 hours unless the user
          explicitly accepts a long-travel day. Do not add a place to a day when it pushes that day
          beyond this budget.
        - LONG-JUMP WARNING: Do not silently place two same-day spots together when they are about
          50-70 km apart or more than 1.5 hours apart. If unavoidable, write an explicit note such as
          "Note: Place X and Place Y are far apart; this day involves significant travel time."
        - EFFICIENT ORDER: Within each day, sequence places to minimize backtracking. Start from one
          end of the cluster and move logically through nearby places.
        - BASE CONTINUITY: If Day N ends far from the hotel/base, include the return-to-hotel leg in
          that day's logistics and travel budget. Day N+1 must logically start from the hotel/base or
          from the new hotel if needs_hotel_change=true.
        - MULTI-CITY / MULTI-BASE: For multi-city or multi-region trips, choose the overall city
          sequence first to avoid backtracking, mark inter-city transit days, and do not stack a full
          sightseeing day on top of a long transfer. End with a one-line route summary.
        - LOAD BALANCE AND HOURS: Balance sightseeing and travel load across days. Respect known
          opening hours and practical timing, such as sunset viewpoints late in the day.
        - DAY RATIONALE: Each day object MUST include rationale: one sentence explaining the geographic
          cluster, travel budget, and base continuity. If distance/time is uncertain, say the estimate
          is approximate and recommend verifying in maps.
        - COVERAGE: Use EVERY notable place named in the LIVE WEB INTELLIGENCE and the evidence blocks.
          Spread them across all days at the PLACES PER DAY rate; do not drop places or invent a fixed
          2-per-day pattern. Follow the route end-to-end (entry to exit) so the WHOLE journey is covered,
          not just a couple of early stops.
        - ANTI-GENERIC (mandatory): You MUST name SPECIFIC, REAL attractions, neighbourhoods, viewpoints,
          restaurants and hotels drawn from the LIVE WEB INTELLIGENCE and evidence blocks. NEVER use
          vague placeholder phrasing such as "anchor area", "activity zone", "a venue", "a local spot",
          "nearby", "scenic walk", "in a lively district", or "explore a <theme> area". If the evidence
          does not name a concrete place for a slot, STOP and reason from the real place names that ARE
          present — do NOT invent filler. Every activity line must contain at least one proper noun that
          is an actual place in {request.destination}.
        - NO LOGISTICS-AS-PLACES (mandatory): 'spots' and every day's place lists must ONLY
          contain real, named tourist attractions, landmarks, viewpoints, markets, monasteries,
          restaurants, or venues. NEVER create a spot/place entry for a travel-logistics or
          day-phase label such as "Arrive", "Arrival", "Depart <City>", "Departure", "Early
          Morning", "Transit", "Check-in", "Check-out", "Drive to <City>", "En Route",
          "Free Time", "Return", or "Transfer". These are not places. Arrival, departure,
          driving, and transfer details MUST be described inside that day's `summary`,
          `transport`, and `logistics` fields instead — never given their own place-style
          entry with hours/best_time/transport fields. If a day genuinely has fewer real named
          places than the minimum (e.g. a long transit day), add nearby real attractions along
          the route rather than inventing a fake "place" out of the logistics itself.
        - TIME WINDOWS: Every activity string MUST include a concrete time window, e.g.
          'Explore Arashiyama Bamboo Grove (Morning 6:00-8:30): walk in soft light'.
          Use realistic windows: Morning 6:00-8:30, Late Morning 8:30-11:00, Midday 11:00-13:00,
          Afternoon 14:00-16:30, Late Afternoon 16:30-18:30, Evening 19:00-21:30.
        - NO OVERLAP: Time windows of all activities in a day MUST NOT overlap. Order them chronologically
          and leave travel buffers between places.
        - RETURN DAY: Day {request.trip_length_days} may include return/departure logistics, but it
          MUST still include the requested minimum number of places in both activity lists and spots.
          Mark lower-priority places as optional when needed.
        - WEATHER: Provide an estimated monthly_weather string for {request.travel_month or "the travel month"}
          and a per-day weather block with temperature_c (day), temperature_night_c (night),
          sunrise, sunset, humidity_percent, rainfall_chance_percent.
        - MARKDOWN HIGHLIGHTING (rendered by the UI/CLI): Wrap the most important proper nouns —
          real place names, landmarks, mountains, lakes, neighbourhoods, people, dish names and
          monetary amounts/prices — in **bold** markdown across `overview`, each day's `summary`,
          `transport`, most of the morning/afternoon/evening activity text, `practical_tips`,
          and `transport_options` descriptions. Use *italics* sparingly (e.g. for mood or seasonal
          flavour). Bold should be tasteful and not on every word; bold the standout nouns per
          sentence so the rendered plan looks highlighted and colour-rich.
        - DAY STRUCTURE (render-ready): For each day provide:
            * summary: a 3-4 sentence overview of the day's plan and mood.
            * transport: how to get around that day (car route, metro lines, taxi notes).
            * meals: chronological list starting with breakfast, then lunch, then dinner
              (e.g. ['Breakfast: hotel buffet', 'Lunch: riverside cafe', 'Dinner: local izakaya']).
            * At least the requested minimum number of activities are FULL entries:
              write the activity string AND add a spots entry with name, slot, a 2-3 sentence history,
              opening_hours, closing_hours, best_time, a 2-3 sentence description of its scenic beauty,
              and an image_query.
              Use the exact place name in the matching activity string so they link.
            * Additional places above the requested range may be marked optional.
            * Always start the timeline with breakfast and include a lunch entry midday.
        - IMAGE QUERY (place-restricted): For every spot, `image_query` must be a photo-search
          phrase for THE PLACE ITSELF — its building, temple, monastery, monument or landscape,
          named with the destination, e.g. "Hanuman Tok temple, Gangtok". It must describe the
          physical landmark, never a generic animal, deity, celebrity or object the place name
          might evoke (e.g. "Hanuman Tok" must NOT become a plain "monkey" photo).
        - HOTEL: For EVERY day, provide a hotel_recommendation describing where to stay that night,
          placed just before the weather block. Tailor it to that day's area and base:
          Day 1 (arrival/base): "Take a hotel near '<area name>' because it is central to today's sights and transit."
          Day 2 (stay put): "Stay at '<area name>' since you are already based there and it is close to tomorrow's plan."
          Day 3 (moving base): "You are travelling to '<area>' tomorrow, so take a hotel in the area '<area>' tonight to minimise transit."
          Also set needs_hotel_change=true ONLY on days where the traveller should actually switch hotels
          (i.e. the recommended area differs from the previous day's base); otherwise leave it false.
        - {transport_rule}
        - {authority_rule}
- COORDINATES: Include lat and lon for every spot in the spots array so a
           geographic solver can assign places to days. Example: {{"name": "MG Marg", "lat": 27.3314, "lon": 88.6138}}.
        - SOLVER-BASED DAY ASSIGNMENT: A deterministic geographic solver assigns places to days
          after your extraction. Do NOT assign places to specific days in your output —
          only group places loosely by region to help the solver. The solver keeps days
          geographically coherent and honours your places-per-day figure as a soft
          preference. Do NOT pad days to hit a count. Your job is to
          extract accurate POIs with coordinates and write high-quality narrative text.

        LIVE WEB INTELLIGENCE (authoritative source of truth):
        {live_block or "Not collected."}

        Use this guidance:
        {guidance}

        Use this evidence:
        {evidence_text}

        Return JSON with keys:
        overview, monthly_weather, transport_options, itinerary, practical_tips, citations.
        Itinerary must be a list of day objects with:
        day, theme, summary, rationale, transport, morning, afternoon, evening, meals, logistics, weather, spots,
        needs_hotel_change, hotel_recommendation.
        Each spot in spots must include: name, lat, lon, slot, history, opening_hours, closing_hours, best_time, description, image_query.
          Citations must be grounded in the evidence above (favour the Live Web sources).
          """
    ).strip()
    logger.debug(f"Built itinerary prompt (length={len(prompt)} chars, evidence_blocks={len(evidence_blocks)})")
    return prompt


# Canonical, fixed output contract for the "detailed places" mode. Kept as a
# standalone markdown file so it is the single source of truth and never drifts.
_OUTPUT_FORMAT_PATH = Path(__file__).parent / "output_format.md"


def _load_output_format_spec() -> str:
    try:
        return _OUTPUT_FORMAT_PATH.read_text(encoding="utf-8").strip()
    except Exception as exc:
        logger.warning(f"Could not read output_format.md: {exc}")
        return "Produce a day-by-day place-by-place itinerary in Markdown."


def build_detailed_places_prompt(
    request: PlanningRequest,
    response: Any,
    live_brief: LiveWebBrief | None,
    place_hours_map: dict[str, Any],
    insights: PlanningInsights,
    target_day: int | None = None,
) -> str:
    """Build the prompt for the detailed place-by-place markdown itinerary.

    Uses the canonical ``output_format.md`` contract plus the REAL opening hours
    fetched via the Google Places tool and the per-day core places already chosen
    by the standard planner.

    If ``target_day`` is set, only that day's core places are included and the
    model is told to return just that single day (used for parallel generation).
    """
    logger.debug(
        f"Building detailed-places prompt destination={request.destination!r} "
        f"core_places_by_day={len(getattr(response, 'itinerary', []))} "
        f"hours_fetched={len(place_hours_map)} target_day={target_day}"
    )
    spec = _load_output_format_spec()

    place_lo, place_hi = parse_place_range(request.places_per_day)

    # ---- REAL opening hours (from the Google Places tool) ----
    hours_lines: list[str] = []
    for venue, ph in place_hours_map.items():
        if isinstance(ph, dict):
            status = ph.get("status")
            hours = ph.get("opening_hours") or []
        else:
            status = getattr(ph, "status", None)
            hours = getattr(ph, "opening_hours", None) or []
        joined = "; ".join(str(h) for h in hours) if hours else status or "Not available"
        hours_lines.append(f"- {venue}: {joined}")
    hours_block = "\n".join(hours_lines) if hours_lines else "No opening-hour data was retrieved."

    # ---- CORE places per day (from the standard plan) ----
    # Filtered through _is_real_place_name so logistics/day-phase labels
    # (e.g. "Arrive", "Depart Gangtok", "Early", "Transit") never get promoted
    # into the detailed-places prompt as if they were real attractions.
    core_lines: list[str] = []
    other_lines: list[str] = []
    dropped_logistics: list[str] = []
    for day in getattr(response, "itinerary", []):
        day_num = getattr(day, "day", None)
        is_target = target_day is None or day_num == target_day
        spots = getattr(day, "spots", None) or []
        names: list[str] = []
        for s in spots:
            n = s.get("name") if isinstance(s, dict) else getattr(s, "name", None)
            if not n:
                continue
            if _is_real_place_name(n):
                names.append(str(n))
            else:
                dropped_logistics.append(str(n))
        names = names[:place_hi]
        if not names:
            names = [f"(let the model choose a real place in {request.destination})"]
        if is_target:
            core_lines.append(f"Day {day_num} core places: " + " | ".join(names))
        else:
            other_lines.append(f"Day {day_num}: " + " | ".join(names))
    if dropped_logistics:
        logger.debug(
            f"Dropped {len(dropped_logistics)} logistics/day-phase labels from core places: {dropped_logistics}"
        )
    core_block = "\n".join(core_lines) if core_lines else "No core places pre-selected."
    other_block = "\n".join(other_lines) if other_lines else "None known — you are the only author of the plan."

    live_block = _format_live_brief(live_brief) if live_brief else "Not collected."

    guidance = dedent(
        f"""
        Route strategy: {insights.route.strategy}
        Transit notes: {"; ".join(insights.route.transit_notes)}
        Budget assumptions: {"; ".join(insights.budget.assumptions)}
        """
    ).strip()

    fare_source = ""
    if live_brief:
        fare_source = (
            "Use the LIVE WEB INTELLIGENCE 'Fair charges' and 'Public transport availability' "
            "sections below as the authoritative source for fares and transport options per place."
        )

    if target_day is not None:
        scope_instruction = (
            f"Return ONLY the single Day {target_day} object inside the 'days' array - nothing for the other days."
        )
    else:
        scope_instruction = f"Begin at Day 1 and continue through Day {request.trip_length_days}."

    return dedent(
        f"""
        {spec}

        === TRIP INPUT ===
        Destination: {request.destination}
        Trip length: {request.trip_length_days} days
        Interests: {", ".join(request.interests) or "General sightseeing"}
        Travel month: {request.travel_month or "Flexible"}
        Budget level: {request.budget_level}
        CORE places per day (soft target): aim for between {place_lo} and {place_hi}
        (user asked '{request.places_per_day}'). These get the full detail block.
        Fewer than {place_lo} is acceptable when the day's core list is genuinely
        short (e.g. travel days or sparse regions) — do NOT add filler places just to
        reach a count.

        === ROUTE GUIDANCE (follow this journey order) ===
        {guidance}

        === CORE PLACES PER DAY (use these real names) ===
        {core_block}

        === PLACES ALREADY SCHEDULED ON OTHER DAYS (never repeat these on this day) ===
        {other_block}

        STRICT DEDUPE & REGION RULES:
        - A day MUST NOT contain any place that is already a core place on another day of the
          trip — including as is_optional=true (e.g. do NOT write 'Enchey Monastery (optional)'
          on a Tsomgo Lake day when Enchey Monastery is already scheduled on the Gangtok day).
          Repeating a visited place on a later day is the worst error.
        - Never list the same place twice within one day.
        - Any is_optional=true extras must be REAL places in the SAME area/region as that day's
          core places (same neighbourhood or a short drive) — never halfway across the
          destination. Prefer 0-2 extras over padding a day with wrong-area stays.
        - The 'name' field of every place MUST be PLAIN TEXT — no **bold** or *italic* markdown
          inside the name (write 'Nathula Pass', never '**Nathula Pass**'). Markdown emphasis
          belongs only inside description, key_note, transport, and best_time.

        === REAL OPENING HOURS (from Google Places tool — use these, do not guess) ===
        {hours_block}

        === LIVE WEB INTELLIGENCE (authoritative source of truth) ===
        {live_block}

        {fare_source}

        Return ONLY valid JSON matching the schema at the top (root key "days"). {scope_instruction}
        Every CORE place must
        include description, opening_closing, best_time, transport, key_note,
        "is_optional": false and a "keywords" array. Optional extra places use
        "is_optional": true with description, key_note and keywords only
        (no opening_closing or transport).
        Ensure the returned day object has "day": {target_day if target_day is not None else "N"} where N is the day number.

        Never output a "place" entry for arrival, departure, transit, packing, or
        check-in/out phases — these belong only in the day-level summary/transport text,
        not as a named place with its own description, hours, or transport block.

        CRITICAL WORD COUNT REQUIREMENTS:
        - description: MUST be 180-220 words. This is STRICTLY enforced.
        - key_note: MUST be a single concise sentence of 20-30 words only.
          Keep it to one line; no multiple sentences or elaboration.

        Each description must include:
        1. History and cultural significance
        2. Physical description of the place
        3. Visitor experience and what to see
        4. Practical tips (best time to visit, cost, etc.)
        5. Local context and nearby attractions

        For every place, populate "keywords" with the important terms that appear verbatim
        inside that place's "description", each tagged with a category:
        "place" (locations/landmark names), "altitude" (elevation/height in m or ft),
        "person" (famous/historical people), "deity" (gods/saints/religious figures),
        "other" (any other locally important term). These are used by the renderer to
        colour the text, so the "text" values must match the description exactly.

        Add light markdown emphasis to every narrative field (description, key_note,
        transport, best_time AND the day-level summary in "days"): wrap real proper
        nouns (place names, mountains, lakes, famous people, landmarks, dish names,
        prices/amounts, the destination itself) in **bold** for emphasis, and use
        *italics* sparingly for atmospheric or secondary phrasing. This makes the
        CLI and web UI render the itinerary with eye-catching highlights. Keep it
        terse and natural — do not bold every word; bold only a handful of the most
        important nouns per field.
        """
    ).strip()


def _detailed_system_prompt():
    return get_settings().DETAILED_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Day realignment: regenerate the day-level narrative (theme, summary, hotel)
# AFTER the deterministic solver has fixed which places belong to which day.
# The LLM's original theme/summary/hotel described its own (possibly wrong)
# day composition; this pass makes header, narrative and accommodation match
# the FINAL place list exactly.
# ---------------------------------------------------------------------------


def _day_realign_system_prompt():
    return get_settings().DAY_REALIGN_SYSTEM_PROMPT


def build_day_realign_prompt(
    request: PlanningRequest,
    day_num: int,
    day_places: list[str],
    prev_day_places: list[str],
    budget_level: str | None = None,
) -> str:
    """Build the prompt that realigns one day's theme/summary/hotel with the
    solver's FINAL place list for that day.

    ``day_places`` and ``prev_day_places`` are already-final place names (never
    logistics labels). The model must only write narrative around them.
    """
    logger.debug(f"build_day_realign_prompt day={day_num} places={len(day_places)} prev_places={len(prev_day_places)}")
    places_block = "\n".join(f"- {name}" for name in day_places) or "- (no places)"
    prev_block = "\n".join(f"- {name}" for name in prev_day_places) or "- (first day / no previous)"

    return dedent(
        f"""
        Destination: {request.destination}
        Day number: {day_num}
        Budget level: {budget_level or request.budget_level or "midrange"}

        FINAL places for Day {day_num} (FIXED — write the narrative around exactly these):
        {places_block}

        Previous day's places (context for needs_hotel_change only):
        {prev_block}

        Return ONLY the JSON object described in your instructions.
        """
    ).strip()
