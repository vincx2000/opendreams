from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.repositories import books as books_repo
from app.repositories import loans as loans_repo
from app.repositories import members as members_repo


@pytest.fixture(autouse=True)
def _reset_state():
    books_repo.reset()
    members_repo.reset()
    loans_repo.reset()
    yield


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
