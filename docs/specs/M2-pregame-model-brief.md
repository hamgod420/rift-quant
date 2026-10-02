# M2 Build Brief -- pregame (post-draft) win model v0 + evaluation harness

Self-contained spec. Data scope: games from 2020 onward (user directive,
QUESTIONS.md Q2). Trainable on partial data; the harness must report per-
league-season sample sizes so thin slices are visible, not silent.

SUBSET MODE (current reality, 2026-08-21): Leaguepedia is rate-limited until
~tomorrow, so ONLY LCK 2026 + LEC 2026 (747 games) are ingested right now.
Build the FULL pipeline and verify it end-to-end on this subset with
adapted time splits (train = games before 2026-06-01, validation =
2026-06-01..2026-07-15, test = after 2026-07-15; report the split sizes).
Expect WEAK, high-variance metrics on 747 games -- that is fine and must be
reported honestly; the deliverable is a correct, retrainable pipeline, not
final numbers. Make the split dates config constants so the real 2020+
retrain is a config change plus rerun. The full-data splits in the rails
section below apply AFTER backfill; encode both presets.

## Context

rift-quant (this repo). Read first: docs/QUESTIONS.md (Q8/Q10/Q12/Q13/Q14),
docs/research/08-pandaskill-method.md (rating method, incl. code-level
corrections), docs/research/03-modeling-literature.md (benchmarks). Data
lives in DuckDB views over parquet: v_games, v_game_players, v_draft_actions,
v_player_champ_history (see src/riftquant/store/views.py, README-DEV.md).

## Non-negotiable rails

- POINT-IN-TIME: every feature for game G uses only games with
  start_time < G.start_time. Implement as-of joins centrally (one feature-
  builder API), never ad hoc. Add a leakage tripwire test: shuffle-date
  refit must crater performance; post-draft accuracy > 65% on the time-split
  test triggers a hard "investigate leakage" failure in eval output.
- Time splits only: train <= 2025-06-30, validation 2025-07-01..2025-12-31,
  test 2026+. Also produce a rolling-origin variant (quarterly folds).
- Metrics: Brier (primary), log loss, ECE (10-bin), accuracy. Baselines that
  MUST appear in every scorecard: (a) global blue-side rate, (b) per-league
  side rate, (c) team-Elo-only logistic. Beat (c) on Brier or do not ship.
- Calibration: isotonic on validation; report pre/post ECE.
- Expected honest numbers (Q14): 55-63% accuracy. Report whatever comes out.

## Layers to build

1. riftquant/ratings/:
   - openskill_ratings.py: PlackettLuce, TEAM-RESULT mode default (two
     5-player teams ranked by game outcome). Per report 08: PandaSkill's FFA
     mode hurts raw accuracy -- implement the FFA variant behind a flag for
     later comparison, default OFF.
   - Adopt the mu_ctx + mu_meta split: domestic games update mu_ctx;
     international-event games (worlds/msi/first_stand/lta_cross tournaments)
     update mu_meta per region. Offset update exactly as report 08 describes.
   - Roster handling: rating follows the PLAYER (player_id), team rating =
     aggregate of the 5 starters as-of game date. New player init: league-
     mean prior with high sigma. No inactivity decay in v0 (matches source).
   - CLI: build-ratings -> data/processed/ratings/player_ratings.parquet
     (player_id, as_of, mu_ctx, mu_meta_region, sigma, games_played).
2. riftquant/features/pregame.py -- feature builder emitting one row per
   game with groups (each column prefixed by group):
   - side_: blue/red, league, era flags (fearless_era, first_selection_era).
   - team_: sum/mean/min of player mu (ctx + meta-adjusted for cross-region
     games), sigma aggregates, roster continuity (games this exact 5-stack
     played together), recent form (win rate last 10, decayed).
   - pc_: player-champion proficiency per slot: empirical-Bayes shrunk
     winrate (prior = player's overall WR, strength ~10 games), games-on-
     champ (log), days-since-last-played-champ, champ played in fearless
     game N context.
   - draft_: pick order features from v_draft_actions (first-pick champ,
     counterpick slots), series game number, champs burned count (fearless).
   - meta_: champion pro presence+WR on this patch and the prior patch
     (computed point-in-time from pro games only), comp damage mix
     (AD/AP from a static champion tag table -- create
     data/reference/champ_tags.csv seeded from ddragon tags), scaling proxy.
   - CLI: build-features -> data/processed/features/pregame.parquet.
3. riftquant/models/pregame.py:
   - Baselines (side rates, elo-logistic), LR (L2, standardized), LightGBM
     (monotonic constraints on team rating diff), isotonic calibration.
   - CLI: train-pregame (fits on train, calibrates on val), eval-pregame
     (scorecard: metrics per split + per league + per season, baseline
     table, calibration curve data, feature importances) -> writes
     docs/eval/pregame_v0_<date>.md (ASCII tables) + parquet of per-game
     predictions.
   - predict-pregame --game-id X (historical) prints P(blue win) + top
     feature contributions (SHAP or LGBM contribs).
4. Tests: as-of join correctness (constructed mini-fixture where peeking
   would flip the answer), rating update math vs hand-computed example,
   shrinkage math, split boundaries, tripwire fires on a deliberately leaky
   feature fixture.

## Deps

lightgbm, scikit-learn, openskill (add to pyproject; keep versions current).
If lightgbm wheels fail on this Windows box, fall back to xgboost and say so.

## Constraints

House rules: ASCII only, no AI attribution, no commits, additive cli.py
edits, ruff clean, all existing tests stay green. Target ~1200-1800 new
source lines. Runtime: full feature build over ~5-8k games must stay under
~5 min (polars, vectorized; no per-row python loops over games).

## Verification loop

1. build-ratings on current data; spot-check: a known top team's players
   (e.g. Gen.G/T1 LCK) rank above relegation-tier players in mu_ctx.
2. build-features; row count == v_games count for covered leagues; NO NULL
   explosion (report null rates per feature group).
3. train-pregame + eval-pregame on the time splits; scorecard written; all
   baselines present; tripwire not fired (or fired and investigated).
4. predict-pregame on 3 famous games (e.g. a T1 2026 game) prints sane
   probabilities and contributions.
5. Full pytest green, ruff clean.
Report: files+lines, the SCORECARD ITSELF pasted (all metrics + baselines),
null-rate table, deviations, limitations. Honest numbers only -- a model that
does not beat Elo-only is a valid, reportable outcome.
