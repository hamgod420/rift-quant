# QUESTIONS.md -- self-answered design questions

Per your directive: every question I would have asked you, answered myself,
recorded here for review. Format: chosen answer, why, and what would make us
revisit. ALL answers are provisional until you sign off. Questions marked
[RESEARCH] have agents verifying them now; answers get updated when reports land.

Status legend: [OK] confident default | [?] genuine judgment call, please review
| [RESEARCH] pending verification.

---

## Scope and data

### Q1. Which games exactly are in scope? [?]
**A:** All main-stage games of LCK, LPL, LEC, and the Americas top flight
(whatever the LCS successor is called in 2026 -- likely "LTA North"/"LCS"),
regular season + playoffs, PLUS international events (Worlds, MSI, First Stand)
restricted to matches involving teams from those four leagues.
**Why:** Internationals are the highest-liquidity prediction targets (biggest
Polymarket volume) and force cross-league strength calibration, which the model
needs anyway. Excluding them would make the model useless for exactly the games
people care most about.
**Revisit if:** You want strictly the four domestic leagues only.

### Q2. How far back does training data go? [USER DECISION 2026-08-21]
**A (your directive):** "Focus on games past 2019" -- scope is games from
2020 onward, for everything: training data, player profiles, ingestion,
analysis. The old two-tier plan (2014+ for profiles) is dropped.
Interpretation note: I read "past 2019" as strictly after 2019 (2020+); if
you meant to include the 2019 season itself, say so -- it is a one-line
change to the backfill slices.
Physical constraint that does not change: timeline FRAMES only exist from
2023 (LCK) / 2024 (LEC) / 2025 (LPL) -- Riot's feed has nothing older. So
2020-2022 games contribute scoreboard-level data (Leaguepedia + OE bulk
files), and the in-game model trains on 2023+ regardless.
**Applied to:** backfill_leaguepedia.sh slices (2020+ added), game index
(2020+), M2 training window.

### Q3. What does "LCS" mean now? [RESOLVED 2026-08-21]
**A:** Resolved cleanly: LTA (2025's merged LCS+CBLOL+LLA) was dissolved after
one season; **LCS runs independently again in 2026** (8 teams). Schema keeps
lineage mapping LCS(-2024) -> LTA North (2025) -> LCS (2026-) as one
continuous league_id. 2026 top tier: LCK (10 teams), LPL (14/12), LEC (10/12),
LCS (8) -- all on 3 splits/year, Bo3 regular season, Bo5 playoffs. Bo3
regular seasons everywhere is good news for sample size (more games per match)
and makes series-context features (fearless) apply to nearly all games.
**Source:** docs/research/05-league-landscape-2026.md
**Update (measured, same day):** lolesports carries the 2025 LCS-lineage games
under separate league ids (lta_n = LTA North, plus lta_cross) -- added to the
indexer so the LCS series is continuous 2024 -> 2025(LTA) -> 2026. Also added
worlds/msi/first_stand ids (Q1 scope).

### Q4. Primary historical data source? [RESOLVED 2026-08-21 -- FLIPPED]
**A:** **Leaguepedia Cargo API is PRIMARY**, not Oracle's Elixir. Research
found OE alive but fragile: single-maintainer, suffered a DNS-hijack/malware
incident (Apr 2026), LPL/LDL pipeline outage Jul-Aug 2026 with uncertain
backfill, downloads now behind an unscriptable React/Cloudflare app (old S3
dead), and the schema has NO runes/items. Leaguepedia is the only source with
exact per-slot pick/ban ORDER, runes, exact patch, and role (no timelines --
those come from livestats, Q26). Plan: (1) Leaguepedia ingestor first;
(2) OE bulk files loaded semi-manually as cross-validation + pre-2023 breadth;
(3) gol.gg as low-volume enrichment (item timings, gold graphs);
(4) livestats frames for timelines. acs.leagueoflegends.com confirmed dead
(2021). leaguepedia_parser lib is dead -- we build directly on cargoquery.
**Why:** Primary source must be scriptable and multi-maintainer; OE is
neither anymore.
**Revisit if:** OE publishes a stable programmatic endpoint again.
**Source:** docs/research/01-historical-data-sources.md

### Q5. LPL data gaps -- how to handle? [RESEARCH]
**A (provisional):** Accept that LPL has historically thin public data (no
public Riot match history for years; limited timeline data). Ingest what
scoreboard-level data exists (Leaguepedia/gol.gg/OE), flag LPL rows with a
data-completeness tier, and let the model handle missing in-game features via
feature masks rather than dropping games.
**Why:** LPL is priority #2 for you; dropping it is unacceptable, so the schema
must tolerate partial data from day one.
**Revisit if:** Research finds a good LPL timeline source.

### Q6. Do we use solo queue data? [OK]
**A:** Yes, but only as player-level prior features (champion pool, recent form,
new-champion proficiency), never as core training rows. Pro and solo queue are
different games.
**Why:** Pro sample sizes per player-champion are tiny (often n<5); solo queue
is the only way to estimate "can this player actually play this champion"
without absurd variance. Standard practice in the literature.
**Revisit if:** Mapping pro players to soloq accounts proves too unreliable
(Chinese superserver especially).
**Update 2026-08-21 (research):** Confirmed constraints: (1) LPL Super Server
is unreachable via Riot API and NO tracker covers it -- LPL player soloq form
is a permanent gap; LPL profiles lean on pro games + international-event soloq
only. (2) Riot match history retention is ~2 years -- soloq history cannot be
backfilled deeper, so the soloq collector should start early to accumulate.
(3) Riot Personal API key (~50 req/min, instant) suffices for tracking pro
players' accounts; production key only if we ever scrape ladders. (4) Account
mapping: lolpros.gg has the best PUUID-anchored methodology; dpm.lol/
trackingthepros/deeplol usable but undocumented. (5) Spectator-V5 is being
deactivated -- do not build anything on live spectate.
Source: docs/research/06-static-and-soloq-data.md

### Q7. Where do runes / exact champion state come from? [RESOLVED 2026-08-21]
**A:** GRID is OUT for us: its free Open Access tier excludes LoL entirely
(CS2/Dota only, verified on the live application form); LoL is
contact-sales commercial only. Bayes Esports went insolvent in 2025 (GRID
bought the IP). The timeline source is therefore the UNOFFICIAL lolesports
API, which the agent verified ALIVE today with real calls:
- esports-api.lolesports.com/persisted/gw/* (public key) -- schedules, games,
  2026 LCK/LPL/LEC data confirmed.
- feed.lolesports.com/livestats/v1/{window,details}/{gameId} (NO key) --
  frame-level gold/items/level/objectives; historical backfill confirmed on a
  May 2026 game; paging via startingTime, ~8-10s of frames per call,
  ~180-220 calls per full game.
All community wrapper libs are dead (2015-2022) -- we write our own connector.
Runes for pro games: gol.gg / Leaguepedia where recorded. Cooldown-level state
remains unobservable; ceiling documented.
**Ceiling update (measured during M4a build):** the frames feed contains NO
XP data anywhere, no void grubs, no herald fields; items are in /details
only. In-game models use level + gold as XP proxies; grubs/herald come from
scoreboard sources or are skipped. Full measured schema in RESEARCH_LOG
2026-08-21 (M4a entry).
**Revisit if:** we ever pay for GRID commercial (only path to sub-200ms feeds).
**Source:** docs/research/02-live-official-feeds.md

### Q26. How deep does livestats historical retention go? [MEASURED 2026-08-21]
**A:** I probed it directly (real API calls, one game per league-year, HTTP
status + frame presence verified):
- LCK: frames served for Aug 2023 -> 2026. Spring 2022 and earlier: the
  completed-events index is EMPTY (discovery fails there).
- LEC: 2024 -> 2026 served; 2023 index empty.
- LPL: 2025 -> 2026 served; 2023/2024 index empty (LPL joined the pipeline
  late -- consistent with its known data-poverty).
- Tournament metadata exists back to 2012, but frame discovery via
  completedEvents walls at the above dates. Frames may exist for older games
  if gameIds are found elsewhere -- low priority.
So the in-game model trains on: ~3 seasons LCK + ~2.5 LEC + ~1.5 LPL (+LCS,
same probe pending), thousands of games -- enough for v1. Frame ARCHIVER still
ships in M1 (retention policy is Riot's whim; local archive ends the risk).
Mechanics confirmed: window endpoint returns 10 frames/call, keyless.
**Correction (measured during M1 build/index):** (1) frames-per-call is NOT
fixed at 10 (22 observed with startingTime; pager drives off timestamps).
(2) LPL is far worse than "2025+": the persisted index holds only ~15 LPL
games TOTAL across 2025-2026 -- LPL has effectively NO free frame coverage.
LPL rides the scoreboard-only data tier (Q5) and its in-game predictions
carry wider uncertainty; measured counts: LCK 2023+ 1894 games indexed,
LEC 2024+ 1090, LCS 2024+ 480 (+LTA 2025 pending), LPL 15.
**Why:** Measured, not assumed.
**Source:** probe script in session scratchpad; results in RESEARCH_LOG.md.

---

## Modeling

### Q8. What is the v0 model? [OK]
**A:** Two models, built in this order:
1. **Pregame/post-draft model**: gradient-boosted trees (LightGBM) +
   logistic-regression ensemble on: team ratings (Elo-family, player-based),
   side (blue/red), player-champion proficiency, champion meta strength on
   patch, composition/synergy features, draft context (fearless-draft state,
   pick order). Data available immediately from historical sources.
2. **In-game model**: LightGBM on timeline frames (gold/xp/cs diffs, kills,
   objectives, dragon soul state, baron timers, item/level state, time
   interactions), initialized from the pregame prior and blending toward
   game-state dominance as time advances.
**Why:** GBDTs are the documented sweet spot for tabular esports prediction;
deep sequence models are a v2 experiment, not a v0 risk.
**Revisit if:** Literature review returns strong evidence for a different
architecture.
**Update 2026-08-21 (lit review):** Plan confirmed with refinements. v0 stays
LR/Elo baseline + LightGBM. v1 adopts the **PandaSkill (2025)** pattern for the
rating layer: per-role performance scores (XGBoost on box stats) feeding an
OpenSkill Bayesian rating with explicit region-strength decomposition -- it is
literally our LCK/LPL/LEC calibration problem, reported 67-70% accuracy on
inter-region games. Live WP: logistic remains the production standard for
interpretability/speed; we ship LR alongside GBM and compare. Synergy: learned
embeddings (GAE/DraftRec lineage; a 2026 mastery-prior/archetype paper
addresses small pro samples directly). Source: docs/research/03-modeling-literature.md

### Q9. How is "momentum/tempo" modeled? [?]
**A:** As engineered features only (gold slope over rolling 2-3 min windows,
objective streaks, kill-trade deltas) -- and I will explicitly test whether they
add predictive power beyond current state. Sports analytics literature mostly
finds "momentum" is already priced into state; I expect the same and will not
force it.
**Why:** Intellectual honesty; momentum features that do not validate get cut.
**Revisit if:** You have a specific tempo hypothesis you want encoded (e.g.
tempo = item/objective timing advantages, which IS real state, not momentum).

### Q10. How is player bias / player history encoded? [OK]
**A:** Three layers per player: (1) a skill rating (OpenSkill/TrueSkill-family,
updated per game, role-aware); (2) champion-pool proficiency: empirical-Bayes
shrunk winrate + play count per champion with patch-era decay, pro data blended
with soloq priors; (3) matchup profile: role-vs-role lane stats (early gold/cs
diffs vs specific opponents) with heavy shrinkage. These feed the pregame model
as features; the same tables power the standalone "player matchup win %" query
you asked for.
**Why:** Matches your stated goals; shrinkage is mandatory at pro sample sizes.
**Revisit if:** never -- but the exact shrinkage strengths are tunable.

### Q11. Champion synergy/counters at pro sample sizes? [OK]
**A:** Regularized pairwise matrices are too sparse on pro data alone. Plan:
learn champion embeddings from large solo-queue corpora (or use meta-stat
priors), then fine-tune/calibrate composition features on pro games. Encode
comp archetypes (engage/poke/split/scaling curves) as interpretable features
alongside embeddings.
**Why:** Standard small-data trick: borrow strength from the big corpus.
**Revisit if:** Embeddings underperform simple archetype tags (possible!).

### Q12. Fearless draft -- how does it change the model? [CONFIRMED 2026-08-21]
**A:** Confirmed: HARD fearless (champion locked for BOTH teams once played,
per-series, no carryover to Bo1s) is universal in 2026 across all tier-1
leagues plus First Stand/MSI/Worlds. Model consequences stand as designed:
(1) series-context draft features (game N, champs burned by both sides);
(2) champion-pool DEPTH as first-class player feature; (3) pre-2025 era flag.
NEW wrinkle found: 2026 introduced "Right of First Selection" -- side choice
is decoupled from draft-order priority, so BLUE SIDE IS NOW PARTLY ENDOGENOUS
(teams choose it). The side feature must be interpreted as "side + who chose
it" where recorded; blue-side winrate baselines pre/post this rule are not
directly comparable. Open sub-question in the report: exact Bo1-fearless
handling and LPL soft-fearless residue from 2025 -- era flags cover it.
**Source:** docs/research/05-league-landscape-2026.md

### Q13. Evaluation protocol? [OK]
**A:** Time-based splits only (train on past, validate on later season, test on
held-out most-recent). Primary metrics: Brier score + log loss + calibration
curves (ECE). Secondary: accuracy. Mandatory baselines to beat: (a) blue-side
winrate, (b) team-Elo-only logistic, (c) closing market odds where we have them
(the real bar for trading). Kelly-simulated ROI backtest once odds capture
exists.
**Why:** Random splits leak (same teams/patches straddle train/test).
Calibration is the product for trading; accuracy alone is vanity.
**Revisit if:** never on time-splits; metric weights negotiable.

### Q14. What accuracy should we expect? (expectation-setting) [CONFIRMED 2026-08-21]
**A:** Lit review confirms: draft-only ceiling ~55-63% for pro (team quality
dominates; the draft itself adds little). In-game follows a consistent S-curve
across LoL/Dota/HoK studies: ~50% at 0, ~60% at 10min, ~70% at 15-20min
(GD@15 era), ~80% at 25min, 90%+ at 30-35min. These are our sanity rails:
post-draft accuracy above ~65% or an in-game curve far above the S-curve =
LEAKAGE BUG until proven otherwise. Blue-side advantage ~51.9% historically
and DECLINING, and is now regime-dependent (2026 First Selection rule) -- so
side is a feature with an era interaction, not a constant. Trading bar remains
calibration + edge vs market, not raw accuracy. Caveat from the report:
several published accuracy claims have methodology traps (random splits,
soloq-pro mixing); we trust only time-split numbers.
**Source:** docs/research/03-modeling-literature.md

### Q15. "Who should have won" / anomaly flagging? [OK]
**A:** Retrospective reports computed from the in-game model: time-integrated
win probability (dominance), peak WP, WP swings at key events (win-probability-
added per objective/fight), and "conversion failure" flags (e.g. had 85% WP at
25:00 and lost -> throw report with the events that flipped it). Anomaly =
outcome vs dominance divergence beyond threshold, or WP trajectory shapes that
are rare in the corpus.
**Why:** Directly implements your example use case with standard WPA machinery.
**Revisit if:** You want anomaly detection aimed at integrity/match-fixing
specifically (different, more sensitive tooling).
**Update 2026-08-21 (lit review):** No public LoL "deserved-to-win"/throw
detector exists -- this deliverable is genuine whitespace, not a rebuild of
prior art. Source: docs/research/03-modeling-literature.md

---

## Trading

### Q16. Live trading vs broadcast delay -- fatal problem? [MEASURED 2026-08-21 -- MAJOR REVISION]
**A:** I measured it live during an LCK game (BRO vs BFX, 21 mid-game
samples with a frontier-probing method): the FREE keyless livestats feed
serves game state a median of **25.6s behind reality** (20.5-32.3s range),
vs a 5-10 MINUTE broadcast delay. The free feed is ~10-20x faster than the
broadcast. Implications:
- The documented latency-arb bots (report 04) most likely trade on this very
  feed; at ~25s we match retail-invisible speed for free, though licensed
  GRID feeds (sub-200ms) stay faster.
- In-play is UPGRADED from "gated, likely dead" to "viable to research":
  our 25s state + in-game model vs Polymarket prices moved by retail flow
  and same-feed bots. Edge would come from model quality at equal-ish
  latency, not speed alone.
- Roadmap still starts with PRE-GAME/DRAFT markets (simplest, delay-immune),
  but M7 in-play experiments are now a real line item, not a moonshot.
- Measurement status: CONFIRMED across two leagues, three games, same day:
  LCK 25.6s (n=21) and 27.6s (n=22), LEC 26.2s (n=22, range 19.9-36.3s).
  The ~25s figure is uniform. (The first probe method was wrong -- bare
  /window returns game-START frames -- corrected same hour with frontier
  probing; game-start boundary samples are also unreliable, probe only
  games >5min old.)
**Why revised:** measured beats assumed; the assumption was too pessimistic.
**Source:** scripts/measure_feed_delay.py, data/logs/feed_delay_probe3.log,
RESEARCH_LOG 2026-08-21.

### Q17. Polymarket integration scope for now? [CONFIRMED 2026-08-21]
**A:** Build an odds-capture recorder EARLY -- research confirmed Polymarket
publishes NO free historical order-book data and third parties already charge
for it, so forward collection is the only free path to a backtest asset.
Capture facts: single-match LoL markets DO exist (LCK/LPL/LEC), but volume is
bimodal -- marquee matches $50K-$3.8M, regular-season sometimes under $2K.
Fees changed: taker fee on sports/esports is now 0.05 (2026), makers still 0%
plus rebates -- fee model favors our market-making posture. API: CLOB migrated
to V2 (April 2026); old py-clob-client is ARCHIVED -- build against py-sdk /
py-clob-client-v2 only. Resolution via UMA, ~2h undisputed, no LoL-specific
incidents found. No order placement until model beats captured closing odds
over a full split, paper-traded.
**Why:** Cheap now, impossible to backfill later; CLV is the only honest
pre-live validation.
**Revisit if:** never on capture; go-live criteria are yours.
**Source:** docs/research/04-polymarket-trading.md

### Q18. Legal/compliance posture? [?]
**A:** I build research + paper-trading infrastructure. Whether/where live
trading is permissible (jurisdiction, your employment's trading policies --
you work at a crypto custodian) is YOUR decision with your own counsel; the
codebase will keep a hard paper/live switch. Research agent is documenting the
factual 2026 access status (Polymarket US/QCEX etc.) only.
**Why:** Not my call, and employment trading policies at a crypto firm are a
real consideration.
**Revisit:** when you decide.
**Update 2026-08-21 (research):** Factual state: Polymarket US (CFTC-regulated,
via QCEX) launched but covers traditional sports ONLY -- no esports; offshore
Polymarket.com remains geo-blocked for US persons with active VPN enforcement;
a CFTC marketing-practices probe opened June 2026. Separately, Kalshi (US,
CFTC-regulated) showed LARGER measured weekly LoL/esports volume than
Polymarket in the snapshot -- Kalshi may be the more realistic venue for a US
person, pending your compliance review. The odds recorder will capture BOTH
venues. Source: docs/research/04-polymarket-trading.md
**Update 2 (feeds report):** Riot policy tension on record: Riot's developer
portal bans "betting or gambling functionality" in API products, and since
June 2025 Riot mandates betting operators use GRID (scoped to Americas/EMEA
only -- notably NOT LCK/LPL). Personal research/modeling on public data is the
current posture; any productized betting use would require a GRID commercial
license and your compliance review. Source: docs/research/02-live-official-feeds.md

---

## Engineering

### Q19. Stack? [OK]
**A:** Python 3.12+ managed with uv; polars for dataframes; DuckDB + Parquet
as the local analytical store (M1); LightGBM/XGBoost + scikit-learn for models;
pytest; ruff. Postgres only when a live service needs it (M6+). No cloud until
something must run 24/7 (odds capture will need a cheap VPS or an always-on
local box -- decision deferred to M6).
**Why:** Zero-cost, fast, reproducible local-first analytics; DuckDB over
Postgres at this stage because the workload is analytical batch, not OLTP.
**Revisit if:** You prefer pandas or have infra preferences.

### Q20. Project name/location? [?]
**A:** `rift-quant` at `Documents/Github/clodex-test/rift-quant`, fresh git
repo, not committed until you say so.
**Why:** Needed a name to create folders; trivially renameable.
**Revisit:** rename freely.

### Q21. Player/team identity resolution? [OK]
**A:** Leaguepedia player pages as the canonical player ID (they maintain
rename/team-change history); internal surrogate keys; alias tables for OE and
gol.gg name variants. Same pattern for teams (org renames are common).
**Why:** Entity resolution is the classic silent killer in esports data;
solving it at ingest beats patching it in features.
**Revisit if:** research finds a better canonical source.

### Q22. Patch/meta representation? [OK]
**A:** Patch dimension table (patch id, date, season, era flags, major-change
notes), champion-patch stats table (meta strength priors per patch from
aggregate data), decay-weighted rolling champion form. "Game meta" features =
patch-level aggregates (avg game time, dragon soul rates, gold@15 spreads)
computed from pro games on that patch.
**Why:** Makes meta a first-class queryable dimension, which your goals
("understand game meta through statistics") require.
**Revisit if:** never structurally; feature list will grow.
**Update 2026-08-21 (research):** Patch identity is messier than assumed:
Riot's 2025 marketing renaming means marketing patch "26.16" maps to client
version "16.16.1" (offset -10, with a 25.S1.1-style interlude). The patches
dimension gets BOTH identifiers plus a tested translation utility -- never
assume the mapping inline. Champion state source: Data Dragon (alive,
v16.16.1) for base data; Community Dragon for per-rank ability scaling that
ddragon lacks. No maintained buff/nerf-per-patch API exists (community project
dead since 2018) -> we DIY-diff versioned ddragon/cdragon snapshots to
generate "champ X changed on patch Y" flags.
Source: docs/research/06-static-and-soloq-data.md

---

## Process

### Q23. Codex-first dispatch doctrine vs this machine? [OK]
**A:** Codex CLI is not installed here, so research/build dispatches route to
Claude subagents for now (sonnet for research, flagship inline for
architecture). Not blocking; revisit if you install codex.

### Q25. Scraping/ToS boundaries? [OK, added post-research]
**A:** Hard rules adopted: op.gg is OFF LIMITS (ToS explicitly bans scraping
despite permissive robots.txt). lolalytics/u.gg are grey -- use only if no
clean alternative, low rate, revisit before anything commercial. Preferred
clean sources: Riot APIs (keyed), Data Dragon/Community Dragon (intended for
this), Oracle's Elixir bulk files (published for reuse), Leaguepedia Cargo API
(public API with rate courtesy), gol.gg (tolerated, low-rate scrape),
lolpros.gg for account mapping. Every connector carries a source-policy note.
**Why:** Legal hygiene now is cheaper than retrofitting; also matters if this
ever touches real money.
**Revisit if:** you want a stricter (API-only) or looser posture.
**Source:** docs/research/06-static-and-soloq-data.md

### Q27. Are we allowed to record venue market data? [?] -- NEEDS YOUR REVIEW
**A (conservative default I chose):** Per-venue capture toggles; **Polymarket
capture ON, Kalshi capture OFF by default** until you review terms. Basis:
the research agent read Kalshi's "Data Terms of Use" PDF in full -- it
explicitly prohibits using Kalshi Data to train ML/AI systems or archive
datasets without written consent. That hits our recorder directly. The
separate API Developer Agreement (which may carve out different terms) and
Polymarket's automated-access ToS clauses were both unreachable to automated
fetches (Cloudflare / client-rendered) -- flagged for HUMAN review.
Facts otherwise favorable: both venues' market-data REST is public/no-auth
(verified live); Kalshi has real LoL series (KXLOL futures, KXLOLGAME match,
KXLOLMAP per-map) with working orderbooks; Polymarket structures each match
as one event with many binary markets (match/map/totals/handicaps/props).
Options for you: (a) keep Kalshi off; (b) request Kalshi written consent;
(c) read the API Developer Agreement yourself and decide; (d) use
sportsbook-odds aggregators (the-odds-api/Pinnacle) as the benchmark source
instead.
**Why this default:** Reversible, and the odds data's purpose (CLV
benchmarking) is exactly the use their data terms restrict -- not worth
YOLOing.
**Source:** docs/research/07-odds-capture-apis.md

### Q24. What gets built before research lands? [OK]
**A:** Docs (this file, architecture draft, roadmap), schema sketch, and repo
scaffold only. Ingestor code waits for source verification (building against a
dead API is waste). First code lands at M1 with whichever sources survive
research.
