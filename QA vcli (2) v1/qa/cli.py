"""The interactive analyst prompt.

Type a ticker for a full report; type a `:command` for everything else.
"""

from __future__ import annotations

import argparse
import time
from typing import Any

from rich.live import Live
from rich.text import Text

from . import config, providers, render, valuation
from .models import Fact, Facts, Series
from .providers.base import all_providers, collect, collect_series, get_provider
from .registry import all_metrics, get_metric, load_metric_modules

console = render.console

HELP = """
[bold]Analysing[/bold]
  AAPL                 full report for a ticker
  AAPL MSFT NVDA       compare several side by side
  :live [TICKERS]      stream live prices and live multiples (Ctrl-C to stop)
  :valuation [TICKER]  DCF, sensitivity grid and reverse DCF
  :refresh             re-fetch, ignoring every cache

[bold]Valuation assumptions[/bold]  [dim](override -> history -> default)[/dim]
  :set discount_rate 0.09          9, 9% and 0.09 all mean the same
  :set terminal_growth_rate 0.025
  :set fcf_growth_rate 0.12        defaults to the historical FCF CAGR
  :set forecast_years 10

[bold]Inspecting[/bold]
  :fields              every field available for the loaded ticker, with source
  :metrics             every registered metric
  :explain <key>       what a metric means and what it needs
  :sources             providers, priority, and whether they are ready
  :group <name>        show one group only (valuation, profitability, ...)

[bold]Your own data[/bold]
  :set <field> <value> override a field for the loaded ticker
  :unset <field>       drop that override
  :import <path>       load a CSV/JSON of field,value pairs

[bold]Session[/bold]
  :help                this text
  :quit                exit
"""

EXTENDING = """
[bold]Add a metric[/bold]  ->  edit [cyan]qa/metrics/custom.py[/cyan]

    @metric("my_ratio", label="My ratio", group="Custom",
            fmt="ratio", needs=("free_cash_flow", "total_debt"))
    def my_ratio(f):
        return f.num("free_cash_flow") / f.num("total_debt")

Save and rerun — it is registered automatically. Any new .py file in that
folder works the same way.

[bold]Add a data source[/bold]  ->  new file in [cyan]qa/providers/[/cyan]

    @provider
    class MyFeed(Provider):
        name, kind, priority = "myfeed", "longterm", 15
        def fetch(self, ticker):
            return self.pack({"revenue": 1234.0})

Higher priority wins when two providers supply the same field.
"""


class Session:
    """Holds what the prompt is currently looking at."""

    def __init__(self) -> None:
        providers.load_all()
        load_metric_modules()
        self.tickers: list[str] = []
        self.facts: dict[str, Facts] = {}
        self.series: dict[str, dict[str, Series]] = {}
        self.warnings: list[str] = []

    # -- data -------------------------------------------------------------

    def load(self, tickers: list[str], *, refresh: bool = False) -> None:
        if refresh:
            for prov in all_providers():
                invalidate = getattr(prov, "invalidate", None)
                if callable(invalidate):
                    invalidate()
        self.tickers = [t.upper() for t in tickers]
        self.facts = {}
        self.series = {}
        self.warnings = []
        for ticker in self.tickers:
            with console.status(f"fetching {ticker}...", spinner="dots"):
                facts, warnings = collect(ticker)
                series = collect_series(ticker)
            # The DCF defaults its growth rate to the company's own record, so
            # derive it once here rather than re-reading statements per metric.
            growth = valuation.historical_fcf_growth(series)
            if growth is not None:
                facts.add(
                    "fcf_growth_historical",
                    Fact(value=growth, source="derived", priority=config.PRIORITY_LONGTERM),
                )
            self.facts[ticker] = facts
            self.series[ticker] = series
            self.warnings.extend(warnings)

    @property
    def current(self) -> Facts | None:
        return self.facts.get(self.tickers[0]) if self.tickers else None

    def report(self) -> None:
        if not self.tickers:
            console.print("[yellow]No ticker loaded.[/yellow]")
            return
        for ticker in self.tickers:
            facts = self.facts[ticker]
            if len(facts) <= 1:
                console.print(f"[yellow]{ticker}: no data returned — check the symbol.[/yellow]")
                continue
            series = self.series.get(ticker, {}) if len(self.tickers) == 1 else {}
            render.report(facts, series, self.warnings)

    # -- valuation --------------------------------------------------------

    def valuation(self, args: list[str]) -> None:
        """`:valuation [TICKER]` — the DCF, its sensitivity, and the reverse DCF."""
        if args:
            self.load(args)
        if not self.tickers:
            console.print("[yellow]Give a ticker first.[/yellow]")
            return

        ticker = self.tickers[0]
        facts = self.facts[ticker]

        inputs = valuation.Inputs.from_facts(facts)
        if inputs is None:
            console.print(
                "[yellow]Need free_cash_flow and shares_outstanding to value this.[/yellow]\n"
                "[dim]Check :fields, then :set free_cash_flow 1.2b if the feed lacks it.[/dim]"
            )
            return
        if inputs.starting_fcf <= 0:
            console.print(
                f"[yellow]{ticker} free cash flow is "
                f"{render.format_value(inputs.starting_fcf, 'money')} — a DCF on negative "
                "cash flow is meaningless.[/yellow]\n"
                "[dim]Override a normalised figure with :set free_cash_flow <value>.[/dim]"
            )
            return

        historical = facts.num("fcf_growth_historical")
        assumptions = valuation.Assumptions.resolve(facts, historical_growth=historical)
        if not assumptions.valid:
            console.print(f"[yellow]{assumptions.invalid_reason()}[/yellow]")
            return

        result = valuation.discounted_cash_flow(inputs, assumptions)
        if result is None:
            console.print("[yellow]The DCF could not be computed from these inputs.[/yellow]")
            return

        grid = valuation.sensitivity_grid(inputs, assumptions)
        price = facts.num("price")
        reverse = (
            valuation.reverse_dcf(inputs, assumptions, price, historical_growth=historical)
            if price
            else None
        )
        stability = valuation.fcf_stability(self.series.get(ticker, {}))
        render.valuation_report(ticker, result, grid, reverse, price, stability)
        if price and reverse is None:
            console.print(
                "[dim]Reverse DCF: no growth rate between -90% and +300% reaches "
                "today's price, so there is nothing honest to report.[/dim]\n"
            )

    # -- live -------------------------------------------------------------

    def live(self, tickers: list[str], interval: float) -> None:
        tickers = [t.upper() for t in tickers] or self.tickers
        if not tickers:
            console.print("[yellow]Give a ticker first.[/yellow]")
            return

        streamers = [
            prov for prov in all_providers()
            if prov.available() and hasattr(prov, "start_live")
        ]
        connected = []
        for prov in streamers:
            try:
                if prov.start_live(tickers):
                    connected.append(prov.name)
                else:
                    stream = getattr(prov, "_stream", None)
                    reason = getattr(stream, "error", None) or "no live entitlement"
                    console.print(f"[yellow]{prov.name}: {reason}[/yellow]")
            except Exception as exc:
                console.print(f"[yellow]{prov.name}: {exc}[/yellow]")

        if connected:
            console.print(f"[green]streaming[/green] via {', '.join(connected)} · Ctrl-C to stop")
        else:
            console.print("[yellow]No live stream connected; polling snapshots instead.[/yellow]")

        # Live mode shows the multiples that actually move with the price.
        shown = [m for m in all_metrics() if m.key in ("pe_ttm", "pe_forward", "pb", "ps", "market_cap")]

        def tick() -> Any:
            return render.live_table([(collect(t)[0], shown) for t in tickers])

        interval = max(interval, 1.0)
        try:
            if console.is_terminal:
                with Live(console=console, refresh_per_second=4, transient=False) as live:
                    while True:
                        live.update(tick())
                        time.sleep(interval)
            else:
                # Live redraws in place, which a pipe or a redirect never shows.
                # Fall back to one printed block per tick so piped output works.
                while True:
                    console.print(tick())
                    console.print(Text("-" * 60, style=render.DIM))
                    time.sleep(interval)
        except KeyboardInterrupt:
            console.print("[dim]stopped[/dim]")
        finally:
            for prov in streamers:
                stop = getattr(prov, "stop_live", None)
                if callable(stop):
                    stop()

    # -- commands ---------------------------------------------------------

    def command(self, line: str) -> bool:
        """Run a `:command`. Returns False to quit."""
        parts = line[1:].split()
        if not parts:
            return True
        name, args = parts[0].lower(), parts[1:]

        if name in ("quit", "exit", "q"):
            return False
        if name in ("help", "h", "?"):
            console.print(HELP)
        elif name in ("extend", "extending"):
            console.print(EXTENDING)
        elif name == "live":
            interval = config.LIVE_INTERVAL
            symbols = []
            for arg in args:
                if arg.replace(".", "").isdigit():
                    interval = float(arg)
                else:
                    symbols.append(arg)
            self.live(symbols, interval)
        elif name in ("valuation", "value", "dcf"):
            self.valuation(args)
        elif name == "refresh":
            self.load(self.tickers, refresh=True)
            self.report()
        elif name == "fields":
            facts = self.current
            if facts is None:
                console.print("[yellow]Load a ticker first.[/yellow]")
            else:
                console.print(render.fields_table(facts))
        elif name == "metrics":
            console.print(render.metrics_table())
        elif name == "sources":
            console.print(render.providers_table(all_providers()))
        elif name == "explain":
            self._explain(args)
        elif name == "group":
            self._group(args)
        elif name == "set":
            self._set(args)
        elif name == "unset":
            self._unset(args)
        elif name == "import":
            self._import(args)
        else:
            console.print(f"[yellow]Unknown command :{name} — try :help[/yellow]")
        return True

    def _explain(self, args: list[str]) -> None:
        if not args:
            console.print("[yellow]Usage: :explain <metric key>[/yellow]")
            return
        metric = get_metric(args[0])
        if metric is None:
            console.print(f"[yellow]No metric named {args[0]} — see :metrics[/yellow]")
            return
        console.print(f"\n[bold cyan]{metric.key}[/bold cyan]  {metric.label}  [dim]({metric.group})[/dim]")
        console.print(metric.about or "[dim]no description[/dim]")
        console.print(f"[dim]needs: {', '.join(metric.needs) or 'nothing in particular'}[/dim]")
        facts = self.current
        if facts is not None:
            value = metric.compute(facts)
            console.print(f"[dim]{facts.ticker}:[/dim] {render.format_value(value, metric.fmt)}\n")

    def _group(self, args: list[str]) -> None:
        facts = self.current
        if facts is None or not args:
            console.print("[yellow]Usage: :group <name>, with a ticker loaded.[/yellow]")
            return
        panels = render.metrics_panels(facts, only_group=args[0])
        if not panels:
            console.print(f"[yellow]Nothing in group {args[0]}.[/yellow]")
            return
        for panel in panels:
            console.print(panel)

    def _imported(self) -> Any:
        return get_provider("imported")

    def _set(self, args: list[str]) -> None:
        if len(args) < 2 or not self.tickers:
            console.print("[yellow]Usage: :set <field> <value>, with a ticker loaded.[/yellow]")
            return
        value = self._imported().set(self.tickers[0], args[0], " ".join(args[1:]))
        console.print(f"[green]set[/green] {self.tickers[0]}.{args[0]} = {value}")
        self.load(self.tickers)

    def _unset(self, args: list[str]) -> None:
        if not args or not self.tickers:
            console.print("[yellow]Usage: :unset <field>[/yellow]")
            return
        self._imported().clear(self.tickers[0], args[0])
        console.print(f"[green]cleared[/green] {args[0]}")
        self.load(self.tickers)

    def _import(self, args: list[str]) -> None:
        if not args or not self.tickers:
            console.print("[yellow]Usage: :import <path.csv|.json>, with a ticker loaded.[/yellow]")
            return
        try:
            count = self._imported().load(args[0], self.tickers[0])
        except Exception as exc:
            console.print(f"[red]{exc}[/red]")
            return
        console.print(f"[green]imported[/green] {count} fields into {self.tickers[0]}")
        self.load(self.tickers)


def banner() -> None:
    console.print()
    console.print(Text("  QA — ticker analysis", style="bold bright_cyan"))
    console.print(
        Text("  massive + finnhub for live · yfinance for long-term", style=render.DIM)
    )
    console.print(Text("  type a ticker, or :help · :sources · :extend", style=render.DIM))
    console.print()


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Interactive ticker analysis.")
    parser.add_argument("tickers", nargs="*", help="analyse these immediately")
    parser.add_argument("--live", action="store_true", help="go straight into live mode")
    parser.add_argument("--interval", type=float, default=config.LIVE_INTERVAL)
    parser.add_argument("--once", action="store_true", help="print one report and exit")
    args = parser.parse_args(argv)

    session = Session()

    if args.tickers:
        session.load(args.tickers)
        if args.live:
            session.live(args.tickers, args.interval)
            return 0
        session.report()
        if args.once:
            return 0
    else:
        banner()

    while True:
        try:
            line = console.input("[bold bright_cyan]ticker[/bold bright_cyan] [dim]>[/dim] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            return 0
        if not line:
            continue
        if line.startswith(":"):
            if not session.command(line):
                return 0
            continue
        session.load(line.replace(",", " ").split())
        session.report()
