from __future__ import annotations

import asyncio

import typer

from agentic_tour_planner.ingestion.service import IngestionService

app = typer.Typer(help="Knowledge ingestion commands.")


@app.command()
def wikivoyage(destination: str) -> None:
    typer.echo(asyncio.run(IngestionService().ingest_wikivoyage(destination)).model_dump_json(indent=2))


@app.command()
def web(url: str) -> None:
    typer.echo(asyncio.run(IngestionService().ingest_web(url)).model_dump_json(indent=2))


@app.command()
def youtube(url: str) -> None:
    typer.echo(asyncio.run(IngestionService().ingest_youtube(url)).model_dump_json(indent=2))


@app.command()
def file(path: str) -> None:
    typer.echo(asyncio.run(IngestionService().ingest_file(path)).model_dump_json(indent=2))


@app.command()
def manifest(path: str, force: bool = False, limit: int | None = None) -> None:
    typer.echo(
        asyncio.run(IngestionService().ingest_manifest(path, force=force, limit=limit)).model_dump_json(indent=2)
    )


@app.command("wikivoyage-dump")
def wikivoyage_dump(
    raw_dir: str | None = None,
    force: bool = False,
    limit: int | None = None,
    batch_size: int | None = None,
) -> None:
    run = IngestionService().ingest_wikivoyage_dump(raw_dir, force=force, limit=limit, batch_size=batch_size)
    typer.echo(run.model_dump_json(indent=2))


@app.command("insert-or-update")
def insert_or_update_dump(
    raw_dir: str | None = None,
    limit: int | None = None,
    batch_size: int | None = None,
) -> None:
    run = IngestionService().insert_or_update_dump(raw_dir, limit=limit, batch_size=batch_size)
    typer.echo(run.model_dump_json(indent=2))


@app.command()
def sources(limit: int = 20) -> None:
    for record in IngestionService().list_sources(limit):
        typer.echo(record.model_dump_json(indent=2))
