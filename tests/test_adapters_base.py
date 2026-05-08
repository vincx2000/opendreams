from __future__ import annotations

from pathlib import Path

import pytest

from opendream.adapters import (
    Adapter,
    get_adapter,
    list_adapters,
    register_adapter,
)
from opendream.trace import Session


def test_built_in_adapters_are_registered():
    names = list_adapters()
    assert "claude_code" in names
    assert "aider" in names
    assert "generic_jsonl" in names


def test_get_adapter_returns_instance():
    a = get_adapter("aider")
    assert isinstance(a, Adapter)
    assert a.name == "aider"


def test_get_adapter_unknown_raises():
    with pytest.raises(KeyError, match="unknown adapter"):
        get_adapter("nonexistent")


def test_register_requires_name():
    class NoName(Adapter):
        def discover_sessions(self, root: Path) -> list[Path]:
            return []

        def parse_sessions(self, path: Path) -> list[Session]:
            return []

    with pytest.raises(ValueError, match="missing a `name`"):
        register_adapter(NoName)


def test_abstract_methods_enforced():
    # Cannot instantiate without both methods.
    class Partial(Adapter):
        name = "partial"

        def discover_sessions(self, root: Path) -> list[Path]:
            return []

    with pytest.raises(TypeError):
        Partial()
