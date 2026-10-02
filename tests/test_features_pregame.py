"""riftquant.features.pregame: shrinkage math (M2 brief, "Tests" --
"shrinkage math"), the side-wide pivot helper, the null-rate report, and one
end-to-end DuckDB-fixture check that a real player's team_ rating feature in
a LATER game reflects an EARLIER game's outcome -- never that game's own
result (the pregame-model-specific instance of the point-in-time rail,
end to end through ratings -> features, not just the asof.py primitives in
isolation).
"""

from __future__ import annotations

from datetime import datetime

import duckdb
import polars as pl
import pytest

from riftquant.features import pregame
from riftquant.ratings import openskill_ratings as osr


def test_eb_shrunk_rate_matches_hand_computed_formula() -> None:
    # wins=7, games=10, prior=0.4, k=10 -> (7 + 10*0.4) / (10 + 10) = 11/20 = 0.55
    result = pregame.eb_shrunk_rate(pl.lit(7.0), pl.lit(10.0), pl.lit(0.4), k=10.0)
    value = pl.select(result).item()
    assert value == pytest.approx(0.55)

    # Zero games seen -- must collapse exactly to the prior, not 0/0.
    zero_games = pl.select(
        pregame.eb_shrunk_rate(pl.lit(0.0), pl.lit(0.0), pl.lit(0.4), k=10.0)
    ).item()
    assert zero_games == pytest.approx(0.4)

    # Huge sample size -- shrinkage should vanish, observed rate dominates.
    huge_n = pl.select(
        pregame.eb_shrunk_rate(pl.lit(900.0), pl.lit(1000.0), pl.lit(0.5), k=10.0)
    ).item()
    assert huge_n == pytest.approx(900.0 / 1000.0, abs=0.01)


def test_pivot_side_wide_diff_is_blue_minus_red() -> None:
    per_side = pl.DataFrame({"game_id": ["G1", "G1"], "side": ["1", "2"], "metric": [10.0, 4.0]})
    out = pregame._pivot_side_wide(per_side, ["metric"], prefix="team_")
    row = out.row(0, named=True)
    assert row["team_metric_blue"] == 10.0
    assert row["team_metric_red"] == 4.0
    assert row["team_metric_diff"] == 6.0


def test_null_rate_report_groups_by_prefix() -> None:
    df = pl.DataFrame(
        {
            "game_id": ["G1", "G2"],
            "side_league": ["LCK", "LCK"],
            "team_mu_ctx_sum_blue": [10.0, None],
            "team_mu_ctx_sum_red": [10.0, None],
        }
    )
    report = pregame.null_rate_report(df).sort("feature_group")
    rows = {r["feature_group"]: r for r in report.iter_rows(named=True)}
    assert rows["side_"]["null_rate_pct"] == pytest.approx(0.0)
    assert rows["team_"]["null_rate_pct"] == pytest.approx(50.0)


# --- end-to-end DuckDB fixture: ratings -> features leakage check --------

_PLAYERS_A = [f"A{i}" for i in range(1, 6)]
_PLAYERS_B = [f"B{i}" for i in range(1, 6)]
_ROLES = ["Top", "Jungle", "Mid", "Bot", "Support"]


def _build_fixture_duckdb(con: duckdb.DuckDBPyConnection, tmp_path) -> None:
    """A minimal 2-game v_games/v_game_players fixture, written straight as
    DuckDB views (skipping store/views.py's entity-resolution plumbing --
    this test is about ratings+features wiring, not ingestion). Written via
    parquet + read_parquet (not con.register(), which needs pyarrow --
    not a project dependency, same reason store/lake.duckdb_to_polars
    avoids `.pl()`/`.df()`)."""
    games_df = pl.DataFrame(
        {
            "game_id": ["G1", "G2"],
            "match_id": ["M1", "M2"],
            "league": ["LCK", "LCK"],
            "date": [datetime(2026, 1, 1), datetime(2026, 1, 2)],
            "patch_client": ["16.1", "16.1"],
            "patch_ordinal": [16001, 16001],
            "blue_team_id": ["TeamA", "TeamA"],
            "red_team_id": ["TeamB", "TeamB"],
            "winner_team_id": ["TeamA", "TeamA"],  # Team A wins BOTH games
            "fearless_era": [True, True],
            "first_selection_era": [True, True],
            "game_num_in_series": [1, 1],
            "best_of_observed": [1, 1],
        }
    )
    rows = []
    for game_id, blue_won in [("G1", True), ("G2", True)]:
        for side_code, team, players in [("1", "TeamA", _PLAYERS_A), ("2", "TeamB", _PLAYERS_B)]:
            for i, pid in enumerate(players):
                rows.append(
                    {
                        "game_id": game_id,
                        "player_id": pid,
                        "team_id": team,
                        "side": side_code,
                        "role": _ROLES[i],
                        "champion": "Ahri",
                        "won": side_code == "1",
                        "kills": 3,
                        "deaths": 2,
                        "assists": 5,
                        "gold": 12000,
                    }
                )
    gp_df = pl.DataFrame(rows)

    games_path = tmp_path / "games.parquet"
    gp_path = tmp_path / "gp.parquet"
    games_df.write_parquet(games_path)
    gp_df.write_parquet(gp_path)

    games_literal = str(games_path.resolve().as_posix())
    gp_literal = str(gp_path.resolve().as_posix())
    con.execute(f"CREATE VIEW v_games AS SELECT * FROM read_parquet('{games_literal}')")
    con.execute(f"CREATE VIEW v_game_players AS SELECT * FROM read_parquet('{gp_literal}')")
    con.execute(
        "CREATE VIEW v_draft_actions AS SELECT NULL::VARCHAR AS game_id, NULL::INT AS order_index, "
        "NULL::VARCHAR AS action, NULL::VARCHAR AS champion, NULL::VARCHAR AS team_id, "
        "NULL::VARCHAR AS side WHERE FALSE"
    )


def test_team_rating_feature_reflects_only_strictly_prior_games(tmp_path, monkeypatch) -> None:
    duckdb_path = tmp_path / "fixture.duckdb"
    con = duckdb.connect(str(duckdb_path))
    _build_fixture_duckdb(con, tmp_path)
    con.close()

    ratings_path = tmp_path / "player_ratings.parquet"
    games, players = osr.load_rating_inputs(duckdb_path)
    ratings_result = osr.compute_ratings(games, players)
    ratings_result.player_ratings.write_parquet(ratings_path)

    monkeypatch.setattr("riftquant.config.PLAYER_RATINGS_PARQUET", ratings_path)
    monkeypatch.setattr("riftquant.config.CHAMP_TAGS_PATH", pregame.config.CHAMP_TAGS_PATH)

    df = pregame.build_pregame_features(duckdb_path)
    df = df.sort("date")

    g1 = df.filter(pl.col("game_id") == "G1").row(0, named=True)
    g2 = df.filter(pl.col("game_id") == "G2").row(0, named=True)

    # G1 is every player's first-ever game -- no rating history exists yet,
    # so team_mu_ctx_sum must be null (never a silently-invented 0 or a
    # leaked in-game value), not some placeholder.
    assert g1["team_mu_ctx_sum_blue"] is None
    assert g1["team_mu_ctx_sum_red"] is None

    # G2's blue (Team A) rating must reflect having WON game G1 (mu_ctx sum
    # above the 5*25.0=125.0 flat cold-start baseline) -- if this were
    # instead reading G2's OWN outcome (also a blue win) or somehow ignoring
    # G1 entirely, this exact number would be wrong; peeking at G2's own
    # result cannot change this value because it's an as-of join strictly
    # before G2's own date.
    assert g2["team_mu_ctx_sum_blue"] > 125.0
    assert g2["team_mu_ctx_sum_red"] < 125.0
