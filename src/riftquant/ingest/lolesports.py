"""lolesports persisted-API connector.

Base https://esports-api.lolesports.com/persisted/gw, public broadcast key
(no login flow). Response shapes below were confirmed with live calls against
the real API on 2026-08-21 while building this module -- notably:
  - getCompletedEvents nests events at data.schedule.events (not data.events).
  - games[] under an event lists every game slot implied by the series'
    best-of count, INCLUDING games never played when a series ends early
    (e.g. a 2-0 sweep in a Bo3 still lists a 3rd game id). An unplayed game's
    `vods` list is empty; a played one is not. `has_vod` below is that
    heuristic -- the authoritative signal is livestats returning HTTP 204 for
    the game id (see ingest/livestats.py), which the archiver already
    handles, so this is a best-effort filter for callers, not a guarantee.
"""

from __future__ import annotations

import time
from datetime import date, datetime

import httpx
from pydantic import BaseModel, Field

from riftquant import config
from riftquant.http import get_json, new_client
from riftquant.store import lake

_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = new_client(config.USER_AGENT)
        _client.headers["x-api-key"] = config.DEFAULT_PUBLIC_KEY
    return _client


class League(BaseModel):
    id: str
    slug: str
    name: str


class Tournament(BaseModel):
    id: str
    slug: str
    start_date: date = Field(alias="startDate")
    end_date: date = Field(alias="endDate")


class EventTeam(BaseModel):
    name: str
    code: str


class Strategy(BaseModel):
    type: str
    count: int


class EventMatch(BaseModel):
    id: str
    teams: list[EventTeam] = Field(default_factory=list)
    strategy: Strategy


class EventGame(BaseModel):
    id: str
    vods: list[dict] = Field(default_factory=list)


class CompletedEvent(BaseModel):
    start_time: datetime = Field(alias="startTime")
    match: EventMatch
    games: list[EventGame] = Field(default_factory=list)


class GameIndexRow(BaseModel):
    """Normalized, flat, one-row-per-game index entry."""

    game_id: str
    match_id: str
    game_number: int
    series_best_of: int
    strategy_type: str
    team1_code: str
    team1_name: str
    team2_code: str
    team2_name: str
    start_time: datetime
    league: str
    tournament: str
    tournament_id: str
    has_vod: bool


def list_leagues() -> list[League]:
    """GET getLeagues. Persists the raw list, returns typed rows."""
    data = get_json(_get_client(), f"{config.LOLESPORTS_BASE}/getLeagues", params={"hl": "en-US"})
    raw = (data or {}).get("data", {}).get("leagues", [])
    lake.append_jsonl_gz(lake.raw_path("lolesports", "leagues.jsonl.gz"), raw)
    return [League.model_validate(item) for item in raw]


def list_tournaments(league_slug: str, since: int | None = None) -> list[Tournament]:
    """GET getTournamentsForLeague. `since` keeps tournaments starting on or
    after Jan 1 of that year."""
    if league_slug not in config.LEAGUE_IDS:
        raise ValueError(f"unknown league slug {league_slug!r}; known: {sorted(config.LEAGUE_IDS)}")
    data = get_json(
        _get_client(),
        f"{config.LOLESPORTS_BASE}/getTournamentsForLeague",
        params={"hl": "en-US", "leagueId": config.LEAGUE_IDS[league_slug]},
    )
    leagues = (data or {}).get("data", {}).get("leagues", [])
    raw = leagues[0].get("tournaments", []) if leagues else []
    lake.append_jsonl_gz(lake.raw_path("lolesports", "tournaments", f"{league_slug}.jsonl.gz"), raw)
    tournaments = [Tournament.model_validate(item) for item in raw]
    if since is not None:
        cutoff = date(since, 1, 1)
        tournaments = [t for t in tournaments if t.start_date >= cutoff]
    return tournaments


def completed_events(tournament_id: str) -> list[CompletedEvent]:
    """GET getCompletedEvents. An empty result is expected (not an error) for
    tournaments predating a league's livestats pipeline -- see
    docs/QUESTIONS.md Q26 (e.g. LCK <=2022, LEC <=2023, LPL <=2024)."""
    data = get_json(
        _get_client(),
        f"{config.LOLESPORTS_BASE}/getCompletedEvents",
        params={"hl": "en-US", "tournamentId": tournament_id},
    )
    raw = (data or {}).get("data", {}).get("schedule", {}).get("events", [])
    lake.append_jsonl_gz(
        lake.raw_path("lolesports", "completed_events", f"{tournament_id}.jsonl.gz"), raw
    )
    return [CompletedEvent.model_validate(item) for item in raw]


def get_event_details(match_id: str) -> dict | None:
    """GET getEventDetails -- fallback lookup for a single match's games
    (richer than completed_events: includes per-game state + side), used
    when the primary completed_events path needs cross-checking."""
    data = get_json(
        _get_client(),
        f"{config.LOLESPORTS_BASE}/getEventDetails",
        params={"hl": "en-US", "id": match_id},
    )
    event = (data or {}).get("data", {}).get("event")
    if event:
        path = lake.raw_path("lolesports", "event_details", f"{match_id}.jsonl.gz")
        lake.append_jsonl_gz(path, [event])
    return event


def build_game_index(league_slug: str, since: int | None = None) -> list[GameIndexRow]:
    """Walk tournaments -> completed events -> one flat row per game slot."""
    rows: list[GameIndexRow] = []
    for tournament in list_tournaments(league_slug, since=since):
        for event in completed_events(tournament.id):
            t1 = event.match.teams[0] if len(event.match.teams) > 0 else EventTeam(name="", code="")
            t2 = event.match.teams[1] if len(event.match.teams) > 1 else EventTeam(name="", code="")
            for i, game in enumerate(event.games, start=1):
                rows.append(
                    GameIndexRow(
                        game_id=game.id,
                        match_id=event.match.id,
                        game_number=i,
                        series_best_of=event.match.strategy.count,
                        strategy_type=event.match.strategy.type,
                        team1_code=t1.code,
                        team1_name=t1.name,
                        team2_code=t2.code,
                        team2_name=t2.name,
                        start_time=event.start_time,
                        league=league_slug,
                        tournament=tournament.slug,
                        tournament_id=tournament.id,
                        has_vod=len(game.vods) > 0,
                    )
                )
        time.sleep(0.2)  # courtesy between tournament-level calls
    return rows
