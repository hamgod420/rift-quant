"""Polymarket connector: gamma-api (discovery/catalog), CLOB (book/price),
data-api (public trade tape). All three surfaces are public/no-auth for
market data.

Re-verified live 2026-08-21 while building this module (fresh curl calls
against today's production endpoints, on top of the same-day findings in
docs/research/07-odds-capture-apis.md):
  - GET gamma-api /events?tag_slug=league-of-legends&closed=false found real
    upcoming LCK/LPL matches (e.g. lol-hle1-t1-2026-08-23 -- Hanwha Life
    Esports vs T1, LCK Round 3-4; lol-edg-jdg-2026-08-23 -- EDG vs JDG, LPL).
  - `outcomes`, `outcomePrices`, and `clobTokenIds` on a gamma market object
    are JSON-encoded STRINGS, not native arrays (e.g.
    `"outcomes": "[\\"Hanwha Life Esports\\", \\"T1\\"]"`) -- confirmed by
    inspecting the live response's Python types directly, not just eyeballing
    printed JSON (a double-encoded field looks identical to a real array once
    printed). `_json_list` below handles both shapes defensively anyway.
  - CLOB GET /book, /price, /midpoint on a real match token, and data-api GET
    /trades?market=<conditionId>, all returned live data matching the shapes
    documented in the research doc; /trades?market=<conditionId> returns
    trades for BOTH outcome tokens of that binary market (confirmed: a
    20-trade pull mixed both team outcomes), so one trades call per market
    (not per token) is enough.

v0 scope: match-winner markets only -- the market whose slug equals its
parent event's slug. Polymarket also lists per-map winners, totals,
handicaps, and a long tail of props (15-30+ per match); those are out of
scope until mapping.py's entity resolution matures (brief: "filter to
match-winner markets first").
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from riftquant import config
from riftquant.http import get_json, new_client
from riftquant.odds.discovery import MarketMeta

_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = new_client(config.USER_AGENT)
    return _client


def _sleep() -> None:
    time.sleep(config.POLYMARKET_SLEEP_SECS)


def json_list(raw: Any) -> list[str]:
    """gamma-api double-encodes some array fields as JSON strings (see module
    docstring); tolerate a real list too in case that ever changes."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _parse_gamma_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def discover_lol_markets(now: datetime | None = None) -> list[MarketMeta]:
    """GET gamma-api /events for the league-of-legends tag; keep only each
    event's full-match-winner market (market.slug == event.slug). Futures /
    season-winner events (their markets carry no gameStartTime) are skipped
    -- they are not per-match markets."""
    now = now or datetime.now(UTC)
    data = get_json(
        _get_client(),
        f"{config.GAMMA_BASE}/events",
        params={
            "tag_slug": config.LOL_TAG_SLUG,
            "closed": "false",
            "limit": 100,
            "order": "id",
            "ascending": "false",
        },
    )
    _sleep()

    found: list[MarketMeta] = []
    for event in data or []:
        event_slug = event.get("slug", "")
        for market in event.get("markets", []):
            if market.get("slug") != event_slug or market.get("closed"):
                continue  # per-map / total / handicap / prop, or already closed
            outcomes = json_list(market.get("outcomes"))
            start_time = _parse_gamma_ts(market.get("gameStartTime"))
            if start_time is None or len(outcomes) != 2:
                continue  # not a real per-match market (e.g. a season future)
            found.append(
                MarketMeta(
                    venue="polymarket",
                    market_id=market["slug"],
                    event_id=event_slug,
                    title=market.get("question") or event.get("title", ""),
                    team1=outcomes[0],
                    team2=outcomes[1],
                    start_time=start_time,
                    discovered_at=now,
                    outcomes=outcomes,
                    clob_token_ids=json_list(market.get("clobTokenIds")),
                    condition_id=market.get("conditionId"),
                    closed=bool(market.get("closed")),
                )
            )
    return found


def fetch_book(token_id: str) -> dict | None:
    book = get_json(_get_client(), f"{config.CLOB_BASE}/book", params={"token_id": token_id})
    _sleep()
    return book


def quote_from_book(book: dict) -> dict[str, float | None]:
    bids = book.get("bids") or []
    asks = book.get("asks") or []
    best_bid = max((float(b["price"]) for b in bids), default=None)
    best_ask = min((float(a["price"]) for a in asks), default=None)
    mid = (best_bid + best_ask) / 2 if best_bid is not None and best_ask is not None else None
    return {"bid": best_bid, "ask": best_ask, "mid": mid}


def fetch_trades(condition_id: str, limit: int = 100) -> list[dict]:
    trades = get_json(
        _get_client(),
        f"{config.POLYMARKET_DATA_API_BASE}/trades",
        params={"market": condition_id, "limit": limit},
    )
    _sleep()
    return trades or []


def trade_epoch(trade: dict) -> float:
    try:
        return float(trade.get("timestamp", 0))
    except (TypeError, ValueError):
        return 0.0


def fetch_market_status(market_slug: str) -> dict | None:
    """GET gamma-api /markets?slug=... -- a market-level slug lookup (the
    event-level slug returns an empty list; confirmed live and noted in the
    research doc)."""
    items = get_json(_get_client(), f"{config.GAMMA_BASE}/markets", params={"slug": market_slug})
    _sleep()
    return items[0] if items else None
