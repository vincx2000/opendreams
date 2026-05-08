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


def _require_iso(s: str | None) -> datetime:
    """Parse an ISO timestamp from a NOT NULL column. Raises if the row is corrupt."""
    if s is None:
        raise ValueError("expected non-null timestamp column")
    return datetime.fromisoformat(s)


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
        started_at=_require_iso(row["started_at"]),
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


# ---------- Reflections ----------

def save_reflection(reflection: Reflection, path: Path | str | None = None) -> None:
    """Insert (or replace) a reflection. Whole payload stored as JSON."""
    payload = reflection.model_dump_json()
    conn = _connect(_resolve(path))
    try:
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO reflections (id, session_id, created_at, payload)
                VALUES (?, ?, ?, ?)
                """,
                (
                    str(reflection.id),
                    str(reflection.session_id),
                    _iso(reflection.created_at),
                    payload,
                ),
            )
    finally:
        conn.close()


def load_reflection(
    reflection_id: UUID | str, path: Path | str | None = None
) -> Reflection | None:
    conn = _connect(_resolve(path))
    try:
        row = conn.execute(
            "SELECT payload FROM reflections WHERE id = ?", (str(reflection_id),)
        ).fetchone()
    finally:
        conn.close()
    return Reflection.model_validate_json(row["payload"]) if row else None


def list_reflections(path: Path | str | None = None) -> list[Reflection]:
    """Return all reflections, oldest first."""
    conn = _connect(_resolve(path))
    try:
        rows = conn.execute(
            "SELECT payload FROM reflections ORDER BY created_at ASC"
        ).fetchall()
    finally:
        conn.close()
    return [Reflection.model_validate_json(r["payload"]) for r in rows]


# ---------- Memory entries ----------

def save_memory_entry(entry: MemoryEntry, path: Path | str | None = None) -> None:
    """Insert (or replace) a memory entry."""
    conn = _connect(_resolve(path))
    try:
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO memory_entries
                  (id, kind, content, scope, confidence, created_at, last_reinforced_at,
                   deprecated_at, deprecation_reason, evidence_reflection_ids)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(entry.id),
                    entry.kind,
                    entry.content,
                    entry.scope,
                    entry.confidence,
                    _iso(entry.created_at),
                    _iso(entry.last_reinforced_at),
                    _iso(entry.deprecated_at),
                    entry.deprecation_reason,
                    json.dumps([str(u) for u in entry.evidence_reflection_ids]),
                ),
            )
    finally:
        conn.close()


def list_memory_entries(
    include_deprecated: bool = False,
    path: Path | str | None = None,
) -> list[MemoryEntry]:
    """Return memory entries. Active-only by default, ordered by created_at."""
    sql = "SELECT * FROM memory_entries"
    if not include_deprecated:
        sql += " WHERE deprecated_at IS NULL"
    sql += " ORDER BY created_at ASC"
    conn = _connect(_resolve(path))
    try:
        rows = conn.execute(sql).fetchall()
    finally:
        conn.close()
    return [_row_to_memory_entry(r) for r in rows]


def _row_to_memory_entry(row: sqlite3.Row) -> MemoryEntry:
    return MemoryEntry(
        id=UUID(row["id"]),
        kind=row["kind"],
        content=row["content"],
        scope=row["scope"],
        confidence=row["confidence"],
        created_at=_require_iso(row["created_at"]),
        last_reinforced_at=_require_iso(row["last_reinforced_at"]),
        deprecated_at=_parse_iso(row["deprecated_at"]),
        deprecation_reason=row["deprecation_reason"],
        evidence_reflection_ids=[UUID(u) for u in json.loads(row["evidence_reflection_ids"])],
    )


# ---------- Memory embeddings (vec0) — DEFERRED-FEATURE PREP ----------

# Not called by any v0 code path. SPEC.md §9.6 forbids dynamic retrieval
# in v0; these helpers exist so the `memory_embeddings` table created in
# `init_db` is reachable end-to-end (no half-wired schema) and so v0.5's
# MCP semantic-retrieval server can land without touching this layer.
# Callers must supply embeddings produced elsewhere — this module never
# generates them.


def save_memory_embedding(
    memory_id: UUID | str,
    embedding: list[float],
    path: Path | str | None = None,
) -> None:
    """Insert (or replace) the embedding vector for a memory entry.

    `embedding` must have length `EMBEDDING_DIM` (the vec0 table is
    dimension-locked at creation). Use `delete_memory_embedding` to remove.
    """
    if len(embedding) != EMBEDDING_DIM:
        raise ValueError(
            f"embedding has length {len(embedding)}, expected {EMBEDDING_DIM} "
            f"(table is dimension-locked at creation)"
        )
    conn = _connect(_resolve(path))
    try:
        with conn:
            # vec0 INSERT OR REPLACE keyed on the TEXT primary key.
            conn.execute(
                "INSERT OR REPLACE INTO memory_embeddings (id, embedding) VALUES (?, ?)",
                (str(memory_id), sqlite_vec.serialize_float32(embedding)),
            )
    finally:
        conn.close()


def delete_memory_embedding(
    memory_id: UUID | str, path: Path | str | None = None
) -> None:
    conn = _connect(_resolve(path))
    try:
        with conn:
            conn.execute(
                "DELETE FROM memory_embeddings WHERE id = ?", (str(memory_id),)
            )
    finally:
        conn.close()


def find_similar_memory_entries(
    query_embedding: list[float],
    *,
    limit: int = 10,
    path: Path | str | None = None,
) -> list[tuple[MemoryEntry, float]]:
    """k-nearest-neighbor lookup over `memory_embeddings`, returning
    `(MemoryEntry, distance)` pairs sorted ascending by distance.

    Rows whose memory entry is deprecated are skipped. Used by v0.5's MCP
    semantic-retrieval server; v0 does not call this.
    """
    if len(query_embedding) != EMBEDDING_DIM:
        raise ValueError(
            f"query_embedding has length {len(query_embedding)}, expected {EMBEDDING_DIM}"
        )
    # sqlite-vec's vec0 KNN query requires the k bound inside the WHERE clause
    # (`k = ?`), not as a SQL LIMIT. We over-fetch slightly so the post-filter
    # for deprecated entries doesn't starve the result set.
    conn = _connect(_resolve(path))
    try:
        rows = conn.execute(
            """
            SELECT me.*, vec.distance AS distance
              FROM memory_embeddings AS vec
              JOIN memory_entries     AS me ON me.id = vec.id
             WHERE vec.embedding MATCH ?
               AND k = ?
               AND me.deprecated_at IS NULL
             ORDER BY vec.distance
            """,
            (sqlite_vec.serialize_float32(query_embedding), max(limit * 2, 1)),
        ).fetchall()
    finally:
        conn.close()
    pairs = [(_row_to_memory_entry(r), float(r["distance"])) for r in rows]
    return pairs[:limit]


# ---------- Dream cycles ----------

def save_dream_cycle(cycle: DreamCycle, path: Path | str | None = None) -> None:
    """Insert (or replace) a dream cycle. Whole payload stored as JSON."""
    payload = cycle.model_dump_json()
    conn = _connect(_resolve(path))
    try:
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO dream_cycles
                  (id, created_at, applied, applied_at, payload)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(cycle.id),
                    _iso(cycle.created_at),
                    int(cycle.applied),
                    _iso(cycle.applied_at),
                    payload,
                ),
            )
    finally:
        conn.close()


def list_dream_cycles(path: Path | str | None = None) -> list[DreamCycle]:
    """Return all dream cycles, oldest first."""
    conn = _connect(_resolve(path))
    try:
        rows = conn.execute(
            "SELECT payload FROM dream_cycles ORDER BY created_at ASC"
        ).fetchall()
    finally:
        conn.close()
    return [DreamCycle.model_validate_json(r["payload"]) for r in rows]
