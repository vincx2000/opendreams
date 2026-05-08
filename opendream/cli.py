"""
opendream.cli
-------------

Typer entry point. Wires the v0 commands listed in SPEC.md §7.
"""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime
from json import JSONDecodeError
from pathlib import Path
from typing import Optional
from uuid import UUID

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from opendream import consolidate, memory, reflect, store
from opendream.adapters import get_adapter, list_adapters
from opendream.llm import extract_json


DRYRUN_DIR = Path("/tmp/od_dryrun")


def _review_cycle_in_editor(cycle):
    """Open the dream cycle JSON in $EDITOR, return the (possibly edited) cycle.

    Returns None if the user clears the file or aborts (saves empty / leaves
    the original instructional banner unchanged would still re-validate, but
    an empty file is treated as an abort signal).

    Re-validation is via Pydantic; if the user introduces a schema error the
    editor reopens until the JSON is valid or the file is cleared.
    """
    import os
    import shlex
    import subprocess

    from opendream.trace import DreamCycle

    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
    editor_argv = shlex.split(editor)
    banner = (
        "// Edit the dream cycle below before applying. Save & quit to apply.\n"
        "// Clear the file (or save empty JSON) to abort.\n"
        "// JSON below — JSON does not allow comments, so these `//` lines must\n"
        "// be removed before saving (or kept on lines that aren't part of the JSON object).\n"
    )
    payload = cycle.model_dump_json(indent=2)

    while True:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(payload)
            tmp_path = Path(tmp.name)

        # Best-effort: print the banner to stderr so the user sees it before
        # we hand over to the editor (avoids polluting the JSON itself).
        console.print(f"[dim]{banner}[/dim]")
        try:
            subprocess.run([*editor_argv, str(tmp_path)], check=True)
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            console.print(f"[red]editor failed: {exc}[/red]")
            tmp_path.unlink(missing_ok=True)
            return None

        edited = tmp_path.read_text(encoding="utf-8").strip()
        tmp_path.unlink(missing_ok=True)

        if not edited or edited in ("{}", "[]"):
            return None

        try:
            return DreamCycle.model_validate_json(edited)
        except (ValidationError, JSONDecodeError) as exc:
            # Schema or JSON-syntax problems are recoverable — reopen the
            # editor with the user's edits so they can fix them. Anything
            # else (e.g. PermissionError, OSError on the temp dir) is a
            # real failure and propagates out of this loop.
            console.print(f"[red]invalid edit:[/red] {exc}")
            console.print("[yellow]reopening editor with your edits...[/yellow]")
            payload = edited  # let the user fix it from where they left off

app = typer.Typer(help="OpenDream — memory consolidation for AI agents.")
sessions_app = typer.Typer(help="Inspect ingested sessions.")
reflections_app = typer.Typer(help="Inspect stored Stage 1 reflections.")
dreams_app = typer.Typer(help="Inspect stored Stage 2 dream cycles.")
memory_app = typer.Typer(help="Inspect and export consolidated memory.")
eval_app = typer.Typer(help="Run the OpenDream eval suite (baseline vs dreamed).")
app.add_typer(sessions_app, name="sessions")
app.add_typer(reflections_app, name="reflections")
app.add_typer(dreams_app, name="dreams")
app.add_typer(memory_app, name="memory")
app.add_typer(eval_app, name="eval")

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


@app.command("ingest")
def ingest(
    adapter_name: str = typer.Argument(
        ...,
        help=f"Adapter name. Registered: {', '.join(list_adapters())}.",
    ),
    source: str = typer.Argument(
        ...,
        help="Path to a session file or directory; `-` for stdin (treated as JSONL).",
    ),
    db_path: Path = typer.Option(
        store.DEFAULT_DB_PATH, "--path", help="OpenDream database path."
    ),
) -> None:
    """Ingest sessions into OpenDream via the named adapter."""
    try:
        adapter = get_adapter(adapter_name)
    except KeyError as exc:
        raise typer.BadParameter(str(exc)) from exc

    if source == "-":
        # Read stdin into a temp file the adapter can re-open. We use
        # delete=False because some adapters (claude_code, generic_jsonl)
        # call `path.open()` themselves; the try/finally below guarantees
        # the file is removed even if parse_sessions raises.
        data = sys.stdin.read()
        with tempfile.NamedTemporaryFile(
            "w", suffix=".jsonl", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)
        try:
            sessions = adapter.parse_sessions(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)
        source_label = "<stdin>"
    else:
        root = Path(source)
        if not root.exists():
            console.print(
                f"[red]source path does not exist:[/red] {root}"
            )
            raise typer.Exit(2)
        targets = adapter.discover_sessions(root)
        if not targets:
            console.print(
                f"[yellow]{adapter_name}: no session files discovered under {root}[/yellow]"
            )
            return
        sessions = []
        for target in targets:
            sessions.extend(adapter.parse_sessions(target))
        source_label = source

    if not sessions:
        console.print("[yellow]no sessions parsed[/yellow]")
        return

    # Surface a clear error if the DB hasn't been initialized — without this
    # the user gets a bare sqlite3.OperationalError stack trace deep in store.
    if not Path(db_path).expanduser().exists():
        console.print(
            f"[red]database not initialized at[/red] {db_path}\n"
            f"[dim]run `opendream init --path {db_path}` first[/dim]"
        )
        raise typer.Exit(2)

    for s in sessions:
        store.save_session(s, path=db_path)
    console.print(
        f"[green]ingested {len(sessions)} session(s)[/green] via "
        f"[bold]{adapter_name}[/bold] from [bold]{source_label}[/bold]"
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


@sessions_app.command("show")
def sessions_show(
    session_id: str = typer.Argument(..., help="Session id (UUID)."),
    limit: Optional[int] = typer.Option(
        None, "--limit", help="Truncate to first N messages."
    ),
    db_path: Path = typer.Option(
        store.DEFAULT_DB_PATH, "--path", help="OpenDream database path."
    ),
) -> None:
    """Print the messages of one session."""
    session = store.load_session(UUID(session_id), path=db_path)
    if session is None:
        console.print(f"[red]session {session_id} not found[/red]")
        raise typer.Exit(1)

    console.print(
        f"[bold]{session.id}[/bold]  agent={session.agent}  "
        f"messages={len(session.messages)}  started_at={session.started_at.isoformat()}"
    )
    if session.task_description:
        console.print(f"[dim]task:[/dim] {session.task_description.splitlines()[0][:120]}")
    console.print()
    msgs = session.messages[:limit] if limit else session.messages
    for m in msgs:
        body = m.content.replace("\n", " ")
        if len(body) > 160:
            body = body[:160] + f"… [+{len(m.content) - 160} chars]"
        console.print(f"  [{m.index:4d}] [cyan]{m.role.value:10s}[/cyan]  {body}")
    if limit and len(session.messages) > limit:
        console.print(f"\n[dim]... +{len(session.messages) - limit} more messages[/dim]")


# ---------- reflections ----------

@reflections_app.command("list")
def reflections_list(
    db_path: Path = typer.Option(
        store.DEFAULT_DB_PATH, "--path", help="OpenDream database path."
    ),
) -> None:
    """List stored reflections."""
    reflections = store.list_reflections(path=db_path)
    if not reflections:
        console.print("[dim]no reflections yet[/dim]")
        return
    table = Table()
    table.add_column("id", overflow="fold")
    table.add_column("session_id", overflow="fold")
    table.add_column("completeness")
    table.add_column("confidence")
    table.add_column("candidates", justify="right")
    for r in reflections:
        table.add_row(
            str(r.id),
            str(r.session_id),
            r.session_completeness,
            r.reflection_confidence,
            str(len(r.candidates_for_memory)),
        )
    console.print(table)


@reflections_app.command("show")
def reflections_show(
    reflection_id: str = typer.Argument(..., help="Reflection id (UUID)."),
    db_path: Path = typer.Option(
        store.DEFAULT_DB_PATH, "--path", help="OpenDream database path."
    ),
) -> None:
    """Pretty-print one reflection as JSON."""
    ref = store.load_reflection(UUID(reflection_id), path=db_path)
    if ref is None:
        console.print(f"[red]reflection {reflection_id} not found[/red]")
        raise typer.Exit(1)
    console.print_json(ref.model_dump_json())


# ---------- dreams ----------

@dreams_app.command("list")
def dreams_list(
    db_path: Path = typer.Option(
        store.DEFAULT_DB_PATH, "--path", help="OpenDream database path."
    ),
) -> None:
    """List stored dream cycles."""
    cycles = store.list_dream_cycles(path=db_path)
    if not cycles:
        console.print("[dim]no dream cycles yet[/dim]")
        return
    table = Table()
    table.add_column("id", overflow="fold")
    table.add_column("created_at")
    table.add_column("applied", justify="center")
    table.add_column("updates", justify="right")
    table.add_column("non_updates", justify="right")
    table.add_column("reflections", justify="right")
    for c in cycles:
        table.add_row(
            str(c.id),
            c.created_at.isoformat(timespec="seconds"),
            "✓" if c.applied else "—",
            str(len(c.updates)),
            str(len(c.non_updates)),
            str(len(c.reflections_considered)),
        )
    console.print(table)


def _reflect_cmd(
    session_id: Optional[str] = typer.Option(
        None, "--session-id", help="Reflect on a single session by id."
    ),
    all_pending: bool = typer.Option(
        False, "--all-pending", help="Reflect on every session without a reflection."
    ),
    show_json: bool = typer.Option(
        False,
        "--show-json",
        help="Pretty-print the parsed Reflection JSON to stdout (for prompt tuning).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help=(
            "Render the prompt to /tmp/od_dryrun/reflect_<id>.txt without "
            "calling the LLM. For prompt tuning."
        ),
    ),
    do_import: bool = typer.Option(
        False,
        "--import-json",
        help=(
            "Read a Reflection JSON from stdin (or --from FILE), validate, "
            "and store as if the LLM had produced it."
        ),
    ),
    from_file: Optional[Path] = typer.Option(
        None,
        "--from",
        help="Path to a JSON file (used with --import-json instead of stdin).",
    ),
    max_message_chars: Optional[int] = typer.Option(
        None,
        "--max-message-chars",
        help=(
            "Cap each rendered message body at N chars (default: no cap). "
            "Use to compress sessions whose Write/Edit tool calls embed full "
            "file contents. Try 1000 — drops a 638-msg Claude Code session "
            "from ~165K to ~50K tokens with no loss of agent intent."
        ),
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
    if dry_run and do_import:
        raise typer.BadParameter("--dry-run and --import-json are mutually exclusive")
    if from_file and not do_import:
        raise typer.BadParameter("--from requires --import-json")
    if do_import and not session_id:
        raise typer.BadParameter("--import-json requires --session-id")

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

        if dry_run:
            system, user = reflect.render_prompt(
                session, max_message_chars=max_message_chars
            )
            DRYRUN_DIR.mkdir(parents=True, exist_ok=True)
            out = DRYRUN_DIR / f"reflect_{sid}.txt"
            out.write_text(
                f"=== SYSTEM ===\n{system}\n\n=== USER ===\n{user}\n",
                encoding="utf-8",
            )
            console.print(f"[green]wrote prompt[/green] {out}")
            continue

        if do_import:
            raw = (
                from_file.read_text(encoding="utf-8")
                if from_file
                else sys.stdin.read()
            )
            ref = reflect.reflection_from_json(extract_json(raw), sid)
            store.save_reflection(ref, path=db_path)
            console.print(
                f"[green]imported reflection[/green] for {sid} -> {ref.id}"
            )
            if show_json:
                console.print_json(ref.model_dump_json())
            continue

        ref = reflect.reflect_on(session, max_message_chars=max_message_chars)
        store.save_reflection(ref, path=db_path)
        console.print(f"[green]reflected[/green] {sid} -> reflection {ref.id}")
        if show_json:
            console.print_json(ref.model_dump_json())


@app.command("dream")
def dream(
    last: int = typer.Option(
        20, "--last", help="Consider the N most recent reflections."
    ),
    review: bool = typer.Option(
        False, "--review", help="Open the dream diff in $EDITOR before applying."
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help=(
            "Render the consolidate prompt to /tmp/od_dryrun/dream_<ts>.txt "
            "without calling the LLM. For prompt tuning."
        ),
    ),
    do_import: bool = typer.Option(
        False,
        "--import-json",
        help=(
            "Read a DreamCycle JSON from stdin (or --from FILE), validate, "
            "and apply as if the LLM had produced it."
        ),
    ),
    from_file: Optional[Path] = typer.Option(
        None,
        "--from",
        help="Path to a JSON file (used with --import-json instead of stdin).",
    ),
    db_path: Path = typer.Option(
        store.DEFAULT_DB_PATH, "--path", help="OpenDream database path."
    ),
) -> None:
    """Run Stage 2 (consolidation) over recent reflections."""
    if dry_run and do_import:
        raise typer.BadParameter("--dry-run and --import-json are mutually exclusive")
    if from_file and not do_import:
        raise typer.BadParameter("--from requires --import-json")

    reflections = store.list_reflections(path=db_path)[-last:]
    if not reflections:
        console.print("[dim]no reflections to dream over[/dim]")
        return
    current = store.list_memory_entries(path=db_path)

    if dry_run:
        system, user = consolidate.render_prompt(reflections, current)
        DRYRUN_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        out = DRYRUN_DIR / f"dream_{ts}.txt"
        out.write_text(
            f"=== SYSTEM ===\n{system}\n\n=== USER ===\n{user}\n",
            encoding="utf-8",
        )
        console.print(
            f"[green]wrote prompt[/green] {out} "
            f"({len(reflections)} reflection(s), {len(current)} memory entr(ies))"
        )
        return

    if do_import:
        raw = from_file.read_text(encoding="utf-8") if from_file else sys.stdin.read()
        cycle = consolidate.dream_cycle_from_json(extract_json(raw), reflections)
    else:
        cycle = consolidate.consolidate(reflections, current)

    if review:
        cycle = _review_cycle_in_editor(cycle)
        if cycle is None:
            # User aborted (cleared the file or saved empty JSON).
            console.print("[yellow]review aborted; nothing applied[/yellow]")
            return

    store.save_dream_cycle(cycle, path=db_path)
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
    raise typer.Exit(1)


@memory_app.command("diff")
def memory_diff(
    since: str = typer.Option(
        ...,
        "--since",
        help="ISO date or datetime; only dream cycles applied on/after this are shown.",
    ),
    db_path: Path = typer.Option(
        store.DEFAULT_DB_PATH, "--path", help="OpenDream database path."
    ),
) -> None:
    """Show how consolidated memory has evolved since a given date."""
    try:
        cutoff = datetime.fromisoformat(since)
    except ValueError as exc:
        raise typer.BadParameter(f"--since must be ISO 8601: {exc}") from exc

    cycles = [
        c
        for c in store.list_dream_cycles(path=db_path)
        if c.applied and c.applied_at and c.applied_at >= cutoff
    ]
    if not cycles:
        console.print(f"[dim]no dream cycles applied since {cutoff.isoformat()}[/dim]")
        return

    for c in cycles:
        console.print(f"[bold]dream {c.id}[/bold]  applied {c.applied_at}")
        console.print(f"  [dim]{c.summary}[/dim]")
        for upd in c.updates:
            target = f" target={upd.target_id}" if upd.target_id else ""
            preview = (upd.content or "").splitlines()[0][:80] if upd.content else ""
            console.print(
                f"  [cyan]{upd.operation}[/cyan] [magenta]{upd.kind}[/magenta]"
                f"{target}  {preview}"
            )
        console.print()


@memory_app.command("export")
def memory_export(
    fmt: str = typer.Option(
        "agents-md",
        "--format",
        help="Export format. v0 ships `agents-md` (writes/refreshes AGENTS.md "
        "between OpenDream markers).",
    ),
    out: Path = typer.Option(
        Path("AGENTS.md"), "--out", help="Output file path."
    ),
    db_path: Path = typer.Option(
        store.DEFAULT_DB_PATH, "--path", help="OpenDream database path."
    ),
) -> None:
    """Export consolidated memory into AGENTS.md (idempotent section)."""
    if fmt != "agents-md":
        raise typer.BadParameter(f"unknown format: {fmt}")
    written = memory.export_agents_md(out, path=db_path)
    console.print(f"[green]wrote[/green] {written}")


app.command("reflect")(_reflect_cmd)


# ---------- eval ----------

@eval_app.command("list-tasks")
def eval_list_tasks(
    tasks_dir: Path = typer.Option(
        Path("eval/tasks"), "--tasks-dir", help="Directory containing task subdirs."
    ),
) -> None:
    """List the eval tasks that would be discovered."""
    from eval.runner import load_tasks

    tasks = load_tasks(tasks_dir)
    if not tasks:
        console.print(f"[yellow]no tasks found under[/yellow] {tasks_dir}")
        return
    table = Table()
    table.add_column("task_id")
    table.add_column("expected_test", justify="center")
    for t in tasks:
        table.add_row(
            t.task_id,
            "✓" if t.expected_test_path.exists() else "—",
        )
    console.print(table)


@eval_app.command("run")
def eval_run(
    runner_name: str = typer.Option(
        "claude_code", "--runner", help="Agent runner: claude_code | aider."
    ),
    fixture_dir: Path = typer.Option(
        Path("eval/fixtures/library_api"),
        "--fixture",
        help="Codebase the agent works on for every trial.",
    ),
    tasks_dir: Path = typer.Option(
        Path("eval/tasks"), "--tasks-dir", help="Directory containing task subdirs."
    ),
    trials: int = typer.Option(5, "--trials", help="Trials per task per condition."),
    only: Optional[str] = typer.Option(
        None,
        "--only",
        help="Comma-separated task_id substrings to filter the suite (e.g. `01,06`).",
    ),
    baseline_only: bool = typer.Option(
        False, "--baseline", help="Run only the baseline condition (no AGENTS.md)."
    ),
    dreamed_only: bool = typer.Option(
        False, "--dreamed", help="Run only the dreamed condition (requires --agents-md)."
    ),
    agents_md: Optional[Path] = typer.Option(
        None,
        "--agents-md",
        help="Path to AGENTS.md to inject for the dreamed condition.",
    ),
    workdir: Optional[Path] = typer.Option(
        None,
        "--workdir",
        help="Where to materialize per-trial workspaces (default: ./.opendream-eval).",
    ),
) -> None:
    """Run the eval suite and print the lift report."""
    from eval.agents import AiderRunner, ClaudeCodeRunner
    from eval.runner import AgentRunner, load_tasks, run_eval

    if baseline_only and dreamed_only:
        raise typer.BadParameter("--baseline and --dreamed are mutually exclusive")
    if dreamed_only and agents_md is None:
        # Use plain stderr write rather than typer.BadParameter: on Click 8.2+
        # the Rich-formatted error panel hides the message body from CliRunner's
        # captured stderr, breaking tests that assert on the message text.
        typer.echo("error: --dreamed requires --agents-md", err=True)
        raise typer.Exit(2)

    runner: AgentRunner
    if runner_name == "claude_code":
        runner = ClaudeCodeRunner()
    elif runner_name == "aider":
        runner = AiderRunner()
    else:
        typer.echo(
            f"error: unknown --runner {runner_name!r}; expected one of "
            "['aider', 'claude_code']",
            err=True,
        )
        raise typer.Exit(2)

    tasks = load_tasks(tasks_dir)
    if only:
        wanted = [s.strip() for s in only.split(",") if s.strip()]
        tasks = [t for t in tasks if any(w in t.task_id for w in wanted)]
    if not tasks:
        console.print("[yellow]no tasks match[/yellow]")
        return

    console.print(
        f"[bold]Running[/bold] {len(tasks)} task(s) × "
        f"{1 if (baseline_only or dreamed_only) else 2} condition(s) × {trials} trial(s) "
        f"via [cyan]{runner_name}[/cyan]"
    )

    # The harness always runs both conditions; we filter the report afterwards
    # to match --baseline/--dreamed.
    report = run_eval(
        tasks,
        runner,
        fixture_dir=fixture_dir,
        trials=trials,
        opendream_md=agents_md,
        workdir=workdir,
    )

    # Filter trials per --baseline/--dreamed
    if baseline_only:
        report.trials = [t for t in report.trials if t.condition == "baseline"]
    elif dreamed_only:
        report.trials = [t for t in report.trials if t.condition == "dreamed"]

    table = Table(title="Per-task success rate")
    table.add_column("task_id")
    if not dreamed_only:
        table.add_column("baseline", justify="right")
    if not baseline_only:
        table.add_column("dreamed", justify="right")
    if not (baseline_only or dreamed_only):
        table.add_column("Δ pp", justify="right")

    breakdown = report.per_task()
    for task_id, rates in sorted(breakdown.items()):
        row = [task_id]
        if not dreamed_only:
            row.append(f"{rates.get('baseline', 0.0):.0%}")
        if not baseline_only:
            row.append(f"{rates.get('dreamed', 0.0):.0%}")
        if not (baseline_only or dreamed_only):
            delta = (rates.get("dreamed", 0.0) - rates.get("baseline", 0.0)) * 100
            row.append(f"{delta:+.1f}")
        table.add_row(*row)
    console.print(table)

    if not (baseline_only or dreamed_only):
        console.print(
            f"\n[bold]baseline[/bold]: {report.success_rate('baseline'):.0%}    "
            f"[bold]dreamed[/bold]: {report.success_rate('dreamed'):.0%}    "
            f"[bold]lift[/bold]: {report.lift_pp():+.1f}pp"
        )


if __name__ == "__main__":
    app()
