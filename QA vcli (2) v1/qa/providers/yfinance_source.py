"""yfinance — the long-term layer: statements, share counts, price history.

Deliberately not used for the live price; Yahoo's quote is delayed and scraped.
Massive and Finnhub cover that, and outrank this provider on `price`.
"""

from __future__ import annotations

import math
from typing import Any, Iterable

from .. import config
from ..models import Fact, Series
from .base import CachedProvider, provider

try:
    import yfinance as yf
except ImportError:  # pragma: no cover - optional dependency
    yf = None


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _row(statement, labels: Iterable[str]) -> list[float | None] | None:
    """First matching row across alternative yfinance labels, newest first."""
    if statement is None or getattr(statement, "empty", True):
        return None
    for label in labels:
        if label in statement.index:
            return [_num(v) for v in statement.loc[label].tolist()]
    return None


def _latest(statement, labels: Iterable[str]) -> float | None:
    row = _row(statement, labels)
    if not row:
        return None
    for value in row:
        if value is not None:
            return value
    return None


def _periods(statement) -> list[str]:
    if statement is None or getattr(statement, "empty", True):
        return []
    return [str(c)[:10] for c in statement.columns]


@provider
class YFinanceProvider(CachedProvider):
    name = "yfinance"
    kind = "longterm"
    priority = config.PRIORITY_LONGTERM
    describe = "Annual/quarterly statements, share count, profile, price history"
    ttl = config.FUNDAMENTALS_TTL

    def available(self) -> bool:
        return yf is not None

    def unavailable_reason(self) -> str:
        return "pip install yfinance"

    def __init__(self) -> None:
        super().__init__()
        self._tickers: dict[str, Any] = {}

    def _ticker(self, ticker: str):
        # yfinance memoises statements on the Ticker object, so reusing it
        # means `series()` costs nothing after `fetch()` has run.
        key = ticker.upper()
        if key not in self._tickers:
            self._tickers[key] = yf.Ticker(key)
        return self._tickers[key]

    def invalidate(self, ticker: str | None = None) -> None:
        # The Ticker objects memoise statements, so dropping only the fact
        # cache would leave `:refresh` serving the same numbers back.
        super().invalidate(ticker)
        if ticker is None:
            self._tickers.clear()
        else:
            self._tickers.pop(ticker.upper(), None)

    def fetch(self, ticker: str) -> dict[str, Fact]:
        return self.cached(ticker, lambda: self._build(ticker))

    def _build(self, ticker: str) -> dict[str, Fact]:
        stock = self._ticker(ticker)
        try:
            info = stock.get_info() or {}
        except Exception:
            info = {}

        income = getattr(stock, "income_stmt", None)
        balance = getattr(stock, "balance_sheet", None)
        cashflow = getattr(stock, "cashflow", None)

        operating_cf = _latest(cashflow, ("Operating Cash Flow", "Total Cash From Operating Activities"))
        capex = _latest(cashflow, ("Capital Expenditure", "Capital Expenditures"))
        free_cash_flow = _latest(cashflow, ("Free Cash Flow",))
        if free_cash_flow is None and operating_cf is not None and capex is not None:
            # yfinance reports capex as a negative outflow.
            free_cash_flow = operating_cf + capex

        values: dict[str, Any] = {
            # Identity
            "name": info.get("longName") or info.get("shortName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "currency": info.get("currency") or info.get("financialCurrency"),
            "exchange": info.get("fullExchangeName") or info.get("exchange"),
            "country": info.get("country"),
            "employees": _num(info.get("fullTimeEmployees")),
            "summary": info.get("longBusinessSummary"),
            # Price context (low priority; live providers override `price`)
            "price": _num(info.get("currentPrice") or info.get("regularMarketPrice")),
            "previous_close": _num(info.get("previousClose")),
            "day_high": _num(info.get("dayHigh")),
            "day_low": _num(info.get("dayLow")),
            "week52_high": _num(info.get("fiftyTwoWeekHigh")),
            "week52_low": _num(info.get("fiftyTwoWeekLow")),
            "avg_volume": _num(info.get("averageVolume")),
            "beta": _num(info.get("beta")),
            # Per-share and counts
            "shares_outstanding": _num(info.get("sharesOutstanding")),
            "eps_ttm": _num(info.get("trailingEps")),
            "eps_forward": _num(info.get("forwardEps")),
            "book_value_per_share": _num(info.get("bookValue")),
            "dividend_per_share": _num(info.get("trailingAnnualDividendRate") or info.get("dividendRate")),
            "payout_ratio": _num(info.get("payoutRatio")),
            # Income statement
            "revenue": _latest(income, ("Total Revenue", "Operating Revenue")),
            "gross_profit": _latest(income, ("Gross Profit",)),
            "operating_income": _latest(income, ("Operating Income", "EBIT")),
            "net_income": _latest(income, ("Net Income", "Net Income Common Stockholders")),
            "ebitda": _latest(income, ("EBITDA", "Normalized EBITDA")) or _num(info.get("ebitda")),
            "interest_expense": _latest(income, ("Interest Expense",)),
            # Balance sheet
            "total_assets": _latest(balance, ("Total Assets",)),
            "total_liabilities": _latest(
                balance, ("Total Liabilities Net Minority Interest", "Total Liab")
            ),
            "total_equity": _latest(
                balance, ("Stockholders Equity", "Total Stockholder Equity", "Common Stock Equity")
            ),
            "cash": _latest(
                balance,
                ("Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents"),
            ),
            "total_debt": _latest(balance, ("Total Debt",)) or _num(info.get("totalDebt")),
            "current_assets": _latest(balance, ("Current Assets", "Total Current Assets")),
            "current_liabilities": _latest(balance, ("Current Liabilities", "Total Current Liabilities")),
            "inventory": _latest(balance, ("Inventory",)),
            # Cash flow
            "operating_cash_flow": operating_cf,
            "capex": capex,
            "free_cash_flow": free_cash_flow,
            # Analyst context
            "target_mean_price": _num(info.get("targetMeanPrice")),
            "recommendation": info.get("recommendationKey"),
        }
        return self.pack(values)

    def series(self, ticker: str) -> dict[str, Series]:
        stock = self._ticker(ticker)
        income = getattr(stock, "income_stmt", None)
        cashflow = getattr(stock, "cashflow", None)
        periods = _periods(income)
        out: dict[str, Series] = {}

        wanted = [
            ("revenue", income, ("Total Revenue", "Operating Revenue")),
            ("net_income", income, ("Net Income", "Net Income Common Stockholders")),
            ("operating_income", income, ("Operating Income", "EBIT")),
            ("free_cash_flow", cashflow, ("Free Cash Flow",)),
        ]
        for name, statement, labels in wanted:
            row = _row(statement, labels)
            if not row:
                continue
            statement_periods = _periods(statement) or periods
            out[name] = Series(
                name=name, periods=statement_periods, values=row, source=self.name
            )
        return out
