"""Finnhub — real-time quotes, trade websocket, and vendor-computed metrics."""

from __future__ import annotations

import json
import math
import sys
import threading
import time
from typing import Any

from .. import config
from ..models import Fact
from .base import CachedProvider, provider

try:
    import finnhub
except ImportError:  # pragma: no cover - optional dependency
    finnhub = None

try:
    import websocket as ws_client
except ImportError:  # pragma: no cover - optional dependency
    ws_client = None

WS_URL = "wss://ws.finnhub.io?token={token}"
#: Finnhub reports market cap in millions of the listing currency.
MARKET_CAP_UNIT = 1_000_000


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _first(metrics: dict, *keys: str) -> float | None:
    for key in keys:
        value = _num(metrics.get(key))
        if value is not None:
            return value
    return None


class FinnhubTradeStream:
    """Last traded price per symbol, over Finnhub's websocket.

    Daemon thread, reconnects with backoff. `last_price` is None until the
    first print arrives — quiet symbols and closed markets are normal.
    """

    def __init__(self, api_key: str) -> None:
        self._url = WS_URL.format(token=api_key)
        self._lock = threading.Lock()
        self._prices: dict[str, float] = {}
        self._symbols: set[str] = set()
        self._stop = threading.Event()
        self._connected = threading.Event()
        self._app: Any = None
        self._thread: threading.Thread | None = None

    def start(self, symbols: list[str]) -> None:
        with self._lock:
            self._symbols.update(s.upper() for s in symbols)
        if self._thread and self._thread.is_alive():
            self._subscribe(symbols)
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        app = self._app
        if app is not None:
            try:
                app.close()
            except Exception:
                pass

    def wait_connected(self, timeout: float) -> bool:
        return self._connected.wait(timeout)

    def last_price(self, symbol: str) -> float | None:
        with self._lock:
            return self._prices.get(symbol.upper())

    def _subscribe(self, symbols: list[str]) -> None:
        app = self._app
        if app is None or not self._connected.is_set():
            return
        for symbol in symbols:
            try:
                app.send(json.dumps({"type": "subscribe", "symbol": symbol.upper()}))
            except Exception:
                return

    def _run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            self._app = ws_client.WebSocketApp(
                self._url,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=lambda *_: self._connected.clear(),
            )
            self._app.run_forever(ping_interval=30, ping_timeout=10)
            if self._stop.is_set():
                return
            # Back off so a hard failure (bad key, no network) does not spin.
            time.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

    def _on_open(self, app: Any) -> None:
        self._connected.set()
        with self._lock:
            symbols = list(self._symbols)
        for symbol in symbols:
            app.send(json.dumps({"type": "subscribe", "symbol": symbol}))

    def _on_message(self, _app: Any, raw: str) -> None:
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            return
        if message.get("type") != "trade":
            return
        with self._lock:
            for trade in message.get("data") or []:
                price = _num(trade.get("p"))
                symbol = trade.get("s")
                if price is not None and symbol:
                    self._prices[symbol.upper()] = price

    def _on_error(self, _app: Any, error: Exception) -> None:
        self._connected.clear()
        print(f"finnhub websocket: {error}", file=sys.stderr)


@provider
class FinnhubProvider(CachedProvider):
    name = "finnhub"
    kind = "live"
    priority = config.PRIORITY_SNAPSHOT
    describe = "Real-time quote, trade websocket, vendor per-share metrics"
    ttl = config.FUNDAMENTALS_TTL

    def __init__(self) -> None:
        super().__init__()
        self._client: Any = None
        self._stream: FinnhubTradeStream | None = None

    def available(self) -> bool:
        return finnhub is not None and config.api_key(config.FINNHUB_KEY) is not None

    def unavailable_reason(self) -> str:
        if finnhub is None:
            return "pip install finnhub-python"
        return f"set {config.FINNHUB_KEY}"

    def client(self) -> Any:
        if self._client is None:
            key = config.api_key(config.FINNHUB_KEY)
            if key is None:
                raise RuntimeError(f"{config.FINNHUB_KEY} is not set")
            self._client = finnhub.Client(api_key=key)
        return self._client

    # -- live streaming ---------------------------------------------------

    def stream(self) -> FinnhubTradeStream | None:
        if ws_client is None:
            return None
        key = config.api_key(config.FINNHUB_KEY)
        if key is None:
            return None
        if self._stream is None:
            self._stream = FinnhubTradeStream(key)
        return self._stream

    def start_live(self, tickers: list[str]) -> bool:
        stream = self.stream()
        if stream is None:
            return False
        stream.start(tickers)
        return stream.wait_connected(timeout=8.0)

    def stop_live(self) -> None:
        if self._stream is not None:
            self._stream.stop()

    def live_price(self, ticker: str) -> Fact | None:
        if self._stream is None:
            return None
        price = self._stream.last_price(ticker)
        if price is None:
            return None
        fact = self.fact(price, unit="price")
        if fact is None:
            return None
        # Streaming prints outrank this provider's own REST snapshot.
        return Fact(
            value=fact.value,
            source=f"{self.name}:ws",
            as_of=fact.as_of,
            unit=fact.unit,
            priority=config.PRIORITY_LIVE,
        )

    # -- snapshot ---------------------------------------------------------

    def quote(self, ticker: str) -> dict[str, Fact]:
        """Uncached: the current REST quote. Called on every live redraw."""
        data = self.client().quote(ticker) or {}
        # Finnhub returns c == 0 for an unknown or unlicensed symbol.
        price = _num(data.get("c")) or None
        return self.pack(
            {
                "price": price,
                "previous_close": _num(data.get("pc")),
                "day_open": _num(data.get("o")),
                "day_high": _num(data.get("h")),
                "day_low": _num(data.get("l")),
            }
        )

    def fetch(self, ticker: str) -> dict[str, Fact]:
        facts = dict(self.cached(ticker, lambda: self._metrics(ticker)))
        try:
            facts.update(self.quote(ticker))
        except Exception:
            pass
        live = self.live_price(ticker)
        if live is not None:
            facts["price"] = live
        return facts

    def _metrics(self, ticker: str) -> dict[str, Fact]:
        payload = self.client().company_basic_financials(ticker, "all") or {}
        m = payload.get("metric") or {}
        market_cap = _first(m, "marketCapitalization")
        return self.pack(
            {
                "eps_ttm": _first(m, "epsTTM", "epsExclExtraItemsTTM", "epsAnnual"),
                "book_value_per_share": _first(
                    m, "bookValuePerShareQuarterly", "bookValuePerShareAnnual"
                ),
                "revenue_per_share": _first(m, "revenuePerShareTTM", "revenuePerShareAnnual"),
                "cash_flow_per_share": _first(m, "cashFlowPerShareTTM", "cashFlowPerShareAnnual"),
                "dividend_per_share": _first(m, "dividendPerShareTTM", "dividendPerShareAnnual"),
                "market_cap": market_cap * MARKET_CAP_UNIT if market_cap else None,
                "forward_pe_vendor": _first(m, "forwardPE"),
                "peg_vendor": _first(m, "pegTTM"),
                "operating_margin_vendor": _first(m, "operatingMarginTTM"),
                "eps_growth_3y": _first(m, "epsGrowth3Y"),
                "eps_growth_5y": _first(m, "epsGrowth5Y"),
                "revenue_growth_5y": _first(m, "revenueShareGrowth5Y"),
                "week52_high": _first(m, "52WeekHigh"),
                "week52_low": _first(m, "52WeekLow"),
                "beta": _first(m, "beta"),
            }
        )
