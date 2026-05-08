"""
opendream.adapters
------------------

Importing this package registers every shipped adapter so the CLI's
polymorphic `opendream ingest <name> <path>` dispatch sees them.
"""

from opendream.adapters import aider, claude_code, generic_jsonl  # noqa: F401
from opendream.adapters.base import Adapter, get_adapter, list_adapters, register_adapter

__all__ = ["Adapter", "get_adapter", "list_adapters", "register_adapter"]
