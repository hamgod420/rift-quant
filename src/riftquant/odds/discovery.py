"""Odds-market discovery: find active/upcoming LoL match-winner markets per
venue and persist their metadata to data/raw/odds/markets/<venue>.jsonl.gz.

v0 scope (docs/specs/M1b-odds-recorder-brief.md): match-winner markets only.
Polymarket lists 15-30+ per-map/prop markets per match too; those are out of
scope until mapping.py's entity resolution matures ("filter to match-winner
markets first" per the brief). Persistence is append-only like the rest of
the lake: re-running discovery just appends a fresh discovered_at snapshot,
and `load_tracked` below dedupes to the latest one per market_id.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, Field

from riftquant import config
from riftquant.store import lake


class MarketMeta(BaseModel):
    """Venue-agnostic market metadata. One row per trackable market: for
    Polymarket that is one binary contract (2 clob_token_ids, one per team);
    for Kalshi it is one ticker (one team as the "yes" side; its mirror
    ticker for the other team is a separate MarketMeta row)."""

    venue: str
    market_id: str  # polymarket: market slug. kalshi: market ticker.
    event_id: str  # polymarket: event slug. kalshi: event ticker.
    market_type: str = "match_winner"
    title: str
    team1: str
    team2: str
    start_time: datetime | None = None
    discovered_at: datetime
    outcomes: list[str] = Field(default_factory=list)
    clob_token_ids: list[str] = Field(default_factory=list)  # polymarket only
    condition_id: str | None = None  # polymarket only (Data API trade key)
    closed: bool = False


def markets_path(venue: str) -> Path:
    return lake.raw_path("odds", "markets", f"{venue}.jsonl.gz")


def capture_path(venue: str, day: date) -> Path:
    return lake.raw_path("odds", venue, f"{day.isoformat()}.jsonl.gz")


def persist_discovered(venue: str, markets: list[MarketMeta]) -> int:
    return lake.append_jsonl_gz(markets_path(venue), (m.model_dump(mode="json") for m in markets))


def discover_all(venues: dict[str, bool] | None = None) -> dict[str, list[MarketMeta]]:
    """Run discovery for each enabled venue and persist results.

    Local imports below (rather than module-level) are deliberate: polymarket
    and kalshi both import MarketMeta from this module, so importing them at
    module level here would be circular. `venues` overrides
    config.ODDS_VENUES_ENABLED (mainly for tests); the CLI never overrides it,
    so Kalshi only ever runs here if a human has flipped the config default.
    """
    from riftquant.odds import kalshi, polymarket

    enabled = config.ODDS_VENUES_ENABLED if venues is None else venues
    results: dict[str, list[MarketMeta]] = {}
    if enabled.get("polymarket"):
        results["polymarket"] = polymarket.discover_lol_markets()
    if enabled.get("kalshi"):
        results["kalshi"] = kalshi.discover_lol_markets()
    for venue, markets in results.items():
        persist_discovered(venue, markets)
    return results


def load_tracked(
    venue: str,
    *,
    within_hours: float | None = None,
    now: datetime | None = None,
    limit: int | None = None,
) -> list[MarketMeta]:
    """Latest-known discovered markets for `venue`, deduped by market_id
    (highest discovered_at wins), closed markets dropped, optionally capped
    to markets starting within `within_hours` of `now` and/or truncated to
    the `limit` soonest-starting rows. No lower time bound is applied: a
    market's own `closed` flag is trusted as the "still worth polling"
    signal, so an in-progress match stays tracked regardless of how long ago
    it started.
    """
    now = now or datetime.now(UTC)
    latest: dict[str, MarketMeta] = {}
    for rec in lake.read_jsonl_gz(markets_path(venue)):
        market = MarketMeta.model_validate(rec)
        prev = latest.get(market.market_id)
        if prev is None or market.discovered_at >= prev.discovered_at:
            latest[market.market_id] = market

    rows = [m for m in latest.values() if not m.closed]
    if within_hours is not None:
        horizon = now + timedelta(hours=within_hours)
        rows = [m for m in rows if m.start_time is None or m.start_time <= horizon]
    rows.sort(key=lambda m: (m.start_time is None, m.start_time or now))
    if limit is not None:
        rows = rows[:limit]
    return rows


def last_capture_ts(venue: str, market_id: str, day: date | None = None) -> datetime | None:
    """Max capture_ts recorded for `market_id` in `day`'s (default: today
    UTC) capture file. Used by `odds-status`; scanning only the current
    day's file is a deliberate v0 simplification, not a full history scan."""
    day = day or datetime.now(UTC).date()
    last: datetime | None = None
    for rec in lake.read_jsonl_gz(capture_path(venue, day)):
        if rec.get("market_id") != market_id:
            continue
        raw_ts = rec.get("capture_ts")
        if not raw_ts:
            continue
        parsed = datetime.fromisoformat(raw_ts)
        if last is None or parsed > last:
            last = parsed
    return last
