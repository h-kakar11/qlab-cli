"""Multi-stage discounted cash flow.

Forecast N years of free cash flow, discount each back, add a Gordon growth
terminal value, then bridge enterprise value to equity and divide by shares:

    FCF_t = FCF_0 (1 + g)^t                      for t = 1..N
    PV_t  = FCF_t / (1 + r)^t
    TV    = FCF_N (1 + g_T) / (r - g_T)
    EV    = sum(PV_t) + TV / (1 + r)^N
    FV    = (EV + cash - debt) / shares

`DCFResult` keeps the whole working, not just the answer, because the split
between forecast and terminal value is what tells you how much of the number
you should believe.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import Facts
from .common import (
    Assumptions,
    Inputs,
    per_share,
    present_value,
    terminal_value,
)


@dataclass(frozen=True)
class Flow:
    """One forecast year."""

    year: int
    cash_flow: float
    discount_factor: float
    present_value: float


@dataclass(frozen=True)
class DCFResult:
    inputs: Inputs
    assumptions: Assumptions
    flows: list[Flow]
    pv_forecast: float
    terminal_value: float
    pv_terminal: float
    enterprise_value: float
    equity_value: float
    fair_value: float

    @property
    def terminal_dependency(self) -> float | None:
        """Share of enterprise value that is terminal value.

        Past roughly 75% the valuation is mostly an opinion about the year
        after the forecast ends, which is worth knowing before acting on it.
        """
        if self.enterprise_value <= 0:
            return None
        return self.pv_terminal / self.enterprise_value * 100.0

    def upside(self, price: float | None) -> float | None:
        if not price or price <= 0:
            return None
        return (self.fair_value / price - 1.0) * 100.0


def discounted_cash_flow(inputs: Inputs, assumptions: Assumptions) -> DCFResult | None:
    """The full model. Returns None when the assumptions cannot support one."""
    if not assumptions.valid or inputs.starting_fcf <= 0:
        return None

    growth = assumptions.fcf_growth
    rate = assumptions.discount_rate

    flows: list[Flow] = []
    for year in range(1, assumptions.forecast_years + 1):
        cash_flow = inputs.starting_fcf * (1.0 + growth) ** year
        factor = 1.0 / (1.0 + rate) ** year
        flows.append(
            Flow(
                year=year,
                cash_flow=cash_flow,
                discount_factor=factor,
                present_value=cash_flow * factor,
            )
        )

    pv_forecast = sum(flow.present_value for flow in flows)
    final = terminal_value(flows[-1].cash_flow, rate, assumptions.terminal_growth)
    if final is None:
        return None
    pv_terminal = present_value(final, rate, assumptions.forecast_years)

    enterprise_value = pv_forecast + pv_terminal
    fair = per_share(enterprise_value, inputs.cash, inputs.debt, inputs.shares)
    if fair is None:
        return None

    return DCFResult(
        inputs=inputs,
        assumptions=assumptions,
        flows=flows,
        pv_forecast=pv_forecast,
        terminal_value=final,
        pv_terminal=pv_terminal,
        enterprise_value=enterprise_value,
        equity_value=enterprise_value + inputs.cash - inputs.debt,
        fair_value=fair,
    )


def from_facts(facts: Facts, *, historical_growth: float | None = None) -> DCFResult | None:
    """Convenience path for metrics, which only ever hold a `Facts`."""
    inputs = Inputs.from_facts(facts)
    if inputs is None:
        return None
    if historical_growth is None:
        historical_growth = facts.num("fcf_growth_historical")
    return discounted_cash_flow(
        inputs, Assumptions.resolve(facts, historical_growth=historical_growth)
    )
