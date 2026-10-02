"""Recorder daemon: polls each enabled venue's tracked markets on an
interval, appending observations to data/raw/odds/<venue>/<YYYY-MM-DD>.jsonl.gz.

Two capture cadences per the brief, from ONE book fetch per side (so the
cadences don't double the request volume): a compact top-of-book+mid "quote"
every tick, and a heavier full-book "book" snapshot every
config.ODDS_FULL_BOOK_INTERVAL_SECS (5 min). "trade" covers everything new
since the last poll (per-market via MarketState.last_trade_ts); "resolution"
is written once and then skipped for the rest of the run.

Loop mechanics are venue-agnostic via the VenueClient protocol, so
`poll_market` is unit-testable with a fake client and no live network -- see
tests/test_recorder.py.
"""

from __future__ import annotations

import signal
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Protocol

from riftquant import config
from riftquant.odds import discovery, kalshi, polymarket
from riftquant.odds.discovery import MarketMeta
from riftquant.store import lake


class VenueClient(Protocol):
    """Everything the recorder loop needs from one venue's connector."""

    def snapshot(self, market: MarketMeta, want_full_book: bool) -> tuple[list[dict], list[dict]]:
        """(quotes, books) -- `books` is populated only when `want_full_book`
        is True, at no extra request cost (same fetch as the quote)."""
        ...

    def trades(self, market: MarketMeta, since_ts: float) -> list[tuple[float, dict]]:
        """(epoch_seconds, raw_trade) pairs strictly newer than since_ts."""
        ...

    def resolution(self, market: MarketMeta) -> dict | None:
        """None while still open/unsettled; a dict once resolved."""
        ...


class PolymarketClient:
    def snapshot(self, market: MarketMeta, want_full_book: bool) -> tuple[list[dict], list[dict]]:
        quotes: list[dict] = []
        books: list[dict] = []
        for outcome, token_id in zip(market.outcomes, market.clob_token_ids, strict=False):
            book = polymarket.fetch_book(token_id)
            if book is None:
                continue
            quote = polymarket.quote_from_book(book)
            quotes.append({"outcome": outcome, "token_id": token_id, **quote})
            if want_full_book:
                books.append({"outcome": outcome, "token_id": token_id, "raw": book})
        return quotes, books

    def trades(self, market: MarketMeta, since_ts: float) -> list[tuple[float, dict]]:
        if not market.condition_id:
            return []
        out = []
        for trade in polymarket.fetch_trades(market.condition_id):
            ts = polymarket.trade_epoch(trade)
            if ts > since_ts:
                out.append((ts, trade))
        return out

    def resolution(self, market: MarketMeta) -> dict | None:
        status = polymarket.fetch_market_status(market.market_id)
        if status is None or not status.get("closed"):
            return None
        return {
            "closed": True,
            "outcome_prices": polymarket.json_list(status.get("outcomePrices")),
            "raw": status,
        }


class KalshiClient:
    """Never invoked live by this project's own tooling while
    config.ODDS_VENUES_ENABLED["kalshi"] is False -- see kalshi.py docstring.
    """

    def snapshot(self, market: MarketMeta, want_full_book: bool) -> tuple[list[dict], list[dict]]:
        book = kalshi.fetch_orderbook(market.market_id)
        if book is None:
            return [], []
        top = kalshi.quote_from_orderbook(book)
        quote = {"outcome": market.team1, "token_id": market.market_id, **top}
        books = []
        if want_full_book:
            books.append({"outcome": market.team1, "token_id": market.market_id, "raw": book})
        return [quote], books

    def trades(self, market: MarketMeta, since_ts: float) -> list[tuple[float, dict]]:
        out = []
        for trade in kalshi.fetch_trades(market.market_id):
            ts = kalshi.trade_epoch(trade)
            if ts > since_ts:
                out.append((ts, trade))
        return out

    def resolution(self, market: MarketMeta) -> dict | None:
        status = kalshi.fetch_market_status(market.market_id)
        if status is None or not kalshi.is_terminal(status):
            return None
        return {"status": status.get("status"), "result": status.get("result"), "raw": status}


def _client_for(venue: str) -> VenueClient:
    if venue == "polymarket":
        return PolymarketClient()
    if venue == "kalshi":
        return KalshiClient()
    raise ValueError(f"unknown odds venue {venue!r}")


@dataclass
class MarketState:
    last_full_book_ts: float = 0.0
    last_trade_ts: float = 0.0
    resolved: bool = False


class DayWriter:
    """One JsonlGzWriter per (venue, date); a run that crosses UTC midnight
    rotates to a new file automatically since each tick looks up `now`'s
    date."""

    def __init__(self) -> None:
        self._writers: dict[tuple[str, date], lake.JsonlGzWriter] = {}

    def get(self, venue: str, day: date) -> lake.JsonlGzWriter:
        key = (venue, day)
        writer = self._writers.get(key)
        if writer is None:
            writer = lake.JsonlGzWriter(discovery.capture_path(venue, day))
            self._writers[key] = writer
        return writer

    def close_all(self) -> None:
        for writer in self._writers.values():
            writer.close()
        self._writers.clear()


def poll_market(
    writer: lake.JsonlGzWriter,
    client: VenueClient,
    market: MarketMeta,
    state: MarketState,
    now: datetime,
) -> int:
    """One poll pass for one market. Raises on venue/HTTP errors -- the
    caller (`run`, below) catches per-market so one bad market or a venue
    outage doesn't stop the others (brief: "survives venue downtime")."""
    n = 0
    capture_ts = now.isoformat()
    envelope = {"venue": market.venue, "market_id": market.market_id, "event_id": market.event_id}

    book_age = now.timestamp() - state.last_full_book_ts
    want_full_book = book_age >= config.ODDS_FULL_BOOK_INTERVAL_SECS
    quotes, books = client.snapshot(market, want_full_book)
    for quote in quotes:
        writer.write({"capture_ts": capture_ts, "obs_type": "quote", **envelope, **quote})
        n += 1
    if want_full_book:
        for book in books:
            writer.write({"capture_ts": capture_ts, "obs_type": "book", **envelope, **book})
            n += 1
        state.last_full_book_ts = now.timestamp()

    for ts, raw_trade in client.trades(market, state.last_trade_ts):
        record = {"capture_ts": capture_ts, "obs_type": "trade", **envelope, "trade": raw_trade}
        writer.write(record)
        state.last_trade_ts = max(state.last_trade_ts, ts)
        n += 1

    # Resolution can't happen before the scheduled start (or "unknown"), so
    # skip the extra HTTP call for markets that are still days out.
    if not state.resolved and (market.start_time is None or now >= market.start_time):
        result = client.resolution(market)
        if result is not None:
            writer.write({"capture_ts": capture_ts, "obs_type": "resolution", **envelope, **result})
            state.resolved = True
            n += 1
    return n


def run(
    *,
    interval: int = config.ODDS_RECORD_INTERVAL_SECS,
    limit: int = config.ODDS_DEFAULT_MARKET_LIMIT,
    hours_ahead: float = config.ODDS_DEFAULT_HOURS_AHEAD,
    venues: dict[str, bool] | None = None,
    duration_secs: float | None = None,
    discover_first: bool = True,
    echo: Callable[[str], None] = print,
) -> int:
    """Run the recorder loop until SIGINT or `duration_secs` elapses.
    Returns the total observation count written (mainly useful for tests /
    bounded runs -- an interactive CLI run is normally stopped with Ctrl+C,
    which flushes and closes every open writer via the `finally` block
    below before the process exits).
    """
    enabled = config.ODDS_VENUES_ENABLED if venues is None else venues
    active_venues = [v for v, on in enabled.items() if on]
    if discover_first:
        discovery.discover_all(enabled)

    clients = {venue: _client_for(venue) for venue in active_venues}
    states: dict[tuple[str, str], MarketState] = {}
    writers = DayWriter()
    stop = {"flag": False}

    def _on_sigint(_signum: int, _frame: object) -> None:
        stop["flag"] = True
        echo("record-odds: caught Ctrl+C, flushing and stopping...")

    old_handler = signal.signal(signal.SIGINT, _on_sigint)
    total = 0
    start = time.monotonic()
    try:
        while not stop["flag"]:
            now = datetime.now(UTC)
            for venue in active_venues:
                markets = discovery.load_tracked(
                    venue, within_hours=hours_ahead, now=now, limit=limit
                )
                client = clients[venue]
                writer = writers.get(venue, now.date())
                for market in markets:
                    state = states.setdefault((venue, market.market_id), MarketState())
                    if state.resolved:
                        continue
                    try:
                        total += poll_market(writer, client, market, state, now)
                    except Exception as exc:  # noqa: BLE001 -- log + continue, never crash the loop
                        echo(f"[{venue}] poll error for {market.market_id}: {exc}")
            if duration_secs is not None and time.monotonic() - start >= duration_secs:
                break
            for _ in range(interval):
                if stop["flag"]:
                    break
                time.sleep(1)
    finally:
        writers.close_all()
        signal.signal(signal.SIGINT, old_handler)
    return total
