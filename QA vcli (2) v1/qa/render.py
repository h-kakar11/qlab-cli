"""Terminal rendering, built on `rich`.

Number formatting lives in `FORMATTERS`. To add a format, add an entry there
and pass its name as `fmt=` on your metric.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Callable

from rich.columns import Columns
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .models import Facts, Series
from .registry import Metric, all_metrics

console = Console()

DIM = "grey58"
ACCENT = "bright_cyan"
GOOD = "bright_green"
BAD = "bright_red"


def _money(value: float) -> str:
    for cutoff, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(value) >= cutoff:
            return f"{value / cutoff:,.2f}{suffix}"
    return f"{value:,.0f}"


FORMATTERS: dict[str, Callable[[float], str]] = {
    "ratio": lambda v: f"{v:,.2f}",
    "percent": lambda v: f"{v:,.2f}%",
    "signed_percent": lambda v: f"{v:+,.2f}%",
    # A difference between two rates is percentage points, not a percentage.
    "signed_pp": lambda v: f"{v:+,.2f}pp",
    "money": _money,
    "count": lambda v: f"{v:,.0f}",
    "price": lambda v: f"{v:,.2f}",
    "plain": lambda v: f"{v:g}",
}


def format_value(value: float | None, fmt: str = "ratio") -> str:
    if value is None or not math.isfinite(value):
        return "—"
    return FORMATTERS.get(fmt, FORMATTERS["ratio"])(value)


def _tone(metric: Metric, value: float | None) -> str:
    """Green/red only where a sign genuinely means better or worse."""
    if value is None:
        return ""
    if metric.fmt == "signed_percent":
        return GOOD if value > 0 else BAD if value < 0 else ""
    return ""


def header_panel(facts: Facts, warnings: list[str]) -> Panel:
    price = facts.num("price")
    previous = facts.num("previous_close")
    change = (price / previous - 1.0) * 100.0 if price and previous else None

    title = Text()
    title.append(facts.ticker, style=f"bold {ACCENT}")
    name = facts.get("name")
    if name:
        title.append(f"  {name}", style="bold white")

    line = Text()
    if price is not None:
        line.append(f"{price:,.2f}", style="bold white")
        currency = facts.get("currency")
        if currency:
            line.append(f" {str(currency).upper()}", style=DIM)
    else:
        line.append("no price", style=DIM)
    if change is not None:
        line.append("   ")
        line.append(f"{change:+.2f}%", style=GOOD if change >= 0 else BAD)
    line.append(f"   via {facts.source_of('price')}", style=DIM)

    meta_bits = [
        str(facts.get(key))
        for key in ("exchange", "sector", "industry", "country")
        if facts.get(key)
    ]
    body = [line]
    if meta_bits:
        body.append(Text(" · ".join(meta_bits), style=DIM))
    for warning in warnings:
        body.append(Text(f"! {warning}", style="yellow"))

    return Panel(Group(*body), title=title, border_style=ACCENT, padding=(0, 2))


def metrics_panels(facts: Facts, *, only_group: str | None = None) -> list[Panel]:
    """One panel per metric group; empty groups are dropped."""
    grouped: dict[str, list[tuple[Metric, float | None]]] = {}
    for metric in all_metrics():
        if only_group and metric.group.lower() != only_group.lower():
            continue
        grouped.setdefault(metric.group, []).append((metric, metric.compute(facts)))

    panels: list[Panel] = []
    for group, rows in grouped.items():
        if not any(value is not None for _, value in rows):
            continue
        table = Table.grid(padding=(0, 2))
        table.add_column(style=DIM, no_wrap=True)
        table.add_column(justify="right", no_wrap=True)
        for metric, value in rows:
            table.add_row(
                metric.label,
                Text(format_value(value, metric.fmt), style=_tone(metric, value) or "white"),
            )
        panels.append(Panel(table, title=Text(group, style="bold"), border_style=DIM, padding=(0, 1)))
    return panels


def history_panel(series: dict[str, Series], limit: int = 5) -> Panel | None:
    if not series:
        return None
    periods: list[str] = []
    for item in series.values():
        if item.periods:
            periods = item.periods[:limit]
            break
    if not periods:
        return None

    table = Table(box=None, pad_edge=False, expand=False)
    table.add_column("", style=DIM, no_wrap=True)
    for period in periods:
        table.add_column(period[:7], justify="right", no_wrap=True)

    for name, item in series.items():
        label = name.replace("_", " ").capitalize()
        cells = [format_value(v, "money") for v in item.values[:limit]]
        cells += ["—"] * (len(periods) - len(cells))
        table.add_row(label, *cells)

    return Panel(table, title=Text("History (annual)", style="bold"), border_style=DIM, padding=(0, 1))


def report(facts: Facts, series: dict[str, Series], warnings: list[str]) -> None:
    console.print()
    console.print(header_panel(facts, warnings))
    panels = metrics_panels(facts)
    if panels:
        console.print(Columns(panels, equal=False, expand=False))
    history = history_panel(series)
    if history:
        console.print(history)
    console.print(
        Text(f"{len(facts)} fields · {datetime.now():%H:%M:%S} · :help for commands", style=DIM)
    )
    console.print()


def fields_table(facts: Facts) -> Table:
    table = Table(title=f"{facts.ticker} — fields", box=None, pad_edge=False)
    table.add_column("field", style=ACCENT, no_wrap=True)
    table.add_column("value", justify="right")
    table.add_column("source", style=DIM, no_wrap=True)
    for name, fact in facts:
        number = fact.number
        shown = format_value(number, "money" if abs(number) >= 1e6 else "ratio") if number is not None else str(fact.value)
        if len(shown) > 60:
            shown = shown[:57] + "..."
        table.add_row(name, shown, fact.source)
    return table


def metrics_table() -> Table:
    table = Table(title="Registered metrics", box=None, pad_edge=False)
    table.add_column("key", style=ACCENT, no_wrap=True)
    table.add_column("label", no_wrap=True)
    table.add_column("group", style=DIM, no_wrap=True)
    table.add_column("needs", style=DIM)
    for metric in all_metrics():
        table.add_row(metric.key, metric.label, metric.group, ", ".join(metric.needs) or "—")
    return table


def providers_table(providers) -> Table:
    table = Table(title="Data sources", box=None, pad_edge=False)
    table.add_column("provider", style=ACCENT, no_wrap=True)
    table.add_column("kind", no_wrap=True)
    table.add_column("priority", justify="right", style=DIM)
    table.add_column("status", no_wrap=True)
    table.add_column("what it supplies", style=DIM)
    for prov in providers:
        ok = prov.available()
        table.add_row(
            prov.name,
            prov.kind,
            str(prov.priority),
            Text("ready", style=GOOD) if ok else Text(prov.unavailable_reason(), style="yellow"),
            prov.describe,
        )
    return table


def _rate(value: float) -> str:
    return f"{value * 100:,.2f}%"


def _note(assumptions, name: str) -> Text:
    """Where an assumption came from, so a default never reads as a fact."""
    origin = assumptions.sources.get(name, "")
    style = {"set": ACCENT, "historical": GOOD}.get(origin, DIM)
    if origin.startswith("historical,"):
        style = "yellow"
    return Text(f"({origin})" if origin else "", style=style)


def valuation_panel(result, price: float | None) -> Panel:
    """The DCF, with its working shown."""
    table = Table.grid(padding=(0, 2))
    table.add_column(style=DIM, no_wrap=True)
    table.add_column(justify="right", no_wrap=True)
    table.add_column(no_wrap=True)

    assumptions = result.assumptions
    inputs = result.inputs

    def row(label: str, value: str, note: Text | str = "", style: str = "white") -> None:
        table.add_row(label, Text(value, style=style), note)

    row("Current price", format_value(price, "price") if price else "—")
    row("Starting FCF", _money(inputs.starting_fcf))
    row("FCF growth", _rate(assumptions.fcf_growth), _note(assumptions, "fcf_growth_rate"))
    row(
        "Forecast period",
        f"{assumptions.forecast_years} years",
        _note(assumptions, "forecast_years"),
    )
    row("Discount rate", _rate(assumptions.discount_rate), _note(assumptions, "discount_rate"))
    row(
        "Terminal growth",
        _rate(assumptions.terminal_growth),
        _note(assumptions, "terminal_growth_rate"),
    )

    table.add_row("", "", "")
    row("PV of forecast FCF", _money(result.pv_forecast))
    row("PV of terminal value", _money(result.pv_terminal))
    row("Enterprise value", _money(result.enterprise_value))
    row("+ Cash", _money(inputs.cash))
    row("- Debt", _money(inputs.debt))
    row("Equity value", _money(result.equity_value))
    row("/ Shares outstanding", _money(inputs.shares))

    table.add_row("", "", "")
    row("DCF fair value", format_value(result.fair_value, "price"), "", f"bold {ACCENT}")

    upside = result.upside(price)
    if upside is not None:
        row(
            "Upside / (downside)",
            f"{upside:+,.2f}%",
            "",
            f"bold {GOOD if upside >= 0 else BAD}",
        )

    dependency = result.terminal_dependency
    if dependency is not None:
        # Past ~75% the answer is mostly an opinion about the year after the
        # forecast ends, which the reader should see before acting on it.
        tone = GOOD if dependency < 60 else "yellow" if dependency < 80 else BAD
        hint = "" if dependency < 80 else "assumption-driven"
        row("Terminal value dependency", f"{dependency:,.1f}%", Text(hint, style=BAD), tone)

    return Panel(
        table,
        title=Text("DCF valuation", style="bold"),
        border_style=ACCENT,
        padding=(0, 2),
    )


def fcf_stability_panel(stability) -> Panel:
    """Context for the growth assumption: a smooth climb or a coin flip?"""
    table = Table.grid(padding=(0, 2))
    table.add_column(style=DIM, no_wrap=True)
    table.add_column(justify="right", no_wrap=True)

    table.add_row(
        "FCF CAGR",
        Text(_rate(stability.cagr) if stability.cagr is not None else "—", style="white"),
    )

    if stability.growth_volatility is not None:
        volatility = stability.growth_volatility
        tone = GOOD if volatility < 0.15 else "yellow" if volatility < 0.35 else BAD
        table.add_row("FCF growth volatility", Text(_rate(volatility), style=tone))
    else:
        table.add_row("FCF growth volatility", Text("—", style=DIM))

    negative_tone = GOOD if stability.negative_years == 0 else BAD
    table.add_row(
        "Negative FCF years",
        Text(f"{stability.negative_years}/{stability.total_years}", style=negative_tone),
    )

    return Panel(
        table,
        title=Text("FCF stability", style="bold"),
        border_style=DIM,
        padding=(0, 2),
    )


def sensitivity_panel(grid) -> Panel:
    """Fair value across the two least knowable inputs."""
    table = Table(box=None, pad_edge=False, expand=False)
    table.add_column("r \\ g", style=DIM, no_wrap=True)
    for growth in grid.terminal_growths:
        table.add_column(_rate(growth), justify="right", no_wrap=True)

    for rate, row in zip(grid.discount_rates, grid.values):
        cells = [Text(_rate(rate), style=DIM)]
        for growth, value in zip(grid.terminal_growths, row):
            if value is None:
                cells.append(Text("—", style=DIM))
                continue
            base = grid.is_base(rate, growth)
            cells.append(
                Text(
                    format_value(value, "price"),
                    style=f"bold {ACCENT}" if base else "white",
                )
            )
        table.add_row(*cells)

    body: list[Any] = [table]
    spread = grid.spread()
    if spread:
        low, high = spread
        body.append(
            Text(
                f"range {format_value(low, 'price')} – {format_value(high, 'price')}"
                f"   ·   base case highlighted",
                style=DIM,
            )
        )

    return Panel(
        Group(*body),
        title=Text("Sensitivity — discount rate vs terminal growth", style="bold"),
        border_style=DIM,
        padding=(0, 2),
    )


def reverse_dcf_panel(rev) -> Panel:
    """What growth the current price already assumes."""
    table = Table.grid(padding=(0, 2))
    table.add_column(style=DIM, no_wrap=True)
    table.add_column(justify="right", no_wrap=True)

    table.add_row("Current price", Text(format_value(rev.price, "price"), style="white"))
    table.add_row(
        "Implied FCF growth",
        Text(_rate(rev.implied_growth), style=f"bold {ACCENT}"),
    )
    table.add_row("Discount rate", Text(_rate(rev.assumptions.discount_rate), style=DIM))
    table.add_row("Terminal growth", Text(_rate(rev.assumptions.terminal_growth), style=DIM))
    table.add_row("Forecast period", Text(f"{rev.assumptions.forecast_years} years", style=DIM))

    body: list[Any] = [table]
    if rev.historical_growth is not None:
        table.add_row("", "")
        table.add_row(
            "Historical FCF growth",
            Text(_rate(rev.historical_growth), style="white"),
        )
        gap = rev.gap
        if gap is not None:
            table.add_row(
                "Implied vs historical",
                Text(f"{gap:+,.1f}pp", style=BAD if gap > 0 else GOOD),
            )
            verdict = (
                "the price assumes better than the track record"
                if gap > 0
                else "the price assumes less than the track record"
            )
            body.append(Text(verdict, style=DIM))

    return Panel(
        Group(*body),
        title=Text("Reverse DCF — what the price implies", style="bold"),
        border_style=DIM,
        padding=(0, 2),
    )


def valuation_report(
    ticker: str, result, grid, rev, price: float | None, stability=None
) -> None:
    console.print()
    console.print(Text(f"  {ticker} — valuation", style=f"bold {ACCENT}"))
    console.print()
    console.print(valuation_panel(result, price))
    if stability is not None:
        console.print(fcf_stability_panel(stability))
    if grid is not None:
        console.print(sensitivity_panel(grid))
    if rev is not None:
        console.print(reverse_dcf_panel(rev))
    console.print(
        Text("  :set discount_rate 0.09 · :set fcf_growth_rate 0.12 · :set forecast_years 10", style=DIM)
    )
    console.print()


def live_table(rows: list[tuple[Facts, list[Metric]]]) -> Table:
    """Compact one-row-per-ticker view for live mode."""
    table = Table(box=None, pad_edge=False, expand=False)
    table.add_column("ticker", style=f"bold {ACCENT}", no_wrap=True)
    table.add_column("price", justify="right", no_wrap=True)
    table.add_column("chg", justify="right", no_wrap=True)
    table.add_column("src", style=DIM, no_wrap=True)

    metrics = rows[0][1] if rows else []
    for metric in metrics:
        table.add_column(metric.label, justify="right", no_wrap=True)

    for facts, shown in rows:
        price = facts.num("price")
        previous = facts.num("previous_close")
        change = (price / previous - 1.0) * 100.0 if price and previous else None
        cells = [
            facts.ticker,
            format_value(price, "price"),
            Text(format_value(change, "signed_percent"), style=GOOD if (change or 0) >= 0 else BAD),
            facts.source_of("price"),
        ]
        cells += [format_value(m.compute(facts), m.fmt) for m in shown]
        table.add_row(*cells)
    return table
