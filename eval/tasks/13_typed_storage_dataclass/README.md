# Refactor: replace dict-based repo state with a typed storage class

Each resource repository keeps its data as a module-level
`dict[int, Model]` plus an `itertools.count` for IDs. Replace this with
a small `_Storage[T]` dataclass (or class) that owns the dict and the
counter together, encapsulating both behind a typed object instead of
two parallel module-level globals.

Wherever a repo function currently reaches for `_BOOKS`, `_MEMBERS`, or
`_LOANS` directly, it should instead call methods on its `_Storage`
instance.

Constraints:
- Public function names exposed by each repo module are unchanged.
- All existing tests stay green. `reset()` continues to work — it can
  delegate to a single `clear()` on the storage object.
- This is a refactor, not a feature change: behavior must remain
  identical.
