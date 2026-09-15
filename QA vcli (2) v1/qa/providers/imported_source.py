"""Your own numbers — the highest-priority provider.

Anything you supply here overrides every vendor, which makes it the right place
for figures the APIs get wrong, private estimates, or fields no feed carries
(a normalised EPS, your own WACC, a segment revenue split).

Two ways in:

1. A file per ticker under `data/`, picked up automatically:
     data/NVDA.csv   ->  field,value        (one pair per line)
     data/NVDA.json  ->  {"field": value}
   `data/_shared.json` applies to every ticker.

2. At runtime, from the CLI:
     :set wacc 0.091
     :import data/my_numbers.csv
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

from .. import config
from ..models import Fact
from .base import Provider, provider


def _coerce(raw: Any) -> Any:
    """Numbers as floats, everything else left as-is."""
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw) if math.isfinite(float(raw)) else None
    if not isinstance(raw, str):
        return raw
    text = raw.strip().replace(",", "").replace("$", "")
    if not text:
        return None
    suffix = {"k": 1e3, "m": 1e6, "b": 1e9, "t": 1e12}
    multiplier = 1.0
    if text[-1].lower() in suffix:
        multiplier = suffix[text[-1].lower()]
        text = text[:-1]
    if text.endswith("%"):
        try:
            return float(text[:-1])
        except ValueError:
            return raw
    try:
        return float(text) * multiplier
    except ValueError:
        return raw


def read_file(path: Path) -> dict[str, Any]:
    """Load a CSV (`field,value`) or JSON (`{"field": value}`) override file."""
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist")

    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"{path} must contain a JSON object of field -> value")
        return {str(k): _coerce(v) for k, v in payload.items()}

    values: dict[str, Any] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.reader(handle):
            if len(row) < 2 or not row[0].strip() or row[0].lstrip().startswith("#"):
                continue
            values[row[0].strip()] = _coerce(row[1])
    return values


@provider
class ImportedProvider(Provider):
    name = "imported"
    kind = "import"
    priority = config.PRIORITY_IMPORTED
    describe = "Your own values from data/<TICKER>.csv|.json, :set and :import"

    def __init__(self) -> None:
        #: Set at runtime by `:set`; keyed by ticker, plus "*" for all tickers.
        self.overrides: dict[str, dict[str, Any]] = {}

    def available(self) -> bool:
        return True

    def set(self, ticker: str, field: str, value: Any) -> Any:
        coerced = _coerce(value)
        self.overrides.setdefault(ticker.upper(), {})[field] = coerced
        return coerced

    def clear(self, ticker: str, field: str | None = None) -> None:
        key = ticker.upper()
        if field is None:
            self.overrides.pop(key, None)
        else:
            self.overrides.get(key, {}).pop(field, None)

    def load(self, path: str | Path, ticker: str) -> int:
        """Merge a file into the runtime overrides for `ticker`."""
        values = read_file(Path(path))
        self.overrides.setdefault(ticker.upper(), {}).update(values)
        return len(values)

    def _from_disk(self, ticker: str) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for candidate in (
            config.IMPORT_DIR / "_shared.json",
            config.IMPORT_DIR / "_shared.csv",
            config.IMPORT_DIR / f"{ticker}.json",
            config.IMPORT_DIR / f"{ticker}.csv",
        ):
            if candidate.exists():
                try:
                    values.update(read_file(candidate))
                except Exception as exc:
                    raise RuntimeError(f"could not read {candidate.name}: {exc}") from exc
        return values

    def fetch(self, ticker: str) -> dict[str, Fact]:
        ticker = ticker.upper()
        values = self._from_disk(ticker)
        values.update(self.overrides.get("*", {}))
        values.update(self.overrides.get(ticker, {}))
        return self.pack(values)
