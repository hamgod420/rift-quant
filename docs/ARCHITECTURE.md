# ARCHITECTURE.md -- v0 draft (pre-research, revise when reports land)

Round 1 draft. Everything here is subject to the research reports in
`docs/research/`; sections that depend on unverified sources are marked
[PENDING-RESEARCH].

## 1. System overview

```
                +------------------+
   sources ---> |  INGEST layer    | ---> data lake (parquet) ---> DuckDB views
                +------------------+
                  connectors, each isolated:
                  - oracles_elixir   (bulk CSV)         [PENDING-RESEARCH]
                  - leaguepedia      (Cargo API)        entity canon
                  - golgg            (scraper)          gap-filler
                  - lolesports_feed  (livestats frames) [PENDING-RESEARCH]
                  - grid             (official, if approved)
                  - ddragon/cdragon  (static per-patch)
                  - riot_soloq       (player form)
                  - odds_capture     (polymarket + books)

                +------------------+
   lake ------> |  ENTITY layer    |  players, teams, leagues, patches
                +------------------+  alias resolution, roster stints

                +------------------+
   entities --> |  FEATURE layer   |  point-in-time feature store
                +------------------+  every feature: (entity, as_of, value)
                  groups: team_strength, player_skill, player_champ,
                  matchup, comp_synergy, meta_patch, draft_context,
                  ingame_state (frame-level)

                +------------------+
   features --> |  MODEL layer     |  pregame model | ingame model
                +------------------+  + calibration + blending
                          |
          +---------------+----------------+
          v               v                v
      ANALYSIS        PREDICTION        TRADING
      retro reports   live win %        pricing, quotes,
      WPA, throws,    post-draft %      paper-trade ledger,
      anomalies       matchup query     risk limits
```

## 2. Data model (core tables, first cut)

Entity tables:
- `leagues(league_id, name, region, lineage_notes)` -- lineage maps LCS->LTA-N etc.
- `teams(team_id, canonical_name)` + `team_aliases(alias, team_id, valid_from, valid_to)`
- `players(player_id, canonical_handle)` + `player_aliases(...)`
- `roster_stints(player_id, team_id, role, start_date, end_date)`
- `patches(patch_id, version_string, release_date, season, era_flags)`
- `champions(champ_id, name)` + `champion_patch(champ_id, patch_id, stats_json, change_flags)`

Game tables:
- `series(series_id, tournament_id, best_of, date, fearless_flag)`
- `games(game_id, series_id, game_num, patch_id, blue_team, red_team, winner, duration, data_tier)`
   - `data_tier`: completeness class (full-timeline / scoreboard-only / minimal) -- LPL tolerance
- `game_players(game_id, player_id, team_id, role, champ_id, runes_json?, kills, deaths, ..., gold10, gd10, gd15, ...)`
- `draft_actions(game_id, seq, type[ban|pick], side, champ_id)` -- exact order
- `frames(game_id, ts, blue_gold, red_gold, ..., per_player_json)` -- timeline where available
- `objective_events(game_id, ts, type, side, detail)` -- dragons(elemental type), herald/grubs, baron, towers, atakhan

Derived/feature tables:
- `player_ratings(player_id, as_of, rating, sigma, role)`
- `team_ratings(team_id, as_of, rating_components)`
- `player_champ_stats(player_id, champ_id, as_of, games, wins, shrunk_wr, last_played, soloq_prior)`
- `matchup_stats(player_a, player_b, role, as_of, n, gd10_mean, ...)`
- `meta_patch_stats(patch_id, league_id, champ_id, presence, wr, role_dist)`
- `market_prices(market_id, game_id?, ts, bid, ask, mid, source)` -- odds capture

Principle: every feature queryable "as of" a timestamp. No feature computed
from data dated after the game it feeds. Enforced by the feature layer API,
not by discipline.

## 3. Models

### 3.1 Pregame (post-draft) model -- M2
- Input feature groups: side, team ratings (player-aggregated), player-champ
  proficiency (5v5), matchup priors, comp features (scaling curves, damage mix,
  engage/disengage tags, synergy embedding scores), meta strength of picks on
  patch, draft-order context, fearless-draft pool-depth context, recent form,
  inter-league strength (for internationals), patch/era flags.
- Architecture: LightGBM (monotonic constraints where sane) ensembled with an
  L2 logistic regression on the same features; isotonic calibration on a
  rolling validation window.
- Also emit a pre-draft variant (teams + players known, no champs) for
  draft-phase trading.

### 3.2 In-game model -- M4
- Row = (game, timestamp) frame; label = eventual winner.
- Features: pregame prior (the 3.1 output -- crucial early), gold/xp/cs diffs,
  kill/death state, objective state (dragons by type, soul point/soul, grubs,
  herald, baron buff live w/ remaining time, atakhan, towers/inhibs w/ respawn),
  level/item power spikes, death timers, time-of-game, and interactions.
- Architecture: LightGBM with time bucketing OR single model with time
  interactions (test both); calibration per time bucket.
- Blending: P(win|t) = w(t)*pregame + (1-w(t))*state-model early game, learned w.
- v2 candidates (only if v1 validates): sequence model over frames for
  trajectory/momentum, survival-analysis framing for objective timing.

### 3.3 Retro analysis toolkit -- M5
- WP timeline per historical game; WPA attribution per event window.
- "Deserved winner": time-integrated WP + threshold rules; throw/comeback
  catalog; anomaly score = P(observed trajectory | corpus).

## 4. Trading (M6+, gated on model validation)
- odds_capture daemon from M1-M2 (cheap, accumulates the backtest asset).
- Pricing: model prob -> fair price -> quote with spread >= f(uncertainty,
  adverse-selection risk); Kelly-fraction sizing capped hard.
- Paper ledger first; live switch is a config flag behind explicit human action.
- In-play trading GATED on the latency question (see QUESTIONS.md Q16).

## 5. Evaluation harness (built WITH M2, not after)
- Rolling-origin backtests; metrics: Brier, log loss, ECE, accuracy.
- Baselines: blue-side rate, Elo-only, market closing price (when captured).
- Every model version gets a scorecard artifact checked into docs/eval/.

## 6. Explicit non-goals for now
- No vision/VOD parsing (positions from minimap) -- future maybe.
- No scrim/soloq-as-training-rows.
- No real-money orders until validation gates pass and you approve posture.

## 7. Known observability ceiling
Public feeds do not expose: cooldowns, summoner spell timers (sometimes
broadcast-overlay only), ward positions (partial), player camera/inputs.
"Every aspect of the game" therefore means "every aspect the data exposes,
plus engineered proxies" -- documented per-feature in the feature registry.
