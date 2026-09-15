"""Provider base class and registry.

A provider turns a ticker into `Fact`s. To add one: subclass `Provider`,
decorate it with `@provider`, and drop the file in `qa/providers/`. It is
discovered on import — nothing else to wire up.

    from qa.providers.base import Provider, provider

    @provider
    class MyFeed(Provider):
        name = "myfeed"
        kind = "longterm"
        priority = 15

        def available(self):
            return True

        def fetch(self, ticker):
            return {"price": self.fact(123.4)}
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable, ClassVar

from ..models import Fact, Facts, Series

#: kind: "longterm" (statements, history), "live" (streaming/current quotes),
#: "import" (your own data). Shown in `:sources`.
Kind = str


class Provider:
    name: ClassVar[str] = "unnamed"
    kind: ClassVar[Kind] = "longterm"
    priority: ClassVar[int] = 0
    #: One line shown in `:sources`.
    describe: ClassVar[str] = ""

    def available(self) -> bool:
        """False disables the provider (missing key, missing package)."""
        return True

    def unavailable_reason(self) -> str:
        return "unavailable"

    def fetch(self, ticker: str) -> dict[str, Fact]:
        """Return field name -> Fact. Raise freely; the engine catches."""
        raise NotImplementedError

    def series(self, ticker: str) -> dict[str, Series]:
        """Optional: historical series for the history panel."""
        return {}

    # -- helpers for subclasses -------------------------------------------

    def fact(self, value: Any, *, unit: str = "", as_of: datetime | None = None) -> Fact | None:
        if value is None:
            return None
        return Fact(
            value=value,
            source=self.name,
            as_of=as_of or datetime.now(timezone.utc),
            unit=unit,
            priority=self.priority,
        )

    def pack(self, mapping: dict[str, Any], *, units: dict[str, str] | None = None) -> dict[str, Fact]:
        """Build a fact dict from plain values, dropping the Nones."""
        units = units or {}
        out: dict[str, Fact] = {}
        for key, value in mapping.items():
            built = self.fact(value, unit=units.get(key, ""))
            if built is not None:
                out[key] = built
        return out


class CachedProvider(Provider):
    """Provider whose `fetch` result is reused for `ttl` seconds per ticker."""

    ttl: ClassVar[float] = 3600.0

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, dict[str, Fact]]] = {}

    def cached(self, ticker: str, build: Callable[[], dict[str, Fact]]) -> dict[str, Fact]:
        hit = self._cache.get(ticker)
        if hit and time.monotonic() - hit[0] < self.ttl:
            return hit[1]
        result = build()
        self._cache[ticker] = (time.monotonic(), result)
        return result

    def invalidate(self, ticker: str | None = None) -> None:
        if ticker is None:
            self._cache.clear()
        else:
            self._cache.pop(ticker, None)


_PROVIDERS: dict[str, Provider] = {}


def provider(cls: type[Provider]) -> type[Provider]:
    """Class decorator: instantiate once and register."""
    _PROVIDERS[cls.name] = cls()
    return cls


def all_providers() -> list[Provider]:
    return sorted(_PROVIDERS.values(), key=lambda p: (p.priority, p.name))


def get_provider(name: str) -> Provider | None:
    return _PROVIDERS.get(name)


def collect(ticker: str, *, only: set[str] | None = None) -> tuple[Facts, list[str]]:
    """Run every available provider and merge the results by priority.

    Returns the merged facts plus any provider-level warnings, so one dead
    feed degrades the report instead of ending the run.
    """
    facts = Facts(ticker)
    warnings: list[str] = []
    for prov in all_providers():
        if only is not None and prov.name not in only:
            continue
        if not prov.available():
            continue
        try:
            facts.merge(prov.fetch(ticker))
        except Exception as exc:
            warnings.append(f"{prov.name}: {exc}")
    return facts, warnings


def collect_series(ticker: str) -> dict[str, Series]:
    out: dict[str, Series] = {}
    for prov in all_providers():
        if not prov.available():
            continue
        try:
            out.update(prov.series(ticker))
        except Exception:
            continue
    return out
