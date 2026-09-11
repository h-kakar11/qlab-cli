# QLAB CLI

A command-line quantitative market analysis tool that combines data from multiple market-data providers to produce real-time market information, valuation analysis, financial metrics, technical analysis, analyst estimates, peer comparisons, and more.

## What is QLAB CLI?

QLAB CLI is a command-line interface for analysing publicly traded companies using extensive financial and market data.

It combines data from multiple providers, prioritises sources, calculates quantitative metrics, and exposes the results through a simple CLI.

The goal is to provide a single interface for:

* Company and financial analysis
* Real-time market data
* Valuation
* DCF analysis
* Fair-value estimation
* Technical analysis
* Analyst estimates
* Comparable-company analysis
* Scenario and stress testing
* Custom data overrides

---

## Data Sources

QLAB uses multiple providers so that different types of data can come from the most appropriate source.

| Provider   | Role                                                                    | Priority |
| ---------- | ----------------------------------------------------------------------- | -------: |
| `yfinance` | Annual & quarterly financial statements, daily OHLCV, analyst estimates |       10 |
| `finnhub`  | Real-time quotes, trade WebSocket, per-share metrics, peer discovery    |       20 |
| `massive`  | Live trades/quotes, daily snapshots, ticker details                     |       20 |
| `imported` | User-provided values                                                    |       40 |

### Data priority

Providers are assigned priorities when multiple sources can provide the same field.

User-imported data has the highest priority, allowing you to override API-provided values when required.

---

## Requirements

* Python 3
* A Finnhub API key
* A Massive API key

Python dependencies are installed through `requirements.txt`.

### API Keys

#### Finnhub

A free Finnhub API key can be obtained here:

[Finnhub API Key Registration](https://finnhub.io/register?utm_source=chatgpt.com)

#### Massive

A free Massive API key can be obtained here:

[Massive API Keys](https://massive.com/dashboard/keys?utm_source=chatgpt.com)

---

## Installation

### 1. Clone or download the repository

Install the repository into any directory on your computer.

### 2. Open PowerShell

Navigate to the root directory of the repository:

```powershell
cd "C:\the directory you chose"
```

Make sure you are in the repository root before continuing.

### 3. Install dependencies

```powershell
py -m pip install -r requirements.txt
```

### 4. Configure your API keys

Set your Finnhub API key:

```powershell
setx FINNHUB_API_KEY "your-key"
```

Set your Massive API key:

```powershell
setx MASSIVE_API_KEY "your-key"
```

**Close and reopen PowerShell after running `setx`** so that the environment variables become available.

---

## Running QLAB

From the repository root, run:

```powershell
py analyse.py
```

QLAB will prompt you for a ticker.

For example:

```text
Enter ticker: NVDA
```

Enter the market symbol of the company you want to analyse.

QLAB will then load the available data and perform the relevant analysis.

---

## What You Can Do

QLAB currently provides access to a range of quantitative analysis tools, including:

* DCF valuation
* Growth assumptions
* Intrinsic valuation models
* Relative valuation
* Fair-value frameworks
* Sensitivity analysis
* Reverse DCF
* Scenario analysis
* Stress testing
* Technical analysis
* Analyst estimates
* Comparable-company analysis
* Real-time market data
* Custom data overrides
* Provider and data-source inspection

The analysis available for a ticker depends on the data provided by the configured sources.

---

# Commands

QLAB provides several commands for analysing and inspecting a loaded ticker.

### Basic analysis

```text
(ticker)
```

General information and analysis for the specified market symbol.

Example:

```text
NVDA
```

---

### Live data

```text
:live (ticker)
```

Stream prices and live multiples.

You can optionally specify the refresh interval in seconds:

```text
:live (ticker) [integer seconds]
```

Example:

```text
:live NVDA 5
```

You can also use:

```text
(ticker) --live
```

or:

```text
(ticker) --live --interval n
```

where `n` is the interval in seconds.

---

### Valuation

```text
:valuation (ticker)
```

Runs valuation analysis including:

* DCF
* Sensitivity grid
* Reverse DCF

Example:

```text
:valuation NVDA
```

---

### Verbose analysis

```text
:verbose (ticker)
```

Runs the available analysis represented in `ideas.md`.

Implemented ideas are computed, while unavailable functionality is honestly reported as `n/a`.

Example:

```text
:verbose NVDA
```

---

### Technical analysis

```text
:technicals (ticker)
```

Returns technical analysis based on daily market data, including:

* Returns
* Risk
* Trends
* Indicators

Example:

```text
:technicals NVDA
```

---

### Analyst estimates

```text
:estimates (ticker)
```

Returns available analyst information, including:

* Consensus estimates
* Estimate revisions
* Earnings surprises
* Ratings
* Price targets

Example:

```text
:estimates NVDA
```

---

### Peer analysis

```text
:peers (ticker)
```

Finds comparable companies and shows the fair values implied by their multiples.

Example:

```text
:peers NVDA
```

---

### Fields

```text
:fields
```

Displays every field available for the currently loaded ticker, together with its data source.

---

### Metrics

```text
:metrics
```

Displays registered metrics.

To explain a specific metric:

```text
:explain <key>
```

Example:

```text
:explain revenue_growth
```

---

### Sources

```text
:sources
```

Displays:

* Configured data providers
* Provider priorities
* Provider readiness/status

---

### Groups

```text
:group valuation
```

Runs a specific analysis group.

Currently, the command accepts one group at a time.

---

### Manual overrides

```text
:set <field> <value>
```

Manually override a field for the current analysis.

Example:

```text
:set beta 1.2
```

---

### Import data

```text
:import <path>
```

Import custom data from a CSV or JSON file containing `field,value` pairs.

Example:

```text
:import EXAMPLE.csv
```

Imported values can override API-provided data according to the provider priority system.

---

### Refresh data

```text
:refresh
```

Re-fetches data while ignoring cached values.

Useful when you want to ensure the analysis is using freshly retrieved data.

---

### Extend QLAB

```text
:extend
```

Provides information about how to add additional metrics and data providers to QLAB.

---

# Custom Data

QLAB allows you to provide your own data.

You can add custom values to:

```text
EXAMPLE.csv
```

Imported/user-provided values have higher priority than API data, allowing you to override values supplied by external providers.

This is useful when:

* You have a more accurate value
* A provider does not supply a required field
* You want to test an assumption
* You want to run a custom valuation scenario

---

# `ideas.md`

`ideas.md` contains the planned analysis and functionality for QLAB.

Completed ideas are marked using ~~strikethrough~~.

This provides a simple overview of what has already been implemented and what is planned for future development.

---

# Project Structure

A simplified overview of the project:

```text
QLAB CLI/
├── analyse.py
├── requirements.txt
├── ideas.md
├── EXAMPLE.csv
└── ...
```

The project is designed around separate data providers, registered fields/metrics, and analysis modules so that additional data sources and quantitative calculations can be added over time.

---

# Development

QLAB is designed to be extensible.

New functionality can be added through:

* New metrics
* New analysis modules
* New data providers
* Additional imported data
* New CLI commands

Use:

```text
:extend
```

for guidance on extending the system.

---

# Disclaimer

## this is not financial advice. you are responsible for everything. 

QLAB is an analytical and research tool.

Its calculations, valuations, estimates, and other outputs are not financial advice and should not be treated as a guarantee of future performance or investment returns.

Always verify important data and assumptions before making financial decisions.
