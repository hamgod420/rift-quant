"""DuckDB views over the parquet lake, + the M1 exit-criteria metrics
(M1c brief, "DuckDB views" and CLI `build-views`/`validate-m1`).

build_views() does three things in order: (1) resolve team/player entities
into alias parquet tables (see riftquant.entities), (2) (re)build the
patches dimension from every ingested ScoreboardGames row seen so far, (3)
(re)create data/riftquant.duckdb with views over all of it. run_validate_m1()
then queries those views for the M1 exit metrics.

v_games' `best_of_observed` is the max game number actually PLAYED in a
match_id's series, not the nominal Bo3/Bo5 format -- Leaguepedia's
ScoreboardGames table carries no explicit series-format field, so a 2-0 Bo3
sweep and an actual Bo2 would look identical from this data alone (the same
lower-bound-approximation caveat the lolesports connector documents for its
own unplayed-game-slot quirk).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import duckdb
import polars as pl

from riftquant import config
from riftquant import patches as patches_mod
from riftquant.entities import players as players_mod
from riftquant.entities import resolve as resolve_mod
from riftquant.entities import teams as teams_mod
from riftquant.entities.resolve import SQL_NORMALIZE_EXPR
from riftquant.ingest.leaguepedia import leaguepedia_table_path
from riftquant.store import lake

DUCKDB_PATH = config.DATA_ROOT / "riftquant.duckdb"

# Domestic leagues only: a clean, static OverviewPage tag prefix exists for
# each (see ingest.leaguepedia.LEAGUEPEDIA_LEAGUE_PATTERNS). Internationals
# (worlds/msi/first_stand) don't have a matching lolesports game_index slug
# shaped the same way, so they're out of scope for this cross-check.
_CROSS_CHECK_LEAGUES = [("lck", "LCK"), ("lec", "LEC"), ("lpl", "LPL"), ("lcs", "LCS")]

# Standard competitive-draft slot order (side, action, slot-within-array) ->
# global order_index 1-20: 3 bans/side, 3 picks/side, 4 bans/side, 2
# picks/side, alternating B/R -- the fixed "tournament draft" sequence used
# in pro play since its introduction, unchanged in structure since (also
# Leaguepedia's own live-draft-overlay order). Team1/Team2 follow the same
# blue/red convention noted in ingest/leaguepedia.py.
_DRAFT_ORDER_VALUES = """
    ('team1','ban',1,1), ('team2','ban',1,2),
    ('team1','ban',2,3), ('team2','ban',2,4),
    ('team1','ban',3,5), ('team2','ban',3,6),
    ('team1','pick',1,7), ('team2','pick',1,8),
    ('team2','pick',2,9), ('team1','pick',2,10),
    ('team1','pick',3,11), ('team2','pick',3,12),
    ('team2','ban',4,13), ('team1','ban',4,14),
    ('team2','ban',5,15), ('team1','ban',5,16),
    ('team2','pick',4,17), ('team1','pick',4,18),
    ('team1','pick',5,19), ('team2','pick',5,20)
"""


def _norm(col: str) -> str:
    return SQL_NORMALIZE_EXPR.format(col=col)


def _posix(path: Path) -> str:
    return path.resolve().as_posix()


def _sql_path_literal(path: Path) -> str:
    """A quoted SQL string literal for `path`. DuckDB's CREATE VIEW cannot
    bind prepared-statement parameters (the view text has to be fully
    resolved SQL up front), so the path is escaped and inlined instead."""
    return "'" + _posix(path).replace("'", "''") + "'"


def _parse_dt(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


# --- Step 1: entity resolution ------------------------------------------


def _read_column(path: Path, col: str) -> list[str]:
    if not path.exists():
        return []
    df = pl.read_parquet(path)
    if col not in df.columns:
        return []
    return df[col].to_list()


def run_entity_resolution() -> dict[str, int]:
    """Rebuild team_aliases.parquet + player_aliases.parquet from the
    current lake state, and overwrite unresolved_entities.csv with whatever
    is unresolved right now. A full rebuild each call (not an incremental
    upsert) -- stale aliases (e.g. a removed override) must be able to
    disappear, which an upsert-forever table could never do.

    Output paths are recomputed here via lake.processed_path()/config.DATA_ROOT
    rather than read off entities.teams.TEAM_ALIASES_PARQUET /
    entities.players.PLAYER_ALIASES_PARQUET / entities.resolve.
    UNRESOLVED_ENTITIES_PATH directly -- those are plain module-level
    constants evaluated once at import time, so a test that
    monkeypatches config.DATA_PROCESSED/DATA_ROOT *after* this module graph
    has already been imported (which pytest's collection phase does for
    every test module up front) would otherwise still resolve to the
    pre-monkeypatch (real production) paths, silently overwriting the real
    data lake's alias tables with whatever tiny fixture that test built.
    Confirmed happening in this session: running the existing test suite
    was wiping data/processed/entities/player_aliases.parquet down to 0
    rows. Recomputing fresh here closes that gap without changing the
    public constants (still fine as read-only defaults for other callers)."""
    team_aliases_path = lake.processed_path("entities", "team_aliases.parquet")
    player_aliases_path = lake.processed_path("entities", "player_aliases.parquet")
    unresolved_path = config.DATA_ROOT / "reference" / "unresolved_entities.csv"

    teams_path = leaguepedia_table_path("teams")
    games_path = leaguepedia_table_path("scoreboard_games")
    rosters_path = leaguepedia_table_path("tournament_rosters")
    picks_path = leaguepedia_table_path("picks_and_bans")
    players_path = leaguepedia_table_path("players")
    scoreboard_players_path = leaguepedia_table_path("scoreboard_players")

    team_pages = pl.read_parquet(teams_path).to_dicts() if teams_path.exists() else []
    observed_team_names: set[str] = set()
    observed_team_names.update(_read_column(games_path, "team1"))
    observed_team_names.update(_read_column(games_path, "team2"))
    observed_team_names.update(_read_column(games_path, "win_team"))
    observed_team_names.update(_read_column(rosters_path, "team"))
    observed_team_names.update(_read_column(picks_path, "team1"))
    observed_team_names.update(_read_column(picks_path, "team2"))

    team_resolver = teams_mod.build_team_resolver(team_pages, observed_team_names)
    team_alias_df = team_resolver.to_alias_frame()
    team_aliases_path.parent.mkdir(parents=True, exist_ok=True)
    team_alias_df.write_parquet(team_aliases_path)

    player_pages = pl.read_parquet(players_path).to_dicts() if players_path.exists() else []
    name_link_pairs: list[tuple[str, str]] = []
    if scoreboard_players_path.exists():
        spdf = pl.read_parquet(scoreboard_players_path)
        name_link_pairs = list(zip(spdf["name"].to_list(), spdf["link"].to_list(), strict=True))

    player_resolver = players_mod.build_player_resolver(player_pages, name_link_pairs)
    player_alias_df = player_resolver.to_alias_frame()
    player_aliases_path.parent.mkdir(parents=True, exist_ok=True)
    player_alias_df.write_parquet(player_aliases_path)

    unresolved = team_resolver.unresolved + player_resolver.unresolved
    resolve_mod.write_unresolved_entities(unresolved, path=unresolved_path)

    # NOTE: collision_count() (the resolver's own bookkeeping), not
    # find_collisions() on the persisted alias frames -- EntityResolver
    # never persists a colliding normalized_alias in the first place (it's
    # a plain dict, one canonical_id per key), so find_collisions() applied
    # to team_alias_df/player_alias_df is always 0 by construction and
    # would silently under-report real dupes detected during this build.
    dupes = team_resolver.collision_count() + player_resolver.collision_count()
    return {
        "team_aliases": team_alias_df.height,
        "player_aliases": player_alias_df.height,
        "unresolved": len(unresolved),
        "entity_dupes": dupes,
    }


# --- Step 2: patches dimension -------------------------------------------


def rebuild_patches_table() -> int:
    """(Re)build data/processed/patches.parquet from every patch/date pair
    seen across ALL ingested ScoreboardGames rows (the full current lake,
    not just the most recent lp-ingest call) -- see patches.py for the merge
    semantics that keep release_date correct across incremental runs.

    Writes to a freshly-computed `lake.processed_path("patches.parquet")`
    rather than the module-level `patches_mod.PATCHES_PARQUET` default --
    see run_entity_resolution's docstring for why (test-isolation gap that
    was silently corrupting the real patches.parquet on every pytest run)."""
    patches_path = lake.processed_path("patches.parquet")
    games_path = leaguepedia_table_path("scoreboard_games")
    if not games_path.exists():
        return 0
    gdf = pl.read_parquet(games_path)
    observations: list[tuple[str, datetime]] = []
    for patch, dt_str in zip(gdf["patch"].to_list(), gdf["date_time_utc"].to_list(), strict=True):
        dt = _parse_dt(dt_str)
        if patch and dt:
            observations.append((patch, dt))
    rows = patches_mod.build_patches_table(observations)
    patches_mod.write_patches_parquet(rows, path=patches_path)
    return len(rows)


# --- Step 3: DuckDB views --------------------------------------------------

V_GAMES_SQL = f"""
CREATE OR REPLACE VIEW v_games AS
WITH base AS (
    SELECT
        g.game_id,
        g.match_id,
        g.overview_page,
        split_part(g.overview_page, '/', 1) AS league,
        g.overview_page AS tournament,
        CAST(g.date_time_utc AS TIMESTAMP) AS date,
        p.marketing_version AS patch_marketing,
        p.client_version AS patch_client,
        p.ordinal AS patch_ordinal,
        bta.canonical_id AS blue_team_id,
        rta.canonical_id AS red_team_id,
        wta.canonical_id AS winner_team_id,
        COALESCE(p.fearless_era, FALSE) AS fearless_era,
        COALESCE(p.first_selection_era, FALSE) AS first_selection_era,
        COALESCE(p.atakhan_era, FALSE) AS atakhan_era,
        ROW_NUMBER() OVER (
            PARTITION BY g.match_id ORDER BY CAST(g.date_time_utc AS TIMESTAMP)
        ) AS game_num_in_series
    FROM _raw_scoreboard_games g
    LEFT JOIN _raw_patches p ON p.marketing_version = g.patch
    LEFT JOIN _raw_team_aliases bta ON {_norm("g.team1")} = bta.normalized_alias
    LEFT JOIN _raw_team_aliases rta ON {_norm("g.team2")} = rta.normalized_alias
    LEFT JOIN _raw_team_aliases wta ON {_norm("g.win_team")} = wta.normalized_alias
)
SELECT *, MAX(game_num_in_series) OVER (PARTITION BY match_id) AS best_of_observed
FROM base
"""

V_GAME_PLAYERS_SQL = f"""
CREATE OR REPLACE VIEW v_game_players AS
SELECT
    sp.game_id,
    sp.match_id,
    pta.canonical_id AS player_id,
    sp.link AS player_link_raw,
    sp.team AS team_name_raw,
    tta.canonical_id AS team_id,
    sp.side,
    sp.role,
    sp.champion,
    TRY_CAST(sp.kills AS INTEGER) AS kills,
    TRY_CAST(sp.deaths AS INTEGER) AS deaths,
    TRY_CAST(sp.assists AS INTEGER) AS assists,
    TRY_CAST(sp.gold AS INTEGER) AS gold,
    TRY_CAST(sp.cs AS INTEGER) AS cs,
    sp.primary_tree,
    sp.secondary_tree,
    sp.keystone_rune,
    (sp.player_win = 'Yes') AS won
FROM _raw_scoreboard_players sp
LEFT JOIN _raw_player_aliases pta ON {_norm("sp.link")} = pta.normalized_alias
LEFT JOIN _raw_team_aliases tta ON {_norm("sp.team")} = tta.normalized_alias
"""

V_DRAFT_ACTIONS_SQL = f"""
CREATE OR REPLACE VIEW v_draft_actions AS
WITH order_lookup(side, action, slot, order_index) AS (VALUES {_DRAFT_ORDER_VALUES}),
unpivoted AS (
    SELECT pb.game_id, pb.match_id, pb.team1, pb.team2, 'team1' AS side, 'ban' AS action,
           u.champion, u.slot
    FROM _raw_picks_and_bans pb, UNNEST(pb.team1_bans) WITH ORDINALITY AS u(champion, slot)
    UNION ALL
    SELECT pb.game_id, pb.match_id, pb.team1, pb.team2, 'team2', 'ban', u.champion, u.slot
    FROM _raw_picks_and_bans pb, UNNEST(pb.team2_bans) WITH ORDINALITY AS u(champion, slot)
    UNION ALL
    SELECT pb.game_id, pb.match_id, pb.team1, pb.team2, 'team1', 'pick', u.champion, u.slot
    FROM _raw_picks_and_bans pb, UNNEST(pb.team1_picks) WITH ORDINALITY AS u(champion, slot)
    UNION ALL
    SELECT pb.game_id, pb.match_id, pb.team1, pb.team2, 'team2', 'pick', u.champion, u.slot
    FROM _raw_picks_and_bans pb, UNNEST(pb.team2_picks) WITH ORDINALITY AS u(champion, slot)
)
SELECT
    up.game_id,
    up.match_id,
    ol.order_index,
    up.action,
    up.champion,
    CASE up.side WHEN 'team1' THEN bta.canonical_id ELSE rta.canonical_id END AS team_id,
    up.side
FROM unpivoted up
JOIN order_lookup ol ON ol.side = up.side AND ol.action = up.action AND ol.slot = up.slot
LEFT JOIN _raw_team_aliases bta ON {_norm("up.team1")} = bta.normalized_alias
LEFT JOIN _raw_team_aliases rta ON {_norm("up.team2")} = rta.normalized_alias
ORDER BY up.game_id, ol.order_index
"""

V_PLAYER_CHAMP_HISTORY_SQL = """
CREATE OR REPLACE VIEW v_player_champ_history AS
SELECT
    gp.player_id,
    gp.champion,
    g.patch_marketing,
    g.patch_client,
    g.date,
    gp.won AS result_win
FROM v_game_players gp
JOIN v_games g ON g.game_id = gp.game_id
WHERE gp.player_id IS NOT NULL
"""

_EMPTY_PATCHES_VIEW_SQL = """
CREATE OR REPLACE VIEW _raw_patches AS
SELECT
    CAST(NULL AS VARCHAR) AS marketing_version,
    CAST(NULL AS VARCHAR) AS client_version,
    CAST(NULL AS INTEGER) AS ordinal,
    CAST(NULL AS BOOLEAN) AS fearless_era,
    CAST(NULL AS BOOLEAN) AS first_selection_era,
    CAST(NULL AS BOOLEAN) AS atakhan_era
WHERE FALSE
"""


@dataclass
class BuildViewsResult:
    patches_rows: int
    team_aliases: int
    player_aliases: int
    unresolved_entities: int
    entity_dupes: int
    views_created: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def build_views(duckdb_path: Path | None = None) -> BuildViewsResult:
    """Entity-resolve, rebuild the patches dimension, then create/refresh
    every view in data/riftquant.duckdb. Safe to rerun any time after
    lp-ingest adds more data."""
    duckdb_path = duckdb_path or DUCKDB_PATH
    duckdb_path.parent.mkdir(parents=True, exist_ok=True)

    entity_stats = run_entity_resolution()
    patches_rows = rebuild_patches_table()

    warnings: list[str] = []
    views_created: list[str] = []

    con = duckdb.connect(str(duckdb_path))
    try:
        # _raw_patches always exists (real data or a typed empty view) so
        # v_games' LEFT JOIN never binder-errors against a missing table --
        # every OTHER raw source below is a true lp-ingest prerequisite and
        # is skipped (with a warning) rather than faked when absent.
        # Paths recomputed fresh (not read off the *_mod module constants)
        # so this matches exactly what run_entity_resolution/
        # rebuild_patches_table just wrote above -- see run_entity_
        # resolution's docstring for why the module constants themselves
        # can be stale under a monkeypatched config.
        patches_path = lake.processed_path("patches.parquet")
        team_aliases_path = lake.processed_path("entities", "team_aliases.parquet")
        player_aliases_path = lake.processed_path("entities", "player_aliases.parquet")
        if patches_path.exists():
            literal = _sql_path_literal(patches_path)
            sql = f"CREATE OR REPLACE VIEW _raw_patches AS SELECT * FROM read_parquet({literal})"
            con.execute(sql)
        else:
            con.execute(_EMPTY_PATCHES_VIEW_SQL)
            warnings.append("patches.parquet not found; _raw_patches is an empty placeholder")

        required_sources = {
            "_raw_scoreboard_games": leaguepedia_table_path("scoreboard_games"),
            "_raw_scoreboard_players": leaguepedia_table_path("scoreboard_players"),
            "_raw_picks_and_bans": leaguepedia_table_path("picks_and_bans"),
            "_raw_team_aliases": team_aliases_path,
            "_raw_player_aliases": player_aliases_path,
        }
        available: set[str] = set()
        for view_name, path in required_sources.items():
            if path.exists():
                literal = _sql_path_literal(path)
                sql = f"CREATE OR REPLACE VIEW {view_name} AS SELECT * FROM read_parquet({literal})"
                con.execute(sql)
                available.add(view_name)
            else:
                warnings.append(f"{path} not found; {view_name} not created")

        if {"_raw_scoreboard_games", "_raw_team_aliases"} <= available:
            con.execute(V_GAMES_SQL)
            views_created.append("v_games")
        else:
            warnings.append("v_games skipped: missing prerequisite raw view(s)")

        if {"_raw_scoreboard_players", "_raw_player_aliases", "_raw_team_aliases"} <= available:
            con.execute(V_GAME_PLAYERS_SQL)
            views_created.append("v_game_players")
        else:
            warnings.append("v_game_players skipped: missing prerequisite raw view(s)")

        if {"_raw_picks_and_bans", "_raw_team_aliases"} <= available:
            con.execute(V_DRAFT_ACTIONS_SQL)
            views_created.append("v_draft_actions")
        else:
            warnings.append("v_draft_actions skipped: missing prerequisite raw view(s)")

        if {"v_games", "v_game_players"} <= set(views_created):
            con.execute(V_PLAYER_CHAMP_HISTORY_SQL)
            views_created.append("v_player_champ_history")
        else:
            warnings.append("v_player_champ_history skipped: v_games/v_game_players unavailable")
    finally:
        con.close()

    return BuildViewsResult(
        patches_rows=patches_rows,
        team_aliases=entity_stats["team_aliases"],
        player_aliases=entity_stats["player_aliases"],
        unresolved_entities=entity_stats["unresolved"],
        entity_dupes=entity_stats["entity_dupes"],
        views_created=views_created,
        warnings=warnings,
    )


# --- validate-m1 metrics ---------------------------------------------------


@dataclass
class ValidateM1Result:
    coverage: dict
    entity_dupes: dict[str, int]
    cross_check: list[dict]


def coverage_metrics(
    con: duckdb.DuckDBPyConnection, leagues: tuple[str, ...] = ("LCK", "LEC")
) -> dict:
    """Coverage % of `leagues` games having full 5v5 + draft order + parsed
    patch, per the M1 exit criterion."""
    placeholders = ", ".join("?" for _ in leagues)
    params = list(leagues)
    total = con.execute(
        f"SELECT COUNT(*) FROM v_games WHERE league IN ({placeholders})", params
    ).fetchone()[0]
    if total == 0:
        return {
            "total_games": 0,
            "full_5v5": 0,
            "has_draft_order": 0,
            "has_patch": 0,
            "full_coverage": 0,
            "coverage_pct": 0.0,
            "date_min": None,
            "date_max": None,
        }
    full_5v5 = con.execute(
        f"""
        SELECT COUNT(*) FROM v_games g WHERE g.league IN ({placeholders})
        AND (SELECT COUNT(*) FROM v_game_players gp
             WHERE gp.game_id = g.game_id AND gp.player_id IS NOT NULL) = 10
        """,
        params,
    ).fetchone()[0]
    has_draft = con.execute(
        f"""
        SELECT COUNT(*) FROM v_games g WHERE g.league IN ({placeholders})
        AND (SELECT COUNT(*) FROM v_draft_actions da WHERE da.game_id = g.game_id) = 20
        """,
        params,
    ).fetchone()[0]
    has_patch = con.execute(
        f"""
        SELECT COUNT(*) FROM v_games
        WHERE league IN ({placeholders}) AND patch_client IS NOT NULL
        """,
        params,
    ).fetchone()[0]
    full_all = con.execute(
        f"""
        SELECT COUNT(*) FROM v_games g WHERE g.league IN ({placeholders})
        AND g.patch_client IS NOT NULL
        AND (SELECT COUNT(*) FROM v_game_players gp
             WHERE gp.game_id = g.game_id AND gp.player_id IS NOT NULL) = 10
        AND (SELECT COUNT(*) FROM v_draft_actions da WHERE da.game_id = g.game_id) = 20
        """,
        params,
    ).fetchone()[0]
    date_min, date_max = con.execute(
        f"SELECT MIN(date), MAX(date) FROM v_games WHERE league IN ({placeholders})", params
    ).fetchone()
    return {
        "total_games": total,
        "full_5v5": full_5v5,
        "has_draft_order": has_draft,
        "has_patch": has_patch,
        "full_coverage": full_all,
        "coverage_pct": (full_all / total * 100.0),
        "date_min": date_min,
        "date_max": date_max,
    }


def entity_dupe_counts() -> dict[str, int]:
    """Count of entity dupes per the brief: DISTINCT normalized names that
    collide across 2+ canonical ids (same normalized name -> multiple
    canonical ids), per entity type. Read from
    data/reference/unresolved_entities.csv (written by
    run_entity_resolution/build_views) rather than the persisted alias
    parquet: EntityResolver never persists a colliding normalized_alias in
    the first place (ambiguous names are excluded, not arbitrarily picked),
    so the alias table itself is always collision-free by construction and
    can't answer this question -- the CSV's "ambiguous" rows are the only
    record of what WAS detected. validate-m1 runs as a separate process
    from build-views, hence reading the persisted report rather than
    needing a live EntityResolver."""
    counts: dict[str, set[str]] = {"team": set(), "player": set()}
    # Fresh, not resolve_mod.UNRESOLVED_ENTITIES_PATH -- see
    # run_entity_resolution's docstring (same module-constant staleness
    # issue; here it would just mis-READ under a monkeypatched config
    # rather than corrupt real data, but the fix is the same).
    path = config.DATA_ROOT / "reference" / "unresolved_entities.csv"
    if path.exists():
        with path.open("r", encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                if "ambiguous" not in (row.get("reason") or ""):
                    continue
                entity_type = row.get("entity_type", "")
                if entity_type in counts:
                    counts[entity_type].add(row.get("normalized_name", ""))
    return {k: len(v) for k, v in counts.items()}


def cross_check_game_index(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """Join rate between Leaguepedia-derived v_games and the lolesports
    game_index parquet, matched on normalized team-name pair + start-time
    proximity (<=12h) -- NOT ids, since no id is shared between the two
    sources. LPL is expected to show a much lower join rate: Leaguepedia has
    full LPL scoreboard coverage but the lolesports persisted API carries
    almost no LPL events (config.py, verified 2026-08-21) -- only a handful
    of LPL games exist in that index at all, so a near-zero LPL join rate
    here is expected, not a defect."""
    results: list[dict] = []
    for slug, tag in _CROSS_CHECK_LEAGUES:
        lp_rows = con.execute(
            "SELECT game_id, blue_team_id, red_team_id, date FROM v_games WHERE league = ?", [tag]
        ).fetchall()
        idx_path = lake.processed_path("game_index", f"{slug}.parquet")
        if not idx_path.exists() or not lp_rows:
            results.append(
                {
                    "league": slug,
                    "leaguepedia_games": len(lp_rows),
                    "game_index_games": 0,
                    "joined": 0,
                    "join_rate_pct": 0.0,
                }
            )
            continue

        idx_df = pl.read_parquet(idx_path)
        idx_keys = []
        for r in idx_df.select(
            ["team1_name", "team1_code", "team2_name", "team2_code", "start_time"]
        ).iter_rows(named=True):
            names = {
                resolve_mod.normalize_name(r["team1_name"] or ""),
                resolve_mod.normalize_name(r["team1_code"] or ""),
                resolve_mod.normalize_name(r["team2_name"] or ""),
                resolve_mod.normalize_name(r["team2_code"] or ""),
            }
            start = r["start_time"].replace(tzinfo=None) if r["start_time"] else None
            idx_keys.append((names, start))

        joined = 0
        for _game_id, blue_id, red_id, date in lp_rows:
            wanted = {
                resolve_mod.normalize_name(blue_id or ""),
                resolve_mod.normalize_name(red_id or ""),
            }
            for names, start in idx_keys:
                if (
                    (wanted & names)
                    and start is not None
                    and date is not None
                    and abs((start - date).total_seconds()) <= 12 * 3600
                ):
                    joined += 1
                    break

        results.append(
            {
                "league": slug,
                "leaguepedia_games": len(lp_rows),
                "game_index_games": idx_df.height,
                "joined": joined,
                "join_rate_pct": (joined / len(lp_rows) * 100.0) if lp_rows else 0.0,
            }
        )
    return results


def run_validate_m1(duckdb_path: Path | None = None) -> ValidateM1Result:
    duckdb_path = duckdb_path or DUCKDB_PATH
    if not duckdb_path.exists():
        raise FileNotFoundError(f"no duckdb file at {duckdb_path}; run build-views first")
    con = duckdb.connect(str(duckdb_path), read_only=True)
    try:
        coverage = coverage_metrics(con)
        cross_check = cross_check_game_index(con)
    finally:
        con.close()
    return ValidateM1Result(
        coverage=coverage, entity_dupes=entity_dupe_counts(), cross_check=cross_check
    )
