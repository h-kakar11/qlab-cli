"""Shared valuation primitives.

Every model in this package takes plain numbers plus an `Assumptions` bundle,
so none of them care where their inputs came from. That is the seam the later
phases hang off: a WACC-derived discount rate, or a bear/base/bull sweep, is a
different `Assumptions` — not a different engine.

Assumptions resolve in a fixed hierarchy, highest first:

    1. `:set discount_rate 0.09`   — an explicit override always wins
    2. history                     — e.g. FCF growth from the cash flow statement
    3. a static default            — last resort, and labelled as such

`Assumptions.sources` records which rung each value came from so the report can
show it rather than presenting a guess as a fact.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

from ..models import Facts, Series

#: Used only when neither an override nor history supplies a value.
DEFAULT_FORECAST_YEARS = 10
DEFAULT_FCF_GROWTH = 0.10
DEFAULT_DISCOUNT_RATE = 0.10
DEFAULT_TERMINAL_GROWTH = 0.025

#: A historical CAGR outside this band is a trough- or peak-year artefact
#: rather than a forecast. It is clamped when used as a *default* and the
#: clamping is labelled, never silent. An explicit `:set` is not clamped.
GROWTH_CLAMP = (-0.20, 0.30)

#: A typo in `:set forecast_years` should not spin for a million iterations.
MAX_FORECAST_YEARS = 50


def as_rate(value: float | None) -> float | None:
    """Read `9`, `9.0`, `9%` and `0.09` all as 9%.

    Typing `:set discount_rate 9` is the natural thing to do, and the importer
    already turns `9%` into 9.0. So anything above 1.0 is taken as a
    percentage and anything at or below it as a decimal fraction. A growth rate
    above 100% must therefore be written `150`, not `1.5`.
    """
    if value is None or not math.isfinite(value):
        return None
    return value / 100.0 if abs(value) > 1.0 else value


def cagr(values: list[float | None]) -> float | None:
    """Compound annual growth from the oldest to the newest usable value.

    `values` is newest-first, matching `Series`. Returns None when the span is
    too short or either end is non-positive: a swing through zero has no
    meaningful compound rate, and inventing one would poison every model
    downstream.
    """
    usable = [(index, value) for index, value in enumerate(values) if value is not None]
    if len(usable) < 2:
        return None
    newest_index, newest = usable[0]
    oldest_index, oldest = usable[-1]
    if oldest <= 0 or newest <= 0:
        return None
    years = float(oldest_index - newest_index)
    if years <= 0:
        return None
    return (newest / oldest) ** (1.0 / years) - 1.0


def historical_fcf_growth(series: dict[str, Series]) -> float | None:
    """Free cash flow CAGR across whatever annual history is available."""
    item = series.get("free_cash_flow")
    if item is None:
        return None
    return cagr(item.values)


@dataclass(frozen=True)
class FCFStability:
    """Context for the growth assumption: was it a smooth climb or a coin flip?

    A -3.95% CAGR and a 14pp-volatility CAGR are not the same claim about the
    future, even though `Assumptions.resolve` would default to the same number
    for both.
    """

    cagr: float | None
    #: Sample standard deviation of year-over-year FCF growth rates.
    growth_volatility: float | None
    negative_years: int
    total_years: int


def fcf_stability(series: dict[str, Series]) -> FCFStability | None:
    """FCF CAGR, growth volatility and negative-FCF-year count from history."""
    item = series.get("free_cash_flow")
    if item is None:
        return None
    usable = [value for value in item.values if value is not None]
    if not usable:
        return None

    growth_rates: list[float] = []
    for newer, older in zip(item.values, item.values[1:]):
        if newer is not None and older is not None and older > 0:
            growth_rates.append(newer / older - 1.0)

    volatility = None
    if len(growth_rates) >= 2:
        mean = sum(growth_rates) / len(growth_rates)
        variance = sum((g - mean) ** 2 for g in growth_rates) / (len(growth_rates) - 1)
        volatility = variance**0.5

    return FCFStability(
        cagr=cagr(item.values),
        growth_volatility=volatility,
        negative_years=sum(1 for value in usable if value < 0),
        total_years=len(usable),
    )


@dataclass(frozen=True)
class Inputs:
    """The company-side facts every model in this package needs."""

    starting_fcf: float
    cash: float
    debt: float
    shares: float

    @classmethod
    def from_facts(cls, facts: Facts) -> "Inputs | None":
        fcf = facts.num("free_cash_flow")
        shares = facts.num("shares_outstanding")
        if fcf is None or shares is None or shares <= 0:
            return None
        return cls(
            starting_fcf=fcf,
            cash=facts.num("cash") or 0.0,
            debt=facts.num("total_debt") or 0.0,
            shares=shares,
        )


@dataclass(frozen=True)
class Assumptions:
    """The analyst-side inputs: everything that is judgment, not data."""

    forecast_years: int = DEFAULT_FORECAST_YEARS
    fcf_growth: float = DEFAULT_FCF_GROWTH
    discount_rate: float = DEFAULT_DISCOUNT_RATE
    terminal_growth: float = DEFAULT_TERMINAL_GROWTH
    #: field name -> "set" | "historical" | "historical (clamped)" | "default"
    sources: dict[str, str] = field(default_factory=dict)

    @property
    def valid(self) -> bool:
        """Gordon growth diverges unless the discount rate exceeds terminal growth."""
        return (
            self.forecast_years >= 1
            and self.discount_rate > 0
            and self.discount_rate > self.terminal_growth
        )

    def invalid_reason(self) -> str:
        if self.forecast_years < 1:
            return "forecast_years must be at least 1"
        if self.discount_rate <= 0:
            return "discount_rate must be above zero"
        if self.discount_rate <= self.terminal_growth:
            return (
                f"discount_rate ({self.discount_rate:.2%}) must exceed terminal_growth "
                f"({self.terminal_growth:.2%}) or the terminal value diverges"
            )
        return ""

    def with_(self, **changes: float) -> "Assumptions":
        """A variant of these assumptions — the hook for sensitivity and scenarios."""
        return replace(self, **changes)

    @classmethod
    def resolve(
        cls,
        facts: Facts,
        *,
        historical_growth: float | None = None,
    ) -> "Assumptions":
        """Apply the override -> history -> default hierarchy."""
        sources: dict[str, str] = {}

        def rate(name: str, default: float) -> float:
            override = as_rate(facts.num(name))
            if override is not None:
                sources[name] = "set"
                return override
            sources[name] = "default"
            return default

        years_raw = facts.num("forecast_years")
        if years_raw is not None and years_raw >= 1:
            years = min(int(years_raw), MAX_FORECAST_YEARS)
            sources["forecast_years"] = "set"
        else:
            years = DEFAULT_FORECAST_YEARS
            sources["forecast_years"] = "default"

        growth = as_rate(facts.num("fcf_growth_rate"))
        if growth is not None:
            sources["fcf_growth_rate"] = "set"
        elif historical_growth is not None:
            low, high = GROWTH_CLAMP
            growth = min(max(historical_growth, low), high)
            sources["fcf_growth_rate"] = (
                "historical" if growth == historical_growth else "historical, clamped"
            )
        else:
            growth = DEFAULT_FCF_GROWTH
            sources["fcf_growth_rate"] = "default"

        return cls(
            forecast_years=years,
            fcf_growth=growth,
            discount_rate=rate("discount_rate", DEFAULT_DISCOUNT_RATE),
            terminal_growth=rate("terminal_growth_rate", DEFAULT_TERMINAL_GROWTH),
            sources=sources,
        )


def present_value(amount: float, rate: float, years: float) -> float:
    return amount / (1.0 + rate) ** years


def terminal_value(final_flow: float, discount_rate: float, terminal_growth: float) -> float | None:
    """Gordon growth terminal value off the final forecast flow."""
    if discount_rate <= terminal_growth:
        return None
    return final_flow * (1.0 + terminal_growth) / (discount_rate - terminal_growth)


def per_share(
    enterprise_value: float, cash: float, debt: float, shares: float
) -> float | None:
    """The enterprise-to-equity bridge, then down to one share."""
    if shares <= 0:
        return None
    return (enterprise_value + cash - debt) / shares
