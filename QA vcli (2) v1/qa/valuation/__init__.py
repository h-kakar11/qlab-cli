"""Valuation models.

Each model is its own module and each takes the same two arguments — `Inputs`
(what the company is) and `Assumptions` (what you believe) — so adding one is a
new file, not a change to an existing one. Metrics stay thin wrappers over
these; the CLI's `:valuation` command renders them.

    from qa.valuation import Inputs, Assumptions, discounted_cash_flow

    inputs = Inputs.from_facts(facts)
    assumptions = Assumptions.resolve(facts, historical_growth=0.11)
    result = discounted_cash_flow(inputs, assumptions)
"""

from .common import (
    Assumptions,
    FCFStability,
    Inputs,
    as_rate,
    cagr,
    fcf_stability,
    historical_fcf_growth,
    per_share,
    present_value,
    terminal_value,
)
from .dcf import DCFResult, Flow, discounted_cash_flow
from .gordon_growth import gordon_growth
from .reverse_dcf import ReverseDCF, implied_growth, reverse_dcf
from .sensitivity import Grid, sensitivity_grid

__all__ = [
    "Assumptions",
    "DCFResult",
    "FCFStability",
    "Flow",
    "Grid",
    "Inputs",
    "ReverseDCF",
    "as_rate",
    "cagr",
    "discounted_cash_flow",
    "fcf_stability",
    "gordon_growth",
    "historical_fcf_growth",
    "implied_growth",
    "per_share",
    "present_value",
    "reverse_dcf",
    "sensitivity_grid",
    "terminal_value",
]
