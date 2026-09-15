"""Your metrics live here.

Write a function, decorate it, done — it shows up in the report next run. The
three examples below are real and working; delete them or keep them.

Available formats (`fmt=`): "ratio", "percent", "signed_percent", "money",
"count", "price", "plain".

Rules of thumb:
  * `needs=(...)` lists the fields you divide by or subtract. Anything listed
    there is guaranteed non-None inside your function, and a ticker missing one
    skips the metric instead of erroring.
  * Return None for "not meaningful" (a negative denominator, say).
  * Run `:fields` in the CLI to see every field available for the loaded
    ticker, and `:explain <key>` to read a metric's docstring back.
  * Need a field no provider supplies? `:set my_field 1234`, or drop it in
    `data/<TICKER>.csv`. Imported values outrank every vendor.
"""

from __future__ import annotations

from .. import valuation
from ..models import Facts
from ..registry import metric

# Imported by full path on purpose: `qa.valuation` re-exports functions named
# `gordon_growth` and `reverse_dcf`, which shadow the submodules of the same
# name, so `from ..valuation import gordon_growth` would hand back a function.
from ..valuation.dcf import from_facts as dcf_from_facts
from ..valuation.gordon_growth import from_facts as gordon_from_facts


@metric(
    "owner_earnings_yield",
    label="Owner earnings yield",
    group="Custom",
    fmt="percent",
    needs=("operating_cash_flow", "capex", "price", "shares_outstanding"),
    order=10,
)
def owner_earnings_yield(f: Facts) -> float | None:
    """Buffett's owner earnings (CFO − capex) over market cap.

    yfinance reports capex as a negative outflow, hence the addition.
    """
    owner_earnings = f.num("operating_cash_flow") + f.num("capex")
    cap = f.num("price") * f.num("shares_outstanding")
    if cap <= 0:
        return None
    return owner_earnings / cap * 100.0


@metric(
    "graham_number",
    label="Graham number",
    group="Custom",
    fmt="price",
    needs=("eps_ttm", "book_value_per_share"),
    order=20,
)
def graham_number(f: Facts) -> float | None:
    """sqrt(22.5 x EPS x book value) — Graham's rough fair-value ceiling."""
    eps, book = f.num("eps_ttm"), f.num("book_value_per_share")
    if eps <= 0 or book <= 0:
        return None
    return (22.5 * eps * book) ** 0.5


@metric(
    "margin_of_safety",
    label="Margin of safety",
    group="Custom",
    fmt="signed_percent",
    needs=("price",),
    order=30,
)
def margin_of_safety(f: Facts) -> float | None:
    """Discount of the live price to the Graham number.

    Positive means the price sits below that ceiling. Depends on another
    metric, which is fine — just call its function.
    """
    fair = graham_number(f)
    if fair is None:
        return None
    return (fair / f.num("price") - 1.0) * 100.0

# --------------------------------------------------------------------------
# Valuation models
#
# The maths lives in `qa/valuation/`; these are deliberately thin. Run
# `:valuation` for the full working — the forecast table, the sensitivity grid
# and the reverse DCF — rather than just these headline numbers.
#
# Assumptions resolve as override -> history -> default:
#     :set discount_rate 0.09        (or 9, or 9% — all the same)
#     :set terminal_growth_rate 0.025
#     :set fcf_growth_rate 0.12      defaults to the historical FCF CAGR
#     :set forecast_years 10
# --------------------------------------------------------------------------

DCF_NEEDS = ("free_cash_flow", "shares_outstanding")


@metric(
    "dcf_fair_value",
    label="DCF fair value",
    group="Custom",
    fmt="price",
    needs=DCF_NEEDS,
    order=40,
)
def dcf_fair_value(f: Facts) -> float | None:
    """Multi-stage DCF: N forecast years discounted, plus a terminal value."""
    result = dcf_from_facts(f)
    return None if result is None else result.fair_value


@metric(
    "dcf_upside",
    label="DCF upside",
    group="Custom",
    fmt="signed_percent",
    needs=DCF_NEEDS + ("price",),
    order=50,
)
def dcf_upside(f: Facts) -> float | None:
    """Distance from the live price to the DCF fair value."""
    result = dcf_from_facts(f)
    return None if result is None else result.upside(f.num("price"))


@metric(
    "terminal_dependency",
    label="Terminal value dependency",
    group="Custom",
    fmt="percent",
    needs=DCF_NEEDS,
    order=60,
)
def terminal_dependency(f: Facts) -> float | None:
    """Share of the DCF that is terminal value.

    High is not wrong, but past ~75% the valuation is mostly a claim about the
    year after the forecast ends, and the sensitivity grid matters more than
    the point estimate.
    """
    result = dcf_from_facts(f)
    return None if result is None else result.terminal_dependency


@metric(
    "gordon_growth_fair_value",
    label="Gordon growth value",
    group="Custom",
    fmt="price",
    needs=DCF_NEEDS,
    order=70,
)
def gordon_growth_fair_value(f: Facts) -> float | None:
    """Perpetuity value with no forecast period — the simple-model cross-check.

    Assumes steady terminal growth starts immediately, so it will sit well
    below the DCF for anything currently growing quickly.
    """
    return gordon_from_facts(f)


@metric(
    "implied_growth",
    label="Implied FCF growth",
    group="Custom",
    fmt="percent",
    needs=DCF_NEEDS + ("price",),
    order=80,
)
def implied_growth(f: Facts) -> float | None:
    """Reverse DCF: the growth rate today's price already assumes."""
    inputs = valuation.Inputs.from_facts(f)
    if inputs is None:
        return None
    assumptions = valuation.Assumptions.resolve(
        f, historical_growth=f.num("fcf_growth_historical")
    )
    growth = valuation.implied_growth(inputs, assumptions, f.num("price"))
    return None if growth is None else growth * 100.0


@metric(
    "implied_vs_historical",
    label="Implied vs historical",
    group="Custom",
    fmt="signed_pp",
    needs=DCF_NEEDS + ("price", "fcf_growth_historical"),
    order=90,
)
def implied_vs_historical(f: Facts) -> float | None:
    """Percentage points the priced-in growth sits above its own track record.

    Positive means the market expects the company to do better than it has.
    """
    implied = implied_growth(f)
    historical = f.num("fcf_growth_historical")
    if implied is None or historical is None:
        return None
    return implied - historical * 100.0