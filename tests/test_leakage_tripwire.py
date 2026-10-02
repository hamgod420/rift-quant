"""Leakage tripwires (M2 brief, non-negotiable rails: "shuffle-date refit
must crater performance"; "post-draft accuracy > 65% on the time-split test
triggers a hard 'investigate leakage' failure in eval output"; "Tests" --
"tripwire fires on a deliberately leaky feature fixture").

Two independent tripwires, two independent tests:
  1. `test_shuffled_dates_crater_the_recent_form_signal` -- a METHODOLOGY
     check on the as-of toolkit itself: if a feature's predictive power
     depends on point-in-time-correct ordering, scrambling which date
     label attaches to which game must crater it. A buggy as-of join that
     silently ignores date order (e.g. uses the whole dataset regardless of
     `<`) would NOT crater under this test, which is exactly the failure
     mode it's designed to catch.
  2. `test_hard_failure_flag_fires_on_a_deliberately_leaky_feature` -- the
     runtime check inside eval_pregame: a feature engineered to leak the
     outcome must push test-split accuracy over the brief's 65% ceiling and
     the scorecard must flag it, not silently report a great-looking number.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

import polars as pl
from sklearn.linear_model import LogisticRegression

from riftquant import config
from riftquant.features import asof
from riftquant.models import pregame as models_pregame


def _career_fixture(n_games: int = 40) -> pl.DataFrame:
    """One player's 40-game career: loses the first half, wins the second
    half -- a clean, deterministic "improved over time" story. Each game's
    outcome depends ENTIRELY on its position in true career order, so a
    correctly as-of-joined "recent form" feature should predict it almost
    perfectly; scrambling which date label attaches to which game should
    destroy that, since the feature would then be built from an
    effectively-random subset of the player's OTHER games rather than the
    truly-prior ones.
    """
    won = [0] * (n_games // 2) + [1] * (n_games // 2)
    dates = [datetime(2026, 1, 1) + timedelta(days=i) for i in range(n_games)]
    return pl.DataFrame(
        {
            "player_id": ["CAREER"] * n_games,
            "game_id": [f"G{i}" for i in range(n_games)],
            "date": dates,
            "won": won,
        }
    )


def _fit_and_score(df: pl.DataFrame) -> float:
    featured = asof.strictly_prior_rolling_mean(
        df, group_by=["player_id"], order_by="date", value_col="won", window_size=10
    )
    featured = featured.drop_nulls("won_rolling10_before")
    x = featured["won_rolling10_before"].to_numpy().reshape(-1, 1)
    y = featured["won"].to_numpy()
    clf = LogisticRegression().fit(x, y)
    return float(clf.score(x, y))


def test_shuffled_dates_crater_the_recent_form_signal() -> None:
    df = _career_fixture()
    true_accuracy = _fit_and_score(df)

    rng = random.Random(0)
    shuffled_dates = df["date"].to_list()
    rng.shuffle(shuffled_dates)
    shuffled = df.with_columns(pl.Series("date", shuffled_dates))
    shuffled_accuracy = _fit_and_score(shuffled)

    assert true_accuracy > 0.85
    assert shuffled_accuracy < true_accuracy - 0.2


def test_hard_failure_flag_fires_on_a_deliberately_leaky_feature() -> None:
    # 200 games, time-split so ~half land in "test" (config's active preset
    # cutoffs). The label is an unpredictable coin flip EXCEPT for one
    # feature column that is literally a copy of the outcome -- a model
    # trained on it should score far above the brief's 65% leakage ceiling
    # on the test split, and eval_pregame must say so, not just report a
    # great Brier score.
    rng = random.Random(0)
    n = 200
    dates = [datetime(2025, 1, 1) + timedelta(days=i) for i in range(n)]
    blue_win = [rng.random() < 0.5 for _ in range(n)]
    leaky_feature = [1.0 if w else 0.0 for w in blue_win]
    df = pl.DataFrame(
        {
            "game_id": [f"G{i}" for i in range(n)],
            "date": dates,
            "league": ["LCK"] * n,
            "blue_win": [int(w) for w in blue_win],
            "side_leak_of_outcome": leaky_feature,
        }
    )
    preset = config.PregameSplitPreset(
        name="test-preset",
        train_end=dates[0] + timedelta(days=120),
        val_end=dates[0] + timedelta(days=150),
    )

    scorecard = models_pregame.run_scorecard(
        df, feature_cols=["side_leak_of_outcome"], preset=preset
    )

    assert scorecard.leakage_investigation_triggered is True
    assert scorecard.test_metrics["lgbm_full"]["accuracy"] > 0.65
