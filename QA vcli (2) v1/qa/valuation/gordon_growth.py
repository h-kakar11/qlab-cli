"""Single-stage perpetuity valuation.

    EV = FCF (1 + g) / (r - g)

This values the business as though it enters perpetual steady growth
immediately — no forecast period at all. That is a genuinely different claim
from the DCF next door, so it stays a separate model rather than a special case
of one: it is the sanity check you compare a forecast against, and it is the
only thing available when a company's cash flows are too erratic to forecast.
"""

from __future__ import annotations

from ..models import Facts
from .common import Assumptions, Inputs, per_share


def gordon_growth(inputs: Inputs, assumptions: Assumptions) -> float | None:
    if not assumptions.valid or inputs.starting_fcf <= 0:
        return None
    enterprise_value = (
        inputs.starting_fcf
        * (1.0 + assumptions.terminal_growth)
        / (assumptions.discount_rate - assumptions.terminal_growth)
    )
    return per_share(enterprise_value, inputs.cash, inputs.debt, inputs.shares)


def from_facts(facts: Facts) -> float | None:
    inputs = Inputs.from_facts(facts)
    if inputs is None:
        return None
    return gordon_growth(inputs, Assumptions.resolve(facts))
