from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from agentic_tour_planner.domain.models import BudgetLevel, PlanningRequest
from agentic_tour_planner.pipeline.agentic_pipeline import AgenticTourPlannerPipeline
from agentic_tour_planner.storage.sqlite_store import SQLitePlanStore
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)

app = typer.Typer(help="End-to-end travel planning pipeline.")
console = Console()


def _validate_destination(destination: str) -> str:
    logger.debug(f"Validating destination input (len={len(destination.strip())})")
    if len(destination.strip()) < 2:
        console.print("[red]Destination must be at least 2 characters.[/red]")
        raise typer.Exit(code=1)
    return destination.strip()


def _validate_days(days: int) -> int:
    logger.debug(f"Validating trip length input (days={days})")
    if days < 1 or days > 30:
        console.print("[red]Trip length must be between 1 and 30 days.[/red]")
        raise typer.Exit(code=1)
    return days


def _print_plan(response) -> None:
    logger.debug("Rendering plan output")
    console.print()
    overview = Panel(
        response.overview,
        title="[bold blue]Trip Overview[/bold blue]",
        border_style="blue",
    )
    console.print(overview)
    console.print()

    for day in response.itinerary:
        table = Table(title=f"Day {day.day}: {day.theme}", title_style="bold green")
        table.add_column("Period", style="cyan", width=12)
        table.add_column("Activities", style="white")
        table.add_row("Morning", "\n".join(day.morning))
        table.add_row("Afternoon", "\n".join(day.afternoon))
        table.add_row("Evening", "\n".join(day.evening))
        if day.meals:
            table.add_row("Meals", "\n".join(day.meals))
        if day.logistics:
            table.add_row("Logistics", "\n".join(day.logistics))
        console.print(table)
        console.print()

    if response.practical_tips:
        tips = "\n".join(f"  • {tip}" for tip in response.practical_tips)
        console.print(Panel(tips, title="[bold yellow]Practical Tips[/bold yellow]", border_style="yellow"))
        console.print()

    if response.citations:
        citations = "\n".join(
            f"  • [{c.title}]({c.url})" + (f" — {c.note}" if c.note else "")
            for c in response.citations
        )
        console.print(Panel(citations, title="[bold dim]Citations[/bold dim]", border_style="dim"))
        console.print()

    footer = Text()
    footer.append(f"Generated with {response.provider_used}/{response.model_used}", style="italic dim")
    console.print(footer)


@app.command()
def plan(
    destination: str = typer.Argument(..., help="City or destination name", callback=_validate_destination),
    days: int = typer.Option(3, "--days", "-d", help="Trip length in days", callback=_validate_days),
    origin: str | None = typer.Option(None, "--origin", "-o", help="Departure city"),
    interests: list[str] = typer.Option([], "--interest", "-i", help="Interest keywords (repeatable)"),
    budget: BudgetLevel = typer.Option("midrange", "--budget", "-b", help="Budget tier"),
    month: str | None = typer.Option(None, "--month", "-m", help="Travel month"),
    notes: str | None = typer.Option(None, "--notes", "-n", help="Custom notes or constraints"),
    provider: str | None = typer.Option(None, "--provider", "-p", help="LLM provider override"),
    model: str | None = typer.Option(None, "--model", help="Model name override"),
    no_live: bool = typer.Option(False, "--no-live", help="Skip live web data"),
    output: Path | None = typer.Option(
        None, "--output", "-O", help="Save plan as JSON to file", dir_okay=False,
    ),
) -> None:
    logger.info(f"plan command: destination={destination} days={days} budget={budget} provider={provider or 'default'}")
    request = PlanningRequest(
        destination=destination,
        trip_length_days=days,
        origin=origin,
        interests=interests,
        budget_level=budget,
        travel_month=month,
        notes=notes,
        provider=provider,
        model=model,
        include_live_data=not no_live,
    )

    console.print(Panel(f"[bold]Planning a {days}-day trip to [cyan]{destination}[/cyan][/bold]"))
    console.print()

    with console.status("[bold green]Generating your travel plan...[/bold green]", spinner="dots"):
        pipeline = AgenticTourPlannerPipeline()
        store = SQLitePlanStore()
        logger.debug("Running pipeline")
        response = asyncio.run(pipeline.run(request))
        store.save_plan(request, response)

    _print_plan(response)

    if output:
        output.write_text(response.model_dump_json(indent=2))
        logger.info(f"Plan saved to {output}")
        console.print(f"[dim]Plan saved to {output}[/dim]")


@app.command()
def interactive() -> None:
    logger.info("Starting interactive mode")
    destination = _validate_destination(console.input("[bold]Destination: [/bold]").strip())

    days_raw = console.input("[bold]Trip length (days) [3]: [/bold]").strip()
    days = _validate_days(int(days_raw)) if days_raw else 3

    origin = console.input("[bold]Origin (optional): [/bold]").strip() or None
    interests_raw = console.input("[bold]Interests (comma-separated): [/bold]").strip()
    interests = [i.strip() for i in interests_raw.split(",")] if interests_raw else []
    budget_raw = console.input("[bold]Budget tier (budget/midrange/luxury) [midrange]: [/bold]").strip()
    budget: BudgetLevel = budget_raw if budget_raw in {"budget", "midrange", "luxury"} else "midrange"  # type: ignore[assignment]
    month = console.input("[bold]Travel month (optional): [/bold]").strip() or None
    notes = console.input("[bold]Notes/constraints (optional): [/bold]").strip() or None

    request = PlanningRequest(
        destination=destination,
        trip_length_days=days,
        origin=origin,
        interests=interests,
        budget_level=budget,
        travel_month=month,
        notes=notes,
    )

    console.print()
    with console.status("[bold green]Generating your travel plan...[/bold green]", spinner="dots"):
        pipeline = AgenticTourPlannerPipeline()
        store = SQLitePlanStore()
        logger.debug("Running pipeline")
        response = asyncio.run(pipeline.run(request))
        store.save_plan(request, response)

    _print_plan(response)


if __name__ == "__main__":
    asyncio.run(app())
