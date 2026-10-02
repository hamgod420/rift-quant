"""store/views.py end to end: entity resolution -> patches dimension ->
DuckDB views -> validate-m1 metrics.

Network-free: this builds a small synthetic parquet lake by hand (no ingest
calls), matching the column shapes ingest.leaguepedia's M1c functions
produce, then exercises build_views()/run_validate_m1() against it -- the
same pipeline the live CLI runs, minus the network.

Fixture: 2 LCK games in the same series (match_id M1).
  - G1: full data -- 10 scoreboard_players rows (5v5) + a complete 20-slot
    picks_and_bans row. TeamA beats TeamB.
  - G2: intentionally INCOMPLETE -- only 8 scoreboard_players rows and no
    picks_and_bans row at all, so it should fail the M1 coverage check.
game_index has exactly one row, matching G1 only (G2 is left unmatched) --
so the cross-check join rate should land at 50%.
"""

from __future__ import annotations

from datetime import UTC, datetime

import polars as pl
import pytest

from riftquant import config
from riftquant.ingest.leaguepedia import leaguepedia_table_path
from riftquant.store import lake, views

_PLAYERS = [f"P{i}" for i in range(1, 11)]  # P1-P5 TeamA, P6-P10 TeamB


def _scoreboard_games_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "game_id": ["G1", "G2"],
            "match_id": ["M1", "M1"],
            # G2 is deliberately >12h from the game_index fixture row below,
            # so only G1 should join in the cross-check test.
            "date_time_utc": ["2026-01-14 08:00:00", "2026-01-15 09:00:00"],
            "patch": ["26.03", "26.03"],
            "team1": ["TeamA", "TeamA"],
            "team2": ["TeamB", "TeamB"],
            "win_team": ["TeamA", "TeamB"],
            "overview_page": ["LCK/2026 Season/Spring", "LCK/2026 Season/Spring"],
        }
    )


def _scoreboard_players_df() -> pl.DataFrame:
    rows = []
    game_rosters = [("G1", _PLAYERS, "TeamA"), ("G2", _PLAYERS[:4] + _PLAYERS[5:9], "TeamB")]
    for game_id, side_players, win_team in game_rosters:
        for p in side_players:
            team = "TeamA" if p in _PLAYERS[:5] else "TeamB"
            rows.append(
                {
                    "unique_line": f"{game_id}-{p}",
                    "game_id": game_id,
                    "match_id": "M1",
                    "overview_page": "LCK/2026 Season/Spring",
                    "name": p,
                    "link": p,
                    "team": team,
                    "side": "1" if team == "TeamA" else "2",
                    "role": "Mid",
                    "role_number": "2",
                    "champion": "Azir",
                    "kills": "3",
                    "deaths": "1",
                    "assists": "5",
                    "gold": "12000",
                    "cs": "250",
                    "primary_tree": "Sorcery",
                    "secondary_tree": "Resolve",
                    "keystone_rune": "Arcane Comet",
                    "player_win": "Yes" if team == win_team else "No",
                    "date_time_utc": "2026-01-14 08:00:00",
                }
            )
    return pl.DataFrame(rows)


def _picks_and_bans_df() -> pl.DataFrame:
    # Only G1 gets a draft row -- G2 is missing one on purpose.
    return pl.DataFrame(
        {
            "unique_line": ["PB1"],
            "game_id": ["G1"],
            "match_id": ["M1"],
            "overview_page": ["LCK/2026 Season/Spring"],
            "team1": ["TeamA"],
            "team2": ["TeamB"],
            "winner": ["TeamA"],
            "team1_bans": [["Ban1", "Ban2", "Ban3", "Ban4", "Ban5"]],
            "team2_bans": [["Ban6", "Ban7", "Ban8", "Ban9", "Ban10"]],
            "team1_picks": [["Pick1", "Pick2", "Pick3", "Pick4", "Pick5"]],
            "team2_picks": [["Pick6", "Pick7", "Pick8", "Pick9", "Pick10"]],
        }
    )


def _teams_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "overview_page": ["TeamA", "TeamB"],
            "name": ["TeamA", "TeamB"],
            "short": ["TA", "TB"],
            "region": ["Korea", "Korea"],
            "is_disbanded": ["No", "No"],
            "renamed_to": ["", ""],
        }
    )


def _players_df() -> pl.DataFrame:
    return pl.DataFrame({"overview_page": _PLAYERS, "player": _PLAYERS, "name": _PLAYERS})


def _game_index_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "game_id": ["idx-1"],
            "team1_name": ["TeamA"],
            "team1_code": ["TA"],
            "team2_name": ["TeamB"],
            "team2_code": ["TB"],
            "start_time": [datetime(2026, 1, 14, 8, 5, 0, tzinfo=UTC)],  # close to G1 only
        }
    )


def _write_parquet(df: pl.DataFrame, path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def _write_fixture_lake(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "DATA_PROCESSED", tmp_path / "processed")

    _write_parquet(_scoreboard_games_df(), leaguepedia_table_path("scoreboard_games"))
    _write_parquet(_scoreboard_players_df(), leaguepedia_table_path("scoreboard_players"))
    _write_parquet(_picks_and_bans_df(), leaguepedia_table_path("picks_and_bans"))
    _write_parquet(_teams_df(), leaguepedia_table_path("teams"))
    _write_parquet(_players_df(), leaguepedia_table_path("players"))

    idx_path = lake.processed_path("game_index", "lck.parquet")
    idx_path.parent.mkdir(parents=True, exist_ok=True)
    _game_index_df().write_parquet(idx_path)


@pytest.fixture
def duckdb_path(tmp_path, monkeypatch):
    _write_fixture_lake(tmp_path, monkeypatch)
    return tmp_path / "riftquant.duckdb"


def test_build_views_end_to_end(duckdb_path) -> None:
    result = views.build_views(duckdb_path)

    assert result.warnings == []
    assert set(result.views_created) == {
        "v_games",
        "v_game_players",
        "v_draft_actions",
        "v_player_champ_history",
    }
    assert result.patches_rows == 1
    assert result.team_aliases >= 2
    assert result.player_aliases == 10
    assert result.unresolved_entities == 0
    assert result.entity_dupes == 0

    import duckdb as duckdb_mod

    con = duckdb_mod.connect(str(duckdb_path), read_only=True)
    try:
        assert con.execute("SELECT COUNT(*) FROM v_games").fetchone()[0] == 2

        g1 = con.execute(
            "SELECT blue_team_id, red_team_id, winner_team_id, patch_client, game_num_in_series, "
            "best_of_observed FROM v_games WHERE game_id = 'G1'"
        ).fetchone()
        assert g1 == ("TeamA", "TeamB", "TeamA", "16.3", 1, 2)

        gp_g1 = con.execute(
            "SELECT COUNT(*) FROM v_game_players WHERE game_id = 'G1'"
        ).fetchone()[0]
        gp_g2 = con.execute(
            "SELECT COUNT(*) FROM v_game_players WHERE game_id = 'G2'"
        ).fetchone()[0]
        assert (gp_g1, gp_g2) == (10, 8)
        resolved_g1 = con.execute(
            "SELECT COUNT(*) FROM v_game_players WHERE game_id = 'G1' AND player_id IS NOT NULL"
        ).fetchone()[0]
        assert resolved_g1 == 10

        draft_rows = con.execute(
            """
            SELECT order_index, action, team_id FROM v_draft_actions
            WHERE game_id = 'G1' ORDER BY order_index
            """
        ).fetchall()
        assert len(draft_rows) == 20
        assert [r[0] for r in draft_rows] == list(range(1, 21))
        assert draft_rows[0] == (1, "ban", "TeamA")  # team1 ban1 first
        assert draft_rows[1] == (2, "ban", "TeamB")  # team2 ban1 second
        draft_g2 = con.execute(
            "SELECT COUNT(*) FROM v_draft_actions WHERE game_id = 'G2'"
        ).fetchone()[0]
        assert draft_g2 == 0

        assert con.execute("SELECT COUNT(*) FROM v_player_champ_history").fetchone()[0] == 18
    finally:
        con.close()


def test_run_validate_m1_metrics(duckdb_path) -> None:
    views.build_views(duckdb_path)
    result = views.run_validate_m1(duckdb_path)

    cov = result.coverage
    assert cov["total_games"] == 2
    assert cov["full_5v5"] == 1
    assert cov["has_draft_order"] == 1
    assert cov["has_patch"] == 2
    assert cov["full_coverage"] == 1
    assert cov["coverage_pct"] == pytest.approx(50.0)

    assert result.entity_dupes == {"team": 0, "player": 0}

    by_league = {row["league"]: row for row in result.cross_check}
    assert by_league["lck"]["leaguepedia_games"] == 2
    assert by_league["lck"]["game_index_games"] == 1
    assert by_league["lck"]["joined"] == 1
    assert by_league["lck"]["join_rate_pct"] == pytest.approx(50.0)
    # No game_index file exists for these -- must report zero, not crash.
    assert by_league["lec"]["game_index_games"] == 0
    assert by_league["lpl"]["game_index_games"] == 0


def test_run_validate_m1_without_build_views_raises_clear_error(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="build-views"):
        views.run_validate_m1(tmp_path / "missing.duckdb")


def test_entity_dupe_counts_detects_a_real_collision(tmp_path, monkeypatch) -> None:
    # Regression test: entity_dupe_counts() must report collisions actually
    # DETECTED during resolution, not re-derive them from the persisted
    # alias table -- EntityResolver never persists a colliding
    # normalized_alias in the first place, so checking the alias table
    # itself would always read 0 regardless of what was found.
    monkeypatch.setattr(config, "DATA_PROCESSED", tmp_path / "processed")
    teams_df = pl.DataFrame(
        {
            "overview_page": ["Team Alpha", "TeamAlpha"],  # collide: both -> "teamalpha"
            "name": ["Team Alpha", "TeamAlpha"],
            "short": ["TAL", "TA2"],
            "region": ["Korea", "Korea"],
            "is_disbanded": ["No", "No"],
            "renamed_to": ["", ""],
        }
    )
    _write_parquet(teams_df, leaguepedia_table_path("teams"))

    stats = views.run_entity_resolution()
    assert stats["entity_dupes"] == 1

    assert views.entity_dupe_counts() == {"team": 1, "player": 0}
