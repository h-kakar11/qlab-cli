"""How much the DCF moves when the two least knowable inputs move.

The discount rate and the terminal growth rate are assumptions, not
measurements, and the terminal value amplifies both. A grid across them says
whether a fair value is a robust conclusion or an artefact of the pair of
numbers that happened to be typed in.

The grid is centred on the live assumptions rather than a fixed 8-12% band, so
it still straddles the base case once a WACC-derived rate replaces the default.
"""

from __future__ import annotations

from dataclasses import dataclass

from .common import Assumptions, Inputs
from .dcf import discounted_cash_flow

#: Offsets from the base case, in percentage points.
DISCOUNT_STEPS = (-2.0, -1.0, 0.0, 1.0, 2.0)
GROWTH_STEPS = (-1.0, -0.5, 0.0, 0.5, 1.0)


@dataclass(frozen=True)
class Grid:
    discount_rates: list[float]
    terminal_growths: list[float]
    #: values[row][col], indexed as [discount_rate][terminal_growth]. None
    #: where the pair is degenerate (r <= g).
    values: list[list[float | None]]
    base: Assumptions

    def is_base(self, discount_rate: float, terminal_growth: float) -> bool:
        return (
            abs(discount_rate - self.base.discount_rate) < 1e-9
            and abs(terminal_growth - self.base.terminal_growth) < 1e-9
        )

    def spread(self) -> tuple[float, float] | None:
        """Lowest and highest fair value across the whole grid."""
        found = [v for row in self.values for v in row if v is not None]
        if not found:
            return None
        return min(found), max(found)


def sensitivity_grid(inputs: Inputs, assumptions: Assumptions) -> Grid | None:
    discount_rates = [assumptions.discount_rate + step / 100.0 for step in DISCOUNT_STEPS]
    terminal_growths = [assumptions.terminal_growth + step / 100.0 for step in GROWTH_STEPS]

    values: list[list[float | None]] = []
    for rate in discount_rates:
        row: list[float | None] = []
        for growth in terminal_growths:
            variant = assumptions.with_(discount_rate=rate, terminal_growth=growth)
            result = discounted_cash_flow(inputs, variant)
            row.append(None if result is None else result.fair_value)
        values.append(row)

    if not any(v is not None for row in values for v in row):
        return None

    return Grid(
        discount_rates=discount_rates,
        terminal_growths=terminal_growths,
        values=values,
        base=assumptions,
    )
