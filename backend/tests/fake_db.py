"""A minimal in-memory stand-in for a SQLAlchemy Session.

Phase 1 routes only use a small slice of the Session API (add / flush / commit
and simple equality + IS NULL filters).  Interpreting those expressions in
memory lets the auth and consent tests exercise the real route and dependency
code with no Postgres and no Docker, which keeps CI fast and hermetic.

If a later phase needs richer query support (joins, aggregates), switch those
tests to a real Postgres service container instead of extending this.
"""

from typing import Any

from sqlalchemy import Null
from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import BinaryExpression, BooleanClauseList, UnaryExpression

from app.models.models import AuditLog


def _expected_value(clause: Any) -> Any:
    """Pull the right-hand comparison value out of a SQLAlchemy expression."""
    right = clause.right
    if isinstance(right, Null):
        return None
    return getattr(right, "value", right)


def _matches(obj: Any, clause: Any) -> bool:
    """Evaluate a SQLAlchemy filter clause against a plain ORM instance."""
    if isinstance(clause, BooleanClauseList):
        return all(_matches(obj, c) for c in clause.clauses)

    if isinstance(clause, BinaryExpression):
        actual = getattr(obj, clause.left.key)
        expected = _expected_value(clause)
        op = clause.operator

        if op is operators.eq:
            return actual == expected
        if op is operators.is_:
            return actual is None if expected is None else actual == expected
        if op is operators.is_not:
            return actual is not None if expected is None else actual != expected
        if op is operators.ne:
            return actual != expected
        raise NotImplementedError(f"FakeSession does not support operator {op!r}")

    raise NotImplementedError(f"FakeSession does not support clause {type(clause).__name__}")


class FakeQuery:
    def __init__(self, rows: list[Any]):
        self._rows = list(rows)

    def filter(self, *criteria: Any) -> "FakeQuery":
        rows = [r for r in self._rows if all(_matches(r, c) for c in criteria)]
        return FakeQuery(rows)

    def order_by(self, *clauses: Any) -> "FakeQuery":
        rows = self._rows
        # Apply in reverse so the first clause is the primary sort key.
        for clause in reversed(clauses):
            if isinstance(clause, UnaryExpression):
                key = clause.element.key
                descending = "DESC" in str(clause).upper()
            else:
                key = clause.key
                descending = False
            rows = sorted(rows, key=lambda r: getattr(r, key), reverse=descending)
        return FakeQuery(rows)

    def all(self) -> list[Any]:
        return list(self._rows)

    def first(self) -> Any | None:
        return self._rows[0] if self._rows else None

    def count(self) -> int:
        return len(self._rows)


class FakeSession:
    """Stores added instances in memory, keyed by model class."""

    def __init__(self) -> None:
        self._store: dict[type, list[Any]] = {}
        self.commits = 0

    # ── Session API used by the routes ────────────────────────────────────
    def add(self, obj: Any) -> None:
        self._store.setdefault(type(obj), []).append(obj)

    def query(self, model: type) -> FakeQuery:
        return FakeQuery(self._store.get(model, []))

    def flush(self) -> None:
        pass

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        pass

    def refresh(self, obj: Any) -> None:
        pass

    def close(self) -> None:
        pass

    def execute(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    # ── Test helpers ──────────────────────────────────────────────────────
    def rows_of(self, model: type) -> list[Any]:
        return list(self._store.get(model, []))

    def audit_actions(self) -> list[str]:
        return [entry.action for entry in self.rows_of(AuditLog)]

    def audit_entries(self) -> list[AuditLog]:
        return self.rows_of(AuditLog)
