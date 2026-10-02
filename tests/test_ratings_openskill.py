"""riftquant.ratings.openskill_ratings: rating update math vs hand-computed
examples (M2 brief, "Tests" -- "rating update math vs hand-computed
example"), new-player init, the mu_ctx/mu_meta offset trick, and basic
robustness (incomplete rosters, FFA flag wiring).

All fixtures build (games, players) frames directly (the same shape
`load_rating_inputs` produces) rather than going through DuckDB -- this
module's own math is the thing under test, not the SQL that feeds it (that
plumbing is covered by test_views.py / the CLI-level smoke test).
"""

from __future__ import annotations

from datetime import datetime

import polars as pl
import pytest
from openskill.models import PlackettLuce

from riftquant import config
from riftquant.ratings import openskill_ratings as osr


def _game_row(game_id: str, date: datetime, league: str, blue: str, red: str, winner: str) -> dict:
    return {
        "game_id": game_id,
        "match_id": game_id,
        "date": date,
        "league": league,
        "blue_team_id": blue,
        "red_team_id": red,
        "winner_team_id": winner,
    }


def _player_rows(game_id: str, side: str, player_ids: list[str]) -> list[dict]:
    return [
        {
            "game_id": game_id,
            "player_id": pid,
            "side": side,
            "kills": 3,
            "deaths": 2,
            "assists": 5,
            "gold": 12000,
        }
        for pid in player_ids
    ]


BLUE_TEAM_A = [f"A{i}" for i in range(1, 6)]
RED_TEAM_B = [f"B{i}" for i in range(1, 6)]


def _games_players_frames(
    games: list[dict], players: list[dict]
) -> tuple[pl.DataFrame, pl.DataFrame]:
    return pl.DataFrame(games), pl.DataFrame(players)


def test_incomplete_roster_game_is_skipped_not_crashed() -> None:
    games = [_game_row("G1", datetime(2026, 1, 1), "LCK", "TeamA", "TeamB", "TeamA")]
    # Only 4 red players -- an incomplete roster must be skipped, not crash.
    players = _player_rows("G1", "1", BLUE_TEAM_A) + _player_rows("G1", "2", RED_TEAM_B[:4])
    g, p = _games_players_frames(games, players)

    result = osr.compute_ratings(g, p)

    assert result.games_processed == 1
    assert result.games_rated == 0
    assert result.player_ratings.height == 0


def test_domestic_games_never_move_meta_from_default() -> None:
    games = [
        _game_row("G1", datetime(2026, 1, 1), "LCK", "TeamA", "TeamB", "TeamA"),
        _game_row("G2", datetime(2026, 1, 2), "LCK", "TeamA", "TeamB", "TeamA"),
        _game_row("G3", datetime(2026, 1, 3), "LCK", "TeamB", "TeamA", "TeamA"),
    ]
    players = []
    for gid, blue, red in [
        ("G1", BLUE_TEAM_A, RED_TEAM_B),
        ("G2", BLUE_TEAM_A, RED_TEAM_B),
        ("G3", RED_TEAM_B, BLUE_TEAM_A),
    ]:
        players += _player_rows(gid, "1", blue) + _player_rows(gid, "2", red)
    g, p = _games_players_frames(games, players)

    result = osr.compute_ratings(g, p)
    df = result.player_ratings

    # No international game occurred -- mu_meta_region/sigma must sit at the
    # untouched library defaults for every snapshot row.
    assert (df["mu_meta_region"] == config.RATING_DEFAULT_MU).all()
    # combined sigma = sqrt(sigma_ctx^2 + DEFAULT_SIGMA^2) >= DEFAULT_SIGMA,
    # and strictly greater once sigma_ctx has shrunk below its own start
    # (it never grows on its own), confirming meta's default sigma is
    # actually folded into the combined column, not silently zeroed.
    assert (df["sigma"] >= config.RATING_DEFAULT_SIGMA - 1e-9).all()

    # Team A won all 3 -- their final mu_ctx must exceed Team B's.
    last = df.sort("as_of").group_by("player_id").last()
    a_mu = last.filter(pl.col("player_id").is_in(BLUE_TEAM_A))["mu_ctx"].mean()
    b_mu = last.filter(pl.col("player_id").is_in(RED_TEAM_B))["mu_ctx"].mean()
    assert a_mu > b_mu


def test_new_player_debuts_at_the_current_league_mean_not_flat_default() -> None:
    # Team A (fixed roster) beats 6 different ONE-OFF opponent squads (30
    # unique players, each appearing in exactly one loss and never playing
    # again). Those 30 low-mu entries outnumber Team A's 5 elevated-mu
    # entries, so the LCK-wide mean mu_ctx across every currently-rated
    # player drifts measurably below 25.0 -- a debutant on yet another new
    # team should start at THAT drifted mean, not the flat 25.0 default
    # (a naive "always beats always loses" 2-team-only setup is actually a
    # poor test here: mu is approximately zero-sum across a closed pair, so
    # the pooled mean barely moves; many distinct one-off losers is what
    # actually displaces the pool average).
    games = []
    players = []
    for i in range(1, 7):
        opponent = [f"OPP{i}_{j}" for j in range(1, 6)]
        games.append(_game_row(f"G{i}", datetime(2026, 1, i), "LCK", "TeamA", f"Opp{i}", "TeamA"))
        players += _player_rows(f"G{i}", "1", BLUE_TEAM_A) + _player_rows(f"G{i}", "2", opponent)
    g, p = _games_players_frames(games, players)
    warmup = osr.compute_ratings(g, p)
    warmup_sorted = warmup.player_ratings.sort("as_of")
    all_ids = warmup_sorted["player_id"].unique().to_list()
    established_mean = sum(
        warmup_sorted.filter(pl.col("player_id") == pid).tail(1)["mu_ctx"].item() for pid in all_ids
    ) / len(all_ids)
    # Plackett-Luce/OpenSkill updates are close to zero-sum for a symmetric
    # starting population, so this shift is small in absolute terms -- but
    # it must be genuinely computed (nonzero, and matched exactly below),
    # not the library's untouched flat default.
    assert established_mean != pytest.approx(config.RATING_DEFAULT_MU, abs=0.01)

    # Replay warmup + one more game where NEWBIE joins a fresh 7th
    # one-off opponent squad against Team A.
    debut_roster = [f"OPP7_{j}" for j in range(1, 5)] + ["NEWBIE"]
    games2 = games + [_game_row("G7", datetime(2026, 1, 7), "LCK", "TeamA", "Opp7", "TeamA")]
    players2 = (
        players + _player_rows("G7", "1", BLUE_TEAM_A) + _player_rows("G7", "2", debut_roster)
    )
    g2, p2 = _games_players_frames(games2, players2)
    result2 = osr.compute_ratings(g2, p2)

    # Hand-computed check: replicate NEWBIE's expected update independently
    # using the openskill library directly. OPP7_1..4 are ALSO brand new in
    # G7, so (per the code path under test) they cold-start at the SAME
    # established mean as NEWBIE, not at NEWBIE's own value or each other's.
    model = PlackettLuce(mu=config.RATING_DEFAULT_MU, sigma=config.RATING_DEFAULT_SIGMA)
    last_before_g7 = warmup.player_ratings.sort("as_of")
    blue_ratings = []
    for pid in BLUE_TEAM_A:
        row = last_before_g7.filter(pl.col("player_id") == pid).tail(1)
        # The persisted "sigma" column is the COMBINED sigma
        # sqrt(sigma_ctx^2 + sigma_meta^2) (report 08 Eq 5); since no
        # international game has happened yet, sigma_meta still sits at the
        # untouched default, so sigma_ctx must be unwrapped back out before
        # feeding it to a domestic (contextual-only) rating update.
        combined_sigma = row["sigma"].item()
        ctx_sigma = (max(combined_sigma**2 - config.RATING_DEFAULT_SIGMA**2, 0.0)) ** 0.5
        blue_ratings.append(model.rating(mu=row["mu_ctx"].item(), sigma=ctx_sigma))
    red_ratings = [
        model.rating(mu=established_mean, sigma=config.RATING_DEFAULT_SIGMA) for _ in range(5)
    ]

    updated = model.rate(teams=[blue_ratings, red_ratings], scores=[1, 0])
    expected_newbie_mu = updated[1][4].mu

    actual_newbie_row = result2.player_ratings.filter(pl.col("player_id") == "NEWBIE")
    assert actual_newbie_row.height == 1
    assert actual_newbie_row["mu_ctx"].item() == pytest.approx(expected_newbie_mu, abs=1e-6)
    # And NOT close to what it would be if cold-started from the flat 25.0
    # default instead of the league mean (guards against silently reverting
    # to the library default).
    assert actual_newbie_row["mu_ctx"].item() != pytest.approx(config.RATING_DEFAULT_MU, abs=0.3)


def test_international_game_freezes_ctx_and_uses_offset_trick_on_meta() -> None:
    # Two domestic regions warmed up to different strengths, then one
    # Worlds game between them.
    lck_games = [
        _game_row(f"L{i}", datetime(2026, 1, i), "LCK", "TeamA", "TeamB", "TeamA")
        for i in range(1, 6)
    ]
    lec_games = [
        _game_row(f"E{i}", datetime(2026, 2, i), "LEC", "TeamC", "TeamD", "TeamD")
        for i in range(1, 6)
    ]
    TEAM_C = [f"C{i}" for i in range(1, 6)]
    TEAM_D = [f"D{i}" for i in range(1, 6)]
    players = []
    for i in range(1, 6):
        players += _player_rows(f"L{i}", "1", BLUE_TEAM_A) + _player_rows(f"L{i}", "2", RED_TEAM_B)
        players += _player_rows(f"E{i}", "1", TEAM_C) + _player_rows(f"E{i}", "2", TEAM_D)
    worlds_game = _game_row("W1", datetime(2026, 3, 1), "Worlds", "TeamA", "TeamD", "TeamA")
    players += _player_rows("W1", "1", BLUE_TEAM_A) + _player_rows("W1", "2", TEAM_D)

    games = lck_games + lec_games + [worlds_game]
    g, p = _games_players_frames(games, players)
    result = osr.compute_ratings(g, p)
    df = result.player_ratings

    assert result.international_games == 1

    ctx_before_worlds = {
        pid: df.filter((pl.col("player_id") == pid) & (pl.col("as_of") < datetime(2026, 3, 1)))
        .sort("as_of")
        .tail(1)["mu_ctx"]
        .item()
        for pid in BLUE_TEAM_A + TEAM_D
    }
    ctx_after_worlds = {
        pid: df.filter(pl.col("player_id") == pid).sort("as_of").tail(1)["mu_ctx"].item()
        for pid in BLUE_TEAM_A + TEAM_D
    }
    # Contextual ratings are FROZEN by an international game.
    for pid in BLUE_TEAM_A + TEAM_D:
        assert ctx_after_worlds[pid] == pytest.approx(ctx_before_worlds[pid], abs=1e-9)

    # Meta moved away from the default for both regions that played Worlds.
    meta_after = (
        df.filter(pl.col("player_id") == BLUE_TEAM_A[0])
        .sort("as_of")
        .tail(1)["mu_meta_region"]
        .item()
    )
    assert meta_after != pytest.approx(config.RATING_DEFAULT_MU, abs=1e-6)

    # Hand-computed cross-check of the offset trick for one LCK player
    # (blue, region "LCK"): rating_before = meta_mu + (ctx_mu - 3*ctx_sigma),
    # sigma = meta_sigma; replay the SAME 10-player Worlds update
    # independently with the library and compare the resulting meta value.
    model = PlackettLuce(mu=config.RATING_DEFAULT_MU, sigma=config.RATING_DEFAULT_SIGMA)

    def _pre_worlds(pid: str) -> tuple[float, float]:
        row = (
            df.filter((pl.col("player_id") == pid) & (pl.col("as_of") < datetime(2026, 3, 1)))
            .sort("as_of")
            .tail(1)
        )
        ctx_mu = row["mu_ctx"].item()
        sigma_total = row["sigma"].item()
        # meta sigma is the default pre-Worlds (never touched yet); ctx
        # sigma = sqrt(sigma_total^2 - meta_sigma^2).
        meta_sigma = config.RATING_DEFAULT_SIGMA
        ctx_sigma = (max(sigma_total**2 - meta_sigma**2, 0.0)) ** 0.5
        return ctx_mu, ctx_sigma

    blue_offset = []
    for pid in BLUE_TEAM_A:
        ctx_mu, ctx_sigma = _pre_worlds(pid)
        theta = ctx_mu - 3.0 * ctx_sigma
        blue_offset.append(
            model.rating(mu=config.RATING_DEFAULT_MU + theta, sigma=config.RATING_DEFAULT_SIGMA)
        )
    red_offset = []
    thetas_d = []
    for pid in TEAM_D:
        ctx_mu, ctx_sigma = _pre_worlds(pid)
        theta = ctx_mu - 3.0 * ctx_sigma
        thetas_d.append(theta)
        red_offset.append(
            model.rating(mu=config.RATING_DEFAULT_MU + theta, sigma=config.RATING_DEFAULT_SIGMA)
        )

    updated = model.rate(teams=[blue_offset, red_offset], scores=[1, 0])
    expected_region_d_meta = (
        sum(u.mu - theta for u, theta in zip(updated[1], thetas_d, strict=True)) / 5
    )

    actual_region_d_meta = (
        df.filter(pl.col("player_id") == TEAM_D[0]).sort("as_of").tail(1)["mu_meta_region"].item()
    )
    assert actual_region_d_meta == pytest.approx(expected_region_d_meta, abs=1e-6)


def test_ffa_flag_changes_the_update_versus_team_result_mode() -> None:
    games = [_game_row("G1", datetime(2026, 1, 1), "LCK", "TeamA", "TeamB", "TeamA")]
    # Give one blue player a much stronger box score than their teammates so
    # FFA's performance-based ranking diverges from the flat team-result
    # win/loss split.
    players = _player_rows("G1", "1", BLUE_TEAM_A) + _player_rows("G1", "2", RED_TEAM_B)
    for row in players:
        if row["player_id"] == "A1":
            row["kills"], row["deaths"], row["assists"], row["gold"] = 15, 0, 10, 20000
    g, p = _games_players_frames(games, players)

    team_result = osr.compute_ratings(g, p, ffa=False)
    ffa = osr.compute_ratings(g, p, ffa=True)

    a1_team_result = team_result.player_ratings.filter(pl.col("player_id") == "A1")["mu_ctx"].item()
    a1_ffa = ffa.player_ratings.filter(pl.col("player_id") == "A1")["mu_ctx"].item()
    assert a1_team_result != pytest.approx(a1_ffa, abs=1e-6)


def test_is_international_league_matches_case_and_separator_insensitively() -> None:
    assert osr.is_international_league("Worlds")
    assert osr.is_international_league("MSI")
    assert osr.is_international_league("First Stand")
    assert osr.is_international_league("first_stand")
    assert osr.is_international_league("lta_cross")
    assert not osr.is_international_league("LCK")
    assert not osr.is_international_league(None)
    assert not osr.is_international_league("")
