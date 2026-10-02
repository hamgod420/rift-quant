"""Best-effort venue-market -> internal-game mapping (v0 stub).

Full entity resolution is future work (docs/specs/M1b-odds-recorder-brief.md
deliverable #2 explicitly scopes this down: "keep this simple and
log-everything"). This matches on normalized team name overlap plus a
start-time tolerance window; anything not cleanly, uniquely matched is
logged to a review file rather than silently dropped or guessed at.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from riftquant.odds.discovery import MarketMeta
from riftquant.store import lake

MATCH_TOLERANCE = timedelta(hours=12)
_NON_ALNUM = re.compile(r"[^a-z0-9]")


def normalize_team(name: str) -> str:
    return _NON_ALNUM.sub("", name.lower())


@dataclass
class MappingResult:
    venue: str
    market_id: str
    matched: bool
    game_id: str | None
    reason: str


def map_market_to_game(market: MarketMeta, game_index: list[dict[str, Any]]) -> MappingResult:
    """`game_index` rows need team1_name/team1_code/team2_name/team2_code and
    start_time keys -- the shape ingest/lolesports.GameIndexRow produces
    (accepted here as plain dicts, not a parquet/DataFrame dependency, so
    this stays trivially unit-testable)."""
    if market.start_time is None:
        return _log_unmatched(market, "market has no start_time to match on")

    wanted = {normalize_team(market.team1), normalize_team(market.team2)}
    candidates = []
    for row in game_index:
        row_teams = {
            normalize_team(str(row.get("team1_name", ""))),
            normalize_team(str(row.get("team1_code", ""))),
            normalize_team(str(row.get("team2_name", ""))),
            normalize_team(str(row.get("team2_code", ""))),
        }
        if not (wanted & row_teams):
            continue
        row_start = row.get("start_time")
        if row_start is not None and abs(row_start - market.start_time) > MATCH_TOLERANCE:
            continue
        candidates.append(row)

    if len(candidates) == 1:
        game_id = candidates[0].get("game_id")
        return MappingResult(market.venue, market.market_id, True, game_id, "unique team+time")
    if not candidates:
        return _log_unmatched(market, "no game_index row shares a team name within the time window")
    return _log_unmatched(market, f"{len(candidates)} ambiguous candidates within the time window")


def _log_unmatched(market: MarketMeta, reason: str) -> MappingResult:
    lake.append_jsonl_gz(
        lake.raw_path("odds", "unmatched_review.jsonl.gz"),
        [
            {
                "venue": market.venue,
                "market_id": market.market_id,
                "title": market.title,
                "team1": market.team1,
                "team2": market.team2,
                "start_time": market.start_time.isoformat() if market.start_time else None,
                "reason": reason,
            }
        ],
    )
    return MappingResult(market.venue, market.market_id, False, None, reason)
