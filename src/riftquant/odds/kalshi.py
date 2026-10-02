"""Kalshi connector (trade-api/v2): REST-only, no WebSocket. Per the research
doc, Kalshi's WS requires an RSA-signed auth handshake even for public
channels, which isn't worth building for a venue that starts disabled;
public REST market data needs zero auth.

COMPLIANCE GATE (docs/QUESTIONS.md Q27): Kalshi's "Data Terms of Use" bars
using Kalshi Data to train an ML/AI system or to archive datasets without
written consent -- exactly this project's purpose. config.ODDS_VENUES_ENABLED
defaults kalshi to False, and per the M1b build brief this module was NOT
exercised against the live API at all while building it (no curl, no
`get_json` call, nothing) -- only unit tests against fixtures below. The code
exists and is tested so the path is ready the moment a human clears the
separate API Developer Agreement and flips the flag; do not add a CLI
bypass for that flag.

Shape provenance: the orderbook and trade shapes below are transcribed
directly from docs/research/07-odds-capture-apis.md's own live-captured
examples (real 2026-08-21 curl output, reproduced verbatim in that doc's
SS2.4 and SS2.8). The exact top-level envelope keys for `/events` and
`/markets/{ticker}` (e.g. whether the list sits under `"events"` / `"markets"`
key) were not shown verbatim in the doc -- they are a best-effort
reconstruction from Kalshi's documented conventions and should be spot-
checked against one real response before this is ever pointed at production
traffic (tracked as a known limitation, not silently assumed correct).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from riftquant import config
from riftquant.http import get_json, new_client
from riftquant.odds.discovery import MarketMeta

TERMINAL_STATUSES = {"settled", "finalized", "determined"}

_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = new_client(config.USER_AGENT)
    return _client


def _parse_kalshi_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def discover_lol_markets(now: datetime | None = None) -> list[MarketMeta]:
    """Walk the confirmed KXLOLGAME (full-match winner) series. KXLOLMAP
    (per-map) and KXLOL (season futures) are out of scope for the same
    "match-winner markets first" reason polymarket.py restricts to the
    top-level market. Each Kalshi match produces two mirrored tickers (one
    per competitor as the "yes" side, per the research doc SS2.8) -- both
    become separate MarketMeta rows since Kalshi has no single object
    covering both sides the way a Polymarket binary market does."""
    now = now or datetime.now(UTC)
    data = get_json(
        _get_client(),
        f"{config.KALSHI_BASE}/events",
        params={
            "series_ticker": config.KALSHI_LOL_MATCH_SERIES,
            "status": "open",
            "with_nested_markets": "true",
        },
    )
    found: list[MarketMeta] = []
    for event in (data or {}).get("events", []):
        event_ticker = event.get("event_ticker", "")
        for market in event.get("markets", []):
            if market.get("status") not in (None, "open"):
                continue
            yes_team = market.get("yes_sub_title") or ""
            no_team = market.get("no_sub_title") or ""
            found.append(
                MarketMeta(
                    venue="kalshi",
                    market_id=market["ticker"],
                    event_id=market.get("event_ticker", event_ticker),
                    title=market.get("title", ""),
                    team1=yes_team,
                    team2=no_team,
                    start_time=_parse_kalshi_ts(market.get("expected_expiration_time")),
                    discovered_at=now,
                    outcomes=[yes_team, no_team],
                    closed=market.get("status") not in (None, "open"),
                )
            )
    return found


def fetch_orderbook(ticker: str) -> dict | None:
    return get_json(_get_client(), f"{config.KALSHI_BASE}/markets/{ticker}/orderbook")


def quote_from_orderbook(book: dict) -> dict[str, float | None]:
    """Kalshi's book carries only bid-side depth per side (reciprocal
    pricing: a yes ask is implied as $1 - best no bid). See research doc
    SS2.4. Accepts either the live `orderbook_fp` key or a plain
    `orderbook` key defensively."""
    fp = book.get("orderbook_fp") or book.get("orderbook") or {}
    yes_levels = fp.get("yes_dollars") or []
    no_levels = fp.get("no_dollars") or []
    yes_bid = max((float(price) for price, _size in yes_levels), default=None)
    no_bid = max((float(price) for price, _size in no_levels), default=None)
    yes_ask = round(1 - no_bid, 4) if no_bid is not None else None
    mid = (yes_bid + yes_ask) / 2 if yes_bid is not None and yes_ask is not None else None
    return {"bid": yes_bid, "ask": yes_ask, "mid": mid}


def fetch_trades(ticker: str, limit: int = 100) -> list[dict]:
    data = get_json(
        _get_client(),
        f"{config.KALSHI_BASE}/markets/trades",
        params={"ticker": ticker, "limit": limit},
    )
    return (data or {}).get("trades", [])


def trade_epoch(trade: dict[str, Any]) -> float:
    raw = trade.get("created_time")
    if not raw:
        return 0.0
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def fetch_market_status(ticker: str) -> dict | None:
    data = get_json(_get_client(), f"{config.KALSHI_BASE}/markets/{ticker}")
    return (data or {}).get("market")


def is_terminal(market_status: dict[str, Any]) -> bool:
    return market_status.get("status") in TERMINAL_STATUSES
