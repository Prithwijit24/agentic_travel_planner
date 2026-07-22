#!/usr/bin/env python
"""Interactive CLI for the Agentic Travel Planner pipeline."""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from enum import Enum
from typing import Any

import typer
import click
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.text import Text

from agentic_tour_planner.utils.logging import configure_logging, get_logger

console = Console()
logger = get_logger(__name__)

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.domain.models import PlanningRequest, parse_place_range
from agentic_tour_planner.llm.hooks import metrics_bus
from agentic_tour_planner.llm.provider import LLMProvider
from agentic_tour_planner.pipeline.agentic_pipeline import AgenticTourPlannerPipeline
from agentic_tour_planner.utils.profiler import StageTimer

app = typer.Typer(help="Agentic Travel Planner - Interactive CLI")


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


def setup_logging(level: LogLevel = LogLevel.INFO) -> None:
    configure_logging(level.value)


_STEP_ICONS = {1: "🔍", 2: "🧠", 3: "📋", 4: "🗺️"}


def print_section(title: str) -> None:
    console.rule(f"[bold cyan]✨ {escape(title)}[/bold cyan]")


def print_step(step: int, name: str, description: str) -> None:
    icon = _STEP_ICONS.get(step, "▶️")
    console.print(
        f"{icon} [bold yellow]Step {step}:[/bold yellow] "
        f"[bold]{escape(name)}[/bold] — {escape(description)}"
    )


def print_step_done(name: str, elapsed: float) -> None:
    console.print(
        f"  [green]✅ {escape(name)} complete[/green]  [dim]⏱️ {elapsed:.2f}s[/dim]"
    )


def _select_provider_interactive() -> str | None:
    """Prompt the user to pick an LLM provider for this plan.

    The model is always taken from the provider's declared list in llm.yml, so the
    user only chooses the provider (not a specific model).
    """
    logger.debug("Prompting user to select LLM provider")
    lp = LLMProvider()
    providers = lp.list_providers()
    if not providers:
        logger.warning("No LLM providers available")
        return None

    print_section("MODEL PROVIDER SELECTION")
    default_provider = get_settings().default_llm_provider or providers[0]
    provider = typer.prompt(
        "Model provider",
        default=default_provider,
        type=click.Choice(providers),
    )
    return provider


# Category -> rich colour used for keyword highlighting in description paragraphs.
CATEGORY_COLORS = {
    "place": "cyan",
    "altitude": "orange",
    "person": "magenta",
    "deity": "yellow",
    "other": "green",
}


def _apply_emphasis(s: str) -> str:
    """Convert **bold** / *italic* to rich markup on an ALREADY escaped string."""
    s = re.sub(r"\*\*(.+?)\*\*", r"[bold]\1[/bold]", s)
    s = re.sub(r"(?<!\*)\*(?!\*)(.+?)\*(?!\*)", r"[italic]\1[/italic]", s)
    return s


def _md_emphasis(text: str) -> str:
    """Escape text then convert lightweight markdown emphasis (**bold**, *italic*)."""
    return _apply_emphasis(escape(text))


def _highlight_names(text: str, names: list[str]) -> str:
    """Escape text, convert emphasis, and wrap any matching place name in a distinct color."""
    escaped = _md_emphasis(text)
    for name in sorted({n for n in names if n}, key=len, reverse=True):
        ename = escape(name)
        if not ename:
            continue
        pattern = re.compile(r"(?i)\b" + re.escape(ename) + r"\b")
        escaped = pattern.sub(f"[bold cyan]{ename}[/bold cyan]", escaped)
    return escaped


def _highlight_keywords(text: str, keywords: list) -> str:
    """Escape text, wrap important keywords by category (bold + colour), then apply emphasis.

    Each keyword is ``{"text": ..., "category": ...}`` (or a ``Keyword`` object). The
    ``text`` must appear verbatim in the description so it can be matched.
    """
    s = escape(text)
    items: list[tuple[str, str]] = []
    for kw in keywords or []:
        if isinstance(kw, dict):
            kt, kc = kw.get("text"), kw.get("category")
        else:
            kt = getattr(kw, "text", None)
            kc = getattr(kw, "category", "other")
        if not kt:
            continue
        items.append((escape(str(kt)), CATEGORY_COLORS.get(kc or "other", "green")))
    # Wrap longer terms first so nested/shorter overlaps don't clobber them.
    items.sort(key=lambda x: len(x[0]), reverse=True)
    for kt, color in items:
        if not kt:
            continue
        pattern = re.compile(r"(?i)\b" + re.escape(kt) + r"\b")
        s = pattern.sub(rf"[bold {color}]{kt}[/bold {color}]", s)
    return _apply_emphasis(s)


_TIME_RE = re.compile(r"\b(\d{1,2}:\d{2}(?:\s*[APap][Mm])?)\b")


def _highlight_times(text: str) -> str:
    """Wrap clock time patterns in bold yellow."""
    return _TIME_RE.sub(r"[bold yellow]\1[/bold yellow]", text)


def _render_weather(w: dict | None) -> str:
    if not w:
        return ""
    parts: list[str] = []
    day = w.get("temperature_c")
    night = w.get("temperature_night_c")
    if day is not None or night is not None:
        if day is not None and night is not None:
            parts.append(
                f"🌡️ Temp (day [orange]{day}°C[/orange] / night [bright_blue]{night}°C[/bright_blue])"
            )
        elif day is not None:
            parts.append(f"🌡️ Temp (day [orange]{day}°C[/orange])")
        else:
            parts.append(f"🌡️ Temp (night [bright_blue]{night}°C[/bright_blue])")
    if w.get("sunrise"):
        parts.append(f"🌅 [bright_orange]Sunrise[/bright_orange] {_highlight_times(escape(w['sunrise']))}")
    if w.get("sunset"):
        parts.append(f"🌇 [grey]Sunset[/grey] {_highlight_times(escape(w['sunset']))}")
    if w.get("humidity_percent") is not None:
        parts.append(f"💧 [magenta]Humidity {w['humidity_percent']}%[/magenta]")
    if w.get("rainfall_chance_percent") is not None:
        parts.append(f"🌧️ [cyan]Rain {w['rainfall_chance_percent']}%[/cyan]")
    return "  " + "   ·   ".join(parts) if parts else ""


def _match_spot(activity: str, spot_by_name: dict) -> dict | None:
    for name, spot in spot_by_name.items():
        if name and name in activity:
            return spot
    return None


_MEAL_RE = re.compile(r"^\s*(breakfast|lunch|dinner)\b[:\-\s]*", re.IGNORECASE)


def _is_meal(text: str) -> bool:
    return bool(_MEAL_RE.match(text or ""))


def _clean_meal(text: str) -> str:
    return _MEAL_RE.sub("", text or "").strip()


def _render_transport(options: list[dict]) -> str:
    if not options:
        return ""
    lines = ["[bold]🚆 Transport Options[/bold]"]
    for opt in options:
        mode = escape(opt.get("mode", "option"))
        fare = escape(opt.get("fare") or "fare N/A")
        desc = escape(opt.get("description") or "")
        notes = escape(opt.get("notes") or "")
        line = f"  • [bold yellow]{mode}[/bold yellow] — 💵 {fare}"
        if desc:
            line += f"  {desc}"
        if notes:
            line += f"  [dim]{notes}[/dim]"
        lines.append(line)
    return "\n".join(lines)


def _render_cost(cost: dict) -> str:
    if not cost:
        return ""
    lines = ["[bold]💰 Cost Estimate[/bold]"]
    for day in cost.get("daily", []) or []:
        items = day.get("items") or []
        item_strs = []
        for i in items:
            label = escape(i.get('label', ''))
            amt = i.get('amount')
            if isinstance(amt, str):
                amt_display = f"[bright_green]{amt}[/bright_green]"
            else:
                amt_display = f"[bright_green]{amt} rupees[/bright_green]"
            item_strs.append(f"{label}: {amt_display}")
        item_str = "; ".join(item_strs)
        subtotal = day.get("subtotal")
        header = f"  [bold]Day {day.get('day')}:[/bold]"
        if item_str:
            header += f" {item_str}"
        if subtotal is not None:
            st_str = subtotal if isinstance(subtotal, str) else f"{subtotal} rupees"
            header += f"  → [bold bright_green]subtotal {_highlight_times(escape(str(st_str)))}[/bold bright_green]"
        lines.append(header)
    overall = cost.get("overall") or {}
    if overall:
        members = overall.get("members", 1)
        ppt = overall.get("per_person_total")
        grand = overall.get("grand_total")
        ppt_str = ppt if isinstance(ppt, str) else (f"{ppt} rupees" if ppt is not None else "N/A")
        grand_str = grand if isinstance(grand, str) else (f"{grand} rupees" if grand is not None else "N/A")
        oline = f"  [bold]Overall (per person: {_highlight_times(escape(str(ppt_str)))}, members: {members}"
        if grand is not None:
            oline += f", grand total: [bold bright_green]{_highlight_times(escape(str(grand_str)))}[/bold bright_green]"
        oline += ")[/bold]"
        lines.append(oline)
    return "\n".join(lines)


def _render_live_web(brief: dict | None) -> str:
    if not brief:
        return ""
    sections = [
        ("🧭 Path instructions", brief.get("path_instructions")),
        ("💵 Fair charges", brief.get("fair_charges")),
        ("🚌 Public transport", brief.get("transport_availability")),
        ("⭐ Place reviews", brief.get("place_reviews")),
        ("🗓️ Day-wise guide", brief.get("daywise_guide")),
    ]
    lines = ["[bold]🌐 Live Web Intelligence (source of truth)[/bold]"]
    for label, value in sections:
        text = (value or "").strip()
        if text:
            lines.append(f"  {label}: [green]{escape(text)}[/green]")
    sources = brief.get("sources") or []
    if sources:
        lines.append("  [dim]Sources:[/dim]")
        for s in sources:
            title = escape(s.get("title", ""))
            url = s.get("url") or "#"
            kind = s.get("kind", "web")
            line = f"    • [{kind}] [link={url}]{title}[/link]"
            if s.get("audio_path"):
                line += f"  [dim]🎧 {escape(s['audio_path'])}[/dim]"
            lines.append(line)
    return "\n".join(lines)


def _render_metrics(metrics: dict | None) -> str:
    if not metrics:
        return ""
    tok = metrics.get("tokens", {})
    tm = metrics.get("time", {})
    lines = ["[bold]📊 Usage Metrics[/bold]"]
    lines.append(
        f"  🪙 [bold]Tokens:[/bold] {tok.get('total_tokens', 0)} total "
        f"(prompt {tok.get('prompt_tokens', 0)} + completion {tok.get('completion_tokens', 0)}) "
        f"across {tok.get('calls', 0)} LLM calls"
    )
    failed = tok.get("failed_calls", 0)
    if failed:
        lines.append(f"  ⚠️ [yellow]{failed} call(s) failed[/yellow]")
    lines.append(
        f"  ⏱️ [bold]Time (estimate):[/bold] {tm.get('total_llm_s', 0):.2f}s LLM time "
        f"over {tm.get('calls', 0)} calls"
    )
    per = tm.get("per_provider_s") or {}
    if per:
        parts = ", ".join(f"{escape(p)}: {s:.2f}s" for p, s in per.items())
        lines.append(f"  ⏱️ [dim]per provider — {parts}[/dim]")
    return "\n".join(lines)


def render_plan(response: dict) -> None:
    """Render the finished travel plan with rich color, emoji icons and bold headers."""
    console.rule("[bold magenta]✨ TRIP PLAN ✨[/bold magenta]")

    console.print(
        Panel(
            escape(response.get("overview", "")),
            title="📝 Overview",
            border_style="cyan",
            expand=False,
        )
    )

    monthly = response.get("monthly_weather")
    month_label = response.get("travel_month") or "this month"
    if monthly:
        console.print(
            f"🌤️ [bold]Estimated weather ({escape(month_label)}):[/bold] {escape(monthly)}"
        )

    console.print(
        f"🤖 [bold]Planner Provider:[/bold] {escape(response.get('provider_used', ''))}    "
        f"⚙️ [bold]Planner Model:[/bold] {escape(response.get('model_used', ''))}"
    )
    worker_routing = response.get("worker_routing")
    if worker_routing:
        console.print("🛠️ [bold]Worker routing (per role):[/bold]")
        role_icons = {"route": "🗺️", "budget": "💰", "timing": "⏰"}
        for role, meta in worker_routing.items():
            if isinstance(meta, (list, tuple)) and len(meta) == 2:
                console.print(
                    f"    {role_icons.get(role, '•')} [bold]{escape(role)}:[/bold] "
                    f"{escape(str(meta[0]))}/{escape(str(meta[1]))}"
                )
    else:
        worker_provider = response.get("worker_provider_used")
        worker_model = response.get("worker_model_used")
        if worker_provider or worker_model:
            console.print(
                f"🛠️ [bold]Worker Provider:[/bold] {escape(worker_provider or '')}    "
                f"⚙️ [bold]Worker Model:[/bold] {escape(worker_model or '')}"
            )

    console.print()
    console.print("[bold]🗺️ Itinerary[/bold]")
    for day in response.get("itinerary", []):
        spots = day.get("spots") or []
        spot_names = [s.get("name") for s in spots if s.get("name")]
        spot_by_name = {s.get("name"): s for s in spots if s.get("name")}
        meals = day.get("meals") or []
        breakfast = meals[0] if meals else None
        remaining = meals[1:]
        lunch = remaining[0] if remaining else None
        dinner = remaining[-1] if len(remaining) >= 2 else None

        morning = day.get("morning") or []
        afternoon = day.get("afternoon") or []
        evening = day.get("evening") or []
        # Drop meal lines from the activity streams (they are rendered from `meals`
        # below) so we never show breakfast/lunch/dinner twice.
        morning_acts = [a for a in morning if not _is_meal(a)]
        afternoon_acts = [a for a in afternoon if not _is_meal(a)]
        evening_acts = [a for a in evening if not _is_meal(a)]

        timeline: list[str] = []
        if breakfast:
            timeline.append(
                f"  🍳 [bold bright_green]Breakfast:[/bold bright_green] {escape(_clean_meal(breakfast))}"
            )

        spot_counter = 0

        def _render_acts(acts: list[str]) -> None:
            nonlocal spot_counter
            for act in acts:
                spot_counter += 1
                is_full = spot_counter % 3 == 1  # 1st, 4th, 7th, 10th spot
                spot = _match_spot(act, spot_by_name) if is_full else None
                if spot:
                    timeline.append(
                        f"  📍 [bold bright_green]{escape(act)}[/bold bright_green]"
                    )
                    name = escape(spot.get("name", "?"))
                    timeline.append(f"     🏛️ [bold cyan]{name}[/bold cyan]")
                    if spot.get("history"):
                        timeline.append(f"     📜 {escape(spot['history'])}")
                    oh, ch = spot.get("opening_hours"), spot.get("closing_hours")
                    if oh or ch:
                        timeline.append(
                            f"     🕒 {escape(oh or '?')} – {escape(ch or '?')}"
                        )
                    if spot.get("best_time"):
                        timeline.append(
                            f"     ⏰ [green]Best time: {escape(spot['best_time'])}[/green]"
                        )
                    if spot.get("description"):
                        timeline.append(f"     🌄 {escape(spot['description'])}")
                else:
                    timeline.append(
                        f"  📍 {_highlight_names(escape(act), spot_names)}"
                    )

        _render_acts(morning_acts)
        if lunch:
            timeline.append(
                f"  🍴 [bold bright_green]Lunch:[/bold bright_green] {escape(_clean_meal(lunch))}"
            )
        _render_acts(afternoon_acts)
        _render_acts(evening_acts)
        if dinner and dinner is not lunch:
            timeline.append(
                f"  🍽️ [bold bright_green]Dinner:[/bold bright_green] {escape(_clean_meal(dinner))}"
            )

        content_parts: list[str] = []
        if day.get("summary"):
            content_parts.append(f"  📝 {escape(day['summary'])}")
        if day.get("transport"):
            content_parts.append(f"  🚌 {escape(day['transport'])}")
        content_parts.append("")
        content_parts.append("[bold bright_green]🟢 Timeline[/bold bright_green]")
        content_parts.append("\n".join(timeline) if timeline else "  (no activities planned)")
        content_parts.append("")

        hotel_rec = day.get("hotel_recommendation")
        if hotel_rec:
            content_parts.append(
                f"  🏨 [bold bright_green]Hotel:[/bold bright_green] {escape(hotel_rec)}"
            )

        weather_line = _render_weather(day.get("weather"))
        if weather_line:
            content_parts.append(weather_line)

        console.print(
            Panel(
                "\n".join(content_parts),
                title=f"📅 Day {day.get('day')}: {escape(day.get('theme', ''))}",
                border_style="green",
                expand=False,
            )
        )

    transport_text = _render_transport(response.get("transport_options") or [])
    if transport_text:
        console.print()
        console.print(transport_text)

    cost = response.get("cost_estimate")
    if cost:
        console.print()
        console.print(_render_cost(cost))

    tips = response.get("practical_tips") or []
    if tips:
        console.print()
        console.print("[bold]💡 Practical Tips[/bold]")
        for tip in tips:
            console.print(f"  • {escape(str(tip))}")

    citations = response.get("citations") or []
    if citations:
        console.print()
        console.print("[bold]🔗 Citations[/bold]")
        for citation in citations:
            if isinstance(citation, dict):
                title = escape(citation.get("title", ""))
                url = citation.get("url") or "#"
                console.print(f"  • [link={url}]{title}[/link]  [dim]{escape(url)}[/dim]")
            else:
                console.print(f"  • {escape(str(citation))}")

    live_brief = response.get("live_web_brief")
    live_text = _render_live_web(live_brief)
    if live_text:
        console.print()
        console.print(live_text)

    metrics_text = _render_metrics(response.get("metrics"))
    if metrics_text:
        console.print()
        console.print(metrics_text)

    profile_text = _render_profile(response.get("profile") or [])
    if profile_text:
        console.print()
        console.print(profile_text)


def _render_detailed_day(day: dict, std_day: dict | None = None) -> None:
    """Render one day of the consolidated itinerary: day plan + detailed places + hotel + weather."""
    day_no = day.get("day", "?")
    theme = day.get("theme", "")
    places = day.get("places", []) or []
    all_names = [p.get("name", "") for p in places if p.get("name")]

    content = ""

    # --- Day plan (≈50-100 words) from the standard itinerary day ---
    if std_day and std_day.get("summary"):
        content += (
            f"[bold yellow]📝 Day Plan:[/bold yellow] "
            f"{_highlight_names(_md_emphasis(std_day["summary"]), all_names)}\n"
        )

    for place in places:
        name = place.get("name", "")
        optional = place.get("is_optional")
        if optional:
            content += f"\n[bold cyan]📍 {escape(name)}[/bold cyan] [dim](optional)[/dim]\n"
        else:
            content += f"\n[bold cyan]📍 {escape(name)}[/bold cyan]\n"

        desc = place.get("description") or ""
        if desc:
            rendered = (
                _highlight_keywords(desc, place.get("keywords"))
                if place.get("keywords")
                else _highlight_names(desc, all_names)
            )
            content += f"[bold yellow]Description:[/bold yellow] {rendered}\n"

        if not optional:
            oc = place.get("opening_closing") or "Not available"
            content += f"[bold cyan]Opening & Closing:[/bold cyan] {_highlight_times(escape(oc))}\n"
            bt = place.get("best_time") or ""
            if bt:
                content += f"[bold green]Best time:[/bold green] {_highlight_times(escape(bt))}\n"
            tr = place.get("transport") or ""
            if tr:
                content += f"[bold magenta]Transport:[/bold magenta] {_highlight_times(escape(tr))}\n"

        kn = place.get("key_note") or ""
        if kn:
            content += f"[bold bright_orange]Key note:[/bold bright_orange] {_highlight_names(kn, all_names)}\n"

    # --- Hotel (label yellow; the hotel text itself is bold) ---
    if std_day and std_day.get("hotel_recommendation"):
        content += (
            f"\n[yellow]🏨 Hotel:[/yellow] [bold]{escape(std_day['hotel_recommendation'])}[/bold]\n"
        )

    # --- Weather (last line, unchanged) ---
    weather_line = _render_weather(std_day.get("weather") if std_day else None)
    if weather_line:
        content += f"\n{weather_line}\n"

    console.print(
        Panel(
            Text.from_markup(content.strip()),
            title=f"📅 [bold yellow]Day {day_no}[/bold yellow] — {escape(theme)}",
            border_style="cyan",
            expand=False,
        )
    )


def _resources_block() -> str:
    """Booking & shopping affiliate links shown at the end of the Overview pane."""
    travel = (
        "[link=https://www.makemytrip.com]makemytrip[/link], "
        "[link=https://www.agoda.com]agoda[/link], "
        "[link=https://www.goibibo.com]goibibo[/link]"
    )
    hotel = f"{travel}, [link=https://www.booking.com]booking[/link]"
    accessories = (
        "[link=https://www.amazon.com]Amazon[/link], "
        "[link=https://www.flipkart.com]flipkart[/link]"
    )
    return (
        "[bold yellow]🧳 Booking & Resources[/bold yellow]\n"
        f"  ✈️ Train/Flight: {travel}\n"
        f"  🏨 Hotel booking: {hotel}\n"
        f"  🛍️ Accessories: {accessories}"
    )


def render_combined(standard: dict, detailed: dict) -> None:
    """Render ONE blended section: standard metadata + detailed places, richly styled."""
    console.rule("[bold magenta]✨ TRIP PLAN ✨[/bold magenta]")

    overview_raw = standard.get("overview", "") or ""
    overview_safe = escape(overview_raw).replace("[", "\\[").replace("]", "\\]")
    console.print(
        Panel(
            overview_safe + "\n\n" + _resources_block(),
            title="📝 Overview",
            border_style="cyan",
            expand=False,
        )
    )

    monthly = standard.get("monthly_weather")
    month_label = standard.get("travel_month") or "this month"
    if monthly:
        console.print(
            f"🌤️ [bold]Estimated weather ({escape(month_label)}):[/bold] {escape(monthly)}"
        )
    console.print(
        f"🤖 [bold]Planner:[/bold] {escape(standard.get('provider_used', ''))}    "
        f"⚙️ [bold]Model:[/bold] {escape(standard.get('model_used', ''))}"
    )
    console.print()

    tips = standard.get("practical_tips") or []
    if tips:
        console.print(
            Panel(
                "\n".join(f"• {escape(t)}" for t in tips),
                title="💡 Practical Tips",
                border_style="green",
                expand=False,
            )
        )

    console.print()
    std_list = standard.get("itinerary", []) or []
    std_days = {d.get("day"): d for d in std_list}
    for i, day in enumerate((detailed or {}).get("days", [])):
        key = day.get("day")
        std_day = std_days.get(key) if key is not None else None
        if std_day is None and i < len(std_list):
            std_day = std_list[i]
        _render_detailed_day(day, std_day)

    transport = standard.get("transport_options") or []
    if transport:
        console.print(
            Panel(_render_transport(transport), title="🚆 Transport", border_style="blue", expand=False)
        )

    cost = standard.get("cost_estimate")
    if cost:
        console.print(
            Panel(_render_cost(cost), title="💰 Cost Estimate", border_style="green", expand=False)
        )

    cites = standard.get("citations") or []
    if cites:
        console.print("[dim]Sources:[/dim]")
        for c in cites[:8]:
            console.print(f"  • {escape(c.get('title', ''))} — {escape(c.get('url', ''))}")


def _render_profile(profile_rows: list[dict]) -> str:
    if not profile_rows:
        return ""
    lines = ["[bold]⏱️  Pipeline Profile (wall-clock)[/bold]"]
    for row in profile_rows:
        is_total = row["stage"] == "TOTAL"
        bar_len = max(int(row["pct"] / 6), 1) if not is_total else 16
        bar = "█" * bar_len
        name = row["stage"]
        elapsed = row["elapsed_s"]
        pct = row["pct"]
        if is_total:
            lines.append(
                f"  [bold bright_green]{bar}[/bold bright_green]  [bold]TOTAL:[/bold] {elapsed:.2f}s"
            )
        else:
            lines.append(
                f"  [bold]{escape(name):<32}[/bold] {bar:<16}  {elapsed:>7.2f}s  ({pct:>5.1f}%)"
            )
    return "\n".join(lines)


async def run_pipeline(request: PlanningRequest, verbose: bool = True, mode: str = "standard", profile: bool = False) -> dict[str, Any]:
    """Run the full pipeline with detailed logging.

    ``mode`` is either ``"standard"`` (structured itinerary) or ``"places"``
    (detailed place-by-place Markdown itinerary built on real opening hours).
    """
    logger.debug(f"run_pipeline start destination={request.destination} live={request.include_live_data}")
    metrics_bus.reset()
    if verbose:
        console.rule("[bold cyan]🚀 AGENTIC TRAVEL PLANNER PIPELINE[/bold cyan]")
    
    # Initialize components
    if verbose:
        logger.info("Initializing pipeline components...")
    
    settings = get_settings()
    pipeline = AgenticTourPlannerPipeline()
    
    if verbose:
        logger.info(f"Planner model: {pipeline.planner_provider}/{pipeline.planner_model}")
        worker_provider, worker_model = pipeline.llm_provider.get_worker_model()
        logger.info(f"Worker model: {worker_provider}/{worker_model}")
        if request.provider:
            logger.info(f"Selected provider override: {request.provider}")
    
    # Step 1: Gather Context
    if verbose:
        print_step(1, "Gather Context", "Retrieving relevant information...")
        logger.info(f"Destination: {request.destination}")
        logger.info(f"Trip length: {request.trip_length_days} days")
        logger.info(f"Interests: {request.interests}")
    
    with pipeline.profiler.track("CLI: Gather Context"):
        context = await pipeline.gather_context(request)
    elapsed = pipeline.profiler.summary().get("CLI: Gather Context", 0.0)
    
    if verbose:
        print_step_done("Gather Context", elapsed)
        logger.debug(f"Documents retrieved: {len(context.documents)}")
        logger.debug(f"Search results: {len(context.search_results)}")
        logger.debug(f"Place hours: {len(context.place_hours)}")
        logger.debug(f"Weather: {context.weather.summary if context.weather else 'N/A'}")
    
    # Step 2: Build Insights
    if verbose:
        print_step(2, "Build Insights", "Generating route, budget, and timing guidance...")
    
    with pipeline.profiler.track("CLI: Build Insights"):
        insights = await pipeline.insights_builder.build(request, context, provider_override=request.provider)
    elapsed = pipeline.profiler.summary().get("CLI: Build Insights", 0.0)
    
    if verbose:
        print_step_done("Build Insights", elapsed)
        logger.debug(f"Route strategy: {insights.route.strategy[:80]}...")
        logger.debug(f"Budget: ${insights.budget.estimated_daily_budget:.0f}/day")
        logger.debug(f"Booking: {insights.timing.booking_window}")
    
    # Step 3: Build Prompt
    if verbose:
        print_step(3, "Build Prompt", "Constructing planning prompt...")
    
    from agentic_tour_planner.pipeline.prompts import build_itinerary_prompt
    prompt = build_itinerary_prompt(request, context, insights)
    
    if verbose:
        print_step_done("Build Prompt", 0.0)
        logger.debug(f"Prompt length: {len(prompt)} characters")
    
    # Step 4: Generate Plan
    if verbose:
        print_step(4, "Generate Plan", "Creating itinerary with LLM...")
    
    start_time = datetime.now()
    response = await pipeline.run(request, context=context, insights=insights)
    elapsed = (datetime.now() - start_time).total_seconds()
    
    if verbose:
        print_step_done("Generate Plan", elapsed)
        logger.info(f"Planner: {response.provider_used}/{response.model_used}")
        logger.info(f"Worker: {response.worker_provider_used}/{response.worker_model_used}")

    profile_rows: list[dict] = []
    if profile:
        profile_rows = pipeline.profiler.as_table()

    detailed = None
    if mode == "places":
        if verbose:
            print_step(5, "Detailed Places", "Fetching real hours + writing place-by-place itinerary...")
        start_time = datetime.now()
        detailed_obj = await pipeline.run_detailed_places(request, response, context=context, insights=insights)
        elapsed = (datetime.now() - start_time).total_seconds()
        if verbose:
            print_step_done("Detailed Places", elapsed)
        detailed = detailed_obj.model_dump() if detailed_obj else None
        if profile:
            profile_rows = pipeline.profiler.as_table()

    return {
        "request": request.model_dump(mode="json"),
        "context": {
            "documents_count": len(context.documents),
            "search_results_count": len(context.search_results),
            "place_hours_count": len(context.place_hours),
            "weather": context.weather.summary if context.weather else None,
        },
        "insights": {
            "route": {
                "strategy": insights.route.strategy,
                "cluster_advice": insights.route.cluster_advice,
                "transit_notes": insights.route.transit_notes,
            },
            "budget": {
                "estimated_daily_budget": insights.budget.estimated_daily_budget,
                "estimated_total_budget": insights.budget.estimated_total_budget,
                "assumptions": insights.budget.assumptions,
                "saving_tips": insights.budget.saving_tips,
            },
            "timing": {
                "season_summary": insights.timing.season_summary,
                "booking_window": insights.timing.booking_window,
                "day_planning_notes": insights.timing.day_planning_notes,
            },
        },
            "response": {
                "plan_id": response.plan_id,
                "overview": response.overview,
            "monthly_weather": response.monthly_weather,
            "travel_month": request.travel_month,
            "transport_options": [t.model_dump() for t in response.transport_options],
            "cost_estimate": response.cost_estimate.model_dump() if response.cost_estimate else None,
                "itinerary": [day.model_dump() for day in response.itinerary],
                "practical_tips": response.practical_tips,
                "citations": [c.model_dump() for c in response.citations],
                "provider_used": response.provider_used,
                "model_used": response.model_used,
                "worker_provider_used": response.worker_provider_used,
                "worker_model_used": response.worker_model_used,
                "live_web_brief": response.live_web_brief.model_dump() if response.live_web_brief else None,
                "worker_routing": pipeline.insights_builder.last_worker_used,
                "generated_at": response.generated_at,
                "metrics": metrics_bus.summary(),
            },
            "detailed": detailed,
            "profile": profile_rows,
    }


@app.command()
def plan(
    destination: str = typer.Option(..., "--destination", "-d", help="Travel destination"),
    days: int = typer.Option(4, "--days", "-n", help="Number of trip days"),
    interests: str = typer.Option("landmarks,food,walks", "--interests", "-i", help="Comma-separated interests"),
    budget: str = typer.Option("midrange", "--budget", "-b", help="Budget level (budget/midrange/luxury)"),
    month: str = typer.Option("June", "--month", "-m", help="Travel month"),
    origin: str = typer.Option("", "--origin", help="Origin city"),
    notes: str = typer.Option("", "--notes", help="Additional notes"),
    live: bool = typer.Option(False, "--live", "-l", help="Include live web data"),
    provider: str = typer.Option(None, "--provider", "-p", help="LLM provider to use (model is taken from llm.yml for that provider)"),
    places_per_day: str = typer.Option("3-5", "--places-per-day", help="Places to visit per day, e.g. '3-5', '3 to 5'"),
    transport: str = typer.Option(None, "--transport", help="Transport mode: 'car' or 'public'"),
    members: int = typer.Option(1, "--members", help="Number of travellers (costs are multiplied by this)"),
    verbose: bool = typer.Option(True, "--verbose", "-v", help="Verbose output"),
    profile: bool = typer.Option(False, "--profile", help="Show detailed pipeline timing profile"),
    log_level: LogLevel = typer.Option(LogLevel.INFO, "--log-level", help="Log level"),
    output_file: str = typer.Option("", "--output", "-f", help="Output file for JSON result"),
    mode: str = typer.Option(
        "standard", "--mode",
        help="Output mode: 'standard' (structured plan) or 'places' (detailed place-by-place Markdown).",
    ),
):
    """Generate a travel plan using the agentic pipeline."""
    setup_logging(log_level)
    logger.info(f"plan command invoked destination={destination} days={days} provider={provider or 'default'}")
    
    request = PlanningRequest(
        destination=destination,
        origin=origin or None,
        trip_length_days=days,
        interests=[i.strip() for i in interests.split(",") if i.strip()],
        budget_level=budget,
        travel_month=month,
        notes=notes or None,
        provider=provider or None,
        places_per_day=places_per_day,
        transport_mode=transport,
        travelers=members,
        include_live_data=live,
        max_attractions_per_day=parse_place_range(places_per_day)[1],
    )
    
    try:
        if mode not in ("standard", "places"):
            mode = "standard"
        result = asyncio.run(run_pipeline(request, verbose=verbose, mode=mode, profile=profile))
        logger.info("Plan generated successfully")

        if result.get("detailed"):
            render_combined(result["response"], result["detailed"])
        else:
            render_plan(result["response"])
        profile_text = _render_profile(result.get("profile") or [])
        if profile_text:
            console.print()
            console.print(profile_text)

        if output_file:
            with open(output_file, "w") as f:
                json.dump(result, f, indent=2, default=str)
            print(f"\nResults saved to: {output_file}")
            if result.get("detailed"):
                det_path = re.sub(r"\.json$", "", output_file) + ".detailed.json"
                with open(det_path, "w") as f:
                    json.dump(result["detailed"], f, indent=2, default=str)
                print(f"Detailed places data saved to: {det_path}")
        
        return 0
        
    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        if verbose:
            logger.exception("Full traceback:")
        return 1


@app.command()
def interactive():
    """Run an interactive session with prompts."""
    setup_logging(LogLevel.INFO)
    logger.info("Starting interactive session")
    
    print_section("AGENTIC TRAVEL PLANNER - INTERACTIVE MODE")
    
    destination = typer.prompt("Destination city (e.g., Kyoto, Paris, Tokyo)")
    
    try:
        days = int(typer.prompt("Number of trip days", default=4))
    except ValueError:
        days = 4
    
    interests_str = typer.prompt("Interests (comma-separated, e.g., temples,food,photography)", default="landmarks,food,walks")
    interests = [i.strip() for i in interests_str.split(",") if i.strip()]
    
    budget = typer.prompt(
        "Budget level",
        default="midrange",
        type=click.Choice(["budget", "midrange", "luxury"]),
    )
    month = typer.prompt("Travel month", default=datetime.now().strftime("%B"))
    
    origin = typer.prompt("Origin city (press Enter to skip)", default="")
    origin = origin if origin else None
    
    notes = typer.prompt("Additional notes (press Enter to skip)", default="")
    notes = notes if notes else None
    
    live = typer.confirm("Include live web data for up-to-date information?", default=False)

    places_per_day = typer.prompt(
        "How many places do you want to visit each day? (e.g. 3-5, '3 to 5')", default="3-5"
    )
    transport_mode = typer.prompt(
        "Transport mode",
        default="public",
        type=click.Choice(["car", "public"]),
    )
    members = typer.prompt("Number of travellers (costs are multiplied by this)", default=1)

    provider = _select_provider_interactive()

    # Interactive mode always produces the consolidated (standard + detailed places) view.
    mode = "places"

    request = PlanningRequest(
        destination=destination,
        origin=origin,
        trip_length_days=days,
        interests=interests,
        budget_level=budget,
        travel_month=month,
        notes=notes,
        provider=provider,
        places_per_day=places_per_day,
        transport_mode=transport_mode,
        travelers=int(members),
        include_live_data=live,
        max_attractions_per_day=parse_place_range(places_per_day)[1],
    )
    
    try:
        result = asyncio.run(run_pipeline(request, verbose=True, mode=mode, profile=True))
        logger.info("Interactive plan generated successfully")
        
        if result.get("detailed"):
            render_combined(result["response"], result["detailed"])
        else:
            render_plan(result["response"])
        profile_text = _render_profile(result.get("profile") or [])
        if profile_text:
            console.print()
            console.print(profile_text)

    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        logger.exception("Full traceback:")
        raise typer.Exit(code=1)


@app.command()
def test():
    """Run a quick test with default parameters."""
    setup_logging(LogLevel.INFO)
    logger.info("Running quick test pipeline")
    
    request = PlanningRequest(
        destination="Kyoto",
        trip_length_days=2,
        interests=["temples", "food"],
        budget_level="midrange",
        travel_month="October",
        include_live_data=False,
    )
    
    try:
        result = asyncio.run(run_pipeline(request, verbose=True))
        logger.info("Test pipeline completed")
        print_section("TEST COMPLETE")
        print(f"Plan ID: {result['response']['plan_id']}")
        print(f"Generated at: {result['response']['generated_at']}")
    except Exception as e:
        logger.error(f"Test failed: {e}")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()