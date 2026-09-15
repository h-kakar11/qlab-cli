"""The shared vocabulary every provider and metric speaks.

A provider produces `Fact`s. A metric consumes them. Neither knows the other
exists, which is what makes both sides cheap to add to.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterator


@dataclass(frozen=True)
class Fact:
    """One value, plus where it came from and when it was true."""

    value: Any
    source: str
    as_of: datetime | None = None
    unit: str = ""
    #: Higher wins when two providers supply the same field. Live quotes should
    #: outrank a daily snapshot; a value you imported by hand outranks both.
    priority: int = 0

    @property
    def number(self) -> float | None:
        try:
            number = float(self.value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None


class Facts:
    """A merged, provenance-keeping bag of `Fact`s for one ticker.

    Highest priority wins on collision, so a provider never has to care what
    else is registered.
    """

    def __init__(self, ticker: str) -> None:
        self.ticker = ticker.upper()
        self._facts: dict[str, Fact] = {}
        #: Every value seen per field, newest last. Useful for `:sources`.
        self.rejected: dict[str, list[Fact]] = {}

    def add(self, name: str, fact: Fact | None) -> None:
        if fact is None or fact.value is None:
            return
        if isinstance(fact.value, float) and not math.isfinite(fact.value):
            return
        existing = self._facts.get(name)
        if existing is not None and existing.priority >= fact.priority:
            self.rejected.setdefault(name, []).append(fact)
            return
        if existing is not None:
            self.rejected.setdefault(name, []).append(existing)
        self._facts[name] = fact

    def merge(self, other: dict[str, Fact]) -> None:
        for name, fact in other.items():
            self.add(name, fact)

    def fact(self, name: str) -> Fact | None:
        return self._facts.get(name)

    def get(self, name: str, default: Any = None) -> Any:
        fact = self._facts.get(name)
        return default if fact is None else fact.value

    def num(self, name: str) -> float | None:
        """The field as a finite float, or None. Metrics use this everywhere."""
        fact = self._facts.get(name)
        return None if fact is None else fact.number

    def has(self, *names: str) -> bool:
        """True only if every name resolves to a usable number."""
        return all(self.num(name) is not None for name in names)

    def source_of(self, name: str) -> str:
        fact = self._facts.get(name)
        return fact.source if fact else "—"

    def names(self) -> list[str]:
        return sorted(self._facts)

    def __contains__(self, name: object) -> bool:
        return name in self._facts

    def __iter__(self) -> Iterator[tuple[str, Fact]]:
        return iter(sorted(self._facts.items()))

    def __len__(self) -> int:
        return len(self._facts)


@dataclass
class Series:
    """An annual or quarterly history: newest first, aligned to `periods`."""

    name: str
    periods: list[str] = field(default_factory=list)
    values: list[float | None] = field(default_factory=list)
    source: str = ""

    def latest(self) -> float | None:
        for value in self.values:
            if value is not None:
                return value
        return None

    def pairs(self) -> list[tuple[str, float | None]]:
        return list(zip(self.periods, self.values))
