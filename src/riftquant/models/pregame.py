"""riftquant.models.pregame -- pregame (post-draft) win model v0 + the
evaluation harness (docs/specs/M2-pregame-model-brief.md, "models/" layer).

Non-negotiable rails this module implements directly:
  - Time-based splits only (`assign_split`, config.PREGAME_SPLIT_ACTIVE) --
    never a random split.
  - Baselines that MUST appear in every scorecard: global blue-side rate,
    per-league blue-side rate, team-Elo-only logistic (`compute_team_elo`).
  - Metrics: Brier (primary), log loss, ECE (10-bin), accuracy.
  - Isotonic calibration fit on validation, pre/post ECE reported.
  - Leakage tripwire: test-split accuracy > 65% on the "primary" model
    (lgbm_full) is flagged as a hard leakage-investigation failure in the
    scorecard, per Q14's own rationale (draft-only ceiling ~55-63%; higher
    is suspicious until proven otherwise).

`run_scorecard` recomputes everything (baselines + LR + LightGBM +
calibration + every split) from `df`/`feature_cols` in one call; both the
train-pregame and eval-pregame CLI commands call it fresh rather than
threading partial state between two process invocations -- simpler and, at
this dataset's size (LightGBM fits in well under a second), the recompute
cost is negligible. train-pregame additionally persists the LightGBM
booster + isotonic calibrator + feature list to disk so predict-pregame
doesn't need to refit anything.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import lightgbm as lgb
import numpy as np
import polars as pl
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from riftquant import config

LEAKAGE_ACCURACY_THRESHOLD = 0.65
MONOTONIC_FEATURE = "team_mu_ctx_sum_diff"
_ID_COLS = {
    "game_id",
    "league",
    "date",
    "patch_client",
    "blue_team_id",
    "red_team_id",
    "winner_team_id",
    "blue_win",
    "split",
}
# High-cardinality identifier-like string columns that carry signal only
# through the numeric/tag features already derived from them (meta_/pc_
# groups) -- excluded from the direct model matrix, not from the feature
# table itself (predict-pregame still shows them for interpretability).
_RAW_IDENTIFIER_COLS = {
    "draft_pick1_champ_blue",
    "draft_pick1_champ_red",
    "draft_pick2_champ_blue",
    "draft_pick2_champ_red",
}


# --- splitting -------------------------------------------------------------


def assign_split(dates: pl.Series, preset: config.PregameSplitPreset) -> pl.Series:
    """train = date < train_end; val = train_end <= date < val_end;
    test = date >= val_end. Boundaries are exact-inclusive on the LOWER
    edge of each bucket (a game exactly at train_end lands in val, not
    train; exactly at val_end lands in test, not val)."""
    return (
        pl.select(
            pl.when(dates < preset.train_end)
            .then(pl.lit("train"))
            .when(dates < preset.val_end)
            .then(pl.lit("val"))
            .otherwise(pl.lit("test"))
            .alias("split")
        )
        .to_series()
        .rename("split")
    )


def season_label(dates: pl.Series) -> pl.Series:
    """Coarse "season" grouping for the per-season scorecard breakdown:
    calendar year + half (H1 Jan-Jun, H2 Jul-Dec). No real split/season
    metadata is ingested yet, so this is a documented proxy, not the
    league's actual Spring/Summer split boundaries."""
    return pl.select(
        (
            dates.dt.year().cast(pl.Utf8)
            + "-H"
            + pl.when(dates.dt.month() <= 6).then(pl.lit("1")).otherwise(pl.lit("2"))
        ).alias("season")
    ).to_series()


# --- metrics -----------------------------------------------------------


def brier_score(preds: np.ndarray, actuals: np.ndarray) -> float:
    return float(np.mean((preds - actuals) ** 2))


def log_loss_score(preds: np.ndarray, actuals: np.ndarray, eps: float = 1e-15) -> float:
    clipped = np.clip(preds, eps, 1.0 - eps)
    return float(-np.mean(actuals * np.log(clipped) + (1.0 - actuals) * np.log(1.0 - clipped)))


def accuracy(preds: np.ndarray, actuals: np.ndarray) -> float:
    return float(np.mean((preds >= 0.5).astype(float) == actuals))


def calibration_curve(preds: np.ndarray, actuals: np.ndarray, n_bins: int = 10) -> pl.DataFrame:
    """Per-bin (predicted mean, actual mean, count) table over `n_bins`
    equal-width [0,1] buckets -- the raw material for both the scorecard's
    "calibration curve data" and the scalar ECE below."""
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    rows = []
    n = len(preds)
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        mask = (preds >= lo) & (preds <= hi) if i == n_bins - 1 else (preds >= lo) & (preds < hi)
        count = int(mask.sum())
        rows.append(
            {
                "bin_lo": round(float(lo), 2),
                "bin_hi": round(float(hi), 2),
                "n": count,
                "pred_mean": float(preds[mask].mean()) if count else None,
                "actual_mean": float(actuals[mask].mean()) if count else None,
                "share_pct": (count / n * 100.0) if n else 0.0,
            }
        )
    return pl.DataFrame(rows)


def ece_from_curve(curve: pl.DataFrame) -> float:
    total = curve["n"].sum()
    if not total:
        return 0.0
    err = 0.0
    for row in curve.iter_rows(named=True):
        if row["n"] == 0:
            continue
        err += (row["n"] / total) * abs(row["pred_mean"] - row["actual_mean"])
    return float(err)


def expected_calibration_error(preds: np.ndarray, actuals: np.ndarray, n_bins: int = 10) -> float:
    return ece_from_curve(calibration_curve(preds, actuals, n_bins))


def all_metrics(preds: np.ndarray, actuals: np.ndarray) -> dict[str, float]:
    return {
        "brier": brier_score(preds, actuals),
        "log_loss": log_loss_score(preds, actuals),
        "ece": expected_calibration_error(preds, actuals),
        "accuracy": accuracy(preds, actuals),
        "n": float(len(actuals)),
    }


# --- baselines ---------------------------------------------------------


def compute_team_elo(games: pl.DataFrame, k: float = 20.0, init: float = 1500.0) -> pl.DataFrame:
    """Team-level Elo, sequential replay in date order (K=20, standard
    logistic expected-score update, 1500 cold start) -- the mandatory
    "team-Elo-only" baseline (M2 brief). A stateful simulation like
    riftquant.ratings.openskill_ratings, not a vectorizable aggregation;
    same justification (cheap at this row count, one Python loop over
    games, not over the larger feature table)."""
    elo: dict[str, float] = {}
    rows = []
    for g in games.sort("date").iter_rows(named=True):
        blue, red = g.get("blue_team_id"), g.get("red_team_id")
        if blue is None or red is None:
            continue
        be, re = elo.get(blue, init), elo.get(red, init)
        rows.append({"game_id": g["game_id"], "elo_diff": be - re})
        winner = g.get("winner_team_id")
        if winner is None:
            continue
        exp_blue = 1.0 / (1.0 + 10.0 ** ((re - be) / 400.0))
        actual_blue = 1.0 if winner == blue else 0.0
        elo[blue] = be + k * (actual_blue - exp_blue)
        elo[red] = re + k * ((1.0 - actual_blue) - (1.0 - exp_blue))
    return (
        pl.DataFrame(rows)
        if rows
        else pl.DataFrame(schema={"game_id": pl.Utf8, "elo_diff": pl.Float64})
    )


@dataclass
class FittedBaselines:
    global_rate: float
    per_league_rate: dict[str, float]
    elo_available: bool
    elo_logistic: LogisticRegression | None = None

    def predict_global(self, n: int) -> np.ndarray:
        return np.full(n, self.global_rate)

    def predict_per_league(self, leagues: list[str]) -> np.ndarray:
        return np.array([self.per_league_rate.get(lg, self.global_rate) for lg in leagues])

    def predict_elo(self, elo_diff: np.ndarray) -> np.ndarray:
        if self.elo_logistic is None:
            return np.full(len(elo_diff), self.global_rate)
        return self.elo_logistic.predict_proba(elo_diff.reshape(-1, 1))[:, 1]


def fit_baselines(train_df: pl.DataFrame, elo: pl.DataFrame | None) -> FittedBaselines:
    y = train_df["blue_win"].cast(pl.Int64).to_numpy().astype(float)
    global_rate = float(y.mean()) if len(y) else 0.5

    per_league: dict[str, float] = {}
    if "league" in train_df.columns:
        for row in (
            train_df.group_by("league")
            .agg(pl.col("blue_win").cast(pl.Int64).mean().alias("rate"))
            .iter_rows(named=True)
        ):
            per_league[row["league"]] = (
                float(row["rate"]) if row["rate"] is not None else global_rate
            )

    elo_logistic = None
    elo_available = elo is not None and elo.height > 0
    if elo_available:
        joined = train_df.select("game_id", "blue_win").join(elo, on="game_id", how="inner")
        if joined.height >= 10 and joined["blue_win"].n_unique() > 1:
            x = joined["elo_diff"].to_numpy().astype(float).reshape(-1, 1)
            y_elo = joined["blue_win"].cast(pl.Int64).to_numpy().astype(float)
            elo_logistic = LogisticRegression().fit(x, y_elo)
        else:
            elo_available = False

    return FittedBaselines(
        global_rate=global_rate,
        per_league_rate=per_league,
        elo_available=elo_available,
        elo_logistic=elo_logistic,
    )


# --- feature matrix prep -------------------------------------------------


def select_model_feature_columns(df: pl.DataFrame) -> list[str]:
    """Everything except id/label columns and the raw high-cardinality
    champion-name identifier columns -- the default `feature_cols` CLI
    commands pass to `run_scorecard`. Boolean columns are cast to Int8
    upstream by `prepare_model_matrix`, not here (this just names them)."""
    return [c for c in df.columns if c not in _ID_COLS and c not in _RAW_IDENTIFIER_COLS]


def prepare_model_matrix(
    df: pl.DataFrame, feature_cols: list[str] | None = None
) -> tuple[pl.DataFrame, list[str]]:
    """One-hot encode the low-cardinality categoricals (side_league,
    draft_*_damage_mix_*) and cast booleans to Int8, returning an
    all-numeric DataFrame plus the resulting (possibly expanded) column
    list. `feature_cols=None` means "everything `select_model_feature_
    columns` would pick"; an explicit list (e.g. in a test) is used as-is
    for whichever of those columns are already numeric/boolean, with any
    categorical ones among them one-hot expanded the same way.
    """
    feature_cols = feature_cols if feature_cols is not None else select_model_feature_columns(df)
    work = df.select(*{c for c in feature_cols if c in df.columns})

    categorical = [c for c in work.columns if work.schema[c] == pl.Utf8]
    if categorical:
        work = work.to_dummies(columns=categorical, drop_first=False)

    bool_cols = [c for c in work.columns if work.schema[c] == pl.Boolean]
    if bool_cols:
        work = work.with_columns([pl.col(c).cast(pl.Int8) for c in bool_cols])

    return work, work.columns


def _impute_train_mean(train_x: pl.DataFrame, *frames: pl.DataFrame) -> list[pl.DataFrame]:
    """Fill nulls in every frame using TRAIN-split column means only (never
    val/test means -- that would leak future distribution info backward).
    Used for LR/Elo-logistic, which can't accept NaN; LightGBM gets the
    raw (possibly-null) matrix separately and handles missing natively."""
    means = {c: (train_x[c].mean() or 0.0) for c in train_x.columns}
    out = []
    for f in (train_x, *frames):
        out.append(f.with_columns([pl.col(c).fill_null(means[c]) for c in f.columns]))
    return out


# --- scorecard -----------------------------------------------------------


@dataclass
class Scorecard:
    preset_name: str
    split_sizes: dict[str, int]
    split_date_ranges: dict[str, tuple]
    train_metrics: dict[str, dict[str, float]] = field(default_factory=dict)
    val_metrics: dict[str, dict[str, float]] = field(default_factory=dict)
    test_metrics: dict[str, dict[str, float]] = field(default_factory=dict)
    per_league_test_metrics: dict[str, dict[str, dict[str, float]]] = field(default_factory=dict)
    per_season_test_metrics: dict[str, dict[str, dict[str, float]]] = field(default_factory=dict)
    calibration_pre: pl.DataFrame | None = None
    calibration_post: pl.DataFrame | None = None
    feature_importances: pl.DataFrame | None = None
    rolling_origin_folds: pl.DataFrame | None = None
    leakage_investigation_triggered: bool = False
    leakage_message: str = ""
    beats_elo_on_test_brier: bool | None = None
    predictions: pl.DataFrame | None = None


def _predict_all_baselines(
    baselines: FittedBaselines, split_df: pl.DataFrame, elo: pl.DataFrame
) -> dict[str, np.ndarray]:
    n = split_df.height
    leagues = split_df["league"].to_list() if "league" in split_df.columns else ["?"] * n
    preds = {
        "global_rate": baselines.predict_global(n),
        "per_league_rate": baselines.predict_per_league(leagues),
    }
    if baselines.elo_available:
        elo_vals = (
            split_df.select("game_id")
            .join(elo, on="game_id", how="left")["elo_diff"]
            .fill_null(0.0)
            .to_numpy()
        )
        preds["elo_logistic"] = baselines.predict_elo(elo_vals)
    return preds


def run_scorecard(
    df: pl.DataFrame,
    feature_cols: list[str],
    preset: config.PregameSplitPreset,
    *,
    calibrate: bool = True,
    lgbm_params: dict | None = None,
) -> Scorecard:
    """Fit every baseline + LR + LightGBM on `train`, calibrate on `val`,
    evaluate everything on train/val/test, and assemble the full scorecard.
    `df` must have game_id/date/blue_win at minimum; league/blue_team_id/
    red_team_id/winner_team_id are used opportunistically when present
    (per-league breakdown, the Elo baseline) and skipped gracefully when
    absent (e.g. a minimal synthetic fixture)."""
    labeled = df.filter(pl.col("blue_win").is_not_null())
    labeled = labeled.with_columns(assign_split(labeled["date"], preset).alias("split"))

    split_sizes = {s: labeled.filter(pl.col("split") == s).height for s in ("train", "val", "test")}
    split_ranges = {}
    for s in ("train", "val", "test"):
        sub = labeled.filter(pl.col("split") == s)
        split_ranges[s] = (sub["date"].min(), sub["date"].max()) if sub.height else (None, None)

    train_df = labeled.filter(pl.col("split") == "train")
    val_df = labeled.filter(pl.col("split") == "val")
    test_df = labeled.filter(pl.col("split") == "test")

    has_team_ids = {"blue_team_id", "red_team_id", "winner_team_id"} <= set(df.columns)
    elo = (
        compute_team_elo(labeled)
        if has_team_ids
        else pl.DataFrame(schema={"game_id": pl.Utf8, "elo_diff": pl.Float64})
    )
    baselines = fit_baselines(train_df, elo if has_team_ids else None)

    x_all, cols = prepare_model_matrix(labeled, feature_cols)
    x_train = x_all.filter(pl.Series(labeled["split"] == "train"))
    x_val = x_all.filter(pl.Series(labeled["split"] == "val"))
    x_test = x_all.filter(pl.Series(labeled["split"] == "test"))
    y_train = train_df["blue_win"].cast(pl.Int64).to_numpy().astype(float)
    y_val = val_df["blue_win"].cast(pl.Int64).to_numpy().astype(float)
    y_test = test_df["blue_win"].cast(pl.Int64).to_numpy().astype(float)

    # --- LR (L2, standardized), NaN-imputed with train-only means ---
    x_train_imp, x_val_imp, x_test_imp = _impute_train_mean(x_train, x_val, x_test)
    lr_preds = {
        "train": np.full(len(y_train), 0.5),
        "val": np.full(len(y_val), 0.5),
        "test": np.full(len(y_test), 0.5),
    }
    if x_train_imp.width > 0 and len(y_train) >= 10 and len(set(y_train.tolist())) > 1:
        scaler = StandardScaler().fit(x_train_imp.to_numpy())
        # L2 is scikit-learn's own LogisticRegression default (an explicit
        # penalty="l2" is deprecated as of sklearn 1.8+) -- the brief's
        # "LR (L2, standardized)" is satisfied by leaving it at default.
        lr = LogisticRegression(max_iter=2000).fit(
            scaler.transform(x_train_imp.to_numpy()), y_train
        )
        lr_preds["train"] = lr.predict_proba(scaler.transform(x_train_imp.to_numpy()))[:, 1]
        if x_val_imp.height:
            lr_preds["val"] = lr.predict_proba(scaler.transform(x_val_imp.to_numpy()))[:, 1]
        if x_test_imp.height:
            lr_preds["test"] = lr.predict_proba(scaler.transform(x_test_imp.to_numpy()))[:, 1]

    # --- LightGBM (monotonic constraint on team rating diff), raw NaN ---
    monotone = [1 if c == MONOTONIC_FEATURE else 0 for c in cols]
    params = {
        "n_estimators": 200,
        "learning_rate": 0.05,
        "num_leaves": 15,
        "min_child_samples": 10,
        "monotone_constraints": monotone,
        "verbosity": -1,
        "random_state": 42,
    }
    if lgbm_params:
        params.update(lgbm_params)
    lgbm = lgb.LGBMClassifier(**params)
    lgbm_preds = {
        "train": np.full(len(y_train), 0.5),
        "val": np.full(len(y_val), 0.5),
        "test": np.full(len(y_test), 0.5),
    }
    feature_importances = None
    if x_train.width > 0 and len(y_train) >= 10 and len(set(y_train.tolist())) > 1:
        lgbm.fit(x_train.to_numpy(), y_train)
        lgbm_preds["train"] = lgbm.predict_proba(x_train.to_numpy())[:, 1]
        if x_val.height:
            lgbm_preds["val"] = lgbm.predict_proba(x_val.to_numpy())[:, 1]
        if x_test.height:
            lgbm_preds["test"] = lgbm.predict_proba(x_test.to_numpy())[:, 1]
        feature_importances = pl.DataFrame(
            {
                "feature": cols,
                "importance": lgbm.booster_.feature_importance(importance_type="gain"),
            }
        ).sort("importance", descending=True)

    # --- isotonic calibration of lgbm, fit on val ---
    calibration_pre = calibration_curve(lgbm_preds["test"], y_test) if len(y_test) else None
    lgbm_cal_preds = dict(lgbm_preds)
    if calibrate and x_val.height >= 10 and len(set(y_val.tolist())) > 1:
        iso = IsotonicRegression(out_of_bounds="clip").fit(lgbm_preds["val"], y_val)
        # Isotonic regression fit on a handful of validation games (the
        # subset preset's val split is 31 games) is a genuinely unstable
        # step function -- it can map an entire tail bin to exactly 0.0/1.0
        # (observed on this dataset). That's an honest reflection of "not
        # enough validation data yet", not something to hide, but handing a
        # literal 0.0/1.0 probability downstream (log-odds, Kelly sizing)
        # is a numerical footgun -- clip away from the extremes as a safety
        # rail, not a calibration fix.
        lgbm_cal_preds = {
            split: np.clip(iso.predict(preds), 0.02, 0.98) for split, preds in lgbm_preds.items()
        }
    calibration_post = calibration_curve(lgbm_cal_preds["test"], y_test) if len(y_test) else None

    def _metrics_for_split(
        split_name: str, split_df: pl.DataFrame, y: np.ndarray
    ) -> dict[str, dict[str, float]]:
        if not len(y):
            return {}
        out: dict[str, dict[str, float]] = {}
        for name, preds in _predict_all_baselines(baselines, split_df, elo).items():
            out[name] = all_metrics(preds, y)
        out["lr_full"] = all_metrics(lr_preds[split_name], y)
        out["lgbm_full"] = all_metrics(lgbm_preds[split_name], y)
        out["lgbm_full_calibrated"] = all_metrics(lgbm_cal_preds[split_name], y)
        return out

    train_metrics = _metrics_for_split("train", train_df, y_train)
    val_metrics = _metrics_for_split("val", val_df, y_val)
    test_metrics = _metrics_for_split("test", test_df, y_test)

    per_league: dict[str, dict[str, dict[str, float]]] = {}
    if "league" in test_df.columns and test_df.height:
        for lg_name in sorted(test_df["league"].unique().to_list()):
            mask = test_df["league"] == lg_name
            sub_df = test_df.filter(mask)
            sub_y = y_test[mask.to_numpy()]
            if not len(sub_y):
                continue
            per_league[lg_name] = {
                "lgbm_full": all_metrics(lgbm_preds["test"][mask.to_numpy()], sub_y),
                "elo_logistic": all_metrics(
                    _predict_all_baselines(baselines, sub_df, elo).get(
                        "elo_logistic", np.full(len(sub_y), 0.5)
                    ),
                    sub_y,
                ),
            }

    per_season: dict[str, dict[str, dict[str, float]]] = {}
    if test_df.height:
        seasons = season_label(test_df["date"])
        for season in sorted(seasons.unique().to_list()):
            mask = (seasons == season).to_numpy()
            sub_y = y_test[mask]
            if not len(sub_y):
                continue
            per_season[season] = {"lgbm_full": all_metrics(lgbm_preds["test"][mask], sub_y)}

    leakage_triggered = bool(
        test_metrics.get("lgbm_full", {}).get("accuracy", 0.0) > LEAKAGE_ACCURACY_THRESHOLD
    )
    test_acc = test_metrics.get("lgbm_full", {}).get("accuracy", 0.0)
    leakage_message = (
        f"lgbm_full test accuracy {test_acc:.3f} exceeds the {LEAKAGE_ACCURACY_THRESHOLD:.0%} "
        "post-draft ceiling (Q14) -- INVESTIGATE LEAKAGE before trusting this run."
        if leakage_triggered
        else "post-draft test accuracy within the expected ceiling; no leakage flag raised."
    )

    beats_elo = None
    if "elo_logistic" in test_metrics and "lgbm_full_calibrated" in test_metrics:
        beats_elo = (
            test_metrics["lgbm_full_calibrated"]["brier"] < test_metrics["elo_logistic"]["brier"]
        )

    predictions = None
    if test_df.height:
        predictions = test_df.select(
            "game_id", "date", "league" if "league" in test_df.columns else "game_id"
        ).with_columns(
            pl.Series("p_blue_win_raw", lgbm_preds["test"]),
            pl.Series("p_blue_win_calibrated", lgbm_cal_preds["test"]),
            pl.Series("actual_blue_win", y_test),
        )

    return Scorecard(
        preset_name=preset.name,
        split_sizes=split_sizes,
        split_date_ranges=split_ranges,
        train_metrics=train_metrics,
        val_metrics=val_metrics,
        test_metrics=test_metrics,
        per_league_test_metrics=per_league,
        per_season_test_metrics=per_season,
        calibration_pre=calibration_pre,
        calibration_post=calibration_post,
        feature_importances=feature_importances,
        leakage_investigation_triggered=leakage_triggered,
        leakage_message=leakage_message,
        beats_elo_on_test_brier=beats_elo,
        predictions=predictions,
    )


# --- persistence (train-pregame -> predict-pregame) -----------------------


def save_model(
    lgbm: lgb.LGBMClassifier,
    feature_cols: list[str],
    calibrator: IsotonicRegression | None,
    out_dir: Path,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    lgbm.booster_.save_model(str(out_dir / "lgbm_model.txt"))
    (out_dir / "feature_columns.json").write_text(json.dumps(feature_cols), encoding="utf-8")
    if calibrator is not None:
        import joblib

        joblib.dump(calibrator, out_dir / "isotonic_calibrator.joblib")


def train_and_save(
    df: pl.DataFrame, feature_cols: list[str], preset: config.PregameSplitPreset, out_dir: Path
) -> Scorecard:
    """train-pregame: fit on train, calibrate on val (via run_scorecard),
    then persist the LightGBM booster + calibrator + feature list for
    predict-pregame."""
    scorecard = run_scorecard(df, feature_cols, preset)

    labeled = df.filter(pl.col("blue_win").is_not_null())
    labeled = labeled.with_columns(assign_split(labeled["date"], preset).alias("split"))
    train_df = labeled.filter(pl.col("split") == "train")
    val_df = labeled.filter(pl.col("split") == "val")
    x_all, cols = prepare_model_matrix(labeled, feature_cols)
    x_train = x_all.filter(pl.Series(labeled["split"] == "train"))
    x_val = x_all.filter(pl.Series(labeled["split"] == "val"))
    y_train = train_df["blue_win"].cast(pl.Int64).to_numpy().astype(float)
    y_val = val_df["blue_win"].cast(pl.Int64).to_numpy().astype(float)

    monotone = [1 if c == MONOTONIC_FEATURE else 0 for c in cols]
    lgbm = lgb.LGBMClassifier(
        n_estimators=200,
        learning_rate=0.05,
        num_leaves=15,
        min_child_samples=10,
        monotone_constraints=monotone,
        verbosity=-1,
        random_state=42,
    )
    lgbm.fit(x_train.to_numpy(), y_train)

    calibrator = None
    if x_val.height >= 10 and len(set(y_val.tolist())) > 1:
        val_preds = lgbm.predict_proba(x_val.to_numpy())[:, 1]
        calibrator = IsotonicRegression(out_of_bounds="clip").fit(val_preds, y_val)

    save_model(lgbm, cols, calibrator, out_dir)
    return scorecard


def load_model(model_dir: Path) -> tuple[lgb.Booster, list[str], IsotonicRegression | None]:
    booster = lgb.Booster(model_file=str(model_dir / "lgbm_model.txt"))
    feature_cols = json.loads((model_dir / "feature_columns.json").read_text(encoding="utf-8"))
    calibrator = None
    calibrator_path = model_dir / "isotonic_calibrator.joblib"
    if calibrator_path.exists():
        import joblib

        calibrator = joblib.load(calibrator_path)
    return booster, feature_cols, calibrator


# --- rolling-origin (quarterly) walk-forward variant ----------------------


def rolling_origin_quarterly_folds(df: pl.DataFrame, feature_cols: list[str]) -> pl.DataFrame:
    """Supplementary walk-forward check (M2 brief, "Also produce a
    rolling-origin variant (quarterly folds)"): train on every quarter
    strictly before the test quarter, slide forward one quarter at a time.
    Uses a lightweight LR (not LightGBM) per fold -- this is a diagnostic
    variance check, not a scorecard-primary metric surface, so a
    fast/simple model is a deliberate scope trade-off, not an oversight.
    """
    labeled = df.filter(pl.col("blue_win").is_not_null())
    if labeled.height == 0:
        return pl.DataFrame(
            schema={
                "quarter": pl.Utf8,
                "n_train": pl.Int64,
                "n_test": pl.Int64,
                "accuracy": pl.Float64,
                "brier": pl.Float64,
            }
        )
    labeled = labeled.with_columns(
        (
            labeled["date"].dt.year().cast(pl.Utf8)
            + "-Q"
            + labeled["date"].dt.quarter().cast(pl.Utf8)
        ).alias("_quarter")
    )
    quarters = sorted(labeled["_quarter"].unique().to_list())
    x_all, _cols = prepare_model_matrix(labeled, feature_cols)
    rows = []
    for i in range(1, len(quarters)):
        test_q = quarters[i]
        train_mask = (labeled["_quarter"] < test_q).to_numpy()
        test_mask = (labeled["_quarter"] == test_q).to_numpy()
        n_train, n_test = int(train_mask.sum()), int(test_mask.sum())
        if n_train < 20 or n_test < 5:
            continue
        x_train, x_test = x_all.filter(pl.Series(train_mask)), x_all.filter(pl.Series(test_mask))
        y_train = (
            labeled.filter(pl.Series(train_mask))["blue_win"]
            .cast(pl.Int64)
            .to_numpy()
            .astype(float)
        )
        y_test = (
            labeled.filter(pl.Series(test_mask))["blue_win"].cast(pl.Int64).to_numpy().astype(float)
        )
        if len(set(y_train.tolist())) < 2:
            continue
        x_train_imp, x_test_imp = _impute_train_mean(x_train, x_test)
        scaler = StandardScaler().fit(x_train_imp.to_numpy())
        lr = LogisticRegression(max_iter=2000).fit(
            scaler.transform(x_train_imp.to_numpy()), y_train
        )
        preds = lr.predict_proba(scaler.transform(x_test_imp.to_numpy()))[:, 1]
        rows.append(
            {
                "quarter": test_q,
                "n_train": n_train,
                "n_test": n_test,
                "accuracy": accuracy(preds, y_test),
                "brier": brier_score(preds, y_test),
            }
        )
    return (
        pl.DataFrame(rows)
        if rows
        else pl.DataFrame(
            schema={
                "quarter": pl.Utf8,
                "n_train": pl.Int64,
                "n_test": pl.Int64,
                "accuracy": pl.Float64,
                "brier": pl.Float64,
            }
        )
    )


# --- ASCII markdown report -------------------------------------------------


def _fmt(v: object, digits: int = 4) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.{digits}f}"
    return str(v)


def _md_table(headers: list[str], rows: list[list[object]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(_fmt(v) for v in row) + " |")
    return "\n".join(lines)


def _metrics_table(metrics_by_model: dict[str, dict[str, float]]) -> str:
    order = [
        "global_rate",
        "per_league_rate",
        "elo_logistic",
        "lr_full",
        "lgbm_full",
        "lgbm_full_calibrated",
    ]
    headers = ["model", "brier", "log_loss", "ece", "accuracy", "n"]
    rows = []
    for name in order:
        m = metrics_by_model.get(name)
        if not m:
            continue
        rows.append([name, m["brier"], m["log_loss"], m["ece"], m["accuracy"], int(m["n"])])
    return _md_table(headers, rows) if rows else "(no rows -- empty split)"


def render_markdown(scorecard: Scorecard, null_rate_table: pl.DataFrame | None = None) -> str:
    """ASCII markdown scorecard -- docs/eval/pregame_v0_<date>.md. Every
    table is a plain markdown pipe table (ASCII: `|`/`-` only), per house
    rules (no unicode box-drawing)."""
    lines: list[str] = []
    lines.append("# Pregame Model v0 Scorecard")
    lines.append("")
    lines.append(f"Split preset: `{scorecard.preset_name}`")
    lines.append("")
    lines.append("## Split sizes")
    lines.append("")
    lines.append(
        _md_table(
            ["split", "n", "date_min", "date_max"],
            [
                [
                    s,
                    scorecard.split_sizes.get(s, 0),
                    *scorecard.split_date_ranges.get(s, (None, None)),
                ]
                for s in ("train", "val", "test")
            ],
        )
    )
    lines.append("")
    lines.append("## Leakage tripwire (post-draft test accuracy > 65% => investigate)")
    lines.append("")
    lines.append(
        ("[FIRED] " if scorecard.leakage_investigation_triggered else "[OK] ")
        + scorecard.leakage_message
    )
    lines.append("")
    if scorecard.beats_elo_on_test_brier is not None:
        lines.append(
            f"Beats team-Elo-only baseline on test Brier: **{scorecard.beats_elo_on_test_brier}** "
            "(lgbm_full_calibrated vs elo_logistic)."
        )
        lines.append("")

    for split_name, metrics in (
        ("train", scorecard.train_metrics),
        ("val", scorecard.val_metrics),
        ("test", scorecard.test_metrics),
    ):
        lines.append(f"## Metrics -- {split_name}")
        lines.append("")
        lines.append(_metrics_table(metrics))
        lines.append("")

    if scorecard.per_league_test_metrics:
        lines.append("## Per-league (test split)")
        lines.append("")
        rows = []
        for league, models in sorted(scorecard.per_league_test_metrics.items()):
            for model_name, m in models.items():
                rows.append([league, model_name, m["brier"], m["accuracy"], int(m["n"])])
        lines.append(_md_table(["league", "model", "brier", "accuracy", "n"], rows))
        lines.append("")

    if scorecard.per_season_test_metrics:
        lines.append("## Per-season (test split)")
        lines.append("")
        rows = []
        for season, models in sorted(scorecard.per_season_test_metrics.items()):
            for model_name, m in models.items():
                rows.append([season, model_name, m["brier"], m["accuracy"], int(m["n"])])
        lines.append(_md_table(["season", "model", "brier", "accuracy", "n"], rows))
        lines.append("")

    for label, curve in (
        ("pre-calibration", scorecard.calibration_pre),
        ("post-calibration", scorecard.calibration_post),
    ):
        lines.append(f"## Calibration curve -- test, {label}")
        lines.append("")
        if curve is None or curve.height == 0:
            lines.append("(no test rows)")
        else:
            rows = [
                [r["bin_lo"], r["bin_hi"], r["n"], r["pred_mean"], r["actual_mean"]]
                for r in curve.iter_rows(named=True)
            ]
            lines.append(_md_table(["bin_lo", "bin_hi", "n", "pred_mean", "actual_mean"], rows))
        lines.append("")

    if scorecard.feature_importances is not None and scorecard.feature_importances.height:
        lines.append("## Feature importances (LightGBM gain, top 20)")
        lines.append("")
        top = scorecard.feature_importances.head(20)
        lines.append(
            _md_table(
                ["feature", "importance"],
                [[r["feature"], r["importance"]] for r in top.iter_rows(named=True)],
            )
        )
        lines.append("")

    if scorecard.rolling_origin_folds is not None and scorecard.rolling_origin_folds.height:
        lines.append("## Rolling-origin quarterly folds (walk-forward, LR-only diagnostic)")
        lines.append("")
        rows = [
            [r["quarter"], r["n_train"], r["n_test"], r["accuracy"], r["brier"]]
            for r in scorecard.rolling_origin_folds.iter_rows(named=True)
        ]
        lines.append(_md_table(["quarter", "n_train", "n_test", "accuracy", "brier"], rows))
        lines.append("")

    if null_rate_table is not None and null_rate_table.height:
        lines.append("## Null-rate by feature group (build-features output)")
        lines.append("")
        rows = [
            [r["feature_group"], r["n_columns"], r["n_rows"], round(r["null_rate_pct"], 2)]
            for r in null_rate_table.iter_rows(named=True)
        ]
        lines.append(_md_table(["feature_group", "n_columns", "n_rows", "null_rate_pct"], rows))
        lines.append("")

    return "\n".join(lines)
