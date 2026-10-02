# ROADMAP.md

Gate rule: a milestone ships only when its exit criteria pass. No milestone
starts real-money anything.

HARD DEADLINE DISCOVERED (2026-08-21): Worlds 2026 runs Oct 15 - Nov 14 --
the highest-liquidity prediction/trading window of the year, ~8 weeks out.
Target: M1-M2 (data + pregame model) and the recorders (odds + frames) live
BEFORE Worlds. Collectors running during Worlds = a season's worth of
marquee-market data we cannot get any other way.

## M0 -- Research (NOW, 2026-08-21)
6 parallel research reports: historical data, live feeds, modeling lit,
Polymarket, 2026 league landscape, static/soloq data.
Exit: reports in docs/research/, QUESTIONS.md updated, sources chosen.

## M1 -- Data foundation + recorders
Ingest chosen historical sources -> parquet lake -> DuckDB; entity resolution
(players/teams/aliases); patches dimension w/ marketing<->client version
translation; data-tier flags (LPL tolerance).
Recorders (all forward-collecting, start ASAP because none can be backfilled):
  a) odds_capture: Polymarket (CLOB V2) + Kalshi esports prices.
  b) frame_archiver: livestats frames for every LCK/LPL/LEC/LCS game.
  c) soloq_collector: pro-player match history (2yr Riot retention window).
Plus: livestats retention-depth probe (how far back do frames exist?).
Exit: one SQL query returns a clean 5v5 game row with draft order + patch for
>= 95% of 2023-2026 LCK/LEC games; entity dupes < 1%; all three recorders
running unattended.

## M2 -- Pregame model v0
Ratings (player+team), player-champ tables, comp features; LightGBM+LR
ensemble; calibration; evaluation harness with baselines.
Exit: beats Elo-only baseline on Brier on held-out most-recent split; scorecard
artifact produced; post-draft win % CLI works for any historical game.
STATUS 2026-08-21: PIPELINE BUILT + subset-verified (165 tests, honest
scorecard at docs/eval/pregame_v0_2026-08-21.md). Exit gate NOT yet passed:
on the 829-game subset the model does not beat Elo-only (expected -- too
little data). Gate re-attempted after the 2020+ Leaguepedia backfill via
`train-pregame --full-data` + `eval-pregame --full-data`.

## M3 -- Player profile DB + matchup queries
Player profiles (pool depth, era history, form); role-matchup win % queries;
fearless pool-depth features.
Exit: "player A vs player B in role R" returns calibrated estimate w/ CI;
profile pages generated for all active LCK/LPL/LEC/Americas players.

## M4 -- In-game model v0
Timeline/frame ingest for covered games; state model + pregame blending;
per-time-bucket calibration.
Exit: WP curve for any covered historical game; Brier at 15:00 beats
gold-diff-logistic baseline; calibration ECE < 3% per bucket.

## M5 -- Retro analysis toolkit
WPA per event, deserved-winner reports, throw/comeback catalog, anomaly flags.
Exit: reproduce 3 known famous throws/upsets with sensible narratives; anomaly
list over a season reviewed and non-embarrassing.

## M6 -- Market validation (paper)
Model vs captured odds; closing-line-value study; paper-trade ledger with
pregame quotes.
Exit: documented edge (or documented no-edge -- honest either way) over >= 1
full split of forward-collected prices.

## M7 -- Live pipeline + trading experiments (gated)
Live ingest, live WP, quoting engine, risk limits; in-play only if latency
research supports it. Real orders only after your explicit go + compliance
review on your side.
