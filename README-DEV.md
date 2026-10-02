# README-DEV

M1 data foundation: python package scaffold, two verified API connectors,
the livestats frame archiver, and a Leaguepedia smoke test. See
docs/specs/M1-build-brief.md for the full spec this was built against.

## Setup

uv (if installed):

    uv sync

Plain pip (Windows venv layout uses Scripts/, not bin/):

    /c/Python314/python -m venv .venv
    .venv/Scripts/pip install -e ".[dev]"

## Commands

    riftquant lp-probe
        Smoke-tests the Leaguepedia Cargo connector: prints up to 3 recent
        LCK 2026 rows from ScoreboardGames.

    riftquant index-games --league lck --since 2025
        Walks lolesports tournaments -> completed events for the league,
        writes/merges data/processed/game_index/<league>.parquet. Safe to
        re-run: rows are de-duplicated on game_id (new data wins).

    riftquant archive-frames --league lck --since 2026 --limit 1
        Archives full livestats timelines (window + details) for up to
        `limit` not-yet-archived, has_vod=True games from the index,
        oldest first. Requires index-games to have been run first for that
        league. Idempotent + resumable: a fully archived game is skipped
        (marked with a `<game_id>.jsonl.gz.done` sentinel); a game
        interrupted mid-archive resumes from its last written frame instead
        of restarting.

    riftquant discover-odds
        One-shot listing of active/upcoming LoL match-winner markets per
        enabled venue (see "Odds recorder" below). Persists what it finds to
        data/raw/odds/markets/<venue>.jsonl.gz.

    riftquant record-odds --interval 30 --duration 200
        Long-running odds capture daemon; see "Odds recorder" below for the
        full writeup. Omit --duration to run until Ctrl+C.

    riftquant odds-status
        Lists every tracked (open, not-yet-closed) market per enabled venue
        with its last capture timestamp (today's UTC capture file), or
        "never" if record-odds hasn't polled it yet.

    riftquant lp-ingest --league lck --season 2026 [--refresh]
        Bulk-ingest one league/season slice of Leaguepedia (Tournaments,
        ScoreboardGames, ScoreboardPlayers, PicksAndBansS7,
        TournamentRosters, Teams, Players) into the parquet lake. See
        "Leaguepedia bulk ingest + entities + views (M1c)" below.

    riftquant build-views
        Resolves player/team entities, rebuilds the patches dimension, and
        (re)creates every DuckDB view over the parquet lake at
        data/riftquant.duckdb. Run after any lp-ingest.

    riftquant validate-m1
        Prints the M1 exit-criteria metrics (LCK/LEC coverage, entity
        dupes, lolesports game-index cross-check). Requires build-views to
        have been run first.

    riftquant normalize-frames [--limit N]
        Normalizes archived livestats games (any game with a raw /window
        archive on disk, regardless of finished/partial state) to tidy 10s
        parquet + objective events. See "Frames normalizer (M4a)" below.
        Idempotent: a game with an existing frames parquet is skipped, even
        if its raw archive keeps growing. Omit --limit to process every
        pending game.

    riftquant frames-status
        Prints archived vs normalized game counts and lists games still
        pending normalization.

    riftquant build-ratings [--ffa/--no-ffa]
        Replays every full-5v5-roster game in date order into per-player
        OpenSkill ratings (mu_ctx + region mu_meta), writing
        data/processed/ratings/player_ratings.parquet. --ffa switches to
        PandaSkill's free-for-all rating mode (default off; team-result
        mode is v0's default). See "Pregame model (M2)" below.

    riftquant build-features
        Builds the pregame (post-draft) feature table -- one row per
        v_games row, columns grouped by prefix (side_/team_/pc_/draft_/
        meta_) -- to data/processed/features/pregame.parquet. Requires
        build-views and build-ratings first.

    riftquant train-pregame [--full-data]
        Fits LightGBM (monotonic constraint on team rating diff) on the
        train split, calibrates (isotonic) on validation, persists the
        model to data/processed/models/pregame/. --full-data switches to
        the 2020+ split preset (see below); default is the current subset
        preset.

    riftquant eval-pregame [--full-data]
        Full scorecard (metrics per split/league/season, the mandatory
        baseline table, calibration curves, feature importances, the
        leakage tripwire) -> docs/eval/pregame_v0_<date>.md.

    riftquant predict-pregame --game-id X
        P(blue win) for a historical game + top LightGBM feature
        contributions. Requires train-pregame to have been run first.

## Data layout

    data/raw/lolesports/leagues.jsonl.gz
    data/raw/lolesports/tournaments/<league_slug>.jsonl.gz
    data/raw/lolesports/completed_events/<tournament_id>.jsonl.gz
    data/raw/lolesports/event_details/<match_id>.jsonl.gz   (fallback path only)
    data/raw/livestats/window/<game_id>.jsonl.gz(.done)
    data/raw/livestats/details/<game_id>.jsonl.gz(.done)
    data/processed/frames/<game_id>.parquet             (tidy 10s rows, see below)
    data/processed/objective_events/<game_id>.parquet   (dragon/tower/inhibitor/baron deltas)
    data/raw/leaguepedia/<table>.jsonl.gz
    data/raw/odds/markets/<venue>.jsonl.gz          (discovered market metadata, append-only)
    data/raw/odds/<venue>/<YYYY-MM-DD>.jsonl.gz     (quote/book/trade/resolution observations)
    data/raw/odds/unmatched_review.jsonl.gz         (mapping.py misses -- see "Odds recorder")
    data/processed/game_index/<league_slug>.parquet
    data/processed/leaguepedia/tournaments.parquet
    data/processed/leaguepedia/scoreboard_games.parquet
    data/processed/leaguepedia/scoreboard_players.parquet
    data/processed/leaguepedia/picks_and_bans.parquet
    data/processed/leaguepedia/tournament_rosters.parquet
    data/processed/leaguepedia/teams.parquet
    data/processed/leaguepedia/players.parquet
    data/processed/patches.parquet
    data/processed/entities/team_aliases.parquet
    data/processed/entities/player_aliases.parquet
    data/reference/alias_overrides.csv       (hand-curated; see "Entity resolution")
    data/reference/unresolved_entities.csv   (generated by build-views; overwritten each run)
    data/riftquant.duckdb                    (views over everything above)

Raw-first: every connector appends the verbatim API response to the matching
`data/raw/...jsonl.gz` log before any normalization happens. Raw logs are
append-only (safe to accumulate duplicates across repeated runs); only the
processed parquet table is de-duplicated (on `game_id`).

## Politeness rules

- livestats: 0.2-0.5s between window/details calls (we use 0.3s), retry
  with backoff on 429/5xx. `startingTime` must be RFC3339 rounded DOWN to a
  multiple of 10 seconds or the API returns HTTP 400.
- Leaguepedia Cargo API: descriptive User-Agent, >=1s between paginated
  calls, <=500 rows/page. A rate-limited request comes back as HTTP 200 with
  an `{"error": {"code": "ratelimited"}}` body (not a 429) -- the connector
  detects that shape specifically and backs off/retries.
- lolesports persisted API: no documented hard limit; a small courtesy sleep
  is applied between tournament-level calls anyway.
- Polymarket (gamma-api/CLOB/data-api): all public/no-auth for market data,
  generous documented limits (Gamma ~400 req/s, CLOB ~900 req/s), but the
  recorder sleeps 1s after every HTTP call regardless (config.POLYMARKET_
  SLEEP_SECS) to stay comfortably under "<=1 req/sec sustained per endpoint
  class" even with several tracked markets. Kalshi is unauthenticated for
  REST market data too, per the research doc -- irrelevant while it stays
  disabled (see "Odds recorder" below).

## Known data quirks worth knowing before touching this code

- `getCompletedEvents.games[]` lists every game slot implied by the series'
  best-of count, including games that were never played because the series
  ended early (e.g. a 2-0 sweep in a Bo3 still lists a 3rd game id with an
  empty `vods` list). The game index keeps these rows with `has_vod=False`;
  `archive-frames` filters them out before archiving. The authoritative
  signal is livestats returning HTTP 204 for such an id, which
  `archive_game` handles regardless (belt and suspenders).
- livestats `/window` frame counts per call are NOT a fixed 10 -- observed
  10 frames on the initial (no `startingTime`) call and 22 frames on a
  later paged call spanning ~9.4s of game time. The pager never assumes a
  count; it drives off frame timestamps and `gameState` only.
- `/details` frames carry no `gameState`, so its paging is bounded by
  `stop_at` (the final timestamp already discovered via `/window`) rather
  than a state check.

## Odds recorder (M1b)

Read-only price/book history for LoL match-winner markets, forward-collected
since no venue publishes free historical order books. Purpose: closing-
line-value benchmarking later (M6). See docs/specs/M1b-odds-recorder-brief.md
for the full spec and docs/research/07-odds-capture-apis.md for the API
mechanics this was built against.

**Compliance gate (docs/QUESTIONS.md Q27) -- read before touching venue
flags.** `config.ODDS_VENUES_ENABLED` defaults to `{"polymarket": True,
"kalshi": False}`. Kalshi's Data Terms of Use bars using Kalshi Data to
train an ML/AI system or archive datasets without written consent, which is
exactly this project's purpose -- Kalshi stays off until a human reads
Kalshi's separate API Developer Agreement and flips the flag by hand.
`riftquant/odds/kalshi.py` exists and is unit-tested against fixtures, but
is never called against the live API by this project's own tooling while
the flag is False, and there is no CLI override.

Scope for v0: match-winner markets only (the market whose slug/ticker
represents the full match, not a per-map/total/handicap/prop). Polymarket
lists 15-30+ additional markets per match; `riftquant/odds/mapping.py`
deliberately stays a simple team-name + start-time-window matcher for now
and logs every non-unique or missing match to
`data/raw/odds/unmatched_review.jsonl.gz` instead of guessing.

Running the daemon long-lived under Windows: it's a plain foreground
console process (no daemonization) -- `signal.SIGINT` (Ctrl+C) triggers a
clean shutdown that flushes and closes every open capture file before
exiting. For an actually-unattended multi-day capture, the simplest option
on Windows is a **Task Scheduler** entry that runs
`.venv\Scripts\riftquant.exe record-odds` (no `--duration`) at logon/startup
with "restart on failure" configured -- the append-only jsonl.gz design
means a restart after a crash or reboot just resumes cleanly (no state to
repair; `--interval`/`--limit`/`--hours-ahead` are safe to reuse as-is).
There is no `--venues` flag on purpose: which venues run is controlled only
by the config flag above, so a Task Scheduler job can never accidentally
start polling Kalshi.

WebSocket was deliberately left out of v0 (the brief allows this: "a clean
15-30s REST poller that never dies beats a fancy WSS client that does").
REST polling needs no dependencies beyond what's already in pyproject.toml
(httpx); a WS client would have added a new one (`websockets`) for marginal
benefit at the market count this recorder tracks today. Revisit if the
tracked-market count grows enough that REST polling cadence becomes the
bottleneck.

## Leaguepedia bulk ingest + entities + views (M1c)

Bulk ingest, entity resolution, the patches dimension, and DuckDB views over
everything -- see docs/specs/M1c-leaguepedia-entities-brief.md for the full
spec. `lp-ingest` extends `riftquant/ingest/leaguepedia.py`'s existing
generic `cargo_query`/`scoreboard_games` (unchanged) with typed fetchers for
Tournaments, ScoreboardPlayers, PicksAndBansS7, TournamentRosters, Teams,
and Players.

**Resumability.** `lp-ingest --league X --season Y` is scoped by an
OverviewPage LIKE pattern (e.g. `LCK/2026%`). The five tournament-scoped
tables are skipped (served from the existing processed parquet) on a rerun
unless `--refresh` is passed -- resumability is at the (table, league,
season) grain, not per-page-offset: an interrupted run leaves no rows for
that slice, so the next run without `--refresh` naturally retries the whole
slice rather than silently claiming partial data as complete. Teams/Players
are looked up globally (bounded to exactly the pages referenced by the
already-ingested games/players in this slice, via `OverviewPage IN (...)`)
and are always incrementally topped up (only pages not already on disk are
fetched), independent of `--refresh`.

**Entity resolution** (`riftquant/entities/`). Canonical id = a Leaguepedia
page name (OverviewPage). `resolve.py` holds the normalizer
(`normalize_name`: lowercase + strip everything but ascii letters/digits --
deliberately does NOT try to strip sponsor tokens like "SK Telecom", since
there's no safe general rule for which tokens are a stripped sponsor vs.
load-bearing identity) and `EntityResolver`, which builds a
normalized-alias -> canonical-id map from canonical ids + observed
(raw-name, canonical-id) pairs, with `data/reference/alias_overrides.csv`
applied last so it always wins. Two names sharing a normalized form but
pointing at different canonical ids are collisions -- flagged, not
arbitrarily picked -- and remain unresolved until an override or a
Leaguepedia-side fix (e.g. a missing `RenamedTo`) resolves them.
`teams.py` sources aliases from Teams' `RenamedTo` chains (e.g. "SK Telecom
T1" -> "T1"); `players.py` sources them from ScoreboardPlayers' own
(`Name`, `Link`) pairs -- Leaguepedia has already resolved its own
redirects into `Link`, so no extra MediaWiki API calls are needed. Anything
that still doesn't resolve is written to
`data/reference/unresolved_entities.csv` (overwritten fresh each
`build-views` run -- a derived report, not raw data) for human review;
nothing is ever guessed.

**Patches dimension** (`riftquant/patches.py`). Parses `"14.23"` (<=2024,
identity), `"25.S1.2"` (2025 seasonal), and `"26.03"`/`"25.04"` (2025
flat+/2026+, marketing year offset -10 from client major) into
`marketing_version`/`client_version`/`ordinal`, plus era flags
(`fearless_era` >=2025, `first_selection_era` >=2026, `atakhan_era` ==2025
only). `client_version` is always two-part `MAJOR.MINOR` -- Data Dragon's
third, per-hotfix point number (e.g. the `.1` in `16.16.1`) isn't
recoverable from Leaguepedia's Patch field and is never synthesized.
`release_date` (min game date seen for that patch) is merged as a MIN
across incremental runs so a later, narrower ingest can't push it later.

**DuckDB views** (`riftquant/store/views.py`, `data/riftquant.duckdb`):
`v_games`, `v_game_players`, `v_draft_actions`, `v_player_champ_history`.
`v_games.best_of_observed` is the max game number actually PLAYED in a
`match_id`'s series (no explicit series-format field exists in
ScoreboardGames), so a 2-0 Bo3 sweep and a real Bo2 look identical from this
data alone -- same caveat as the lolesports connector's own
unplayed-game-slot quirk. `v_draft_actions` assumes Leaguepedia's
established Team1=blue/Team2=red convention (shared by ScoreboardGames and
PicksAndBansS7, and how every downstream consumer -- Oracle's Elixir,
gol.gg -- already interprets these columns); PicksAndBansS7 carries no
separate Side field to independently confirm this against.

**validate-m1** cross-checks `v_games` against
`data/processed/game_index/<league>.parquet` by normalized team-name pair +
a 12-hour start-time tolerance (no id is shared between the two sources).
The join loop is O(leaguepedia_games x game_index_games) per league, fine
at current subset volumes; revisit (e.g. bucket by date first) before
running it over the full 2023-2026 backfill if it gets slow. LPL is expected
to show a much lower join rate than LCK/LEC: Leaguepedia has full LPL
scoreboard coverage but the lolesports persisted API carries almost no LPL
events (`config.py`, verified 2026-08-21) -- a near-zero LPL join rate is
expected, not a defect.

**Known limitations / unverified assumptions:**
- `worlds`'s OverviewPage pattern (`"{season} Season World Championship%"`)
  was confirmed live 2026-08-21. `msi`/`first_stand` patterns in
  `LEAGUEPEDIA_LEAGUE_PATTERNS` are **best-effort, not live-verified** this
  session (further probing hit Leaguepedia's rate limit) -- a 0-row
  `lp-ingest` result for either is a strong signal to check the real
  OverviewPage on lol.fandom.com and fix the pattern, not a sign the league
  has no data.
- `lta_n` ("LTA North/{season}%", the 2025 LCS-lineage season) is likewise
  unverified this session.
- Leaguepedia's shared Cargo rate limit has a cooldown noticeably longer
  than the connector's own 6-attempt/~90s backoff ceiling (hit firsthand
  while building this: a handful of ad hoc probe queries triggered a limit
  that outlasted a full backoff cycle on the next real request). Bursts of
  exploratory querying against this API should expect to need a multi-
  minute cooldown, not just the built-in retry, before a big `lp-ingest`
  run.

## Frames normalizer (M4a)

`riftquant/frames/normalize.py` turns raw livestats frames into a tidy,
10s-resolution parquet per game plus an inferred objective-events parquet.
See docs/specs/M4a-frames-normalizer-brief.md for the full spec; the module
docstring has the complete schema notes learned from reading real archived
frames. Highlights:

- `parse_window(game_id)` / `parse_details(game_id)` parse the raw feed's
  native ~1/sec cadence into polars DataFrames; `downsample_tidy` collapses
  `parse_window`'s output to one row per 10s wall-clock bucket (the frame
  that crosses each boundary, always including the true final frame);
  `extract_objective_events` infers dragon/tower/inhibitor/baron takes from
  count deltas -- run on the FULL-cadence series, not the downsampled one,
  because downsampling can keep a bucket's first frame from BEFORE an
  objective inside that same bucket, which would misattribute the event's
  timing by several seconds.
- `game_clock_s` is cumulative in-game time: wall-clock deltas are summed
  except where either endpoint of that delta isn't `gameState == in_game`
  (i.e. a real pause), which is dropped entirely. Verified against game
  113475493522604199's real ~107.6s mid-game pause.
- Per-player detail in the tidy output is /window's nested fields only
  (gold/level/kills/deaths/assists/creep score/health, NOT items -- those
  live in /details, exposed separately via `parse_details`, not merged in;
  see the module docstring for why). xp_diff and grubs/herald columns from
  the brief's prose are omitted outright: neither field exists anywhere in
  the observed schema (checked across every archived game).
- `objective_events` is scoped to dragon/tower/inhibitor/baron (the
  LoL-standard meaning of "objective"); player kills are not included as a
  discrete event type since they are already continuous in the tidy output
  (`blue_kills`/`red_kills`/`kill_diff`) and would otherwise dominate the
  event volume.
- `normalize-frames` is idempotent by output existence (a game with an
  existing frames parquet is never reprocessed, even if its raw archive
  keeps growing from a concurrent archive-frames run) -- matches
  `archive_game`'s own idempotency style.

## Pregame model (M2)

`riftquant/ratings/`, `riftquant/features/`, `riftquant/models/` -- see
docs/specs/M2-pregame-model-brief.md for the full spec and
docs/research/08-pandaskill-method.md for the rating-layer method this is
adapted from. Highlights:

- **SUBSET MODE (current reality):** only LCK 2026 + LEC 2026 are ingested,
  so the model trains/evaluates on ~1k games (747 with a full 5v5 roster).
  `config.PREGAME_SPLIT_ACTIVE` is the one switch to flip once the 2020+
  backfill lands (`config.PREGAME_SPLIT_FULL`) -- no other code change.
- **Point-in-time correctness** is centralized in
  `riftquant/features/asof.py` (`asof_join_latest` / `strictly_prior_stats`
  / `strictly_prior_rolling_mean` / `strictly_prior_ewm_mean`) -- every
  as-of lookup in `features/pregame.py` routes through one of these three
  functions, never an ad hoc date filter. `asof_join_latest` subtracts a
  1-microsecond epsilon from the query timestamp specifically because
  `player_ratings.parquet` stamps a game's own post-game rating with
  `as_of == that game's own date`; an inclusive backward as-of join would
  otherwise leak a game's own result into its own pregame features.
- **Ratings** (`ratings/openskill_ratings.py`): OpenSkill Plackett-Luce,
  team-result mode by default (PandaSkill's FFA mode is behind `--ffa`,
  off by default -- report 08's own ablation shows FFA alone hurts raw
  accuracy). mu_ctx/mu_meta split with the offset trick for cross-region
  (Worlds/MSI/First Stand) games; untested on live data this session since
  the ingested subset has zero international games (covered by a synthetic
  fixture in tests/test_ratings_openskill.py instead). New players cold-
  start at their region's CURRENT mean mu_ctx (not the flat 25.0 default).
- **Features** (`features/pregame.py`): side_/team_/pc_/draft_/meta_
  column groups, one row per `v_games` row (including games with a partial
  roster -- those just show elevated null rates in team_/pc_/draft_/meta_,
  reported by `null_rate_report`, never silently dropped).
- **Models** (`models/pregame.py`): baselines (global/per-league blue-side
  rate, team-Elo-only logistic) + LR (L2, standardized) + LightGBM
  (monotonic constraint on `team_mu_ctx_sum_diff`) + isotonic calibration
  on the validation split. `run_scorecard` recomputes everything from
  scratch on every call (train-pregame and eval-pregame each call it
  independently) rather than threading partial state between two CLI
  invocations -- simpler, and at this data size LightGBM fits in well
  under a second so the recompute cost doesn't matter.
- **Known gotcha:** isotonic calibration fit on a 31-game validation split
  (the subset preset) is genuinely unstable -- it can map an entire tail
  bin to exactly 0.0/1.0. `run_scorecard` and `predict-pregame` both clip
  calibrated output to `[0.02, 0.98]` as a numerical-safety rail, not a
  calibration fix; the real fix is more validation data (the 2020+
  backfill).
- **Leakage tripwires:** `eval-pregame`'s scorecard hard-flags a >65%
  post-draft test accuracy (Q14's own ceiling) as
  `leakage_investigation_triggered`; tests/test_leakage_tripwire.py checks
  both that flag (on a deliberately-leaky synthetic feature) and that
  shuffling which date label attaches to which game craters a
  point-in-time-dependent feature's signal (the as-of toolkit's own
  correctness check, not just the model's).

## Tests

    pytest              # unit tests only, no network (default; see addopts)
    pytest -m live      # also run the opt-in live smoke test
    ruff check .
