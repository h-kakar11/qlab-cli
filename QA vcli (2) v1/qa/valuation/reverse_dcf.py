"""What growth does today's price already assume?

A forward DCF answers "what is this worth?", which requires you to supply the
growth rate — the very thing you are least sure about. A reverse DCF turns the
model around: hold the price as given and solve for the free cash flow growth
that would justify it.

The output is falsifiable in a way "23% undervalued" is not. An implied 17%
against a historical 11% is a specific claim the market is making, and you can
go and form a view on whether it is achievable.

Fair value rises monotonically with growth, every other input held fixed, so
bisection converges reliably and needs no derivative.
"""

from __future__ import annotations

from dataclasses import dataclass

from .common import Assumptions, Inputs
from .dcf import discounted_cash_flow

#: The search interval for annual FCF growth: -90% to +300%.
GROWTH_BOUNDS = (-0.90, 3.00)
ITERATIONS = 200
TOLERANCE = 1e-9


@dataclass(frozen=True)
class ReverseDCF:
    price: float
    implied_growth: float
    historical_growth: float | None
    assumptions: Assumptions

    @property
    def gap(self) -> float | None:
        """Implied minus historical, in percentage points."""
        if self.historical_growth is None:
            return None
        return (self.implied_growth - self.historical_growth) * 100.0


def implied_growth(
    inputs: Inputs,
    assumptions: Assumptions,
    price: float,
) -> float | None:
    """Solve for the stage-one growth rate that prices the share at `price`."""
    if price <= 0 or not assumptions.valid or inputs.starting_fcf <= 0:
        return None

    def value_at(growth: float) -> float | None:
        result = discounted_cash_flow(inputs, assumptions.with_(fcf_growth=growth))
        return None if result is None else result.fair_value

    low, high = GROWTH_BOUNDS
    low_value, high_value = value_at(low), value_at(high)
    if low_value is None or high_value is None:
        return None
    # Outside the bracket there is no answer to report, and clamping to the
    # bound would quietly present -90% or +300% as if it were a solution.
    if not (low_value <= price <= high_value):
        return None

    for _ in range(ITERATIONS):
        middle = (low + high) / 2.0
        value = value_at(middle)
        if value is None:
            return None
        if abs(value - price) < TOLERANCE or (high - low) < TOLERANCE:
            return middle
        if value < price:
            low = middle
        else:
            high = middle
    return (low + high) / 2.0


def reverse_dcf(
    inputs: Inputs,
    assumptions: Assumptions,
    price: float,
    *,
    historical_growth: float | None = None,
) -> ReverseDCF | None:
    growth = implied_growth(inputs, assumptions, price)
    if growth is None:
        return None
    return ReverseDCF(
        price=price,
        implied_growth=growth,
        historical_growth=historical_growth,
        assumptions=assumptions,
    )
