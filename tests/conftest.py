from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest

from opendream import store
from opendream.trace import Message, MessageRole, Session


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "db.sqlite"
    store.init_db(db_path)
    return db_path


@pytest.fixture
def sample_session() -> Session:
    return Session(
        id=uuid4(),
        agent="aider",
        project_id="/repo/foo",
        started_at=datetime(2026, 5, 1, 12, 0, 0),
        ended_at=datetime(2026, 5, 1, 12, 30, 0),
        task_description="fix the null pointer in parseUser",
        outcome_known=True,
        outcome_success=True,
        messages=[
            Message(index=0, role=MessageRole.USER, content="fix the null pointer in parseUser"),
            Message(
                index=1,
                role=MessageRole.ASSISTANT,
                content="Looking at parseUser...\n\n```python\ndef parseUser(s):\n    ...\n```",
            ),
            Message(index=2, role=MessageRole.USER, content="thanks, all green now"),
        ],
        metadata={"source": "test"},
    )
