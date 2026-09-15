"""Fetch model-ready DCF inputs for a ticker and save them for APE.cpp.

Install once:
    py -m pip install -r requirements.txt

Then run:
    py ticker.py NVDA
    g++ -std=c++17 -O2 APE.cpp -o APE.exe
    .\APE.exe dcf_inputs.txt
"""

from __future__ import annotations

import argparse
import math
from datetime import date
from pathlib import Path
from typing import Iterable

import yfinance as yf


OUTPUT_FILE = Path("dcf_inputs.txt")
DEFAULT_DISCOUNT_RATE = 0.09
DEFAULT_TERMINAL_GROWTH_RATE = 0.025
DEFAULT_FORECAST_YEARS = 5


def as_number(value: object) -> float | None:
    """Return a finite float, or None for absent / non-numeric values."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def statement_value(statement, labels: Iterable[str]) -> tuple[float | None, str | None, object | None]:
    """Get the newest available annual value using alternative yfinance labels."""
    if statement is None or statement.empty:
        return None, None, None

    for label in labels:
        if label not in statement.index:
            continue
        values = statement.loc[label].dropna()
        if not values.empty:
            value = as_number(values.iloc[0])
            if value is not None:
                return value, label, values.index[0]
    return None, None, None


def latest_shares(stock: yf.Ticker, info: dict) -> float | None:
    """Prefer yfinance's dated share history; fall back to the info snapshot."""
    try:
        history = stock.get_shares_full(start="2020-01-01")
        if history is not None and not history.dropna().empty:
            value = as_number(history.dropna().iloc[-1])
            if value is not None:
                return value
    except Exception:
        pass
    return as_number(info.get("sharesOutstanding"))


def recent_fcf_growth(cashflow) -> float:
    """Suggest a bounded historical FCF growth rate; return 0% if not meaningful."""
    fcf, label, _ = statement_value(cashflow, ["Free Cash Flow"])
    if fcf is None or label is None:
        return 0.0

    values = [as_number(value) for value in cashflow.loc[label].dropna().tolist()]
    values = [value for value in values if value is not None]
    if len(values) < 2 or values[0] <= 0 or values[-1] <= 0:
        return 0.0

    years = len(values) - 1
    cagr = (values[0] / values[-1]) ** (1 / years) - 1
    # A raw FCF CAGR can be extreme. A suggestion is only useful when plausible.
    return min(max(cagr, -0.20), 0.20)


def prompt_rate(label: str, default: float) -> float:
    while True:
        raw = input(f"{label} [{default:.2%}]: ").strip()
        if not raw:
            return default
        try:
            value = float(raw.rstrip("%"))
            if raw.endswith("%") or value > 1:
                value /= 100
            return value
        except ValueError:
            print("Enter a percentage, such as 9% or 0.09.")


def prompt_positive_integer(label: str, default: int) -> int:
    while True:
        raw = input(f"{label} [{default}]: ").strip()
        if not raw:
            return default
        try:
            value = int(raw)
            if value > 0:
                return value
        except ValueError:
            pass
        print("Enter a whole number greater than zero.")


def format_money(value: float | None, currency: str) -> str:
    if value is None:
        return "not available"
    return f"{currency} {value:,.0f}"


def required(value: float | None, name: str) -> float:
    if value is None:
        raise RuntimeError(f"{name} was not returned by the data provider for this ticker.")
    return value


def fetch_inputs(ticker: str) -> dict[str, object]:
    stock = yf.Ticker(ticker)
    info = stock.info or {}
    cashflow = stock.cashflow
    balance_sheet = stock.balance_sheet

    fcf, fcf_label, period_end = statement_value(cashflow, ["Free Cash Flow"])
    if fcf is None:
        # A fallback is deliberately explicit: FCF = operating cash flow + capex.
        operating_cash_flow, _, period_end = statement_value(
            cashflow, ["Operating Cash Flow", "Total Cash From Operating Activities"]
        )
        capex, _, _ = statement_value(cashflow, ["Capital Expenditure", "Capital Expenditures"])
        if operating_cash_flow is not None and capex is not None:
            fcf = operating_cash_flow + capex
            fcf_label = "Operating Cash Flow + Capital Expenditure"

    cash, cash_label, _ = statement_value(
        balance_sheet,
        [
            "Cash Cash Equivalents And Short Term Investments",
            "Cash And Cash Equivalents",
            "Cash Financial",
        ],
    )
    debt, debt_label, _ = statement_value(balance_sheet, ["Total Debt"])
    if debt is None:
        current_debt, _, _ = statement_value(
            balance_sheet, ["Current Debt And Capital Lease Obligation", "Current Debt"]
        )
        long_term_debt, _, _ = statement_value(
            balance_sheet, ["Long Term Debt And Capital Lease Obligation", "Long Term Debt"]
        )
        if current_debt is not None or long_term_debt is not None:
            debt = (current_debt or 0.0) + (long_term_debt or 0.0)
            debt_label = "Current Debt + Long Term Debt"

    price = as_number(stock.fast_info.get("last_price"))
    shares = latest_shares(stock, info)
    currency = str(info.get("currency") or "USD")

    return {
        "ticker": ticker,
        "currency": currency,
        "price": price,
        "fcf_year_t": required(fcf, "Free cash flow"),
        "fcf_period_end": period_end,
        "fcf_source": fcf_label or "Unknown",
        "fcf_growth_suggestion": recent_fcf_growth(cashflow),
        "shares_outstanding": required(shares, "Shares outstanding"),
        "cash": required(cash, "Cash"),
        "cash_source": cash_label or "Unknown",
        "debt": required(debt, "Debt"),
        "debt_source": debt_label or "Unknown",
    }


def write_input_file(data: dict[str, object], filename: Path) -> None:
    """Write a human-readable, C++-friendly key=value file atomically."""
    lines = [
        "# Generated by ticker.py. Monetary values are in the issuer's reporting currency.",
        "# Rates are decimals: 9% is written as 0.09.",
        f"ticker={data['ticker']}",
        f"as_of_date={date.today().isoformat()}",
        f"currency={data['currency']}",
        f"price={data['price']:.10g}" if data["price"] is not None else "price=",
        f"fcf_year_t={data['fcf_year_t']:.10g}",
        f"fcf_final_year={data['fcf_final_year']:.10g}",
        f"forecast_years={data['forecast_years']}",
        f"fcf_forecast_growth_rate={data['fcf_forecast_growth_rate']:.10g}",
        f"discount_rate={data['discount_rate']:.10g}",
        f"terminal_growth_rate={data['terminal_growth_rate']:.10g}",
        f"shares_outstanding={data['shares_outstanding']:.10g}",
        f"cash={data['cash']:.10g}",
        f"debt={data['debt']:.10g}",
        f"fcf_source={data['fcf_source']}",
        f"cash_source={data['cash_source']}",
        f"debt_source={data['debt_source']}",
        "discount_rate_source=user_confirmed_assumption",
        "terminal_growth_rate_source=user_confirmed_assumption",
        "fcf_final_year_source=derived_from_fcf_year_t_and_fcf_forecast_growth_rate",
    ]
    temporary = filename.with_suffix(filename.suffix + ".tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temporary.replace(filename)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch reported DCF inputs for a stock symbol.")
    parser.add_argument("ticker", nargs="?", help="Stock ticker, for example NVDA")
    parser.add_argument("--output", default=str(OUTPUT_FILE), help="Output key=value file")
    args = parser.parse_args()

    ticker = (args.ticker or input("Ticker symbol: ")).strip().upper()
    if not ticker:
        print("A ticker symbol is required.")
        return 2

    try:
        data = fetch_inputs(ticker)
    except Exception as error:
        print(f"Could not build DCF inputs for {ticker}: {error}")
        return 1

    print(f"\n{data['ticker']} — reported inputs")
    print(f"  Free cash flow (year t, {data['fcf_period_end']}): {format_money(data['fcf_year_t'], data['currency'])}")
    print(f"  Shares outstanding: {data['shares_outstanding']:,.0f}")
    print(f"  Cash: {format_money(data['cash'], data['currency'])}")
    print(f"  Debt: {format_money(data['debt'], data['currency'])}")
    print(f"  Latest price: {data['price'] if data['price'] is not None else 'not available'} {data['currency']}")
    print("\nConfirm the DCF assumptions (they are not reported market-data fields).")

    forecast_years = prompt_positive_integer("Forecast years to terminal value", DEFAULT_FORECAST_YEARS)
    forecast_growth = prompt_rate("Annual FCF growth through the forecast", data["fcf_growth_suggestion"])
    discount_rate = prompt_rate("Discount rate (WACC only when FCF is FCFF)", DEFAULT_DISCOUNT_RATE)
    terminal_growth = prompt_rate("Terminal growth rate", DEFAULT_TERMINAL_GROWTH_RATE)

    if discount_rate <= terminal_growth:
        print("Discount rate must be greater than terminal growth rate.")
        return 2

    data.update(
        forecast_years=forecast_years,
        fcf_forecast_growth_rate=forecast_growth,
        discount_rate=discount_rate,
        terminal_growth_rate=terminal_growth,
        fcf_final_year=data["fcf_year_t"] * (1 + forecast_growth) ** forecast_years,
    )
    output = Path(args.output)
    write_input_file(data, output)

    print(f"\nFCF in final forecast year: {format_money(data['fcf_final_year'], data['currency'])}")
    print(f"Saved C++ inputs to: {output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
