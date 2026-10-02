"""Player skill ratings via OpenSkill (Plackett-Luce), mu_ctx / mu_meta split
(M2 brief, "ratings/" layer; method per docs/research/08-pandaskill-method.md
S2.2-2.3, "PandaSkill" -- PandaScore, arXiv 2501.10049).

Two-component rating per player: `mu = mu_ctx + mu_meta`. `mu_ctx` is a
purely in-region contextual rating, updated by DOMESTIC games only.
`mu_meta` lives on the REGION (shared identically by every player currently
attributed to that region), updated by INTERNATIONAL games only (Worlds/
MSI/First Stand/LTA-cross, per config.INTERNATIONAL_LEAGUES) via the
"offset trick" (report 08 Eq 6-9): a player enters the international game's
rating update as `meta_mu + (ctx_mu - 3*ctx_sigma)` -- their region's
current meta strength, nudged by a fixed snapshot of their own in-region
standing -- so the contextual layer is read but never itself modified by
international results (no feedback loop back into domestic form). After the
update, the per-player offset is subtracted back out and everyone sharing a
region averages their post-update meta values (arithmetic mean of mu,
quadratic/RMS mean of sigma).

Default rating mode is TEAM-RESULT (two 5-player teams ranked by game
win/loss) per the M2 brief; PandaSkill's own FREE-FOR-ALL mode (all 10
players ranked against each other) is available behind `ffa=True` for a
later side-by-side comparison, default OFF, because report 08's own
ablation table shows FFA hurts raw accuracy on its own (it only pays off
paired with the meta layer, and even then it's a mixed result -- see report
08 S4). FFA needs a per-player "how well did they play" score to rank by;
PandaSkill's real answer is a whole separate trained per-role XGBoost
performance-score model (PScore), which is out of scope for M2 (not listed
under "Layers to build"). `_ffa_perf_scores` below is a crude box-score
composite standing in for that model -- NOT validated as a performance
estimator, only good enough to make the FFA code path exercisable. Since
the default is FFA=False, this proxy never affects the shipped rating.

No inactivity/time decay in v0, matching PandaSkill (report 08 S2.2): a
player benched for a full split keeps their exact (mu, sigma) until their
next game. This is a known, deliberate v0 limitation, not an oversight.

Roster handling: the rating follows the PLAYER (`player_id`), never the
team; a "team rating" is a downstream aggregate of that game's 5 starters,
computed in riftquant.features.pregame, not here.

Sequential replay, not a vectorized batch op: rating updates are a
stateful simulation over games in chronological order (like Elo), which is
not expressible as a polars group-by/window aggregation -- PandaSkill's own
reference implementation processes games the same way (report 08 S2.1,
"global sort" + sequential FFA/team updates). At subset (~1k games) and
full-backfill (~5-8k games) scale this is a Python loop of O(games) with
O(1) work per player (10 players/game), which runs in low single-digit
seconds -- nowhere near the M2 brief's 5-minute budget, which targets
feature *building* (the genuinely large, per-row-over-many-games join
workload), not this replay.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb
import polars as pl
from openskill.models import PlackettLuce
from openskill.models.weng_lin.plackett_luce import PlackettLuceRating

from riftquant import config
from riftquant.store.lake import duckdb_to_polars


@dataclass
class _PlayerCtx:
    mu: float
    sigma: float
    games_played: int = 0
    last_region: str | None = None


@dataclass
class _RegionMeta:
    mu: float
    sigma: float


@dataclass
class RatingsResult:
    player_ratings: pl.DataFrame  # persisted schema: see build_ratings docstring
    games_processed: int
    games_rated: int
    international_games: int
    new_players_initialized: int


def is_international_league(league: str | None) -> bool:
    """True for a Worlds/MSI/First-Stand/LTA-cross style cross-region event
    (config.INTERNATIONAL_LEAGUES), False for a domestic league. Matched
    case-insensitively with whitespace stripped so "First Stand" and
    "first_stand" both resolve the same way regardless of which naming
    convention (Leaguepedia's OverviewPage prefix vs. lolesports' own league
    slug) happens to be in play."""
    if not league:
        return False
    return league.lower().replace(" ", "").replace("-", "") in config.INTERNATIONAL_LEAGUES


def load_rating_inputs(duckdb_path: Path) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Pull the minimal chronological game/roster data build-ratings needs
    from the DuckDB views. Games with no resolved winner or side (can't
    drive a win/loss update) are excluded up front."""
    con = duckdb.connect(str(duckdb_path), read_only=True)
    try:
        games = duckdb_to_polars(
            con,
            """
            SELECT game_id, match_id, date, league, blue_team_id, red_team_id, winner_team_id
            FROM v_games
            WHERE date IS NOT NULL
              AND blue_team_id IS NOT NULL
              AND red_team_id IS NOT NULL
              AND winner_team_id IS NOT NULL
            ORDER BY date, game_id
            """,
        )
        players = duckdb_to_polars(
            con,
            """
            SELECT game_id, player_id, side, kills, deaths, assists, gold
            FROM v_game_players
            WHERE player_id IS NOT NULL AND side IN ('1', '2')
            """,
        )
    finally:
        con.close()
    return games, players


def _ffa_perf_scores(rows: list[dict]) -> list[float]:
    """v0 stand-in for PandaSkill's trained PScore model -- see module
    docstring. Higher is better, consistent with openskill's `scores`
    semantics (magnitude, not just order, affects the update size)."""
    scores = []
    for r in rows:
        k = float(r.get("kills") or 0)
        d = float(r.get("deaths") or 0)
        a = float(r.get("assists") or 0)
        g = float(r.get("gold") or 0)
        scores.append(k + 0.5 * a - d + g / 1000.0)
    return scores


def compute_ratings(
    games: pl.DataFrame, players: pl.DataFrame, *, ffa: bool = False
) -> RatingsResult:
    """Replay `games` (already sorted by date) in order, updating every
    player's contextual + region-meta rating, and emit one snapshot row per
    player per game they played -- the point-in-time history
    riftquant.features.asof.asof_join_latest joins against downstream.
    """
    model = PlackettLuce(mu=config.RATING_DEFAULT_MU, sigma=config.RATING_DEFAULT_SIGMA)

    ctx: dict[str, _PlayerCtx] = {}
    meta: dict[str, _RegionMeta] = {}

    players_by_game: dict[str, list[dict]] = {}
    for row in players.iter_rows(named=True):
        players_by_game.setdefault(row["game_id"], []).append(row)

    snapshot_rows: list[dict] = []
    new_player_count = 0
    international_count = 0
    games_rated = 0

    def _region_mean(region: str) -> float:
        mus = [p.mu for p in ctx.values() if p.last_region == region]
        return sum(mus) / len(mus) if mus else config.RATING_DEFAULT_MU

    def _get_or_init_ctx(player_id: str, region: str) -> _PlayerCtx:
        nonlocal new_player_count
        p = ctx.get(player_id)
        if p is None:
            # New player init: league-mean prior with high sigma (M2 brief).
            # mu starts at the CURRENT mean mu_ctx of every already-rated
            # player in this region (as of this point in the chronological
            # sweep) rather than the flat library default, so a debutant on
            # an established strong/weak region starts closer to their
            # future peers than a neutral 25.0; sigma keeps the library's
            # own high-uncertainty cold-start value either way.
            p = _PlayerCtx(mu=_region_mean(region), sigma=config.RATING_DEFAULT_SIGMA)
            ctx[player_id] = p
            new_player_count += 1
        return p

    def _get_or_init_meta(region: str) -> _RegionMeta:
        m = meta.get(region)
        if m is None:
            m = _RegionMeta(mu=config.RATING_DEFAULT_MU, sigma=config.RATING_DEFAULT_SIGMA)
            meta[region] = m
        return m

    for g in games.iter_rows(named=True):
        roster = players_by_game.get(g["game_id"], [])
        blue = [r for r in roster if r["side"] == "1"]
        red = [r for r in roster if r["side"] == "2"]
        if len(blue) != 5 or len(red) != 5:
            continue  # no full 5v5 roster for this game -- nothing to update

        games_rated += 1
        league = g["league"] or ""
        is_intl = is_international_league(league)
        if is_intl:
            international_count += 1

        def _region_for(pid: str, *, _league=league, _is_intl=is_intl) -> str:
            if not _is_intl:
                return _league
            prior = ctx.get(pid)
            return prior.last_region if (prior and prior.last_region) else _league

        for r in roster:
            _get_or_init_ctx(r["player_id"], _region_for(r["player_id"]))

        blue_won = g["winner_team_id"] == g["blue_team_id"]
        regions_in_game = {r["player_id"]: _region_for(r["player_id"]) for r in roster}

        if not is_intl:
            blue_r = [
                model.rating(mu=ctx[r["player_id"]].mu, sigma=ctx[r["player_id"]].sigma)
                for r in blue
            ]
            red_r = [
                model.rating(mu=ctx[r["player_id"]].mu, sigma=ctx[r["player_id"]].sigma)
                for r in red
            ]
            if ffa:
                order = blue + red
                scores = _ffa_perf_scores(order)
                updated = model.rate(teams=[[r] for r in blue_r + red_r], scores=scores)
                for r, team in zip(order, updated, strict=True):
                    p = ctx[r["player_id"]]
                    p.mu, p.sigma = team[0].mu, team[0].sigma
            else:
                scores = [1, 0] if blue_won else [0, 1]
                updated = model.rate(teams=[blue_r, red_r], scores=scores)
                for side_players, side_updated in zip([blue, red], updated, strict=True):
                    for r, new_r in zip(side_players, side_updated, strict=True):
                        p = ctx[r["player_id"]]
                        p.mu, p.sigma = new_r.mu, new_r.sigma
            for r in roster:
                p = ctx[r["player_id"]]
                p.games_played += 1
                p.last_region = league
        else:
            # Offset trick (report 08 Eq 6-9): freeze contextual ratings,
            # update only the region-shared meta layer.
            for region in set(regions_in_game.values()):
                _get_or_init_meta(region)

            def _offset_rating(r: dict) -> PlackettLuceRating:
                p = ctx[r["player_id"]]
                m = meta[regions_in_game[r["player_id"]]]
                theta = p.mu - 3.0 * p.sigma
                return model.rating(mu=m.mu + theta, sigma=m.sigma)

            blue_off = [_offset_rating(r) for r in blue]
            red_off = [_offset_rating(r) for r in red]
            order = blue + red
            if ffa:
                scores = _ffa_perf_scores(order)
                updated = model.rate(teams=[[r] for r in blue_off + red_off], scores=scores)
                flat_new = [team[0] for team in updated]
            else:
                scores = [1, 0] if blue_won else [0, 1]
                updated = model.rate(teams=[blue_off, red_off], scores=scores)
                flat_new = list(updated[0]) + list(updated[1])

            new_meta_by_player: dict[str, tuple[float, float]] = {}
            for r, new_r in zip(order, flat_new, strict=True):
                p = ctx[r["player_id"]]
                theta = p.mu - 3.0 * p.sigma
                new_meta_by_player[r["player_id"]] = (new_r.mu - theta, new_r.sigma)

            for region in set(regions_in_game.values()):
                members = [pid for pid, reg in regions_in_game.items() if reg == region]
                mus = [new_meta_by_player[pid][0] for pid in members]
                sigmas = [new_meta_by_player[pid][1] for pid in members]
                m = meta[region]
                m.mu = sum(mus) / len(mus)
                m.sigma = (sum(s * s for s in sigmas) / len(sigmas)) ** 0.5

            for r in roster:
                ctx[r["player_id"]].games_played += 1
                # contextual rating + last_region are untouched by an
                # international game -- only meta and games_played move.

        as_of = g["date"]
        for r in roster:
            pid = r["player_id"]
            p = ctx[pid]
            region = regions_in_game[pid]
            m = meta.get(region)
            mu_meta_region = m.mu if m else config.RATING_DEFAULT_MU
            sigma_meta = m.sigma if m else config.RATING_DEFAULT_SIGMA
            combined_sigma = (p.sigma**2 + sigma_meta**2) ** 0.5
            snapshot_rows.append(
                {
                    "player_id": pid,
                    "as_of": as_of,
                    "mu_ctx": p.mu,
                    "mu_meta_region": mu_meta_region,
                    "sigma": combined_sigma,
                    "games_played": p.games_played,
                }
            )

    schema = {
        "player_id": pl.Utf8,
        "as_of": pl.Datetime,
        "mu_ctx": pl.Float64,
        "mu_meta_region": pl.Float64,
        "sigma": pl.Float64,
        "games_played": pl.Int64,
    }
    out = (
        pl.DataFrame(snapshot_rows, schema=schema) if snapshot_rows else pl.DataFrame(schema=schema)
    )

    return RatingsResult(
        player_ratings=out,
        games_processed=games.height,
        games_rated=games_rated,
        international_games=international_count,
        new_players_initialized=new_player_count,
    )


def build_ratings(
    duckdb_path: Path | None = None,
    out_path: Path | None = None,
    *,
    ffa: bool | None = None,
) -> RatingsResult:
    """Full build-ratings entry point: read v_games/v_game_players, replay
    ratings in order, write player_ratings.parquet
    (player_id, as_of, mu_ctx, mu_meta_region, sigma, games_played) -- one
    row per player per game played, the history table every downstream
    as-of join keys off of.
    """
    duckdb_path = duckdb_path or (config.DATA_ROOT / "riftquant.duckdb")
    out_path = out_path or config.PLAYER_RATINGS_PARQUET
    ffa = config.RATINGS_FFA_DEFAULT if ffa is None else ffa

    games, players = load_rating_inputs(duckdb_path)
    result = compute_ratings(games, players, ffa=ffa)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    result.player_ratings.write_parquet(out_path)
    return result
