"""
opendream.cli
-------------

Typer entry point. Wires the v0 commands listed in CLAUDE.md §7.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from uuid import UUID

import typer
from rich.console import Console
from rich.table import Table

from opendream import consolidate, memory, reflect, store
from opendream.adapters import aider as aider_adapter

app = typer.Typer(help="OpenDream — memory consolidation for AI agents.")
ingest_app = typer.Typer(help="Ingest agent sessions into the OpenDream database.")
sessions_app = typer.Typer(help="Inspect ingested sessions.")
memory_app = typer.Typer(help="Inspect and export consolidated memory.")
app.add_typer(ingest_app, name="ingest")
app.add_typer(sessions_app, name="sessions")
app.add_typer(memory_app, name="memory")

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
    db_path: Path = typer.Option(
        store.DEFAULT_DB_PATH, "--path", help="OpenDream database path."
    ),
) -> None:
    """Ingest an Aider chat history file into the OpenDream database."""
    sessions = aider_adapter.parse_file(history_path)
    if not sessions:
        console.print("[yellow]no sessions found[/yellow]")
        return
    for s in sessions:
        store.save_session(s, path=db_path)
    console.print(
        f"[green]ingested {len(sessions)} session(s)[/green] from "
        f"[bold]{history_path}[/bold]"
    )


@sessions_app.command("list")
def sessions_list(
    db_path: Path = typer.Option(
        store.DEFAULT_DB_PATH, "--path", help="OpenDream database path."
    ),
) -> None:
    """List ingested sessions."""
    sessions = store.list_sessions(path=db_path)
    if not sessions:
        console.print("[dim]no sessions ingested yet[/dim]")
        return
    table = Table()
    table.add_column("id", overflow="fold")
    table.add_column("agent")
    table.add_column("started_at")
    table.add_column("messages", justify="right")
    table.add_column("task")
    for s in sessions:
        task = (s.task_description or "").splitlines()[0][:80] if s.task_description else ""
        table.add_row(
            str(s.id), s.agent, s.started_at.isoformat(), str(len(s.messages)), task
        )
    console.print(table)


def _reflect_cmd(
    session_id: Optional[str] = typer.Option(
        None, "--session-id", help="Reflect on a single session by id."
    ),
    all_pending: bool = typer.Option(
        False, "--all-pending", help="Reflect on every session without a reflection."
    ),
    db_path: Path = typer.Option(
        store.DEFAULT_DB_PATH, "--path", help="OpenDream database path."
    ),
) -> None:
    """Run Stage 1 (reflection) on one or more sessions."""
    if not (session_id or all_pending):
        raise typer.BadParameter("pass --session-id ID or --all-pending")
    if session_id and all_pending:
        raise typer.BadParameter("--session-id and --all-pending are mutually exclusive")

    if session_id:
        targets = [UUID(session_id)]
    else:
        existing = {r.session_id for r in store.list_reflections(path=db_path)}
        targets = [s.id for s in store.list_sessions(path=db_path) if s.id not in existing]

    if not targets:
        console.print("[dim]nothing to reflect on[/dim]")
        return

    for sid in targets:
        session = store.load_session(sid, path=db_path)
        if session is None:
            console.print(f"[red]session {sid} not found[/red]")
            continue
        ref = reflect.reflect_on(session)
        store.save_reflection(ref, path=db_path)
        console.print(f"[green]reflected[/green] {sid} -> reflection {ref.id}")


@app.command("dream")
def dream(
    last: int = typer.Option(
        20, "--last", help="Consider the N most recent reflections."
    ),
    review: bool = typer.Option(
        False, "--review", help="Open the dream diff in $EDITOR before applying."
    ),
    db_path: Path = typer.Option(
        store.DEFAULT_DB_PATH, "--path", help="OpenDream database path."
    ),
) -> None:
    """Run Stage 2 (consolidation) over recent reflections."""
    reflections = store.list_reflections(path=db_path)[-last:]
    if not reflections:
        console.print("[dim]no reflections to dream over[/dim]")
        return
    current = store.list_memory_entries(path=db_path)
    cycle = consolidate.consolidate(reflections, current)
    store.save_dream_cycle(cycle, path=db_path)
    if review:
        console.print(
            "[yellow]--review[/yellow] not implemented yet; cycle saved unapplied"
        )
        return
    memory.apply_cycle(cycle, path=db_path)
    console.print(
        f"[green]dream applied[/green]: {len(cycle.updates)} update(s) "
        f"({len(cycle.non_updates)} rejected)"
    )


@memory_app.command("list")
def memory_list(
    include_deprecated: bool = typer.Option(
        False, "--include-deprecated", help="Include deprecated entries."
    ),
    db_path: Path = typer.Option(
        store.DEFAULT_DB_PATH, "--path", help="OpenDream database path."
    ),
) -> None:
    """Show current consolidated memory."""
    entries = store.list_memory_entries(
        include_deprecated=include_deprecated, path=db_path
    )
    if not entries:
        console.print("[dim]memory is empty[/dim]")
        return
    for e in entries:
        tag = "[red]deprecated[/red] " if e.deprecated_at else ""
        console.print(f"{tag}[bold]{e.kind}[/bold] [{e.confidence}] {e.scope}")
        console.print(f"  {e.content}")
        console.print(f"  [dim]{e.id}[/dim]")


@memory_app.command("show")
def memory_show(
    entry_id: str = typer.Argument(..., help="Memory entry id."),
    db_path: Path = typer.Option(
        store.DEFAULT_DB_PATH, "--path", help="OpenDream database path."
    ),
) -> None:
    """Show a single memory entry."""
    target = UUID(entry_id)
    for e in store.list_memory_entries(include_deprecated=True, path=db_path):
        if e.id == target:
            console.print(e.model_dump_json(indent=2))
            return
    console.print(f"[red]entry {entry_id} not found[/red]")


@memory_app.command("export")
def memory_export(
    fmt: str = typer.Option("aider", "--format", help="Export format (only `aider` for v0)."),
    out: Path = typer.Option(Path("OPENDREAM.md"), "--out", help="Output file path."),
    db_path: Path = typer.Option(
        store.DEFAULT_DB_PATH, "--path", help="OpenDream database path."
    ),
) -> None:
    """Export consolidated memory to OPENDREAM.md."""
    if fmt != "aider":
        raise typer.BadParameter(f"unknown format: {fmt}")
    written = memory.export_markdown(out, path=db_path)
    console.print(f"[green]wrote[/green] {written}")


app.command("reflect")(_reflect_cmd)


if __name__ == "__main__":
    app()
