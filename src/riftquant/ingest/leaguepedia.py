"""Leaguepedia Cargo API connector (lol.fandom.com).

Primary historical data source per docs/QUESTIONS.md Q4. Two gotchas
confirmed while building this module:
  - A rate-limited request comes back as HTTP 200 with an error *body*
    (`{"error": {"code": "ratelimited", ...}}`), not an HTTP 429 -- the
    shared riftquant.http retry layer never sees it, so this module retries
    on the body shape itself.
  - Cargo silently replaces "_" with " " in returned field names unless each
    field is aliased to itself (`fields=GameId=GameId,...`); without that,
    `DateTime_UTC` would come back keyed as "DateTime UTC" and break every
    downstream lookup. cargo_query always sends self-aliased fields.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from pathlib import Path

import httpx
import polars as pl
from pydantic import BaseModel

from riftquant import config
from riftquant.http import get_json, new_client
from riftquant.store import lake

_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = new_client(config.LEAGUEPEDIA_USER_AGENT)
    return _client


class CargoRateLimited(RuntimeError):
    """The wiki's shared rate limit was hit; retryable after a backoff."""


class CargoError(RuntimeError):
    """Any other Cargo/MediaWiki API error (bad table/field name, etc.)."""


def _parse_cargo_response(data: dict | None) -> dict:
    data = data or {}
    if "error" in data:
        err = data["error"]
        if err.get("code") == "ratelimited":
            raise CargoRateLimited(err.get("info", "rate limited"))
        raise CargoError(f"{err.get('code')}: {err.get('info')}")
    return data


def _cargo_request(params: dict) -> dict:
    # Retried by hand (not @tenacity.retry) so unit tests can exercise
    # _parse_cargo_response's branches directly without waiting on backoff.
    attempts = 0
    delay = 2.0
    while True:
        attempts += 1
        try:
            data = get_json(_get_client(), config.LEAGUEPEDIA_API, params=params)
            return _parse_cargo_response(data)
        except CargoRateLimited:
            if attempts >= 6:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 30.0)


def cargo_query(
    table: str,
    fields: Iterable[str],
    where: str | None = None,
    *,
    join_on: str | None = None,
    order_by: str | None = None,
    limit: int = config.LEAGUEPEDIA_PAGE_SIZE,
    max_rows: int | None = None,
) -> list[dict]:
    """Generic paginated Cargo query. Persists each raw page to
    data/raw/leaguepedia/<table>.jsonl.gz before returning normalized dicts
    (raw-first). `limit` is the page size (<=500 per the API); `max_rows`
    caps the total returned across pages.
    """
    field_list = list(fields)
    fields_param = ",".join(f"{f}={f}" for f in field_list)
    raw_file = lake.raw_path("leaguepedia", f"{table}.jsonl.gz")

    all_rows: list[dict] = []
    offset = 0
    while True:
        params: dict = {
            "action": "cargoquery",
            "format": "json",
            "tables": table,
            "fields": fields_param,
            "limit": limit,
            "offset": offset,
        }
        if where:
            params["where"] = where
        if join_on:
            params["join_on"] = join_on
        if order_by:
            params["order_by"] = order_by

        data = _cargo_request(params)
        page = [item["title"] for item in data.get("cargoquery", [])]
        if page:
            lake.append_jsonl_gz(raw_file, page)
        all_rows.extend(page)

        if len(page) < limit or (max_rows is not None and len(all_rows) >= max_rows):
            break
        offset += limit
        time.sleep(config.LEAGUEPEDIA_SLEEP_SECS)

    return all_rows[:max_rows] if max_rows is not None else all_rows


class ScoreboardGame(BaseModel):
    game_id: str
    match_id: str
    date_time_utc: str
    patch: str
    team1: str
    team2: str
    win_team: str
    overview_page: str


# Cargo field name -> our snake_case attribute name.
_SCOREBOARD_FIELDS = {
    "GameId": "game_id",
    "MatchId": "match_id",
    "DateTime_UTC": "date_time_utc",
    "Patch": "patch",
    "Team1": "team1",
    "Team2": "team2",
    "WinTeam": "win_team",
    "OverviewPage": "overview_page",
}


def scoreboard_games(
    overview_page_like: str,
    since: str | None = None,
    *,
    max_rows: int | None = None,
) -> list[ScoreboardGame]:
    """Typed helper over the ScoreboardGames table. `overview_page_like` is a
    SQL LIKE pattern, e.g. "LCK/2026%". `since` (a DateTime_UTC-comparable
    string, e.g. "2026-01-01") filters to games on/after that time.
    """
    where = f"OverviewPage LIKE '{overview_page_like}'"
    if since:
        where += f" AND DateTime_UTC >= '{since}'"
    raw_rows = cargo_query(
        "ScoreboardGames",
        _SCOREBOARD_FIELDS.keys(),
        where=where,
        order_by="DateTime_UTC DESC",
        max_rows=max_rows,
    )
    games = []
    for row in raw_rows:
        mapped = {
            py_name: row.get(cargo_name, "") for cargo_name, py_name in _SCOREBOARD_FIELDS.items()
        }
        games.append(ScoreboardGame.model_validate(mapped))
    return games


# --- M1c bulk ingest: Tournaments, ScoreboardPlayers, PicksAndBansS7, ---
# --- TournamentRosters, Players, Teams (docs/specs/M1c-leaguepedia-      ---
# --- entities-brief.md). Field lists below were confirmed live 2026-08-21
# via `action=cargofields` against each table, not guessed from memory.

# Leaguepedia OverviewPage prefixes for `riftquant lp-ingest --league`.
# lck/lpl/lec/lcs confirmed live 2026-08-21 (Tournaments table probe, e.g.
# "LEC/2026 Season/Summer Playoffs" -> prefix "LEC/2026"). lta_n covers the
# 2025 LCS-lineage season under its own tag (docs/QUESTIONS.md Q3: LCS(-2024)
# -> LTA North (2025) -> LCS (2026-)) -- NOT live-verified this session,
# same caveat as msi/first_stand below. worlds uses a year-first page name
# ("2026 Season World Championship", confirmed live) that does NOT follow
# the domestic TAG/YEAR shape. msi/first_stand are BEST-EFFORT patterns,
# not live-verified this session (Leaguepedia rate-limited further probing)
# -- see README-DEV.md "Known limitations" before relying on them; a 0-row
# result from lp-ingest for either is a strong signal the pattern is wrong
# and needs a human to check the real OverviewPage on lol.fandom.com.
LEAGUEPEDIA_LEAGUE_PATTERNS: dict[str, str] = {
    "lck": "LCK/{season}%",
    "lpl": "LPL/{season}%",
    "lec": "LEC/{season}%",
    "lcs": "LCS/{season}%",
    "lta_n": "LTA North/{season}%",
    "worlds": "{season} Season World Championship%",
    "msi": "MSI {season}%",
    "first_stand": "First Stand {season}%",
}

_IN_LIST_CHUNK_SIZE = 50  # keeps Cargo `WHERE ... IN (...)` GET URLs short


def overview_page_pattern(league: str, season: int) -> str:
    """OverviewPage LIKE pattern for a league/season, e.g. ("lck", 2026) ->
    "LCK/2026%". Raises ValueError for an unknown league slug (never
    silently falls back to a guessed pattern)."""
    league = league.lower()
    if league not in LEAGUEPEDIA_LEAGUE_PATTERNS:
        raise ValueError(
            f"unknown league {league!r} for lp-ingest; known: {sorted(LEAGUEPEDIA_LEAGUE_PATTERNS)}"
        )
    return LEAGUEPEDIA_LEAGUE_PATTERNS[league].format(season=season)


def _sql_quote(value: str) -> str:
    return value.replace("'", "''")


def _chunked(items: list[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _split_list(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _map_fields(row: dict, fields: dict[str, str]) -> dict:
    """row keyed by Cargo field name -> dict keyed by our snake_case name,
    same self-aliasing convention as the module's original _SCOREBOARD_FIELDS."""
    return {py_name: row.get(cargo_name, "") for cargo_name, py_name in fields.items()}


def leaguepedia_table_path(name: str) -> Path:
    return lake.processed_path("leaguepedia", f"{name}.parquet")


class TournamentPage(BaseModel):
    overview_page: str
    name: str
    league: str
    region: str
    year: str
    date_start: str


_TOURNAMENT_FIELDS = {
    "OverviewPage": "overview_page",
    "Name": "name",
    "League": "league",
    "Region": "region",
    "Year": "year",
    "DateStart": "date_start",
}


def fetch_tournaments(overview_page_like: str) -> list[TournamentPage]:
    """Typed helper over the Tournaments table, scoped the same way as
    scoreboard_games: an OverviewPage LIKE pattern."""
    where = f"OverviewPage LIKE '{_sql_quote(overview_page_like)}'"
    raw_rows = cargo_query("Tournaments", _TOURNAMENT_FIELDS.keys(), where=where)
    return [
        TournamentPage.model_validate(_map_fields(row, _TOURNAMENT_FIELDS)) for row in raw_rows
    ]


class ScoreboardPlayer(BaseModel):
    unique_line: str
    game_id: str
    match_id: str
    overview_page: str
    name: str
    link: str
    team: str
    side: str
    role: str
    role_number: str
    champion: str
    kills: str
    deaths: str
    assists: str
    gold: str
    cs: str
    primary_tree: str
    secondary_tree: str
    keystone_rune: str
    player_win: str
    date_time_utc: str


_SCOREBOARD_PLAYER_FIELDS = {
    "UniqueLine": "unique_line",
    "GameId": "game_id",
    "MatchId": "match_id",
    "OverviewPage": "overview_page",
    "Name": "name",
    "Link": "link",
    "Team": "team",
    "Side": "side",
    "Role": "role",
    "Role_Number": "role_number",
    "Champion": "champion",
    "Kills": "kills",
    "Deaths": "deaths",
    "Assists": "assists",
    "Gold": "gold",
    "CS": "cs",
    "PrimaryTree": "primary_tree",
    "SecondaryTree": "secondary_tree",
    "KeystoneRune": "keystone_rune",
    "PlayerWin": "player_win",
    "DateTime_UTC": "date_time_utc",
}


def scoreboard_players(
    overview_page_like: str, *, max_rows: int | None = None
) -> list[ScoreboardPlayer]:
    """Typed helper over ScoreboardPlayers: 10 rows per game (5v5), carrying
    champion/role/runes/KDA/gold/cs -- see brief "Scope of data"."""
    where = f"OverviewPage LIKE '{_sql_quote(overview_page_like)}'"
    raw_rows = cargo_query(
        "ScoreboardPlayers",
        _SCOREBOARD_PLAYER_FIELDS.keys(),
        where=where,
        order_by="DateTime_UTC DESC",
        max_rows=max_rows,
    )
    return [
        ScoreboardPlayer.model_validate(
            {py: row.get(cargo, "") for cargo, py in _SCOREBOARD_PLAYER_FIELDS.items()}
        )
        for row in raw_rows
    ]


class PicksAndBans(BaseModel):
    unique_line: str
    game_id: str
    match_id: str
    overview_page: str
    team1: str
    team2: str
    winner: str
    team1_bans: list[str]
    team2_bans: list[str]
    team1_picks: list[str]
    team2_picks: list[str]


_PICKS_AND_BANS_SCALAR_FIELDS = {
    "UniqueLine": "unique_line",
    "GameId": "game_id",
    "MatchId": "match_id",
    "OverviewPage": "overview_page",
    "Team1": "team1",
    "Team2": "team2",
    "Winner": "winner",
}
# Team1/Team2 follow the same side convention as ScoreboardGames (Team1 =
# blue, Team2 = red) -- PicksAndBansS7 carries no separate Side field, so
# this is inferred from established Leaguepedia/downstream-consumer
# convention (Oracle's Elixir, gol.gg both derive blue/red from these same
# two columns) rather than independently re-verified this session.
_SLOT_GROUPS = {
    "team1_bans": [f"Team1Ban{i}" for i in range(1, 6)],
    "team2_bans": [f"Team2Ban{i}" for i in range(1, 6)],
    "team1_picks": [f"Team1Pick{i}" for i in range(1, 6)],
    "team2_picks": [f"Team2Pick{i}" for i in range(1, 6)],
}


def picks_and_bans(overview_page_like: str, *, max_rows: int | None = None) -> list[PicksAndBans]:
    """Typed helper over PicksAndBansS7: one row per game holding all 20
    draft slots as four 5-element lists (bans/picks x team1/team2). See
    store/views.py for how these are unpivoted into 20 ordered actions."""
    all_fields = list(_PICKS_AND_BANS_SCALAR_FIELDS.keys())
    for cols in _SLOT_GROUPS.values():
        all_fields.extend(cols)
    where = f"OverviewPage LIKE '{_sql_quote(overview_page_like)}'"
    raw_rows = cargo_query("PicksAndBansS7", all_fields, where=where, max_rows=max_rows)

    rows = []
    for row in raw_rows:
        mapped = {py: row.get(cargo, "") for cargo, py in _PICKS_AND_BANS_SCALAR_FIELDS.items()}
        for slot_field, cargo_cols in _SLOT_GROUPS.items():
            mapped[slot_field] = [row.get(c, "") for c in cargo_cols]
        rows.append(PicksAndBans.model_validate(mapped))
    return rows


class TournamentRoster(BaseModel):
    unique_line: str
    overview_page: str
    team: str
    tournament: str
    region: str
    roster_links: list[str]
    roles: list[str]
    is_used: str
    is_complete: str


_TOURNAMENT_ROSTER_FIELDS = {
    "UniqueLine": "unique_line",
    "OverviewPage": "overview_page",
    "Team": "team",
    "Tournament": "tournament",
    "Region": "region",
    "IsUsed": "is_used",
    "IsComplete": "is_complete",
}


def tournament_rosters(
    overview_page_like: str, *, max_rows: int | None = None
) -> list[TournamentRoster]:
    fields = list(_TOURNAMENT_ROSTER_FIELDS.keys()) + ["RosterLinks", "Roles"]
    where = f"OverviewPage LIKE '{_sql_quote(overview_page_like)}'"
    raw_rows = cargo_query("TournamentRosters", fields, where=where, max_rows=max_rows)
    rows = []
    for row in raw_rows:
        mapped = {py: row.get(cargo, "") for cargo, py in _TOURNAMENT_ROSTER_FIELDS.items()}
        mapped["roster_links"] = _split_list(row.get("RosterLinks", ""))
        mapped["roles"] = _split_list(row.get("Roles", ""))
        rows.append(TournamentRoster.model_validate(mapped))
    return rows


class PlayerPage(BaseModel):
    overview_page: str
    id: str
    player: str
    name: str
    name_full: str
    country: str
    team: str
    team_last: str
    role: str
    is_retired: str


_PLAYER_PAGE_FIELDS = {
    "OverviewPage": "overview_page",
    "ID": "id",
    "Player": "player",
    "Name": "name",
    "NameFull": "name_full",
    "Country": "country",
    "Team": "team",
    "TeamLast": "team_last",
    "Role": "role",
    "IsRetired": "is_retired",
}


def fetch_player_pages(overview_pages: list[str]) -> list[PlayerPage]:
    """Bounded lookup on the (global, unscoped) Players table, restricted to
    exactly the page names passed in. Callers derive `overview_pages` from
    already-ingested ScoreboardPlayers.Link values for the league/season
    slice being ingested, so this never pulls Leaguepedia's entire player
    roster."""
    rows: list[PlayerPage] = []
    pages = sorted({p for p in overview_pages if p})
    for i, chunk in enumerate(_chunked(pages, _IN_LIST_CHUNK_SIZE)):
        if i > 0:
            time.sleep(config.LEAGUEPEDIA_SLEEP_SECS)
        in_list = ", ".join(f"'{_sql_quote(p)}'" for p in chunk)
        raw_rows = cargo_query(
            "Players", _PLAYER_PAGE_FIELDS.keys(), where=f"OverviewPage IN ({in_list})"
        )
        rows.extend(
            PlayerPage.model_validate(_map_fields(row, _PLAYER_PAGE_FIELDS)) for row in raw_rows
        )
    return rows


class TeamPage(BaseModel):
    overview_page: str
    name: str
    short: str
    region: str
    is_disbanded: str
    renamed_to: str


_TEAM_PAGE_FIELDS = {
    "OverviewPage": "overview_page",
    "Name": "name",
    "Short": "short",
    "Region": "region",
    "IsDisbanded": "is_disbanded",
    "RenamedTo": "renamed_to",
}


def fetch_team_pages(overview_pages: list[str]) -> list[TeamPage]:
    """Bounded lookup on the (global, unscoped) Teams table, restricted to
    exactly the page names passed in (derived from ingested ScoreboardGames
    Team1/Team2/WinTeam values) -- same reasoning as fetch_player_pages."""
    rows: list[TeamPage] = []
    pages = sorted({p for p in overview_pages if p})
    for i, chunk in enumerate(_chunked(pages, _IN_LIST_CHUNK_SIZE)):
        if i > 0:
            time.sleep(config.LEAGUEPEDIA_SLEEP_SECS)
        in_list = ", ".join(f"'{_sql_quote(p)}'" for p in chunk)
        where = f"OverviewPage IN ({in_list})"
        raw_rows = cargo_query("Teams", _TEAM_PAGE_FIELDS.keys(), where=where)
        rows.extend(
            TeamPage.model_validate(_map_fields(row, _TEAM_PAGE_FIELDS)) for row in raw_rows
        )
    return rows


def _existing_slice(path: Path, prefix: str) -> pl.DataFrame | None:
    """Rows already on disk for this league/season prefix, or None if the
    table doesn't exist yet / has no such rows -- the resumability check for
    `ingest_league_season` (skip the live re-fetch unless --refresh)."""
    if not path.exists():
        return None
    df = pl.read_parquet(path)
    if "overview_page" not in df.columns:
        return None
    sliced = df.filter(pl.col("overview_page").str.starts_with(prefix))
    return sliced if sliced.height > 0 else None


def _fetch_missing_pages(
    path: Path, wanted_pages: list[str], fetch_fn, refresh: bool
) -> tuple[list[dict], int]:
    """Incremental fetch for the global Teams/Players tables: only queries
    pages not already present on disk (or all of them, if refresh=True).
    Returns (all rows matching wanted_pages as dicts, count newly fetched)."""
    existing_df = pl.read_parquet(path) if path.exists() else None
    have = set(existing_df["overview_page"].to_list()) if existing_df is not None else set()
    missing = [p for p in wanted_pages if refresh or p not in have]
    new_rows = fetch_fn(missing) if missing else []
    if new_rows:
        df = pl.DataFrame([r.model_dump() for r in new_rows])
        lake.upsert_parquet(df, path, key_cols=["overview_page"])
        time.sleep(config.LEAGUEPEDIA_SLEEP_SECS)
    final_df = pl.read_parquet(path) if path.exists() else pl.DataFrame()
    if final_df.height and wanted_pages:
        final_df = final_df.filter(pl.col("overview_page").is_in(wanted_pages))
    return final_df.to_dicts(), len(new_rows)


def ingest_league_season(league: str, season: int, *, refresh: bool = False) -> dict[str, int]:
    """Fetch+normalize every M1c Cargo table for one (league, season) slice
    into the parquet lake under data/processed/leaguepedia/. Resumable at
    the (table, league, season) grain: if the processed parquet already has
    rows for this league/season and refresh=False, that table is served
    from disk instead of re-hit over the network (raw pages stay
    append-only regardless, per lake.append_jsonl_gz). Returns
    {table_name: row_count_in_this_slice}."""
    pattern = overview_page_pattern(league, season)
    prefix = pattern.rstrip("%")
    counts: dict[str, int] = {}

    def _scoped_slice(name: str, fetch, key_cols: list[str]) -> list[dict]:
        path = leaguepedia_table_path(name)
        if not refresh:
            existing = _existing_slice(path, prefix)
            if existing is not None:
                counts[name] = existing.height
                return existing.to_dicts()
        rows = fetch()
        counts[name] = len(rows)
        if rows:
            df = pl.DataFrame([r.model_dump() for r in rows])
            lake.upsert_parquet(df, path, key_cols=key_cols)
            time.sleep(config.LEAGUEPEDIA_SLEEP_SECS)
        return [r.model_dump() for r in rows]

    _scoped_slice("tournaments", lambda: fetch_tournaments(pattern), ["overview_page"])
    games_d = _scoped_slice("scoreboard_games", lambda: scoreboard_games(pattern), ["game_id"])
    players_d = _scoped_slice(
        "scoreboard_players", lambda: scoreboard_players(pattern), ["unique_line"]
    )
    _scoped_slice("picks_and_bans", lambda: picks_and_bans(pattern), ["game_id"])
    _scoped_slice("tournament_rosters", lambda: tournament_rosters(pattern), ["unique_line"])

    team_names: set[str] = set()
    for d in games_d:
        team_names.update((d["team1"], d["team2"], d["win_team"]))
    team_pages = sorted(team_names - {""})
    team_dicts, _ = _fetch_missing_pages(
        leaguepedia_table_path("teams"), team_pages, fetch_team_pages, refresh
    )
    counts["teams"] = len(team_dicts)

    player_pages = sorted({d["link"] for d in players_d} - {""})
    player_dicts, _ = _fetch_missing_pages(
        leaguepedia_table_path("players"), player_pages, fetch_player_pages, refresh
    )
    counts["players"] = len(player_dicts)

    return counts
