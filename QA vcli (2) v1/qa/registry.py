"""The metric registry — where you add your own math.

Adding a metric is one decorated function. Drop it in `qa/metrics/custom.py`
(or any new module in that folder) and it appears in the report automatically:

    from qa.registry import metric

    @metric("fcf_yield", label="FCF yield", group="Valuation",
            needs=("free_cash_flow", "market_cap"), fmt="percent")
    def fcf_yield(f):
        return f.num("free_cash_flow") / f.num("market_cap") * 100

`needs` names the fields your function requires. If any are missing the metric
is skipped rather than raising, so a half-populated ticker still renders.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

from .models import Facts

#: Order groups appear in the report. Unlisted groups sort last, alphabetically.
GROUP_ORDER = [
    "Price",
    "Valuation",
    "Profitability",
    "Growth",
    "Financial health",
    "Risk",
    "Custom",
]


@dataclass
class Metric:
    key: str
    fn: Callable[[Facts], float | None]
    label: str
    group: str = "Custom"
    fmt: str = "ratio"
    needs: tuple[str, ...] = ()
    unit: str = ""
    #: Free-text note shown by `:explain <key>`.
    about: str = ""
    #: Lower sorts first inside a group.
    order: int = 100
    tags: tuple[str, ...] = field(default_factory=tuple)

    def compute(self, facts: Facts) -> float | None:
        """Never raises: a metric that cannot be computed is simply absent."""
        if self.needs and not facts.has(*self.needs):
            return None
        try:
            value = self.fn(facts)
        except (TypeError, ValueError, ZeroDivisionError, KeyError):
            return None
        if value is None:
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None


_METRICS: dict[str, Metric] = {}


def metric(
    key: str,
    *,
    label: str | None = None,
    group: str = "Custom",
    fmt: str = "ratio",
    needs: tuple[str, ...] | list[str] = (),
    unit: str = "",
    about: str = "",
    order: int = 100,
    tags: tuple[str, ...] = (),
) -> Callable[[Callable[[Facts], float | None]], Callable[[Facts], float | None]]:
    """Register a metric. `fmt` is a key from `qa.render.FORMATTERS`."""

    def decorate(fn: Callable[[Facts], float | None]) -> Callable[[Facts], float | None]:
        _METRICS[key] = Metric(
            key=key,
            fn=fn,
            label=label or key.replace("_", " ").capitalize(),
            group=group,
            fmt=fmt,
            needs=tuple(needs),
            unit=unit,
            about=about or (fn.__doc__ or "").strip(),
            order=order,
            tags=tuple(tags),
        )
        return fn

    return decorate


def all_metrics() -> list[Metric]:
    def sort_key(m: Metric) -> tuple[int, str, int, str]:
        try:
            group_rank = GROUP_ORDER.index(m.group)
        except ValueError:
            group_rank = len(GROUP_ORDER)
        return (group_rank, m.group, m.order, m.label)

    return sorted(_METRICS.values(), key=sort_key)


def get_metric(key: str) -> Metric | None:
    return _METRICS.get(key)


def compute_all(facts: Facts) -> dict[str, float | None]:
    return {m.key: m.compute(facts) for m in all_metrics()}


def load_metric_modules() -> None:
    """Import every module under `qa/metrics/`, so registration happens."""
    from . import metrics

    metrics.load_all()
