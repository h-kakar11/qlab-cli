"""Settings and API keys.

Keys are read from the environment only — never hardcode one in a source file,
because anything committed here is effectively published.

    PowerShell (this session):  $env:FINNHUB_API_KEY = "..."
    Permanent:                  setx FINNHUB_API_KEY "..."   (reopen terminal)
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: Where `:import` looks for hand-maintained CSV/JSON overrides.
IMPORT_DIR = PROJECT_ROOT / "data"

# Provider priorities. A higher number wins when two providers supply the same
# field. Adjust here rather than inside a provider.
PRIORITY_LONGTERM = 10  # yfinance: statements, history, profile
PRIORITY_SNAPSHOT = 20  # daily vendor snapshots
PRIORITY_LIVE = 30  # streaming trade prints
PRIORITY_IMPORTED = 40  # your own numbers always win

#: Seconds a provider may reuse a cached fundamentals response.
FUNDAMENTALS_TTL = 3600.0

#: Default seconds between redraws in live mode.
LIVE_INTERVAL = 2.0


def api_key(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


FINNHUB_KEY = "FINNHUB_API_KEY"
MASSIVE_KEY = "MASSIVE_API_KEY"


def missing_key_hint(env_name: str) -> str:
    return (
        f"{env_name} is not set — that provider is disabled.\n"
        f'  This session:  $env:{env_name} = "your-key"\n'
        f'  Permanent:     setx {env_name} "your-key"  (then reopen the terminal)'
    )
