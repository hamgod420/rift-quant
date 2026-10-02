# M4 Build Brief -- in-game win probability model v0

Self-contained spec. Data: normalized frame parquet from M4a (currently ~230
games and growing while you work -- snapshot the game list at start) plus the
M2 pregame pipeline (prior + as-of API). SUBSET MODE philosophy applies: the
corpus is thin; build the full pipeline, verify end-to-end, report honest
numbers, make retraining trivial as the archive grows.

## Context

Read first: docs/QUESTIONS.md (Q8 3.2, Q14 S-curve expectations, Q26),
src/riftquant/frames/normalize.py (tidy schema: 10s buckets, game_clock_s,
team gold/kills/objectives, nested players; objective_events parquet),
src/riftquant/models/pregame.py + features/asof.py (M2 conventions),
config.py (M2 section for path/split patterns). Data:
data/processed/frames/<game_id>.parquet, data/processed/objective_events/,
data/processed/game_index/*.parquet (winner labels + start_time + league).

## Deliverables

1. riftquant/models/ingame.py (+ features/ingame.py if cleaner):
   - Training-row builder: one row per (game_id, ts_bucket) from tidy frames
     joined to the game index for the winner label. Features: game_clock_s
     (+ bucketed time), gold_diff, kill_diff, tower/inhib diffs, dragon
     counts + soul-point flags per side, baron state, elder, level-based
     proxies from nested players (mean/max level diff), derived slopes
     (gold_diff delta over trailing 60s/180s -- the momentum features, Q9),
     and the M2 pregame prior P(blue) for the game where available (as-of
     correct: prior computed from the M2 model artifact; games missing a
     prior get 0.5 + a missing-flag column).
   - Exclude rows with game_state != in_game; exclude the first 60s.
   - Labels: blue_win from game index (team-name join is already solved in
     the index rows -- winner field exists; verify on 3 games by hand).
2. Models: (a) BASELINE gold-diff-and-time logistic (the literature
   standard); (b) LightGBM on all features; (c) blended variant: model prob
   w(t)-blended with pregame prior, w(t) learned or grid-searched on val.
   Calibration: isotonic per time bucket (0-10min, 10-20, 20-30, 30+) on
   validation; safety-clip [0.02, 0.98].
3. Splits: BY GAME (never by row -- all rows of a game stay in one split),
   time-based on game start_time: train = games before 2025-10-01, val =
   2025-10-01..2025-12-31, test = 2026+. Report game and row counts per
   split. Encode as config constants like M2's presets.
4. Eval scorecard -> docs/eval/ingame_v0_<date>.md: Brier/logloss/accuracy
   PER TIME BUCKET for baseline vs lgbm vs blended (the S-curve table --
   compare against Q14's expected curve: ~60% @10min, ~70% @15-20, ~80%
   @25, 90%+ @30+; far above = leakage investigation), calibration ECE per
   bucket pre/post, and a WP-curve sanity plot as ASCII sparkline or table
   for one famous game.
5. CLI (additive): build-ingame-features, train-ingame, eval-ingame,
   wp-curve --game-id X (prints time series of calibrated P(blue win) with
   key objective events annotated from objective_events parquet).
6. Tests: row-builder correctness on a fixture game (hand-computed diffs,
   slope features, label join), split-by-game invariant, no rows from
   non-in_game states, blending math. No live network in default pytest.

## Constraints

House rules: ASCII, no AI attribution, no commits, additive cli.py edits,
existing 165 tests stay green, ruff clean. You own riftquant/models/ingame*,
riftquant/features/ingame*, tests additions, docs/eval output. Do NOT touch
odds/, frames/normalize.py, ingest/, ratings/, the M2 files (import them).
Background processes keep archiving frames + recording odds concurrently --
snapshot your training game list once at start; do not chase the growing
archive mid-run. Feature build for ~230 games x ~200 rows must stay under
~2 min (polars, vectorized).

## Verification loop

1. build-ingame-features: report games used, rows built, null rates.
2. Hand-verify 1 game: pick a known game, print 3 rows, check gold_diff and
   label against the raw tidy parquet.
3. train-ingame + eval-ingame: scorecard written with per-bucket table; the
   baseline S-curve should roughly match Q14 expectations (report deltas
   honestly; a thin-corpus miss is reportable, silence is not).
4. wp-curve on the T1 vs IG Worlds 2025 game 2 (113475493522604199 -- has a
   real pause) and one 2026 LCK game: curves must be monotone-ish sane, no
   NaNs across the pause.
5. pytest green (all suites), ruff clean.
Report: files+lines, THE SCORECARD pasted, hand-verification excerpt,
deviations, limitations, retrain-on-more-data command sequence.
