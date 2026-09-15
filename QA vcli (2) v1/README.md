to run: use  `py analyse.py`

# QA

Two tools that share a folder:

- **`analyse.py`** — an interactive ticker analysis CLI (below).
- **`ticker.py` + `APE.cpp`** — the DCF pipeline (further down).

## analyse.py — ticker analysis

```powershell
py -m pip install -r requirements.txt
setx FINNHUB_API_KEY "your-key"     # reopen the terminal afterwards
setx MASSIVE_API_KEY "your-key"     # optional; massive.com (formerly Polygon.io)

py analyse.py            # prompt
py analyse.py NVDA       # report, then the prompt
py analyse.py NVDA --live
```

Type a ticker for a full report, or a `:command` for anything else:

| | |
|---|---|
| `AAPL` / `AAPL MSFT NVDA` | report, one or several |
| `:live [TICKERS] [SECS]` | streaming prices and live multiples |
| `:valuation [TICKER]` | DCF, sensitivity grid and reverse DCF |
| `:fields` | every field for the loaded ticker, with its source |
| `:metrics` / `:explain <key>` | what is registered, and what it means |
| `:sources` | providers, priority, and whether each is ready |
| `:group valuation` | one group only |
| `:set <field> <value>` | override a field by hand |
| `:import <path>` | load a CSV/JSON of `field,value` pairs |
| `:refresh` | re-fetch, ignoring caches |
| `:extend` | how to add metrics and providers |

### Where the data comes from

| Provider | Role | Priority |
|---|---|---|
| `yfinance` | Statements, share count, profile, history | 10 |
| `finnhub` | Real-time quote, trade websocket, per-share metrics | 20 |
| `massive` | Live trades/quotes, daily snapshot, ticker details | 20 |
| `imported` | Your own values | 40 |

Highest priority wins per field, so a streaming trade print (promoted to 30)
beats a daily snapshot, and anything you supply beats every vendor. Missing
keys disable a provider rather than breaking the run — `:sources` shows which.

**Plan entitlements matter more than the key.** On Massive's free tier the
websocket does not authenticate on either feed, and `get_snapshot_ticker` /
`get_last_trade` return `NOT_AUTHORIZED`; the provider falls back to ticker
details and the previous-session bar, contributing share count, VWAP and
company data but no live price. Finnhub's free tier does include the trade
websocket, so it carries the live price. `:live` reports which feeds actually
connected and why the others did not.

Every multiple is recomputed from the current price on each refresh, so P/E
moves with the tape instead of freezing at the vendor's daily figure.

### Valuation

`:valuation` runs three things off one set of assumptions.

**A multi-stage DCF.** Forecast N years of free cash flow, discount each back,
add a Gordon growth terminal value, bridge to equity:

```
FCF_t = FCF_0 (1 + g)^t                for t = 1..N
EV    = sum(FCF_t / (1 + r)^t) + TV / (1 + r)^N
TV    = FCF_N (1 + g_T) / (r - g_T)
FV    = (EV + cash - debt) / shares
```

It prints the whole working — the two halves of enterprise value separately,
then the bridge — plus **terminal value dependency**, the share of the answer
that is terminal value. Past roughly 75% the valuation is mostly a claim about
the year after the forecast ends, and the sensitivity grid matters more than
the point estimate.

**FCF stability**, alongside the DCF: FCF CAGR, the sample standard deviation
of year-over-year FCF growth (`growth_volatility`), and how many of the
available years had negative FCF. A -3.95% default growth rate reads very
differently depending on whether it came from a smooth decline or a coin flip
between +80% and -60% years — this panel is what tells you which.

**A sensitivity grid** across discount rate and terminal growth, centred on
your base case rather than a fixed band. It shows whether a fair value is a
robust conclusion or an artefact of two numbers you guessed.

**A reverse DCF**, which is usually the most informative of the three. Rather
than asking what the company is worth, it holds today's price as given and
solves for the FCF growth rate that would justify it, then sets that against
the company's actual historical growth. "Implied 21% vs historical 12%" is a
falsifiable claim about the market's expectations; "23% undervalued" is not.

Assumptions resolve **override → history → default**, and the report labels
which rung each one came from so a default never reads as a fact:

```text
:set discount_rate 0.09          9, 9% and 0.09 all mean the same thing
:set terminal_growth_rate 0.025
:set fcf_growth_rate 0.12        defaults to the historical FCF CAGR
:set forecast_years 10
```

The historical CAGR is clamped to [-20%, +30%] when used as a *default* — a
company coming off a trough year can print a 190% CAGR that is an artefact, not
a forecast — and the report marks it `historical, clamped` when that bites. An
explicit `:set` is never clamped.

The models live in `qa/valuation/` (`dcf.py`, `gordon_growth.py`,
`sensitivity.py`, `reverse_dcf.py`), each taking the same two arguments:
`Inputs` (what the company is) and `Assumptions` (what you believe). Adding a
model is a new file, and the metrics in `qa/metrics/custom.py` stay thin
wrappers over it.

### Valuation roadmap

Not built yet, in rough priority order:

- **Assumption diagnostics as explicit warnings.** Terminal dependency and
  clamped-CAGR sources are already shown (color-coded, `(historical, clamped)`
  labels), but there's no single WARNING-style block that calls out e.g.
  "forecast growth is derived from declining historical FCF" in plain text
  before the numbers. Mostly a `render.py` job — the underlying data
  (`terminal_dependency`, `assumptions.sources`, `fcf_stability`) already
  exists.
- **Reorder `:valuation` to lead with the reverse DCF.** Current price → DCF
  upside → reverse-DCF implied growth vs. historical, before the full forecast
  working. Small change in `valuation_report()`; no new maths.
- **A blended default growth rate.** Weight FCF CAGR against revenue and EPS
  CAGR (`g = w1*g_fcf + w2*g_revenue + w3*g_earnings`) instead of defaulting
  to FCF CAGR alone — FCF is the noisiest of the three and can send a
  misleading default. Needs revenue/EPS annual series pulled the same way
  `free_cash_flow` is (see `historical_fcf_growth` in
  `qa/valuation/common.py`), plus a decision on the weights and how to handle
  a missing signal.
- **Bear/base/bull scenarios.** A named `Assumptions` per case, run through the
  same `discounted_cash_flow()` unchanged — the engine already takes
  `Assumptions` as data, so this is purely a new `qa/valuation/scenarios.py`
  plus a comparison table in `render.py`, not an engine change.

### Adding your own maths

Edit `qa/metrics/custom.py`. One decorated function is the whole job:

```python
@metric("fcf_yield_x", label="FCF yield", group="Custom",
        fmt="percent", needs=("free_cash_flow", "market_cap"))
def fcf_yield_x(f):
    return f.num("free_cash_flow") / f.num("market_cap") * 100
```

`needs` names the fields you divide by; anything listed is guaranteed
non-`None` inside the function, and a ticker missing one skips the metric
instead of raising. Any new `.py` file in `qa/metrics/` is picked up
automatically. `qa/metrics/builtin.py` has ~30 worked examples.

Need a field no feed carries? `:set my_field 1234`, or put it in
`data/<TICKER>.csv` as `field,value` lines (`k`/`m`/`b`/`t` suffixes and `%`
are understood). `data/_shared.json` applies to every ticker.

### Adding a data source

Drop a file in `qa/providers/`:

```python
@provider
class MyFeed(Provider):
    name, kind, priority = "myfeed", "longterm", 15

    def fetch(self, ticker):
        return self.pack({"revenue": 1234.0})
```

It is discovered on import — no list to update.

> Never name a file in the project root `massive.py`: it shadows the installed
> `massive` package and silently disables that provider.

## DCF pipeline

`ticker.py` retrieves the latest annual free cash flow, cash, debt and share-count data available through Yahoo Finance for a ticker, then asks you to confirm the DCF assumptions. It writes `dcf_inputs.txt`, a plain `key=value` file that `APE.cpp` reads.

```powershell
py -m pip install -r requirements.txt
py ticker.py NVDA
g++ -std=c++17 -O2 APE.cpp -o APE.exe
.\APE.exe dcf_inputs.txt
```

Use `py ticker.py NVDA --output nvda_dcf.txt` to retain a separate input file for each company, then run `.\APE.exe nvda_dcf.txt`. `example_dcf_inputs.txt` contains made-up data you can use to test the C++ build immediately: `.\APE.exe example_dcf_inputs.txt`.

The reported inputs are free cash flow in year *t*, cash, debt and shares outstanding. The script labels its reported-source fields in `dcf_inputs.txt`. These need analyst judgment:

- `discount_rate`: the required return. Use WACC only if you have converted cash flow to FCFF; use a cost-of-equity rate for FCFE. The 9% default is a starting assumption, not a quote.
- `terminal_growth_rate`: the perpetual post-forecast growth rate. The 2.5% default is a conservative starting assumption, not company data.
- `fcf_final_year`: calculated as `fcf_year_t × (1 + fcf_forecast_growth_rate)^forecast_years`.

`APE.cpp` calculates the present value of each forecast year's FCF, terminal value using the Gordon growth formula, enterprise value, equity value, and implied value per share. The values must share one currency and scale; Yahoo Finance normally returns both financial statement amounts and shares as raw units. The enterprise-to-equity bridge (`+ cash − debt`) is appropriate for an FCFF/WACC valuation; do not apply it to FCFE without changing the model.

This is a screen-grade DCF. Verify annual filing values, diluted shares, lease/convertible debt, non-operating investments, tax treatment, and the WACC before using it for an investment decision.
