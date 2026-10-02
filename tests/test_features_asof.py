"""riftquant.features.asof: the central point-in-time toolkit (M2 brief,
"Tests" -- "as-of join correctness (constructed mini-fixture where peeking
would flip the answer)").
"""

from __future__ import annotations

from datetime import datetime

import polars as pl
import pytest

from riftquant.features import asof


def test_asof_join_latest_excludes_exact_timestamp_self_row_and_the_future() -> None:
    # History has a row at EXACTLY G1's own timestamp (simulating a rating
    # snapshot the game itself produced) and a row strictly AFTER G1 but
    # before G2. Peeking at either would flip the joined value: including
    # the t=10:00 row would answer 999 instead of 1 for G1; including the
    # t=10:30 row for G1 would answer 2 instead of 1.
    target = pl.DataFrame(
        {
            "player_id": ["P1", "P1"],
            "game_id": ["G1", "G2"],
            "date": [datetime(2026, 1, 1, 10, 0), datetime(2026, 1, 1, 11, 0)],
        }
    )
    history = pl.DataFrame(
        {
            "player_id": ["P1", "P1", "P1"],
            "as_of": [
                datetime(2026, 1, 1, 9, 0),
                datetime(2026, 1, 1, 10, 0),  # exact match to G1 -- must be excluded
                datetime(2026, 1, 1, 10, 30),  # after G1, before G2
            ],
            "val": [1, 999, 2],
        }
    )

    joined = asof.asof_join_latest(
        target, history, by=["player_id"], target_ts="date", history_ts="as_of"
    )
    result = dict(zip(joined["game_id"].to_list(), joined["val"].to_list(), strict=True))

    assert result == {"G1": 1, "G2": 2}


def test_asof_join_latest_no_qualifying_history_is_null() -> None:
    target = pl.DataFrame({"player_id": ["NEW"], "date": [datetime(2026, 1, 1)]})
    history = pl.DataFrame({"player_id": ["OTHER"], "as_of": [datetime(2025, 1, 1)], "val": [5]})

    joined = asof.asof_join_latest(
        target, history, by=["player_id"], target_ts="date", history_ts="as_of"
    )

    assert joined["val"].to_list() == [None]


def test_asof_join_latest_preserves_target_row_order() -> None:
    target = pl.DataFrame(
        {
            "player_id": ["P1", "P1", "P1"],
            "game_id": ["G3", "G1", "G2"],
            "date": [
                datetime(2026, 1, 3),
                datetime(2026, 1, 1),
                datetime(2026, 1, 2),
            ],
        }
    )
    history = pl.DataFrame({"player_id": ["P1"], "as_of": [datetime(2025, 12, 31)], "val": [1]})

    joined = asof.asof_join_latest(
        target, history, by=["player_id"], target_ts="date", history_ts="as_of"
    )

    assert joined["game_id"].to_list() == ["G3", "G1", "G2"]


def test_strictly_prior_stats_counts_and_sums_only_earlier_rows() -> None:
    df = pl.DataFrame(
        {
            "player_id": ["P1", "P1", "P1", "P2"],
            "date": [
                datetime(2026, 1, 1),
                datetime(2026, 1, 2),
                datetime(2026, 1, 3),
                datetime(2026, 1, 1),
            ],
            "won": [1, 0, 1, 1],
        }
    )
    out = asof.strictly_prior_stats(df, group_by=["player_id"], order_by="date", value_col="won")
    out = out.sort("date")
    p1 = out.filter(pl.col("player_id") == "P1")

    assert p1["won_n_before"].to_list() == [0, 1, 2]
    assert p1["won_sum_before"].to_list() == [0.0, 1.0, 1.0]
    # P2's single row must never see P1's history (separate group).
    p2 = out.filter(pl.col("player_id") == "P2")
    assert p2["won_n_before"].to_list() == [0]


def test_strictly_prior_last_timestamp_is_null_on_first_occurrence() -> None:
    df = pl.DataFrame(
        {
            "player_id": ["P1", "P1", "P1"],
            "champion": ["Ahri", "Ahri", "Zed"],
            "date": [datetime(2026, 1, 1), datetime(2026, 1, 5), datetime(2026, 1, 10)],
        }
    )
    out = asof.strictly_prior_last_timestamp(
        df, group_by=["player_id", "champion"], order_by="date", alias="last_played"
    ).sort("date")

    assert out["last_played"].to_list() == [None, datetime(2026, 1, 1), None]


def test_strictly_prior_rolling_mean_matches_hand_computed_trailing_window() -> None:
    # 3 losses then 2 wins; the 3rd game's rolling-2 value must be the mean
    # of games 1-2 (0, 0) = 0.0, and the 5th game's must be the mean of
    # games 3-4 (1, 0) = 0.5 -- never including its own result.
    df = pl.DataFrame(
        {
            "player_id": ["P1"] * 5,
            "date": [datetime(2026, 1, i) for i in range(1, 6)],
            "won": [0, 0, 1, 0, 1],
        }
    )
    out = asof.strictly_prior_rolling_mean(
        df, group_by=["player_id"], order_by="date", value_col="won", window_size=2
    ).sort("date")

    values = out["won_rolling2_before"].to_list()
    assert values[0] is None  # zero prior games
    assert values[1] == pytest.approx(0.0)  # mean of [0]
    assert values[2] == pytest.approx(0.0)  # mean of [0, 0]
    assert values[3] == pytest.approx(0.5)  # mean of [0, 1]
    assert values[4] == pytest.approx(0.5)  # mean of [1, 0]


def test_strictly_prior_ewm_mean_weights_recent_games_more() -> None:
    # A player who lost long ago then has been winning recently should show
    # a decayed recent-form value closer to 1.0 than a flat all-time average
    # (0.5) would give.
    df = pl.DataFrame(
        {
            "player_id": ["P1"] * 6,
            "date": [datetime(2026, 1, i) for i in range(1, 7)],
            "won": [0, 0, 0, 1, 1, 1],
        }
    )
    out = asof.strictly_prior_ewm_mean(
        df, group_by=["player_id"], order_by="date", value_col="won", alpha=0.5
    ).sort("date")
    last_value = out["won_ewm_before"].to_list()[-1]
    assert last_value > 0.5
