# RESEARCH_LOG.md

## 2026-08-21 -- Round 1 kickoff
- Project scaffolded at rift-quant/; git init (no commits yet per protocol).
- QUESTIONS.md written: 24 self-answered design questions for user review.
- ARCHITECTURE.md v0 draft + ROADMAP.md M0-M7 written.
- Dispatched 6 parallel research agents (Claude sonnet; codex CLI not
  installed on this machine):
  1. 01-historical-data-sources.md -- Oracle's Elixir status, Leaguepedia
     Cargo, gol.gg, LPL gaps, coverage matrix
  2. 02-live-official-feeds.md -- GRID open access, lolesports livestats,
     Bayes, broadcast delay
  3. 03-modeling-literature.md -- accuracy benchmarks, methods, ratings,
     synergy, blue side, momentum, WPA/anomaly
  4. 04-polymarket-trading.md -- esports markets, CLOB API, fees, resolution,
     US status, MM mechanics, odds benchmarking
  5. 05-league-landscape-2026.md -- league structure, fearless draft, 2026
     season changes, patch naming, calendars
  6. 06-static-and-soloq-data.md -- ddragon/cdragon, patch diffs, Riot API
     limits, pro->soloq account mapping, meta stat sources
- Pending: integrate reports, update QUESTIONS.md answers, round 2 deep dives,
  then M1 ingest spec.

## 2026-08-21 -- Report 04 (Polymarket) landed
- Single-match LoL markets exist; volume bimodal ($2K tail to $3.8M marquee).
- Taker fee now 0.05 on sports/esports (2026); makers 0% + rebates.
- CLOB migrated to V2 (Apr 2026); py-clob-client ARCHIVED -> use py-sdk /
  py-clob-client-v2.
- UMA resolution ~2h; no LoL dispute incidents found.
- Polymarket US (QCEX/CFTC) = traditional sports only, NO esports; offshore
  geo-blocked for US persons w/ VPN enforcement; CFTC marketing probe Jun 2026.
- Kalshi esports volume MEASURED LARGER than Polymarket snapshot -> capture
  both venues; Kalshi may be the realistic US venue (user's compliance call).
- Broadcast-lag arb bots documented on live LoL markets ($900->$208K case) ->
  in-play trading demoted to gated future case; pregame/draft markets are the
  strategy. QUESTIONS.md Q16/Q17/Q18 updated.
- No historical order-book data available free -> odds recorder is urgent
  (promoted into M1).

## 2026-08-21 -- Report 06 (static + soloq) landed
- ddragon alive (v16.16.1); CRITICAL gotcha: 2025 patch renaming -> marketing
  "26.16" = client "16.16.1" (offset -10, 25.S1.1 interlude). Translation
  utility required; patches table stores both ids.
- cdragon adds per-rank ability scaling (verified on real data).
- No maintained buff/nerf-per-patch API (dead since 2018) -> DIY snapshot
  diffing for change flags.
- Riot Personal API key (~50 req/min, instant) sufficient for pro-player soloq
  tracking; ~2yr match retention -> start soloq collector early; Spectator-V5
  being deactivated (avoid).
- LPL Super Server: unreachable via API, no tracker coverage -> permanent LPL
  soloq gap, recorded in Q6.
- Account mapping: lolpros.gg (PUUID-anchored) best; op.gg scraping = ToS
  violation (hard no); lolalytics/u.gg grey. New Q25 records ToS posture.
- Pro meta by patch: Oracle's Elixir bulk files + gol.gg best free fits.
- QUESTIONS.md Q6/Q22 updated, Q25 added.

## 2026-08-21 -- Report 05 (league landscape) landed
- LTA DISSOLVED after one season; LCS independent again in 2026 (8 teams).
  Lineage LCS -> LTA North (2025) -> LCS (2026) mapped as one league_id.
- 2026: LCK 10, LPL 14/12, LEC 10/12, LCS 8; all 3 splits/yr, Bo3 regular
  season, Bo5 playoffs.
- Hard fearless universal 2026 (per-series, both teams, no Bo1 carryover);
  NEW "Right of First Selection" -> side choice endogenous; side feature gets
  era interaction.
- Patch 26.1 REMOVED Atakhan + Feats of Strength; grubs reworked; epic
  monsters +15% HP; Baron at 20min. Patch naming YY.NN biweekly; pro stage
  ~6 weeks behind live (26.13 vs 26.16) -> meta priors must be computed on
  the PRO patch.
- Ground truth: Worlds 2025 T1 (3-peat) over KT; MSI 2025 Gen.G; First Stand
  2026 BLG; MSI 2026 HLE. WORLDS 2026: Oct 15 - Nov 14 (Allen TX/Brooklyn) --
  the near-term high-liquidity target; ~8 weeks away.
- Leaguepedia fandom.com returned HTTP 402 to agent WebFetch -- verify Cargo
  API reachability from our own machine in round 2.
- QUESTIONS.md Q3 resolved, Q12 confirmed+expanded.

## 2026-08-21 -- Report 02 (live feeds) landed
- GRID Open Access EXCLUDES LoL (verified on live form); commercial only.
  Bayes insolvent 2025, GRID absorbed IP. GRID assumption dead for hobbyists.
- Unofficial lolesports API verified ALIVE with real calls today:
  persisted/gw (public key) serves 2026 league data; livestats window/details
  (NO key) serves frame-level data incl. HISTORICAL (May 2026 game verified;
  ~8-10s frames/call, ~180-220 calls/game). All community wrappers dead --
  write our own connector.
- Broadcasts 5-10 min delayed; bookmakers get sub-200ms GRID feed; Riot
  mandates GRID for betting partners (Americas/EMEA scope only, NOT LCK/LPL);
  Riot dev portal bans betting functionality -> compliance tension recorded
  in Q18.
- OPEN: livestats retention depth beyond ~3 months unmeasured -> new Q26;
  frame archiver promoted into M1; retention probe queued for round 2. Also
  unmeasured: whether the free live feed is delayed like broadcast.
- QUESTIONS.md Q7 resolved, Q26 added, Q18 updated.

## 2026-08-21 -- Report 03 (modeling lit) landed
- Draft-only ceiling 55-63% pro; in-game S-curve 50->60@10->70@15-20->80@25->
  90+@30-35. Sanity rails adopted in Q14 (higher = suspect leakage).
- PandaSkill (2025): per-role XGBoost performance scores -> OpenSkill rating
  with region-strength decomposition; 67-70% inter-region accuracy. Adopted as
  v1 rating-layer blueprint (Q8/Q10).
- LR remains live-WP production standard (interpretability/speed); ship LR
  alongside GBM. Synergy via embeddings (GAE/DraftRec; 2026 mastery-prior
  paper for small pro samples).
- Blue side ~51.9% and declining; regime-dependent post-First-Selection.
- No public deserved-to-win/throw detector exists -- M5 is whitespace.
- Published accuracy claims often methodology-trapped (random splits, soloq
  mixing) -- trust time-split numbers only.

## 2026-08-21 -- Inline verification spikes (main thread, measured)
- Leaguepedia Cargo API reachable from this machine (agent's HTTP 402 was
  proxy-side): ScoreboardGames returned LCK 2026 rows with Patch=26.03 --
  YY.NN naming confirmed in the wild.
- persisted/gw API works with public key; league ids captured: LCS
  98767991299243165, LEC 98767991302996019, LCK 98767991310872058, LPL
  98767991314006698. LCK tournament index goes back to 2012.
- LIVESTATS RETENTION MEASURED (window endpoint, one game per league-year):
    LCK: 2023-08 -> 2026 OK; <=2022 completedEvents index empty.
    LEC: 2024 -> 2026 OK; 2023 index empty.
    LPL: 2025 -> 2026 OK; 2023/2024 index empty.
  Window returns 10 frames/call, keyless. In-game training corpus therefore:
  ~3yr LCK + ~2.5yr LEC + ~1.5yr LPL (+LCS unprobed, assume LEC-like).
  Q26 updated from provisional to measured.

## 2026-08-21 -- Report 01 (historical sources) landed -- ROUND 1 COMPLETE
- Oracle's Elixir: alive but FRAGILE -- single maintainer, DNS-hijack/malware
  incident Apr 2026, LPL/LDL pipeline dark Jul 21 -> restored Aug 11 2026
  (backfill uncertain), downloads behind React/Cloudflare SPA (old S3 dead),
  schema has bans-in-order + 10/15min diffs but NO runes/items.
- Leaguepedia: only source with per-slot pick/ban order + runes + exact patch
  + role; no timelines; leaguepedia_parser dead -> raw cargoquery.
- gol.gg: uniquely runes + item timings + gold-graph per game; no API/ToS;
  low-volume enrichment only.
- acs.leagueoflegends.com dead since Sep 2021. GRID sole official partner.
- DECISION FLIPPED (Q4): Leaguepedia primary, OE semi-manual secondary,
  gol.gg enrichment, livestats for timelines.
- All 6 round-1 reports delivered: docs/research/01..06. Synthesis at
  docs/research/00-synthesis.md.

## 2026-08-21 -- Report 07 (odds-capture APIs) landed
- Both venues: market-data REST public/no-auth (verified live by agent).
  Kalshi WS requires RSA-signed handshake even for public channels;
  Polymarket WS auth-free. Rate limits generous; WS-first + REST-backstop.
- Kalshi LoL series confirmed live: KXLOL (futures), KXLOLGAME (match),
  KXLOLMAP (per-map); real orderbook/trades pulled.
- Polymarket: one event per match, flat binary markets incl. 15-30+ props --
  more granular than Kalshi.
- Storage trivial: tens of MB/day/venue uncompressed.
- LEGAL FLAG: Kalshi Data Terms of Use PROHIBITS ML training + dataset
  archiving without written consent (read in full by agent). API Developer
  Agreement + Polymarket automated-access ToS unreachable to bots -- HUMAN
  REVIEW NEEDED. New Q27: recorder ships with per-venue toggles, Kalshi OFF
  by default. Alternative benchmark: sportsbook aggregators.
- Next: odds-recorder brief written (docs/specs/M1b-odds-recorder-brief.md);
  build dispatch queued behind the M1 builder (same repo, serialize).

## 2026-08-21 -- M1 core scaffold BUILT and verified
- Builder agent delivered src/riftquant (868 lines + 434 test lines): config,
  http (retries/UA), lolesports + livestats + leaguepedia connectors, parquet
  lake, typer CLI (index-games, archive-frames, lp-probe).
- Verification (agent ran, I spot-checked artifacts): 1234 LCK 2025+ games
  indexed to parquet; 2 real LCK 2026 games frame-archived end-to-end
  (~7.9k/7.1k frames, gameState=finished termination, ~31 min game spans);
  idempotent re-runs proven (.done markers); 28 tests green; ruff clean.
- Notable empirical corrections from the builder: frames/call is NOT fixed at
  10 (22 observed with startingTime) -- pager drives off timestamps;
  completed events list UNPLAYED Bo3/Bo5 game slots (HTTP 204 on window) --
  handled as terminal zero-frame state; tzdata needed on Windows.
- Ops started: background jobs indexing LEC 2024+/LPL 2025+/LCS 2024+/LCK
  2023+ and archiving 2 more LCK 2026 games (data/logs/).
- M1b odds-recorder builder dispatched (Polymarket on, Kalshi off per Q27).
- M1c brief written (Leaguepedia bulk ingest + entities + DuckDB views);
  dispatch after M1b returns (cli.py conflict -> serialized).

## 2026-08-21 -- M2 PREGAME MODEL PIPELINE BUILT (subset-verified, honest)
- Full pipeline delivered: OpenSkill ratings (mu_ctx/mu_meta split,
  team-result mode, FFA behind flag), central as-of feature API + leakage
  tripwire, 110 features in 5 groups, baselines + LR + LightGBM + isotonic,
  scorecard generator, rolling-origin CV, predict-pregame CLI. ~2415 source
  lines + ~880 test lines. 165 tests green, ruff clean (I re-verified).
- HONEST SCORECARD (subset: 829 train / 31 val / 152 test): model does NOT
  beat Elo-only on test Brier (lgbm 0.2602-0.2606 vs elo 0.2330; flat side
  rate 0.2369); accuracy 59-63% = exactly Q14's expected band; tripwire NOT
  fired. Expected at this sample size (LightGBM train acc 0.87 vs test 0.61
  = overfit on 829 rows). Verdict deferred to the 2020+ retrain -- which is
  now literally: rerun 5 CLI commands with --full-data after backfill.
- Rating sanity passed: Gen.G/T1/G2 stars top the mu_ctx table; relegation
  players at bottom. predict-pregame produces sane calibrated probs.
- CRITICAL LATENT BUG FOUND+FIXED by builder: entities/patches modules
  computed output paths at import time -> pytest monkeypatching wrote test
  fixtures OVER PRODUCTION parquet (player_aliases wiped to 0 rows by a
  plain pytest run). Fixed (paths computed fresh), production data rebuilt
  and verified. Second occurrence of the "stale/aliased derived state"
  failure class today -- both now guarded.
- Known limitations recorded in the scorecard doc: isotonic unstable at
  n_val=31 (safety-clipped), champ tags not patch-exact, side-choice
  attribution (First Selection) not yet ingested, LightGBM non-determinism
  ~0.005-0.01.

## 2026-08-21 -- OPS INCIDENT: concurrent same-league archive runs corrupted 3 gz files
- Cause: I chained overlapping archive-frames batches for the same league;
  two writers appended to the same game's jsonl.gz -> invalid gzip blocks
  (2 games affected of 568 files; detected by a resume-time decompress
  error, confirmed by full integrity scan).
- Fix: corrupt raw files + done markers + their normalized outputs deleted
  (idempotent re-archive picks them up). RULE ADOPTED: single-lane archiving
  -- exactly one archive-frames batch at a time, rotating leagues; the
  archiver itself should later get a per-game lockfile (future hardening,
  noted for backfill script users: do not run two backfill_frames.sh at
  once).
- Integrity scan is cheap (~seconds for 568 files) -- rerun after any
  suspected overlap.

## 2026-08-21 -- USER DIRECTIVES (mid-run)
- Scope: "focus on games past 2019" -> everything scoped to 2020+ (Q2
  updated as USER DECISION; backfill slices extended 2020-2022; game index
  extending; M2 brief scope updated). Frames stay 2023+ (physical wall).
- Mode: "keep polling until out of credits; if research is exhausted, start
  building" -> M2 pregame-model builder dispatched in SUBSET MODE (full
  pipeline verified on the 747-game 2026 subset; retrain = config change
  once 2020+ backfill lands tomorrow).

## 2026-08-21 -- M4a frames normalizer BUILT and verified
- src/riftquant/frames/normalize.py (605 lines + 409 test lines): raw
  window/details jsonl.gz -> tidy 10s-bucket parquet (team gold/kills/
  objectives + nested per-player) + objective_events parquet (delta-based).
  CLI: normalize-frames, frames-status. 135 tests green; ~1-2s/game.
- Verified on real data: pause exclusion correct (game_clock advanced ~4s
  across a 107.6s wall pause); dragon events == final-frame dragon counts on
  both test games (incl. soul-point case).
- SCHEMA TRUTHS (trust these over any doc): window frames = rfc460Timestamp,
  gameState, blue/redTeam{totalGold,totalKills,towers,inhibitors,barons,
  dragons[],participants[5]{gold,level,kda,cs,hp}}; NO XP ANYWHERE in the
  feed; NO void grubs / herald fields; items live in /details only; pause =
  single 'paused' frame then silence; dragon vocab incl. hextech/chemtech/
  elder; occasional same-millisecond frame bursts.
- Observability ceiling updated: xp_diff unavailable from frames (models use
  level+gold as proxies); grubs/herald must come from Leaguepedia scoreboard
  or be skipped.
- Limitation accepted for v0: normalized outputs do not auto-refresh if a
  raw archive grows later (existence-based idempotency).

## 2026-08-21 -- Second livestats edge case: feed ends without finished flag
- Worlds 2025 AL vs HLE: 11,894 frames archived (41min span) but no
  `finished` frame ever published; beyond-end startingTime probes get
  CLAMPED to the same tail frames (in_game). Pager behaved correctly but
  "partial" games get no .done marker -> every rerun re-spends the 1-hour
  patience budget.
- Fix: STALE_END_AGE=24h -- historical archives whose newest frame is >24h
  old are terminal (done marker; CLI label "ended(no-finish-flag)"); recent
  unfinished games still resume. 2 new tests; 14/14 green; ruff clean.
- Livestats feed catalog so far: (1) unplayed placeholder slots (HTTP 204),
  (2) mid-game pause holes, (3) missing finished flag + tail clamping.
  All three now handled + regression-tested.

## 2026-08-21 -- Leaguepedia cooldown status
- Rate limit persists ~40min after M1c's heavy session (two retry slices
  refused). Plan: retry in 1-2h; overnight run of
  scripts/backfill_leaguepedia.sh is the proper tool (120s inter-slice
  sleeps + resumability).
- Update (+3h): retry fetched a partial burst (some pages landed, resumable)
  then re-limited -- the quota appears to be a rolling window allowing small
  bursts. Mid-day grinding is low-yield; USER ACTION: run
  scripts/backfill_leaguepedia.sh overnight (1-2 sittings). Meanwhile frame
  archive + odds capture chains continue all day.
- Update (+5h, 13:45 UTC): still limited after 5 retries across 5 hours.
  Verdict: likely a DAILY quota per IP, exhausted by M1c's build session.
  Retries stopped for today; the overnight script (or tomorrow) resumes it.
  Everything else unaffected.

## 2026-08-21 -- M1c BUILT + verified; M1 exit criteria MET (subset)
- Builder delivered: Leaguepedia bulk ingest (7 Cargo tables, resumable per
  league-season slice), entity resolution (normalizer + alias overrides +
  unresolved-review CSV), patches dimension w/ marketing<->client translation
  (verified on all 12 live patch strings), DuckDB views (v_games,
  v_game_players, v_draft_actions, v_player_champ_history), validate-m1.
  ~1650 source lines + ~1000 test lines. 121 tests green, ruff clean.
- Live subset (LCK+LEC 2026): 747 games ingested, 100.0% full 5v5 + draft
  order + patch coverage; 0 entity dupes; 100% cross-join vs lolesports
  index. Two real bugs caught by its verification loop (player-page case
  mismatch costing 28% of games; tautological dupes metric).
- INCIDENT + FIX (mine): my independent validate-m1 rerun printed 0%
  coverage from STALE derived state (pre-bugfix alias parquet on disk) --
  silently-wrong, not failing. Fixed: validate-m1 now always rebuilds views
  first (idempotent, seconds). Reverified: deterministic 100%. Lesson:
  validators must never read derived state they did not just build.
- Full backfill estimate: ~30-90 min CLI time across ~28 league-season
  slices; Leaguepedia rate-limit cooldowns dominate (their 90s backoff can
  be outlasted -- needs multi-minute patience between retries).
- Agent-ops lesson: the builder stalled waiting on a background watcher
  notification that can never reach a stopped subagent; resumed via
  SendMessage with poll-don't-wait instructions. Future briefs: tell
  builders to poll, never wait on background events.

## 2026-08-21 -- FEED DELAY MEASURED LIVE: ~25s, NOT broadcast-delayed
- During live LCK (BRO vs BFX): free livestats feed frontier lag median
  25.6s (n=21, range 20.5-32.3s) vs 5-10 min broadcast delay. The free feed
  is ~10-20x faster than broadcast. Q16 majorly revised: in-play trading
  upgraded from "gated moonshot" to "researchable" -- model quality at
  equal-ish latency vs same-feed bots; licensed sub-200ms feeds still
  faster.
- Methodology lesson recorded: probe v1 (bare /window) measured game-START
  frames, produced a false "broadcast-delayed" verdict for ~20 minutes until
  the linear-growth artifact was spotted; v2 frontier-probing (anchor near
  now, walk forward) is correct. Bare /window = first frames; frontier
  requires startingTime walking. Repeat measurement on LEC/LCS days before
  full trust.
- Bonus mechanics: frontier sits INSIDE the documented 45s startingTime
  floor -- empirics beat docs again.
- LEC REPLICATION SUCCESS (TH vs SK mid-game, 15:21 UTC): median 26.2s
  (n=22, 19.9-36.3s) -- matches LCK. ~25s feed lag confirmed across 2
  leagues / 3 games. Q16 finalized.
- LEC probe attempt (TH vs SK, 15:11 UTC): INCONCLUSIVE -- n=2 samples
  (119s/172s) taken within ~3min of game start; empty pre-game ladder rungs
  break the frontier walk at the boundary, overstating lag. Mid-game rerun
  dispatched. Methodology note: frontier probing needs the game >5min old.
- SECOND-GAME CONFIRMATION (same day, BRO vs BFX g2): median frontier lag
  27.6s (n=22), matching probe 3's 25.6s. Footnote: samples taken after the
  game's final frame show linearly growing "lag" (44->170s tail) -- that is
  distance-to-last-frame after game end, not feed delay; live-use code
  should treat a monotonically growing frontier gap as "game likely ended".
  Finding now rests on two independent games; LEC/LCS replication still
  desirable but not blocking.

## 2026-08-21 -- M1b odds recorder BUILT and live-verified
- Builder delivered src/riftquant/odds/ (781 lines + 724 test lines):
  discovery (gamma-api), polymarket client (CLOB V2 REST), kalshi client
  (fixtures-only, flag OFF per Q27 -- zero live calls, verified), recorder
  daemon (quote/book/trade/resolution observations, append-only daily
  jsonl.gz), mapping stub w/ unmatched-review file. CLI: discover-odds,
  record-odds, odds-status. 69 tests green.
- LIVE: discovered 43 real LoL match-winner markets (incl. HLE vs T1 and
  EDG vs JDG on 2026-08-23); 200s run captured 560 observations. Schema
  quirk found: gamma-api outcomes/clobTokenIds are JSON-encoded STRINGS.
- Ops: scripts/record_odds_loop.sh written (restart-forever, hourly
  re-discovery cycles). USER ACTION: run it 24/7 on an always-on box --
  price history is unbackfillable. Session keeps 9-min recorder slots
  chaining meanwhile.
- Fixed the 4 ruff errors in scripts/measure_feed_delay.py (mine); repo
  fully ruff-clean.
- M1c builder dispatched (Leaguepedia bulk ingest + entities + patches +
  DuckDB views + validate-m1) -- the last M1 piece.

## 2026-08-21 -- Pager pause-gap bug found and fixed (inline)
- Worlds 2025 T1vIG g2 archived "partial" at 126 frames (~2min). Probed the
  feed directly: frames EXIST at +3/+10/+20/+30min -> archiver pager bug, not
  missing data. Root cause: "two empty pages -> end of feed" + "non-advancing
  page -> stop" both fire on in-game PAUSE holes; server anchors response
  windows AT startingTime, so the safe fix is linear +10s probing with a
  1-hour patience budget (jumping could overshoot and drop frames).
- Fixed _paginate in src/riftquant/ingest/livestats.py; MAX_PAGES 1000->5000;
  added MAX_GAP_SECS=3600. 4 new regression tests (pause gap, patience
  expiry, overlap dedupe). 12/12 pass, ruff clean. Live re-archive of the
  stalled game dispatched to verify resume-through-pause.
- Lesson recorded: "partial" results in archive logs = investigate feed vs
  pager before trusting; pause holes are ROUTINE at internationals.
- VERIFIED LIVE: stalled game resumed from frame 126, crossed the pause hole,
  completed at 9187 window frames with finished terminal state. skip(done)
  confirmed on the sibling game. Fix is good.

## 2026-08-21 -- Report 08 (PandaSkill deep-dive) landed
- arXiv 2501.10049, code MIT at github.com/PandaScore/PandaSkill -- agent read
  BOTH paper and full source; code corrects paper prose (MinMaxScaler not
  z-score; team layer = logistic regression on 10 raw mu-3sigma scalars).
- Method: per-role XGBoost (15 ratio features, monotonic constraints,
  n_est=2000 lr=0.01) -> win-prob -> percentile PScore (performance decoupled
  from outcome); OpenSkill PlackettLuce in FREE-FOR-ALL over all 10 players
  ranked by PScore with magnitude-weighted updates; mu = mu_ctx + mu_meta,
  domestic games update mu_ctx only, internationals update mu_meta only
  (offset trick kills feedback loops). NO inactivity decay anywhere.
- Eval nuance: the META-RATING drives inter-region accuracy (~70%); FFA
  mechanic HURTS raw accuracy (pays off in fairness/expert-concordance);
  XGBoost barely beats simpler baselines on accuracy -- the edge is
  calibration + role-fairness. Implication for us: adopt the mu_ctx/mu_meta
  split for cross-league calibration; consider team-result OpenSkill (not
  FFA) for pure win prediction, keep PScore for player profiles.
- Data gaps vs our columns: wards, level, damage-taken, event timestamps --
  livestats details frames cover most; Leaguepedia alone does not.
- Bonus: champion-mastery/archetype paper = arXiv 2605.18338 (methods-only,
  unvalidated -- treat as ideas, not ground truth).

## 2026-08-21 -- Game index complete; LPL persisted-API hole confirmed
- Probed LPL tournaments directly: completedEvents nearly empty (2 events in
  split1 2025, 1 in split1 2026, zero elsewhere) -> LPL has effectively NO
  free frame source; rides scoreboard-only tier via Leaguepedia (Q5/Q26
  updated). This matches report 01's "LPL structurally weakest" verdict.
- Found 2025 LCS-lineage league ids: lta_n 113470291645289904, lta_cross
  113475149040947852; added to config.LEAGUE_IDS along with worlds/msi/
  first_stand (Q1 scope). Inline single-file edit.
- GAME INDEX TOTALS (parquet, gameIds frame-capable): LCK 2023+ 1894,
  LEC 2024+ 1090, LCS 2024+ 480, LTA-N 2025 234, LTA-Cross 53, Worlds 2023+
  357, MSI 2023+ 295, First Stand 110, LPL 15. Total ~4528 games.
- Backfill ops: full archive ~1-2 weeks polite runtime -> wrote
  scripts/backfill_frames.sh (priority-ordered, idempotent, restartable;
  BATCH env var). USER ACTION AVAILABLE: run it in a spare terminal to
  accumulate the frame corpus. Meanwhile incremental bounded runs continue
  from this session (LCK run2, LEC run3 in background).
