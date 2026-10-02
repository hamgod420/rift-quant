"""riftquant.models.pregame: split boundaries (M2 brief, "Tests" -- "split
boundaries"), metric functions vs hand-computed examples, and Elo baseline
sanity.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import polars as pl
import pytest

from riftquant import config
from riftquant.models import pregame


def test_assign_split_boundaries_are_exact_and_lower_inclusive() -> None:
    preset = config.PregameSplitPreset(
        name="test", train_end=datetime(2026, 6, 1), val_end=datetime(2026, 7, 15)
    )
    dates = pl.Series(
        "date",
        [
            datetime(2026, 5, 31, 23, 59, 59),  # just before train_end -> train
            datetime(2026, 6, 1, 0, 0, 0),  # exactly train_end -> val, not train
            datetime(2026, 7, 14, 23, 59, 59),  # just before val_end -> val
            datetime(2026, 7, 15, 0, 0, 0),  # exactly val_end -> test, not val
            datetime(2026, 12, 31),  # well after -> test
        ],
    )
    result = pregame.assign_split(dates, preset).to_list()
    assert result == ["train", "val", "val", "test", "test"]


def test_assign_split_all_train_when_every_date_is_early() -> None:
    preset = config.PregameSplitPreset(
        name="test", train_end=datetime(2030, 1, 1), val_end=datetime(2031, 1, 1)
    )
    dates = pl.Series("date", [datetime(2020, 1, 1), datetime(2021, 1, 1)])
    assert pregame.assign_split(dates, preset).to_list() == ["train", "train"]


def test_brier_score_matches_hand_computed_example() -> None:
    preds = np.array([0.9, 0.1, 0.5])
    actuals = np.array([1.0, 0.0, 1.0])
    # (0.9-1)^2=0.01, (0.1-0)^2=0.01, (0.5-1)^2=0.25 -> mean = 0.27/3 = 0.09
    assert pregame.brier_score(preds, actuals) == pytest.approx(0.09)


def test_accuracy_uses_half_threshold() -> None:
    preds = np.array([0.51, 0.49, 0.5, 0.99])
    actuals = np.array([1.0, 1.0, 1.0, 1.0])
    # 0.51->1 (correct), 0.49->0 (wrong), 0.5->1 (correct, >=0.5), 0.99->1 (correct)
    assert pregame.accuracy(preds, actuals) == pytest.approx(0.75)


def test_expected_calibration_error_is_zero_for_perfectly_calibrated_bins() -> None:
    # 10 predictions, each bin's predicted mean equals its actual mean.
    preds = np.array([0.05, 0.05, 0.95, 0.95])
    actuals = np.array([0.0, 1.0, 1.0, 1.0])
    # bin [0,0.1): pred_mean=0.05, actual_mean=0.5 -> NOT zero in general;
    # use a case constructed so pred_mean == actual_mean per bin instead.
    preds2 = np.array([0.05, 0.05])
    actuals2 = np.array([0.0, 0.0])  # bin pred_mean=0.05, actual_mean=0.0 -- still nonzero
    # Simplest true zero-ECE case: predictions exactly match actuals.
    preds3 = np.array([0.0, 0.0, 1.0, 1.0])
    actuals3 = np.array([0.0, 0.0, 1.0, 1.0])
    assert pregame.expected_calibration_error(preds3, actuals3) == pytest.approx(0.0)
    # Sanity: the miscalibrated cases above are NOT silently reported as zero.
    assert pregame.expected_calibration_error(preds, actuals) > 0.0
    assert pregame.expected_calibration_error(preds2, actuals2) > 0.0


def test_calibration_curve_bin_counts_sum_to_total() -> None:
    preds = np.array([0.05, 0.15, 0.55, 0.95, 0.99])
    actuals = np.array([0.0, 1.0, 1.0, 1.0, 0.0])
    curve = pregame.calibration_curve(preds, actuals, n_bins=10)
    assert curve["n"].sum() == len(preds)


def test_compute_team_elo_winner_gains_rating_loser_loses() -> None:
    games = pl.DataFrame(
        {
            "game_id": ["G1", "G2"],
            "date": [datetime(2026, 1, 1), datetime(2026, 1, 2)],
            "blue_team_id": ["TeamA", "TeamA"],
            "red_team_id": ["TeamB", "TeamB"],
            "winner_team_id": ["TeamA", "TeamA"],
        }
    )
    elo = pregame.compute_team_elo(games)
    # G1: both teams cold-start at 1500 -> elo_diff before G1 is 0.
    g1 = elo.filter(pl.col("game_id") == "G1")["elo_diff"].item()
    assert g1 == pytest.approx(0.0)
    # G2: Team A won G1, so its pre-G2 elo_diff over Team B must be positive.
    g2 = elo.filter(pl.col("game_id") == "G2")["elo_diff"].item()
    assert g2 > 0.0


def test_compute_team_elo_skips_rows_with_no_team_id() -> None:
    games = pl.DataFrame(
        {
            "game_id": ["G1"],
            "date": [datetime(2026, 1, 1)],
            "blue_team_id": [None],
            "red_team_id": ["TeamB"],
            "winner_team_id": [None],
        }
    )
    elo = pregame.compute_team_elo(games)
    assert elo.height == 0


def test_select_model_feature_columns_excludes_ids_and_raw_champion_names() -> None:
    df = pl.DataFrame(
        {
            "game_id": ["G1"],
            "league": ["LCK"],
            "date": [datetime(2026, 1, 1)],
            "blue_win": [True],
            "draft_pick1_champ_blue": ["Ahri"],
            "team_mu_ctx_sum_diff": [1.0],
        }
    )
    cols = pregame.select_model_feature_columns(df)
    assert cols == ["team_mu_ctx_sum_diff"]


def test_prepare_model_matrix_one_hot_encodes_categoricals_and_casts_bools() -> None:
    df = pl.DataFrame({"side_league": ["LCK", "LEC"], "side_fearless_era": [True, False]})
    x, cols = pregame.prepare_model_matrix(df, ["side_league", "side_fearless_era"])
    assert "side_fearless_era" in cols
    assert x["side_fearless_era"].dtype == pl.Int8
    assert any(c.startswith("side_league_") for c in cols)
