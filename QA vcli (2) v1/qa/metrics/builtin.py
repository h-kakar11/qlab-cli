"""Standard metrics.

Every one is derived from the live price where a price belongs in the formula,
so the multiples move with the tape instead of freezing at the vendor's daily
snapshot. Leave this file alone and put your own work in `custom.py`.
"""

from __future__ import annotations

from ..models import Facts
from ..registry import metric

# --------------------------------------------------------------------------
# Price
# --------------------------------------------------------------------------


@metric("change_pct", label="Change", group="Price", fmt="signed_percent",
        needs=("price", "previous_close"), order=10)
def change_pct(f: Facts) -> float:
    """Move against the previous close."""
    return (f.num("price") / f.num("previous_close") - 1.0) * 100.0


@metric("range_position", label="52w range position", group="Price", fmt="percent",
        needs=("price", "week52_high", "week52_low"), order=20)
def range_position(f: Facts) -> float | None:
    """Where the price sits in its 52-week range: 0% = low, 100% = high."""
    high, low = f.num("week52_high"), f.num("week52_low")
    if high <= low:
        return None
    return (f.num("price") - low) / (high - low) * 100.0


@metric("market_cap", label="Market cap", group="Price", fmt="money", order=30)
def market_cap(f: Facts) -> float | None:
    """Live where a share count is known, else the vendor's figure."""
    price, shares = f.num("price"), f.num("shares_outstanding")
    if price and shares:
        return price * shares
    return f.num("market_cap")


@metric("enterprise_value", label="Enterprise value", group="Price", fmt="money",
        order=40)
def enterprise_value(f: Facts) -> float | None:
    """Market cap + debt − cash."""
    cap = market_cap(f)
    debt, cash = f.num("total_debt"), f.num("cash")
    if cap is None or debt is None or cash is None:
        return None
    return cap + debt - cash


# --------------------------------------------------------------------------
# Valuation
# --------------------------------------------------------------------------


def _multiple(price: float | None, per_share: float | None) -> float | None:
    """A multiple over a non-positive denominator is meaningless, not negative."""
    if price is None or per_share is None or per_share <= 0:
        return None
    return price / per_share


@metric("pe_ttm", label="P/E (TTM)", group="Valuation", fmt="ratio",
        needs=("price", "eps_ttm"), order=10)
def pe_ttm(f: Facts) -> float | None:
    """Live price over trailing twelve-month EPS."""
    return _multiple(f.num("price"), f.num("eps_ttm"))


@metric("pe_forward", label="P/E (forward)", group="Valuation", fmt="ratio", order=20)
def pe_forward(f: Facts) -> float | None:
    """Live price over forward EPS, falling back to the vendor's forward P/E."""
    value = _multiple(f.num("price"), f.num("eps_forward"))
    return value if value is not None else f.num("forward_pe_vendor")


@metric("peg", label="PEG", group="Valuation", fmt="ratio", order=30)
def peg(f: Facts) -> float | None:
    """P/E divided by the EPS growth rate. Below 1 is the classic screen."""
    pe = pe_ttm(f)
    growth = f.num("eps_growth_5y") or f.num("eps_growth_3y")
    if pe is None or not growth or growth <= 0:
        return f.num("peg_vendor")
    return pe / growth


@metric("pb", label="P/B", group="Valuation", fmt="ratio",
        needs=("price", "book_value_per_share"), order=40)
def price_to_book(f: Facts) -> float | None:
    return _multiple(f.num("price"), f.num("book_value_per_share"))


@metric("ps", label="P/S", group="Valuation", fmt="ratio", order=50)
def price_to_sales(f: Facts) -> float | None:
    """Derived from statement revenue first, so it agrees with EV/Sales.

    Vendor `revenue_per_share` fields lag their own statement revenue badly
    enough to put the two multiples 30%+ apart, so it is only a fallback.
    """
    revenue, shares = f.num("revenue"), f.num("shares_outstanding")
    per_share = revenue / shares if revenue and shares else f.num("revenue_per_share")
    return _multiple(f.num("price"), per_share)


@metric("ev_ebitda", label="EV/EBITDA", group="Valuation", fmt="ratio", order=60)
def ev_ebitda(f: Facts) -> float | None:
    ev, ebitda = enterprise_value(f), f.num("ebitda")
    if ev is None or not ebitda or ebitda <= 0:
        return None
    return ev / ebitda


@metric("ev_sales", label="EV/Sales", group="Valuation", fmt="ratio", order=70)
def ev_sales(f: Facts) -> float | None:
    ev, revenue = enterprise_value(f), f.num("revenue")
    if ev is None or not revenue or revenue <= 0:
        return None
    return ev / revenue


@metric("fcf_yield", label="FCF yield", group="Valuation", fmt="percent", order=80)
def fcf_yield(f: Facts) -> float | None:
    """Free cash flow over market cap — the inverse of P/FCF."""
    cap, fcf = market_cap(f), f.num("free_cash_flow")
    if not cap or fcf is None:
        return None
    return fcf / cap * 100.0


@metric("earnings_yield", label="Earnings yield", group="Valuation", fmt="percent",
        needs=("price", "eps_ttm"), order=90)
def earnings_yield(f: Facts) -> float:
    """The inverse of P/E — comparable against a bond yield."""
    return f.num("eps_ttm") / f.num("price") * 100.0


@metric("dividend_yield", label="Dividend yield", group="Valuation", fmt="percent",
        needs=("price", "dividend_per_share"), order=100)
def dividend_yield(f: Facts) -> float:
    return f.num("dividend_per_share") / f.num("price") * 100.0


# --------------------------------------------------------------------------
# Profitability
# --------------------------------------------------------------------------


def _margin(numerator: float | None, revenue: float | None) -> float | None:
    if numerator is None or not revenue or revenue <= 0:
        return None
    return numerator / revenue * 100.0


@metric("gross_margin", label="Gross margin", group="Profitability", fmt="percent", order=10)
def gross_margin(f: Facts) -> float | None:
    return _margin(f.num("gross_profit"), f.num("revenue"))


@metric("operating_margin", label="Operating margin", group="Profitability",
        fmt="percent", order=20)
def operating_margin(f: Facts) -> float | None:
    value = _margin(f.num("operating_income"), f.num("revenue"))
    return value if value is not None else f.num("operating_margin_vendor")


@metric("net_margin", label="Net margin", group="Profitability", fmt="percent", order=30)
def net_margin(f: Facts) -> float | None:
    return _margin(f.num("net_income"), f.num("revenue"))


@metric("fcf_margin", label="FCF margin", group="Profitability", fmt="percent", order=40)
def fcf_margin(f: Facts) -> float | None:
    return _margin(f.num("free_cash_flow"), f.num("revenue"))


@metric("roe", label="Return on equity", group="Profitability", fmt="percent",
        needs=("net_income", "total_equity"), order=50)
def roe(f: Facts) -> float | None:
    equity = f.num("total_equity")
    if equity <= 0:
        return None
    return f.num("net_income") / equity * 100.0


@metric("roa", label="Return on assets", group="Profitability", fmt="percent",
        needs=("net_income", "total_assets"), order=60)
def roa(f: Facts) -> float | None:
    assets = f.num("total_assets")
    if assets <= 0:
        return None
    return f.num("net_income") / assets * 100.0


@metric("roic", label="Return on capital", group="Profitability", fmt="percent", order=70)
def roic(f: Facts) -> float | None:
    """Operating income after a flat 21% tax, over debt + equity.

    The flat rate is a screening convenience, not the company's real rate.
    """
    operating, debt, equity = f.num("operating_income"), f.num("total_debt"), f.num("total_equity")
    if operating is None or debt is None or equity is None:
        return None
    capital = debt + equity
    if capital <= 0:
        return None
    return operating * 0.79 / capital * 100.0


# --------------------------------------------------------------------------
# Growth
# --------------------------------------------------------------------------


@metric("eps_growth_5y_m", label="EPS growth (5y)", group="Growth", fmt="percent", order=10)
def eps_growth_5y(f: Facts) -> float | None:
    return f.num("eps_growth_5y")


@metric("revenue_growth_5y_m", label="Revenue growth (5y)", group="Growth",
        fmt="percent", order=20)
def revenue_growth_5y(f: Facts) -> float | None:
    return f.num("revenue_growth_5y")


# --------------------------------------------------------------------------
# Financial health
# --------------------------------------------------------------------------


@metric("current_ratio", label="Current ratio", group="Financial health", fmt="ratio",
        needs=("current_assets", "current_liabilities"), order=10)
def current_ratio(f: Facts) -> float | None:
    liabilities = f.num("current_liabilities")
    if liabilities <= 0:
        return None
    return f.num("current_assets") / liabilities


@metric("quick_ratio", label="Quick ratio", group="Financial health", fmt="ratio", order=20)
def quick_ratio(f: Facts) -> float | None:
    """Current assets less inventory, over current liabilities."""
    assets, liabilities = f.num("current_assets"), f.num("current_liabilities")
    if assets is None or not liabilities or liabilities <= 0:
        return None
    return (assets - (f.num("inventory") or 0.0)) / liabilities


@metric("debt_to_equity", label="Debt / equity", group="Financial health", fmt="ratio",
        needs=("total_debt", "total_equity"), order=30)
def debt_to_equity(f: Facts) -> float | None:
    equity = f.num("total_equity")
    if equity <= 0:
        return None
    return f.num("total_debt") / equity


@metric("net_debt_ebitda", label="Net debt / EBITDA", group="Financial health",
        fmt="ratio", order=40)
def net_debt_ebitda(f: Facts) -> float | None:
    debt, cash, ebitda = f.num("total_debt"), f.num("cash"), f.num("ebitda")
    if debt is None or cash is None or not ebitda or ebitda <= 0:
        return None
    return (debt - cash) / ebitda


@metric("interest_cover", label="Interest cover", group="Financial health", fmt="ratio",
        order=50)
def interest_cover(f: Facts) -> float | None:
    """Operating income over interest expense. Higher is safer."""
    operating, interest = f.num("operating_income"), f.num("interest_expense")
    if operating is None or not interest:
        return None
    return operating / abs(interest)


@metric("net_cash_per_share", label="Net cash / share", group="Financial health",
        fmt="ratio", order=60)
def net_cash_per_share(f: Facts) -> float | None:
    cash, debt, shares = f.num("cash"), f.num("total_debt"), f.num("shares_outstanding")
    if cash is None or debt is None or not shares:
        return None
    return (cash - debt) / shares


# --------------------------------------------------------------------------
# Risk
# --------------------------------------------------------------------------


@metric("beta_m", label="Beta", group="Risk", fmt="ratio", order=10)
def beta(f: Facts) -> float | None:
    return f.num("beta")


@metric("upside_to_target", label="Upside to target", group="Risk", fmt="signed_percent",
        needs=("price", "target_mean_price"), order=20)
def upside_to_target(f: Facts) -> float:
    """Distance to the mean analyst target. Sentiment, not valuation."""
    return (f.num("target_mean_price") / f.num("price") - 1.0) * 100.0
