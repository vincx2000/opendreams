"""
app.result
----------

Tiny `Result[T]` sum type. Service functions return `Result[T]` rather than
raising on expected-failure paths; the HTTP layer uses `is_ok` / `is_err` and
the `code` / `value` fields to translate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class Result(Generic[T]):
    value: T | None = None
    code: str | None = None
    message: str | None = None

    @property
    def is_ok(self) -> bool:
        return self.code is None

    @property
    def is_err(self) -> bool:
        return self.code is not None


def Ok(value: T) -> Result[T]:
    return Result(value=value)


def Err(code: str, message: str = "") -> Result:
    return Result(code=code, message=message)
