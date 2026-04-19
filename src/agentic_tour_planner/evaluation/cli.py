from __future__ import annotations

import asyncio

import typer

from agentic_tour_planner.evaluation.ragas_pipeline import RagasEvaluationPipeline

app = typer.Typer(help="RAGAS evaluation commands.")


@app.command()
def export(cases_path: str, output_path: str | None = None) -> None:
    result = asyncio.run(RagasEvaluationPipeline().export_dataset(cases_path, output_path))
    typer.echo(result.model_dump_json(indent=2))


@app.command()
def ragas(cases_path: str, output_path: str | None = None) -> None:
    result = asyncio.run(RagasEvaluationPipeline().run_ragas(cases_path, output_path))
    typer.echo(result.model_dump_json(indent=2))

