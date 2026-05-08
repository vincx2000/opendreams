"""
opendream.adapters.base
-----------------------

Abstract `Adapter` base class and a tiny registry. New adapters subclass
`Adapter`, set a `name`, and call `register_adapter(MyAdapter)` so the CLI's
polymorphic `opendream ingest <name> <path>` finds them.

Note on the interface: the v0 spec originally said `parse_session(path) -> Session`,
but real-world history files (Aider, the generic_jsonl escape hatch) often pack
N sessions into one file. We return `list[Session]` so adapters can preserve
that without filesystem hackery; for 1-file-1-session adapters like
`claude_code` the list has length 1.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

from opendream.trace import Session


class Adapter(ABC):
    """Base class for all session-source adapters."""

    name: ClassVar[str]

    @abstractmethod
    def discover_sessions(self, root: Path) -> list[Path]:
        """Return paths under `root` that this adapter can parse."""

    @abstractmethod
    def parse_sessions(self, path: Path) -> list[Session]:
        """Parse `path` into one or more `Session`s."""


_REGISTRY: dict[str, type[Adapter]] = {}


def register_adapter(adapter_cls: type[Adapter]) -> type[Adapter]:
    """Register an Adapter subclass. Usable as a decorator."""
    if not getattr(adapter_cls, "name", None):
        raise ValueError(f"{adapter_cls!r} is missing a `name` attribute")
    _REGISTRY[adapter_cls.name] = adapter_cls
    return adapter_cls


def get_adapter(name: str) -> Adapter:
    """Instantiate the adapter registered under `name`."""
    if name not in _REGISTRY:
        raise KeyError(
            f"unknown adapter {name!r}; registered: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[name]()


def list_adapters() -> list[str]:
    return sorted(_REGISTRY)
