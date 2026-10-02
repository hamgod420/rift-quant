# M1c Build Brief -- Leaguepedia bulk ingest + entity resolution + DuckDB views

Self-contained spec. DO NOT DISPATCH while the M1b (odds recorder) agent is
running -- both edit cli.py/pyproject.toml (serialize). Extends the riftquant
package (see src/riftquant/, README-DEV.md).

## Context

M1 exit criterion: "one SQL query returns a clean 5v5 game row with draft
order + patch for >= 95% of 2023-2026 LCK/LEC games; entity dupes < 1%."
The Leaguepedia connector (generic cargo_query + scoreboard_games helper)
exists; this pass adds bulk ingest, entity resolution, the patches dimension,
and DuckDB views that join everything.

## Scope of data

Leagues/overview pages: LCK, LPL, LEC, LCS (2023 -> current 2026 splits;
include 2025 "LTA North" pages as LCS lineage), plus internationals: Worlds,
MSI, First Stand (2023->2026) restricted later at query time.
Cargo tables to ingest (raw-first: persist raw json pages, then normalize to
parquet):
- Tournaments (id, name, dates, region, league lineage tag)
- ScoreboardGames (game-level: teams, winner, patch, datetime, links)
- ScoreboardPlayers (player-game rows: player, champ, role, runes if present,
  KDA, gold, cs)
- PicksAndBansS7 (per-slot draft order both sides)
- TournamentRosters or equivalent for rosters per tournament
- Players + Teams pages (canonical names, current + former ids)
Respect rate courtesy (>=1s between calls, max 500 rows/page, paginate by
offset; User-Agent already configured in http.py). Cache raw pages to
data/raw/leaguepedia/<table>/... so re-runs are incremental (skip fetched
offsets unless --refresh).

## Entity resolution

- riftquant/entities/{players.py, teams.py, resolve.py}
- Canonical id = normalized Leaguepedia page name. Alias tables built from
  Players/Teams redirects and observed name variants (case/spacing/sponsor
  prefixes like "T1" vs "SK Telecom T1").
- Deterministic normalizer (lowercase, strip punctuation/sponsor tokens) +
  explicit alias overrides file (data/reference/alias_overrides.csv, created
  empty with header + a few seed examples).
- Emit unresolved/ambiguous names to data/reference/unresolved_entities.csv
  for human review -- never guess silently.

## Patches dimension

- riftquant/patches.py: parse patch strings seen in ScoreboardGames
  ("26.03", "25.S1.2", "14.23" legacy) into a canonical ordinal; store
  marketing_version + client_version (translation rule: 2026 marketing
  "26.NN" -> client "16.NN.x" per docs/research/06; 2025 interlude 25.SN.M;
  <=2024 identity). Table data/processed/patches.parquet with both ids,
  approx release date (min game date seen), season, era flags
  (fearless_era = >=2025, first_selection_era = >=2026, atakhan_era =
  2025 only).
- Unit-test the translation on: "14.23", "25.S1.2", "26.03", "26.16".

## DuckDB views

- riftquant/store/views.py + CLI `riftquant build-views`: creates/refreshes
  data/riftquant.duckdb with views over the parquet lake:
  v_games (one row per game: league, tournament, date, patch ids, blue/red
  team canonical ids, winner, best_of, game_num_in_series, fearless_era...),
  v_game_players (10 rows/game w/ canonical player ids, champ, role),
  v_draft_actions (ordered picks/bans), v_player_champ_history
  (player, champ, patch, date, result -- the base for profiles).
- CLI `riftquant validate-m1`: prints the M1 exit metrics: coverage % of
  LCK/LEC 2023-2026 games having full 5v5 + draft order + patch; count of
  entity dupes detected (same normalized name -> multiple canonical ids);
  cross-check row counts vs the lolesports game index parquet where both
  exist (report join rate by league-year, LPL expected lower).

## Constraints

Same house rules: ASCII only, no AI attribution, no commits, raw-first,
idempotent/resumable, additive cli.py edits only, pydantic models for
normalized rows, tests with fixtures (no network in default pytest run),
ruff clean. Target ~800-1200 new lines excluding tests. Bulk ingest runtime
matters: fetching ~4 leagues x 4 years of ScoreboardGames/Players/PicksAndBans
at 1 req/s will take a while -- implement and verify on a SUBSET live
(LCK 2026 + LEC 2026), and make the full backfill a resumable CLI anyone can
rerun (`riftquant lp-ingest --league lck --season 2023` etc.).

## Verification loop

1. lp-ingest LCK 2026 + LEC 2026 live end-to-end (raw pages cached, parquet
   written; print row counts per table).
2. build-views succeeds; duckdb query over v_games returns plausible counts;
   v_draft_actions shows 20 ordered actions for a spot-checked game.
3. validate-m1 runs and prints its metrics for the ingested subset (coverage
   >= 95% on the subset; entity dupes listed).
4. Patch translation unit tests pass; pytest green; ruff clean.
Report: files+lines, verification output excerpts (real numbers), deviations,
limitations, and the estimated wall-clock for the FULL 2023-2026 backfill.
