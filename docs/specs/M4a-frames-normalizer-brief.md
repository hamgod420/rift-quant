# M4a Build Brief -- livestats frames normalizer (raw -> tidy parquet)

Self-contained spec. Independent of M2 (models); prereq for M4 (in-game
model). Extends the riftquant package.

## Context

data/raw/livestats/{window,details}/<game_id>.jsonl.gz hold raw frames for
~47+ games (growing continuously). Read a couple of real files FIRST to
learn the exact schema -- do not trust this brief's field names over the
data. Window frames: per-team gold/kills/objectives + per-player level/
items/gold-ish; details frames: per-player granular stats. ~1/sec cadence,
7-12k frames per stream per game. gameState field marks in_game/paused/
finished. Frames may contain pause spans and (rare) missing finished flag.

## Deliverables

1. riftquant/frames/normalize.py:
   - parse_window(game_id) + parse_details(game_id) -> polars DataFrames.
   - A game-level TIDY output, downsampled to 10s resolution (keep every
     frame whose ts crosses a 10s boundary; also always keep the final
     frame), one row per (game_id, ts_bucket):
     team-level columns: blue/red gold, kills, towers, inhibs, barons,
     dragons (count + types list + soul point flag), grubs/herald where
     present, plus derived: gold_diff, xp_diff if available, kill_diff.
     per-player columns kept NESTED (polars struct list) -- do not explode
     to 10 columns x stats in v0.
   - Pause handling: mark rows inside pause spans (gameState != in_game);
     derived game_clock_s = cumulative in_game time (wall gaps and pauses
     excluded) so models see game time, not wall time. Document the
     approximation in code.
   - Event extraction: objective_events parquet (game_id, game_clock_s,
     type, killer_team) inferred from count deltas between consecutive
     frames (dragon count +1 => dragon event, etc.). Approximate is fine;
     flag simultaneous multi-increments.
2. CLI additions (additive): normalize-frames [--limit N] (processes any
   archived game lacking a normalized output; idempotent via output
   existence), frames-status (archived vs normalized counts).
   Outputs: data/processed/frames/<game_id>.parquet and
   data/processed/objective_events/<game_id>.parquet.
3. Tests: fixture-driven (build small fixtures from REAL frame excerpts you
   read -- 20-30 frames incl. a pause span and a dragon increment);
   game_clock computation, downsampling boundary logic, event-delta logic,
   idempotent skip. No network in default pytest.

## Constraints

House rules: ASCII, no AI attribution, no commits, additive cli.py edits,
pydantic optional here (polars-native fine), ruff clean, existing tests
green (135 currently). Performance: one game must normalize in <5s; use
polars, stream the gzip (do not load 12k frames x json into python dicts
one-comprehension-at-a-time if avoidable, but correctness > speed in v0).
You own src/riftquant/frames/ + additive cli.py/README-DEV.md edits. Other
agents may write docs/ and data/ concurrently -- irrelevant to you.
Environment: venv at .venv (Windows Scripts/ layout), python 3.14.

## Verification loop

1. Read 2 real raw files (one clean finished game, one with a pause --
   game 113475493522604199 has a real mid-game pause; 113475798006664581
   lacks a finished flag). Confirm schema assumptions in a scratch note.
2. normalize-frames --limit 5 live; show row counts, a 5-row excerpt of one
   tidy output, and the objective_events for one game vs a sanity source
   (dragon counts in final frame == number of dragon events).
3. frames-status shows consistent counts.
4. pytest green, ruff clean.
Report: files+lines, verification excerpts (real numbers), schema notes
learned from the data, deviations, limitations.
