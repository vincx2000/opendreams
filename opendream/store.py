"""
opendream.store
---------------

SQLite + sqlite-vec persistence layer. Single-file database, schema mirrors
the Pydantic models in opendream.trace.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import UUID

import sqlite_vec

from opendream.trace import (
    DreamCycle,
    MemoryEntry,
    Message,
    MessageRole,
    Reflection,
    Session,
)


DEFAULT_DB_PATH = Path.home() / ".opendream" / "db.sqlite"

# vec0 tables are dimension-locked at creation. 1536 matches OpenAI
# text-embedding-3-small; if you swap embedding providers, recreate the table.
EMBEDDING_DIM = 1536


SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    agent TEXT NOT NULL,
    project_id TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    task_description TEXT,
    outcome_known INTEGER NOT NULL DEFAULT 0,
    outcome_success INTEGER,
    metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS messages (
    session_id TEXT NOT NULL,
    "index" INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    tool_name TEXT,
    tool_input TEXT,
    tool_output TEXT,
    timestamp TEXT,
    PRIMARY KEY (session_id, "index"),
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reflections (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_reflections_session_id ON reflections(session_id);

CREATE TABLE IF NOT EXISTS memory_entries (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    scope TEXT NOT NULL,
    confidence TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_reinforced_at TEXT NOT NULL,
    deprecated_at TEXT,
    deprecation_reason TEXT,
    evidence_reflection_ids TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS dream_cycles (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    applied INTEGER NOT NULL DEFAULT 0,
    applied_at TEXT,
    payload TEXT NOT NULL
);
"""


def _vec_schema() -> str:
    return f"""
CREATE VIRTUAL TABLE IF NOT EXISTS memory_embeddings USING vec0(
    id TEXT PRIMARY KEY,
    embedding FLOAT[{EMBEDDING_DIM}]
);
"""


def _resolve(path: Path | str | None) -> Path:
    return (Path(path) if path else DEFAULT_DB_PATH).expanduser()


def _connect(path: Path) -> sqlite3.Connection:
    """Open a sqlite connection with sqlite-vec loaded and FKs enforced."""
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def init_db(path: Path | str | None = None) -> Path:
    """Create the OpenDream database and schema at the given path.

    Returns the resolved path to the database file.
    """
    db_path = _resolve(path).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = _connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.execute(_vec_schema())
        conn.commit()
    finally:
        conn.close()
    return db_path


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _parse_iso(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


def save_session(session: Session, path: Path | str | None = None) -> None:
    """Insert (or replace) a session and all its messages."""
    conn = _connect(_resolve(path))
    try:
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sessions
                  (id, agent, project_id, started_at, ended_at, task_description,
                   outcome_known, outcome_success, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(session.id),
                    session.agent,
                    session.project_id,
                    _iso(session.started_at),
                    _iso(session.ended_at),
                    session.task_description,
                    int(session.outcome_known),
                    None if session.outcome_success is None else int(session.outcome_success),
                    json.dumps(session.metadata),
                ),
            )
            conn.execute("DELETE FROM messages WHERE session_id = ?", (str(session.id),))
            conn.executemany(
                """
                INSERT INTO messages
                  (session_id, "index", role, content, tool_name, tool_input, tool_output, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(session.id),
                        m.index,
                        m.role.value,
                        m.content,
                        m.tool_name,
                        json.dumps(m.tool_input) if m.tool_input is not None else None,
                        m.tool_output,
                        _iso(m.timestamp),
                    )
                    for m in session.messages
                ],
            )
    finally:
        conn.close()


def load_session(session_id: UUID | str, path: Path | str | None = None) -> Session | None:
    """Load a Session (with messages) by id, or None if not found."""
    conn = _connect(_resolve(path))
    try:
        sid = str(session_id)
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
        if row is None:
            return None
        msg_rows = conn.execute(
            'SELECT * FROM messages WHERE session_id = ? ORDER BY "index"',
            (sid,),
        ).fetchall()
    finally:
        conn.close()
    return _row_to_session(row, msg_rows)


def list_sessions(path: Path | str | None = None) -> list[Session]:
    """Return all sessions, ordered by started_at ascending."""
    conn = _connect(_resolve(path))
    try:
        s_rows = conn.execute("SELECT * FROM sessions ORDER BY started_at ASC").fetchall()
        sessions = []
        for row in s_rows:
            msg_rows = conn.execute(
                'SELECT * FROM messages WHERE session_id = ? ORDER BY "index"',
                (row["id"],),
            ).fetchall()
            sessions.append(_row_to_session(row, msg_rows))
    finally:
        conn.close()
    return sessions


def _row_to_session(row: sqlite3.Row, msg_rows: list[sqlite3.Row]) -> Session:
    return Session(
        id=UUID(row["id"]),
        agent=row["agent"],
        project_id=row["project_id"],
        started_at=_parse_iso(row["started_at"]),
        ended_at=_parse_iso(row["ended_at"]),
        task_description=row["task_description"],
        outcome_known=bool(row["outcome_known"]),
        outcome_success=None if row["outcome_success"] is None else bool(row["outcome_success"]),
        metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        messages=[
            Message(
                index=m["index"],
                role=MessageRole(m["role"]),
                content=m["content"],
                tool_name=m["tool_name"],
                tool_input=json.loads(m["tool_input"]) if m["tool_input"] else None,
                tool_output=m["tool_output"],
                timestamp=_parse_iso(m["timestamp"]),
            )
            for m in msg_rows
        ],
    )


# ---------- Stubs to be implemented later ----------

def save_reflection(reflection: Reflection, path: Path | str | None = None) -> None:
    raise NotImplementedError("save_reflection not implemented yet")


def load_reflection(
    reflection_id: UUID | str, path: Path | str | None = None
) -> Reflection | None:
    raise NotImplementedError("load_reflection not implemented yet")


def list_reflections(path: Path | str | None = None) -> list[Reflection]:
    raise NotImplementedError("list_reflections not implemented yet")


def save_memory_entry(entry: MemoryEntry, path: Path | str | None = None) -> None:
    raise NotImplementedError("save_memory_entry not implemented yet")


def list_memory_entries(
    include_deprecated: bool = False,
    path: Path | str | None = None,
) -> list[MemoryEntry]:
    raise NotImplementedError("list_memory_entries not implemented yet")


def save_dream_cycle(cycle: DreamCycle, path: Path | str | None = None) -> None:
    raise NotImplementedError("save_dream_cycle not implemented yet")


def list_dream_cycles(path: Path | str | None = None) -> list[DreamCycle]:
    raise NotImplementedError("list_dream_cycles not implemented yet")
