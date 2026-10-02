# M1 Build Brief -- data foundation + recorders (v0 scaffold)

Self-contained spec for the implementing agent. Read fully before coding.

## Context

Project rift-quant (this repo): win-probability modeling for pro LoL
(LCK/LPL/LEC/LCS). This brief covers the FIRST implementation pass: python
package scaffold + two verified connectors + the frame archiver skeleton.
Architecture: docs/ARCHITECTURE.md. Decisions: docs/QUESTIONS.md.

## Verified API facts (measured 2026-08-21, build against these)

lolesports persisted API:
- Base: https://esports-api.lolesports.com/persisted/gw
- Header: x-api-key: 0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z (public key)
- getLeagues?hl=en-US -> leagues[].{id,slug,name}. Ids: LCS 98767991299243165,
  LEC 98767991302996019, LCK 98767991310872058, LPL 98767991314006698.
- getTournamentsForLeague?hl=en-US&leagueId=X -> tournaments back to 2012
  with {id,slug,startDate,endDate}.
- getCompletedEvents?hl=en-US&tournamentId=X -> events[].games[].id (numeric
  gameId). Index EMPTY for LCK <=2022, LEC <=2023, LPL <=2024 -- treat empty
  as expected, not an error.
- getEventDetails?hl=en-US&id=MATCHID -> match.games[] fallback.

livestats feed:
- Base: https://feed.lolesports.com/livestats/v1 -- NO key needed.
- /window/{gameId} and /window/{gameId}?startingTime=RFC3339 -> {frames:[...]}
  10 frames/call (~1/sec cadence). Page by advancing startingTime past the
  last frame's rfc460Timestamp until frames stop advancing (game end).
  IMPORTANT: startingTime must be rounded to a multiple of 10 seconds and
  must be >= 45s behind wall-clock now for live games.
- /details/{gameId}?startingTime=... -> per-player detail frames (same paging).
- A full game is ~180-220 window calls. Be polite: 0.2-0.5s sleep between
  calls, retry w/ backoff on 429/5xx.

Leaguepedia Cargo API (verified reachable):
- GET https://lol.fandom.com/api.php?action=cargoquery&format=json&tables=...
- Example that works: tables=ScoreboardGames, fields incl. GameId,
  DateTime_UTC, Patch, where=OverviewPage LIKE 'LCK/2026%'.
- Use a descriptive User-Agent; max ~500 rows/query; paginate with offset;
  sleep >=1s between calls. Key tables: ScoreboardGames, ScoreboardPlayers,
  PicksAndBansS7, Tournaments, TournamentRosters, Players, Teams,
  MatchScheduleGame.

## Deliverables

Repo root: c:\Users\andyj\Documents\Github\clodex-test\rift-quant

1. Python package scaffold:
   - pyproject.toml (uv-compatible; deps: httpx, polars, duckdb, pydantic>=2,
     typer, tenacity; dev: pytest, ruff). Python >=3.12. Package name
     riftquant, src layout (src/riftquant/...).
   - Modules: riftquant/{config.py, http.py (shared client: UA, retries,
     rate-limit courtesy), ingest/{lolesports.py, leaguepedia.py,
     livestats.py}, store/{lake.py (parquet writers, data/raw partitioning)},
     cli.py (typer app)}.
2. Connectors (typed pydantic models for responses; raw JSON also persisted
   verbatim to data/raw/<source>/... as gzipped jsonl -- raw-first principle):
   - lolesports: list_leagues, list_tournaments(league), completed_events
     (tournament) -> normalized game index rows (game_id, match_id, series
     best_of, teams, start_time, league, tournament, strategy).
   - livestats: fetch_window_frames(game_id, from_ts=None) generator that
     pages correctly and terminates; archive_game(game_id) writes
     data/raw/livestats/window/<game_id>.jsonl.gz (+details variant).
   - leaguepedia: cargo_query(table, fields, where, ...) generic + one typed
     helper scoreboard_games(overview_page_like, since) -- pagination + rate
     courtesy built in.
3. CLI commands (typer):
   - riftquant index-games --league lck --since 2023 -> writes game index
     parquet via lolesports connector.
   - riftquant archive-frames --league lck --since 2023 --limit N -> archives
     frames for indexed games not yet archived (idempotent, resumable,
     skip-if-exists).
   - riftquant lp-probe -> one Leaguepedia query smoke test printing 3 rows.
4. Tests (pytest, no live network in CI-style tests): paging logic unit-tested
   with canned frame fixtures (make tiny fixtures by hand); startingTime
   rounding; idempotent-skip logic. One optional live smoke test marked
   @pytest.mark.live.
5. README-DEV.md: how to run each command, data layout, politeness rules.

## Constraints

- ASCII only in all files. No AI attribution anywhere. Conventional-commit
  style if committing (do NOT commit -- leave working tree for review).
- Raw-first: never normalize without also persisting the raw payload.
- Idempotent + resumable everywhere (archiver will run unattended later).
- No secrets in code; API key above is Riot's public broadcast key (fine to
  hardcode as DEFAULT_PUBLIC_KEY constant with comment).
- Keep it lean: no ORM, no async complexity beyond httpx sync + tenacity,
  no premature abstraction. Target ~600-900 lines total excluding tests.

## Verification loop (run before declaring done)

1. `uv sync` (or pip install -e .) succeeds.
2. `riftquant lp-probe` prints rows live.
3. `riftquant index-games --league lck --since 2025` produces parquet with
   >100 games.
4. `riftquant archive-frames --league lck --since 2026 --limit 1` archives one
   real game fully (frames advance to game end, file size sane, ~10-40k
   frames... if a game archives in under 60 calls something is wrong).
5. `pytest` green; `ruff check` clean.
Report: what was built, verification output pasted, deviations from brief.

## Out of scope for this pass

Oracle's Elixir ingestor (pending research report), entity resolution, DuckDB
views, odds capture (separate brief), soloq collector, any modeling.
