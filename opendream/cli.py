"""
opendream.cli
-------------

Typer entry point. v0 wires only `init` and a stub `ingest aider`; remaining
commands listed in CLAUDE.md §7 are added as the pipeline lands.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from opendream import store

app = typer.Typer(help="OpenDream — memory consolidation for AI agents.")
ingest_app = typer.Typer(help="Ingest agent sessions into the OpenDream database.")
app.add_typer(ingest_app, name="ingest")

console = Console()


@app.command()
def init(
    path: Path = typer.Option(
        store.DEFAULT_DB_PATH,
        "--path",
        help="Where to create the OpenDream SQLite database.",
    ),
) -> None:
    """Create the OpenDream database and schema."""
    db_path = store.init_db(path)
    console.print(f"[green]opendream initialized[/green] at [bold]{db_path}[/bold]")


@ingest_app.command("aider")
def ingest_aider(
    history_path: Path = typer.Argument(
        ...,
        help="Path to a .aider.chat.history.md file.",
    ),
) -> None:
    """Ingest an Aider chat history file into the OpenDream database."""
    console.print(f"[yellow]not implemented yet[/yellow] (would ingest {history_path})")


if __name__ == "__main__":
    app()
