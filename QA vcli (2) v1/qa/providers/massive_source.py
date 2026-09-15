"""Massive (formerly Polygon.io) — live trades, quotes and the daily snapshot.

The websocket client is asyncio-based, so it runs on its own event loop in a
daemon thread and hands prices back through a lock.

Tier note: the free plan has no websocket access at all — neither the real-time
nor the delayed feed authenticates — and rejects `get_snapshot_ticker` and
`get_last_trade`. What it does allow is `get_ticker_details` and the
previous-session bar, so that is the fallback below. `MASSIVE_FEED=delayed`
selects the delayed feed on plans that include one.
"""

from __future__ import annotations

import asyncio
import math
import os
import threading
import time
from typing import Any

from .. import config
from ..models import Fact
from .base import CachedProvider, provider

#: Seconds to let the client authenticate before believing the socket is up.
AUTH_GRACE = 2.0

try:
    from massive import RESTClient
    from massive.websocket import WebSocketClient
    from massive.websocket.models import Feed, Market
except ImportError:  # pragma: no cover - optional dependency
    RESTClient = None
    WebSocketClient = None
    Feed = Market = None


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _attr(obj: Any, *names: str) -> Any:
    for name in names:
        value = getattr(obj, name, None)
        if value is not None:
            return value
    return None


class MassiveTradeStream:
    """Last trade price per symbol from the Massive stocks websocket."""

    def __init__(self, api_key: str, feed: Any) -> None:
        self._api_key = api_key
        self._feed = feed
        self._lock = threading.Lock()
        self._prices: dict[str, float] = {}
        self._symbols: list[str] = []
        self._connected = threading.Event()
        self._failed = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._client: Any = None
        self._grace = 0.0
        #: Why the stream is not running, for the CLI to show.
        self.error: str | None = None

    def start(self, symbols: list[str]) -> None:
        with self._lock:
            self._symbols = [s.upper() for s in symbols]
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._connected.clear()

    def wait_connected(self, timeout: float) -> bool:
        """True only once auth has had a chance to fail.

        The client authenticates inside `connect()`, so a plan without
        websocket access surfaces as an exception a moment after the socket
        opens. Reporting success before that window would claim a live feed
        that is about to die.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._failed.is_set():
                return False
            if self._connected.is_set() and time.monotonic() >= self._grace:
                return True
            time.sleep(0.1)
        return self._connected.is_set() and not self._failed.is_set()

    def last_price(self, symbol: str) -> float | None:
        with self._lock:
            return self._prices.get(symbol.upper())

    def _handle(self, messages: Any) -> None:
        with self._lock:
            for message in messages:
                symbol = _attr(message, "symbol", "ticker")
                price = _num(_attr(message, "price", "close", "value"))
                if symbol and price is not None:
                    self._prices[str(symbol).upper()] = price

    def _run(self) -> None:
        with self._lock:
            subscriptions = [f"T.{s}" for s in self._symbols]
        try:
            self._client = WebSocketClient(
                api_key=self._api_key,
                feed=self._feed,
                market=Market.Stocks,
                subscriptions=subscriptions,
            )
        except Exception as exc:
            self.error = str(exc)
            self._failed.set()
            return

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        # Auth happens inside connect(); allow it this long to fail.
        self._grace = time.monotonic() + AUTH_GRACE
        self._connected.set()
        try:
            loop.run_until_complete(self._client.connect(self._handle))
        except Exception as exc:
            if not self._stop.is_set():
                self.error = str(exc)
                self._failed.set()
        finally:
            self._connected.clear()
            self._drain(loop)
            loop.close()

    @staticmethod
    def _drain(loop: asyncio.AbstractEventLoop) -> None:
        """Cancel the client's leftover keepalive tasks.

        Closing the loop with them still pending prints 'Task was destroyed but
        it is pending' over whatever the CLI is drawing.
        """
        pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
        if not pending:
            return
        for task in pending:
            task.cancel()
        try:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        except Exception:
            pass


@provider
class MassiveProvider(CachedProvider):
    name = "massive"
    kind = "live"
    priority = config.PRIORITY_SNAPSHOT
    describe = "Live trades/quotes, daily snapshot, splits and dividends"
    ttl = 60.0

    def __init__(self) -> None:
        super().__init__()
        self._client: Any = None
        self._stream: MassiveTradeStream | None = None

    def available(self) -> bool:
        return RESTClient is not None and config.api_key(config.MASSIVE_KEY) is not None

    def unavailable_reason(self) -> str:
        if RESTClient is None:
            return "pip install massive"
        return f"set {config.MASSIVE_KEY}"

    def client(self) -> Any:
        if self._client is None:
            key = config.api_key(config.MASSIVE_KEY)
            if key is None:
                raise RuntimeError(f"{config.MASSIVE_KEY} is not set")
            self._client = RESTClient(key)
        return self._client

    def _feed(self) -> Any:
        choice = os.environ.get("MASSIVE_FEED", "").strip().lower()
        if choice.startswith("delay"):
            return Feed.Delayed
        return Feed.RealTime

    # -- live streaming ---------------------------------------------------

    def start_live(self, tickers: list[str]) -> bool:
        if WebSocketClient is None or not self.available():
            return False
        key = config.api_key(config.MASSIVE_KEY)
        if key is None:
            return False
        if self._stream is None:
            self._stream = MassiveTradeStream(key, self._feed())
        self._stream.start(tickers)
        return self._stream.wait_connected(timeout=8.0)

    def stop_live(self) -> None:
        if self._stream is not None:
            self._stream.stop()

    def live_price(self, ticker: str) -> Fact | None:
        if self._stream is None:
            return None
        price = self._stream.last_price(ticker)
        if price is None:
            return None
        return Fact(
            value=price,
            source=f"{self.name}:ws",
            unit="price",
            priority=config.PRIORITY_LIVE,
        )

    # -- snapshot ---------------------------------------------------------

    def fetch(self, ticker: str) -> dict[str, Fact]:
        facts = dict(self.cached(ticker, lambda: self._snapshot(ticker)))
        live = self.live_price(ticker)
        if live is not None:
            facts["price"] = live
        return facts

    def _snapshot(self, ticker: str) -> dict[str, Fact]:
        client = self.client()
        values: dict[str, Any] = {}

        try:
            snap = client.get_snapshot_ticker("stocks", ticker)
            day = getattr(snap, "day", None)
            prev = getattr(snap, "prev_day", None)
            last = getattr(snap, "last_trade", None)
            values.update(
                {
                    "price": _num(_attr(last, "price", "p")) or _num(_attr(day, "close", "c")),
                    "day_open": _num(_attr(day, "open", "o")),
                    "day_high": _num(_attr(day, "high", "h")),
                    "day_low": _num(_attr(day, "low", "l")),
                    "day_volume": _num(_attr(day, "volume", "v")),
                    "vwap": _num(_attr(day, "vwap", "vw")),
                    "previous_close": _num(_attr(prev, "close", "c")),
                }
            )
        except Exception:
            # Free tiers answer NOT_AUTHORIZED here. The previous-session bar is
            # entitled on every plan, so fall back to it rather than losing the
            # provider. It is a completed session, so its close is a previous
            # close — never a live price.
            try:
                bars = client.get_previous_close_agg(ticker)
                bar = bars[0] if isinstance(bars, list) and bars else bars
                values.update(
                    {
                        "previous_close": _num(_attr(bar, "close", "c")),
                        "previous_open": _num(_attr(bar, "open", "o")),
                        "previous_high": _num(_attr(bar, "high", "h")),
                        "previous_low": _num(_attr(bar, "low", "l")),
                        "previous_volume": _num(_attr(bar, "volume", "v")),
                        "vwap": _num(_attr(bar, "vwap", "vw")),
                    }
                )
            except Exception:
                pass

        try:
            details = client.get_ticker_details(ticker)
            values.update(
                {
                    "name": _attr(details, "name"),
                    "currency": _attr(details, "currency_name"),
                    "exchange": _attr(details, "primary_exchange"),
                    "shares_outstanding": _num(
                        _attr(details, "weighted_shares_outstanding", "share_class_shares_outstanding")
                    ),
                    "market_cap": _num(_attr(details, "market_cap")),
                    "employees": _num(_attr(details, "total_employees")),
                    "description": _attr(details, "description"),
                    "sic_description": _attr(details, "sic_description"),
                }
            )
        except Exception:
            pass

        return self.pack(values)
