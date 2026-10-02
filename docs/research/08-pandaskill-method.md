# PandaSkill — Implementation-Grade Method Extraction

Primary source: **arXiv 2501.10049** — "PandaSkill - Player Performance and Skill
Rating in Esports: Application to League of Legends," Maxime De Bois, Flora
Parmentier, Raphaël Puget, Matthew Tanti, Jordan Peltier (all PandaScore). v1
submitted 2025-01-17, v2 2025-01-20 (differences between v1/v2 not diffed — see
Open Questions). Also indexed on IEEE Xplore (document 11044861); venue/issue not
independently confirmed (page did not render for fetching).

Companion code: **github.com/PandaScore/PandaSkill**, MIT license (confirmed by
reading `LICENSE` directly, Copyright (c) 2024 PandaScore), cloned and read in full
for this report. Live demo: pandaskill.streamlit.app.

**Verification legend** used throughout: **[code]** = read directly from the
PandaSkill repo source in this session (highest confidence — this is what actually
produced the paper's numbers). **[paper]** = extracted from the arXiv HTML via
automated fetch-and-summarize, cross-checked against code where possible.
**[paper-only]** = paper-narrative claim not independently checked against code, or
checked and found to **disagree** with code (flagged explicitly). **[unconfirmed]**
= could not be verified from a primary source in the time available.

---

## 1. Method summary (tl;dr)

PandaSkill is a two-stage pipeline: (1) a **per-role XGBoost model** turns raw
box-score stats into a 0–100 "performance score" (PScore) that predicts *who played
well*, decoupled from *who won*; (2) an **OpenSkill (Plackett-Luce) Bayesian rating**
consumes PScore in a **free-for-all (FFA)** setting — all 10 players in a game are
ranked against each other by PScore, not by 2-team win/loss — so a great performance
on the losing side still raises a player's rating. To make ratings comparable
across isolated regional leagues (LCK vs. LPL vs. LEC vs. LCS, etc.), each player's
rating is split into a **contextual (in-region) component** and a **meta (region
strength) component**: `μ = μ_ctx + μ_meta`. Domestic games update only `μ_ctx`;
international games (Worlds/MSI) update only `μ_meta`, and they do so through an
**offset trick** that prevents a player's international form from inflating their
own domestic standing (no feedback loop). Trained/evaluated on 5 years (2019-09 to
2024-09), 37,388 games, 4,927 players, 8 regions via Leaguepedia. Headline numbers:
performance model hits ~90.7% end-of-game win-prediction accuracy; the full
rating system (PScore + Meta-FFA-OpenSkill) reaches **~70% accuracy on inter-region
(cross-region) games** via a rolling-window logistic-regression forecast, versus
~52% for a naive EWMA baseline and ~67% for vanilla team-outcome OpenSkill — i.e.
the meta-rating layer is what buys most of the inter-region lift, not the FFA
mechanic or the choice of performance model (see §4 for the full, more nuanced
table — the "beats everything" framing in the abstract undersells how close some
baselines actually come). No inactivity/time decay exists anywhere in the system.

---

## 2. Implementation-grade detail per layer

### 2.1 Performance-score layer

**Target & framing [code: `pscore_model.py`, `training_testing_cv.py`; paper Section
IV-A].** For each of the 5 roles independently, an `XGBClassifier` is trained to
predict `y = win` (binary, team-level outcome broadcast to each of that team's
players) from that player's end-of-game box-score features `X`. The **performance
score is not the raw predicted win probability** — it's that probability's
**percentile rank against the training-set distribution of predicted probabilities
for that same role/fold** (see Percentile mapping below). This is the decoupling
mechanism: two players with identical stat lines get the same PScore regardless of
whether their team won, and the percentile transform removes the model's absolute
calibration to win/loss so that "PScore = 90" means "played better than 90% of
performances at this role in this training distribution," not "90% predicted win
probability."

**Exact feature list (15 features, one shared list across all 5 roles) [code:
`run_performance_score_experiment.py` config + `basic_features.py` /
`event_features.py`]:**

| # | Feature | Formula | Monotonicity |
|---|---|---|---|
| 1 | `gold_per_minute` | `gold_earned / (game_length_seconds/60)` | +1 |
| 2 | `cs_per_minute` | `total_minions_killed / game_length_min` | +1 |
| 3 | `xp_per_minute` | `XP_PER_LEVEL_TABLE[level] / game_length_min` (level→XP lookup table, **level used as an XP proxy**, hardcoded per-level XP values 0–18) | +1 |
| 4 | `damage_dealt_per_total_kills` | `total_damage_dealt_to_champions / total_kills` | +1 |
| 5 | `damage_dealt_per_total_kills_per_gold` | same, further `/ gold_earned` | +1 |
| 6 | `damage_taken_per_total_kills` | `total_damage_taken / total_kills` | +1 |
| 7 | `damage_taken_per_total_kills_per_gold` | same, further `/ gold_earned` | +1 |
| 8 | `kla` (kill-life-assist) | `(kills + assists) / (deaths + 1)` | +1 |
| 9 | `largest_multi_kill` | raw stat (0 cleaned to 1 if kills>0) | +1 |
| 10 | `largest_killing_spree_per_total_kills` | `largest_killing_spree / total_kills` | +1 |
| 11 | `wards_placed_per_minute` | `wards_placed / game_length_min` | +1 |
| 12 | `objective_contest_loserate` | see below | **-1** |
| 13 | `objective_contest_winrate` | see below | +1 |
| 14 | `free_kill_ratio` | see below | +1 |
| 15 | `worthless_death_ratio` | see below | **-1** |

`total_kills` = **sum of both teams'** `team_kills` for that game (a game-pace
normalizer, not per-team kills) [code: `preprocess_data.py` line 19]. This, plus
`game_length`, are the "two most common normalizations" the paper text references
[paper, Section V-A2] — **it is per-minute-of-game-length or per-total-game-kills
ratio normalization, not z-scoring and not per-patch normalization.** There is no
patch-level normalization anywhere in the pipeline.

**Event-derived features (require timestamped kill/objective logs, not just
box scores) [code: `event_features.py`]:**
- `objective_contest_winrate` / `objective_contest_loserate`: over neutral epic
  monsters only (drake, Rift Herald, Baron — **void grubs explicitly excluded**,
  code comment: "very recent, and not really contested individually"), a "contested"
  objective event is one where killer+assist participant team-IDs are not unanimous
  (i.e., both teams' players were present in the kill/assist credit window). Win-
  rate/lose-rate = contested objectives your team won or lost, divided by the
  game's total contestable-objective count.
- `worthless_death_ratio` / `free_kill_ratio`: a **±30-second window** (hardcoded,
  `window=30`) around each death event. A death is "worthless" if, within that
  window, the dying player did not get a kill/assist and their team did not take
  an objective. A kill is a "free kill" if the reciprocal condition holds for the
  killer/assist side. Ratios are normalized by `deaths` and `(kills+assists)`
  respectively, with a total-kills-normalized variant also computed but **not**
  used in the default feature list.

**Feature scaling — paper/code discrepancy [paper-only vs. code]:** The
paper's evaluation-section narrative states features were "standardized to zero
mean and unit variance" [paper, Section V-B1, automated extraction]. **The actual
code uses `sklearn.preprocessing.MinMaxScaler`** in `BaseModel.__init__`/`fit`
[code: `base_model.py`, `pscore_model.py`], not `StandardScaler`. This is
inconsequential for XGBoost itself (tree splits are invariant to any monotonic
per-feature rescaling), but it **does** matter for the SVC-based PlayeRank baseline
in the same codebase (scale-sensitive) and for reproducing SHAP-value magnitudes.
**Trust the code (MinMax) if replicating exactly**, not the paper prose.

**Model config [code: `run_performance_score_experiment.py`]:**
```python
XGBClassifier(
    n_estimators=2000,
    learning_rate=0.01,
    monotone_constraints={"feature_0": 1, ..., "feature_11": -1, "feature_12": 1,
                           "feature_13": 1, "feature_14": -1},  # per table above
)
```
xgboost==2.1.2 [code: `requirements.txt`]. No `max_depth`, subsampling, or
regularization params are set — **library defaults apply** for everything else
[code — absence confirmed, not stated as a deliberate choice in the paper].
Monotonicity costs ~1 point of raw accuracy (91.79% unconstrained vs. 90.74%
constrained per role, paper §V-B2/ablations) — a deliberate interpretability
trade-off ("more gold per minute never lowers your score").

**Cross-validation [code: `training_testing_cv.py`]:** Plain `KFold(n_splits=5,
shuffle=True, random_state=42)` **on unique `game_id`**, not time-ordered and not
grouped by player — this is a **shuffled** split, explicitly *not* the temporal
rolling-window split used later for rating evaluation (§4). One model is trained
per role per fold (`one_model_per_role: True`); test-fold performance scores from
all 5 folds are concatenated to cover the full dataset out-of-fold.

**Percentile mapping [code: `percentile_mapper.py`]:** `PercentileMapper.train()`
stores the training fold's predicted win-probabilities as a reference distribution;
`.map()` calls `scipy.stats.percentileofscore(reference_probabilities,
probability)` per test-set prediction. This is fit **per role, per CV fold**, then
applied out-of-fold — i.e., a game's PScore is always relative to a same-role
distribution the model never saw that exact game in.

**Baseline performance models in the same codebase** (for the ablation table in
§4): `PerformanceIndexModel` (Random Forest, `n_estimators=500`, feature-wise
percentile histograms + permutation-importance weights, from Demediuk et al.,
originally Dota 2) and `PlayerankModel` (SVC with `probability=True`, `C=0.1`,
`kernel="linear"`, `max_iter=50000`, weighted-feature dot-product + min-max
rescale ×100, from Pappalardo et al., originally football/soccer) [code:
`perf_index_model.py`, `playerank_model.py`].

### 2.2 Rating layer (OpenSkill)

**Library [code: `bayesian.py` imports, `requirements.txt`]:** `from
openskill.models import PlackettLuce, PlackettLuceRating`, package `openskill==6.0.1`.
**Plackett-Luce is the confirmed variant** (not Thurstone-Mosteller) — the paper
text alone [paper Section IV-B1] only says "the OpenSkill framework" without
naming the variant; the import statement is the authoritative source. Also wraps
`trueskill==0.4.5` behind an adapter class (`TrueSkill`/`TrueSkillRating` in
`skill_rating/trueskill.py`) so the same FFA pipeline can swap in classic TrueSkill
as an ablation (converts scores→ranks via `np.argsort(-scores)` since the
`trueskill` package only accepts ranks, not scores).

**FFA construction from a 5v5 game [code: `bayesian.py::_compute_ratings_after_game`]:**
```python
if use_ffa_setting:
    ffa_ratings_after_game = model.rate(
        teams=[[skill_rating] for skill_rating in ratings_before_game_copy],  # 10 "teams" of 1
        scores=game_performance_scores,   # the 10 PScore values, NOT ranks
    )
```
All 10 players are passed as ten singleton teams; **`scores` receives the raw
PScore percentiles directly** (0–100 floats), not a derived rank. In the
`openskill` library, higher `scores` = better, and — critically for research
question 2 — **the library's `rate()` uses score *magnitude*, not just order, to
scale the update** [openskill.me manual, confirmed via fetch: "scores: higher
values = better performance; magnitude differences matter for match dynamics"].
This means PandaSkill's update is a genuine **margin-weighted FFA update**: a
player who scored PScore=95 while the next-best scored PScore=60 gets a bigger
rating jump than if the runner-up had scored PScore=93. This directly answers
"dynamic-mu vs. weighted update" — **it's a weighted update, with the weight
supplied implicitly by feeding continuous scores instead of integer ranks.**

**Non-FFA baseline [code: same function, else-branch]:** standard 2-team
update, `teams=[winners[0:5], losers[5:10]], scores=[1,0]`. This slicing
assumes the input rows are already sorted winner-block-then-loser-block, which is
guaranteed upstream by a **global sort** in `load_data()`:
`data.sort_values(by=["date","win"], ascending=[True, False])` [code:
`experiments/general/utils.py`] — win=True rows sort before win=False rows within
each date/game. Worth replicating exactly if reusing this code path.

**Effect of good performance despite a loss [code confirms paper]:** because FFA
ranks by PScore alone, `_compute_ratings_after_game` can and does raise a losing
player's `μ` — paper Table I is cited [paper, automated extraction] as showing
multiple Hanwha Life Esports players gaining rating in a loss "due to strong
performances."

**Team aggregation for outcome forecasting — precise, code-verified (this
corrects a vaguer paper-only answer) [code: `skill_rating/evaluation.py`]:** There
is **no explicit team-aggregation formula** (no sum/mean of ratings). Instead:
1. Each player's **pre-game lower-bound scalar** `skill_rating_before = μ - 3σ`
   (the combined contextual+meta lower bound, see §2.3) is used directly as a raw
   feature — **not μ alone, and not (μ,σ) as a pair.**
2. Per game, the 10 players' `skill_rating_before` values are arranged into a
   fixed 10-column vector ordered `[Top,Jungle,Mid,Bot,Support]` for the winning
   team then the same 5 roles for the losing team (`role_order` + the same
   win-descending sort as above).
3. **Data augmentation for order-invariance:** every row is duplicated with the
   two 5-blocks swapped and the label flipped, so the classifier can't learn a
   positional "block A always wins" shortcut.
4. `StandardScaler` + `LogisticRegression(C=1.0)` learns the team-aggregation
   *implicitly* as 10 learned coefficients — this LR **is** the team-aggregation
   function, re-fit every rolling window (see §4).

**Uncertainty (σ) [code: `bayesian.py`, paper Eq. 1–2]:**
`S_i ~ N(μ_i, σ_i²)` [paper Eq. 1]; update `(μ^{t+1},σ^{t+1}) = Ω(μ^t,σ^t,
outcome)` [paper Eq. 2] generically, specialized to `Ω_FFA(μ^t,σ^t,PScore)` for
the FFA case [paper Eq. 3, matches code above]. σ shrinkage itself is entirely
delegated to the `openskill` library's internal Plackett-Luce math (library
defaults: `beta`, `kappa`, `tau` are **not overridden** anywhere in PandaSkill's
code — `PlackettLuce()` is instantiated with zero arguments [code confirmed] —
exact numeric defaults for beta/kappa/tau in openskill 6.0.1 were **not**
independently confirmed in this session **[unconfirmed]**; only `mu=25`,
`sigma=25/3` defaults were confirmed from the library's own docs).

**Cold-start init [code: `bayesian.py` constants]:** `DEFAULT_MU = 25.0`,
`DEFAULT_SIGMA = 25/3` (≈8.33), for **both** new players' contextual rating and
new regions' meta rating [paper confirms: "μ_i=25 and σ_i=25/3, as it is generally
done in Bayesian rating systems," Section IV-B1].

**"Decay" — there is no inactivity/time decay [code + paper, both confirm
absence].** The only rating **reset** event is a **region change** (player
transfers regions): `_reset_rating_sigma_when_region_change` resets that player's
**contextual σ back to `DEFAULT_SIGMA`** (not μ) whenever `region_change=True` for
that game-row, and only when `use_meta_ratings=True`. This is explicitly a
transfer-triggered uncertainty bump, **not** a calendar-time decay function —
don't confuse the two when writing the spec. Region-change is computed upstream as
a simple "did this player's team's mapped region differ from their immediately
previous game's region" flag [code: `player_region.py::attribute_player_region_change`].

### 2.3 Contextual / region (meta-rating) layer

**Decomposition [code `combine_contextual_and_meta_ratings`, paper Eq. 4–5]:**
```
μ_i = μ_i^ctx + μ_i^meta                      (Eq. 4)
σ_i² = (σ_i^ctx)² + (σ_i^meta)²               (Eq. 5)
```
Every player carries **two independent Gaussians**: a contextual (in-region form)
rating and their current region's meta rating (shared identically by every player
in that region — meta rating lives on the **region**, not the player).

**Which component updates, gated by whether the game is cross-region [code:
`_compute_rating_updates_for_game`]:** `meta_game = (len(set(player_regions)) > 1)
and use_meta_ratings`.
- **Intra-region game** → only `μ_ctx/σ_ctx` update via the plain FFA process on
  the 10 players' raw contextual ratings; `μ_meta` untouched [paper Eq. 6].
- **Inter-region game** (e.g. Worlds, MSI) → contextual ratings are **frozen**;
  only the meta layer updates, via an **offset trick** [paper Eq. 7]:
  ```
  rating_before_game[i] = PlackettLuceRating(
      mu    = μ_i^meta + θ_i^ctx,     # θ = lower_bound(μ_ctx, σ_ctx) = μ_ctx − 3σ_ctx
      sigma = σ_i^meta
  )
  ```
  i.e. each player enters the international-game FFA update as "their region's
  current meta strength, nudged by a fixed offset representing how good they are
  *relative to their own region's peers*." After the FFA update:
  ```
  μ_i^meta,new = full_rating_after.mu − θ_i^ctx        # subtract the offset back out
  σ_i^meta,new = full_rating_after.sigma
  ```
  then **all players sharing a region average their post-update meta values**
  [paper Eq. 8–9, code: `_compute_ratings_after_meta_game`]: `μ_region^meta =
  mean(μ_i^meta,new)`, `σ_region^meta = sqrt(mean(σ_i^meta,new²))` (arithmetic mean
  of μ, **quadratic mean (RMS) of σ**, not arithmetic mean). The region's single
  resulting `(μ,σ)` is written back for every player of that region.

**Why this avoids the feedback loop (the exact mechanism you asked about):** the
contextual rating `θ^ctx` used as the offset is **treated as a constant during the
meta update and is never itself modified by international results** ("contextual
rating doesn't change in meta game" — code comment, `bayesian.py` line ~304).
A player's within-region pecking order is therefore causally downstream of
domestic games only; international performance can only move the shared regional
`μ_meta`, and it moves it by the same averaging step for every player from that
region who played that game, not by that individual's own contextual standing
compounding forward. This is what prevents "player has a great Worlds → their
domestic rating inflates → makes their region look artificially stronger next
time they play internationally" style loops.

**Global comparable rating / pairwise comparison [paper Eq. 10]:**
```
P(S_i > S_j) = Φ( (μ_i − μ_j) / sqrt(σ_i² + σ_j²) )
```
used directly for the expert-survey "who is better" evaluation (§4) — literally a
z-score through the standard normal CDF on the combined (contextual+meta) `μ,σ`.
The single-scalar "lower bound" `θ = μ − 3σ` (a conservative ~99.7th-percentile-
floor point estimate) is what's used for leaderboards/rankings [code:
`lower_bound_rating`, used throughout `ranking.py`].

**Regions modeled [code: `player_region.py::MAIN_REGIONS`]:** exactly 8 — Korea,
China, Europe, North America, Asia-Pacific, Vietnam, Brazil, Latin America — plus
a catch-all **"Other"** bucket for teams/players outside the whitelisted
region/series/tournament combinations (exhibition matches, regions not covered,
academy/qualifier rosters explicitly excluded by hand — see the manual corrections
for KeSPA Cup, Demacia Cup, All-Star 2020, and 2023 season-kickoff showmatches in
`player_region.py`). **Worlds and MSI are not separate regions** — they're the
international tournaments where players from the 8 regions face each other and
thus trigger `meta_game=True`; Table II's separate Worlds/MSI game/player counts
[paper] describe those events' game volume, not an additional rating pool.
Region attribution is **time-sliced per team roster per series** (a team's region
can change split-to-split via transfers/relegation), not a static team→region map.

---

## 3. What we adapt vs. adopt for rift-quant

Round-1 (`01-historical-data-sources.md`) already settled on **Leaguepedia Cargo**
as our backbone. Mapping PandaSkill's `game_players_stats.csv` /
`game_events.csv` schema onto Leaguepedia's confirmed `ScoreboardGames` /
`ScoreboardPlayers` / `PicksAndBansS7` fields:

| PandaSkill needs | Leaguepedia equivalent | Verdict |
|---|---|---|
| `player_kills/deaths/assists`, `gold_earned`, `total_minions_killed`, `champion_name`, `role` | `Kills/Deaths/Assists`, `Gold`, `CS`, `Champion`, `Role`/`IngameRole` | **Direct 1:1** — adopt as-is |
| `total_damage_dealt_to_champions` | `DamageToChampions` | **Direct 1:1** |
| `game_length` | `Gamelength` (standard Leaguepedia field per general schema knowledge; not in round-1's directly-quoted excerpt — **re-verify field name**) | Adopt, verify name |
| `wards_placed` | Only `VisionScore` (Riot's composite metric) confirmed in round-1 notes; no raw wards-placed count listed | **Gap** — verify if `WardsPlaced` exists as a Cargo field before assuming; may need to substitute VisionScore or drop the feature |
| `level` (→ our xp_per_minute proxy) | Not listed among confirmed `ScoreboardPlayers` fields | **Gap** — verify; if absent, xp_per_minute either drops or needs a different proxy |
| `total_damage_taken` | Not listed (only `DamageToChampions` confirmed, which is damage *dealt*, not taken) | **Gap** — likely needs gol.gg or Riot match-v5, not Leaguepedia |
| `largest_multi_kill`, `largest_killing_spree` | Not listed; `Pentakills` is the closest confirmed field | **Gap** — Leaguepedia's boxscore looks coarser than Riot's raw participant-stats here |
| **All 4 event-derived features** (`worthless_death_ratio`, `free_kill_ratio`, `objective_contest_winrate/loserate`) — need timestamped kill/objective events with killer/assist/victim IDs | Leaguepedia's `PostgameJsonMetadata.TimelinePage` *pointer exists but its population was explicitly unverified in round-1* | **Critical gap.** These are 4 of 15 features (27%) and require play-by-play, not box scores. Round-1's **unofficial lolesports live-stats feed** (`02-live-official-feeds.md`) is the actual right source for this — it's frame-level and already flagged for the in-game model — but its historical backfill is walled (LCK 2023-08+, LEC 2024+, LPL 2025+), so **event-derived features are only reproducible for recent seasons**, not the full 2019–2024 window PandaSkill used |
| `Team1Bans/Team1Picks` (not used by PandaSkill's performance model, but needed for our own draft layer) | `PicksAndBansS7` per-slot fields | Better than what PandaSkill uses — bonus for us |
| Region attribution (time-sliced roster→region) | `TournamentRosters` + `Tournaments.Region`/`League` | Adopt the *pattern* (time-sliced, not static team→region), rebuild against Leaguepedia's own tables rather than porting PandaSkill's hand-maintained whitelist (which is itself a maintenance smell we should avoid replicating verbatim — see Open Questions) |

**Adopt as-is:**
- The **percentile-of-training-distribution** performance-score transform — cheap,
  role-fair by construction, decouples performance from win/loss exactly as
  specified. Directly portable regardless of which 15 (or fewer) features we can
  actually source.
- **Plackett-Luce FFA with scores (not ranks)** as the rating update — `openskill`
  is a pip-installable, actively maintained library (v6.x on PyPI); no reason not
  to use it directly rather than reimplementing.
- The **μ_ctx + μ_meta split with the offset trick** for region comparability —
  this is the single most valuable, directly-reusable idea for rift-quant, since
  our whole cross-region (LCK/LPL/LEC/LCS) comparability problem is exactly the
  problem this was built for. Adopt the offset-and-average mechanism verbatim; it
  is simple (< 100 lines, we read the whole thing) and has no obvious
  simplification available.
- Monotonic constraints on the performance model — free interpretability
  insurance, ~1pt accuracy cost, worth it for a model whose output humans (traders)
  will sanity-check.

**Adapt / diverge:**
- **Feature set will be smaller** than PandaSkill's 15 until we confirm Leaguepedia
  coverage of wards/level/damage-taken/multi-kill fields (see gaps above), and
  event-derived features will only be trainable on the sub-window where the
  livestats recorder has been running. Plan for a **v0 feature set of ~9-10 pure
  box-score ratios** (everything in the table marked "direct 1:1") with the 4
  event-derived features added once the frame recorder has enough backfill —
  this is consistent with round-1's own v0/v1 staging in `03-modeling-literature.md`.
- **Region whitelist maintenance**: PandaSkill's `MAIN_LEAGUE_SERIES_TOURNAMENT_
  WHITELIST` is a large hand-curated dict of series-name→region mappings with
  manual patches for KeSPA Cup / Demacia Cup / All-Star / showmatches — i.e., even
  PandaScore couldn't fully automate this from raw data. We should expect the same
  tax and budget for it rather than assuming Leaguepedia's `Tournaments.Region`
  field alone resolves it cleanly (their whitelist existing at all is evidence it
  doesn't, for at least some source).
- **We may want μ_meta to update on more than just Worlds/MSI.** PandaSkill only
  triggers `meta_game` on any cross-region game, which in their data is
  overwhelmingly Worlds/MSI/occasional showmatches. Rift-quant may see more
  cross-region signal opportunities (e.g. any online cross-region friendlies) —
  worth checking Leaguepedia's tournament list for other inter-region fixtures
  PandaSkill's 2019-2024 window may not have emphasized.
- **No decay is a deliberate gap we should decide on, not silently inherit.**
  PandaSkill has zero inactivity handling; a player benched for a full split keeps
  their exact σ. For a live trading system (vs. a research leaderboard), stale
  ratings on returning players are a real mispricing risk — round-1 flagged
  "no public prior art" for related problems; this is one more place to make an
  explicit, documented choice (e.g. σ inflation on long gaps) rather than defaulting
  to PandaSkill's silence on it.
- **Team aggregation**: PandaSkill's implicit-LR-coefficients approach requires
  refitting a fresh logistic regression every rolling month and only consumes the
  `μ−3σ` scalar. For rift-quant's pregame model (already planned as LR→LightGBM in
  round-1), feeding the fuller `(μ_ctx, σ_ctx, μ_meta, σ_meta)` per player (20
  features for 2 teams×5 roles) into a GBM instead of collapsing to one scalar
  per player is a reasonable, low-risk enhancement — flag as a "choice we made."

---

## 4. Evaluation protocol to replicate

**Dataset [paper Table II, automated extraction — table values not independently
re-rendered from the PDF, treat as high-but-not-100%-confidence]:** 2019-09-15 to
2024-09-15, Leaguepedia-sourced. 37,388 games / 4,927 players total across Worlds
(592 games/353 players), MSI (312/166), LCK (2,438/198), LPL (3,643/283), LEC
(1,315/149), LCS (1,371/182), PCS (1,295/235), VCS (1,489/158), CBLOL (1,153/196),
LLA (890/175).

**Two separate evaluation protocols — don't conflate them:**

1. **Performance-model evaluation**: shuffled 5-fold CV on `game_id` (§2.1),
   metrics = accuracy, F1, AUC, ECE (25 bins) per role, plus SHAP-based feature
   importance and a Wasserstein-distance role-fairness check.
2. **Rating-system evaluation** [code: `skill_rating/evaluation.py`]: a **rolling
   monthly forecast**, warmup 2019-09-15→2020-09-15, then for each month from
   (warmup_end + 1yr) to the dataset's end: train `LogisticRegression(C=1.0)` on
   the trailing 1 year of games' pre-game `skill_rating_before` vectors (with the
   order-invariance mirroring trick from §2.2), test on the next month, slide
   forward. Concatenate all monthly test predictions for the final metrics. This
   is a genuine walk-forward backtest — replicate this shape, not a random
   train/test split, for any pregame-model claim we want to defend.

**Baselines to replicate side-by-side (both axes are ablation-able
independently — rating baselines × performance-model baselines):**
- Rating: `EWMA` (α=0.05, no Bayesian rating at all) < `OpenSkill` (plain
  team-outcome, non-FFA, no meta) < `FFA_OpenSkill` < `Meta_OpenSkill` <
  `Meta_FFA_OpenSkill` (full method) < `Meta_FFA_TrueSkill` (swap library).
- Performance model: `PScore` (theirs, XGBoost) vs. `PI` (Performance Index,
  Random Forest, Demediuk et al./Dota2 origin) vs. `PlayeRank` (SVC, Pappalardo et
  al./soccer origin).

**Reported results [paper §V-B2, V-C2, V-D2, V-C3, automated extraction —
flagged as the least-independently-verified numeric block in this report; cross-
checked for internal consistency but not re-derived]:**

| Rating config (all use PScore) | Acc. all | Acc. intra-region | Acc. inter-region | ECE all |
|---|---|---|---|---|
| EWMA | 63.06% | 63.33% | 52.34% | 1.43% |
| OpenSkill (plain) | 65.56% | 65.51% | 67.39% | 1.53% |
| Meta_OpenSkill | 65.12% | 65.01% | 69.23% | 0.89% |
| FFA_OpenSkill | 64.79% | 64.86% | 61.71% | 0.77% |
| **Meta_FFA_OpenSkill (full method)** | 64.98% | 64.86% | **70.07%** | 1.01% |
| Meta_FFA_TrueSkill | 65.15% | 65.05% | 68.90% | 2.85% |
| PI + Meta_FFA_OpenSkill | 65.05% | 64.92% | 70.23% | 1.00% |
| PlayeRank + Meta_FFA_OpenSkill | 64.94% | 64.84% | 69.23% | 1.01% |

**Read this table carefully before citing "67-70%" as a clean win** (round-1's
synthesis already cites this range and it holds up, but the mechanism is more
mixed than "PandaSkill beats baselines"):
- **Meta-rating, not FFA, is what fixes inter-region accuracy.** Plain OpenSkill
  (no FFA, no meta) already gets 67.39% inter — FFA *alone* (no meta) actually
  **drops** inter-region accuracy to 61.71%, i.e. FFA by itself hurts cross-region
  prediction; it only pays off once meta-rating is also active.
- **The full method (Meta_FFA_OpenSkill) is not the single best row on any one
  column** — PI+Meta_FFA_OpenSkill edges it on inter accuracy (70.23 vs 70.07) and
  Meta_OpenSkill (no FFA) edges it on ECE (0.89% vs 1.01%). PandaSkill's own
  ablation section is explicit that FFA's payoff is in **expert concordance and
  role-fairness, not raw accuracy** — "FFA setting shows a small decrease in
  accuracy compared to non-FFA OpenSkill" is stated directly by the authors.
- **The performance-model choice (PScore vs. PI vs. PlayeRank) barely moves
  rating accuracy** once Meta_FFA_OpenSkill is the rating scaffold (64.94–65.05%
  all, 69.23–70.23% inter across all three) — PScore's real edge over PI/PlayeRank
  is **calibration and per-role fairness**, shown separately: PScore standalone
  ECE 0.93% (SD 0.03) vs. PlayeRank 1.28% (SD 0.13) vs. PI 2.28% (SD 0.09); role-
  fairness Wasserstein distance PScore 0.09–0.44 (best/lowest) vs. PI 0.35–0.66 vs.
  PlayeRank 2.44 (SD 1.32, worst).
- TrueSkill swap is accuracy-competitive (65.15/65.05/68.90) but **much worse
  calibrated** (ECE 2.85% vs. 1.01%) — a clean, reproducible argument for
  Plackett-Luce/OpenSkill over classic TrueSkill specifically on calibration.

**Expert-survey evaluation [paper §V-D, code: `ranking.py::evaluate_ranking`]:**
5 surveys (Global, Korea, China, Europe, North America), 300 random player pairs
each, PandaScore odds-trader experts vote "who's better." Metrics: **majority
concordance** (model agrees with expert majority), **unanimity concordance**
(model agrees when experts unanimously agree — this is the cleanest signal),
**partial concordance**, per-expert concordance. Global survey: 5 experts / 477
players. PScore+Meta_FFA_OpenSkill: 80.63% majority concordance (2nd place, PI's
variant leads at 80.70%), **88.98% unanimity concordance (best overall)**. Directly
reusable evaluation design for rift-quant if/when we have access to domain-expert
judges (LCK/LPL analysts, or our own trading desk) for a sanity-check layer beyond
pure backtested accuracy.

**To replicate for rift-quant:** (1) same two-track eval (shuffled CV for the
performance model; walk-forward monthly for the rating/outcome model) — do not use
a single random split for the rating evaluation, it will overstate performance by
leaking future meta-rating information backward; (2) always report intra- vs.
inter-region accuracy **separately**, not just pooled, since pooled numbers hide
exactly the effect we care about (LCK vs. LPL comparability); (3) budget for an
expert-concordance sanity check even if crude (2-3 people ranking 50-100 pairs) —
it caught a result (PI edges PScore on majority concordance) that pure accuracy
metrics would have missed entirely.

---

## 5. Open questions

1. **v1 vs. v2 arXiv diff not checked** — submitted 3 days apart, likely a minor
   correction, but not confirmed **[unconfirmed]**.
2. **IEEE Xplore venue name/issue** (document 11044861) — page would not render
   for fetching; confirm venue before citing "peer-reviewed in IEEE Transactions/
   Conference X" in our own spec **[unconfirmed]**.
3. **openskill 6.0.1's exact `beta`/`kappa`/`tau` defaults** were not confirmed
   (only `mu=25`, `sigma=25/3` were, from the library's own docs). If we pin
   `openskill` for rift-quant, read `openskill/models/weng_lin/plackett_luce.py`
   directly rather than assuming textbook Weng-Lin defaults **[unconfirmed]**.
4. **Leaguepedia field gaps** (§3 table): `WardsPlaced` (raw count), `level`,
   `total_damage_taken`, `largest_multi_kill`/`largest_killing_spree` — need a
   live `cargofields` query against `ScoreboardPlayers` (round-1's method) before
   finalizing which of PandaSkill's 15 features port directly vs. need a
   substitute or Riot match-v5/gol.gg fallback.
5. **`PostgameJsonMetadata.TimelinePage` population rate** — round-1 flagged this
   unverified; it's now load-bearing for 4/15 performance features. Needs a
   direct sample-and-check pass (pull N `TimelinePage` values, see if they
   resolve to structured data) before committing to event-derived features on
   the full 2019+ historical window vs. only the livestats-recorder window.
6. **No citing/successor papers found.** Web search (2026-08-21) turned up no
   2025-2026 paper that directly critiques or extends PandaSkill's method
   specifically (searches for "PandaSkill limitations/critique," "esports rating
   improvement 2026," and a Semantic Scholar citation-graph lookup were attempted;
   the citation API rate-limited before returning results and the Semantic
   Scholar page itself didn't render content via fetch). Treat "no known
   successor" as **absence of evidence**, not evidence of absence — worth one
   more pass with a working Semantic Scholar/OpenAlex API key if this matters for
   the spec's literature-review completeness.
7. **Authors' own stated future work** (neural-net performance models, richer
   action-level features, porting to CS2/Dota2) is generic and not actionable for
   us directly, but confirms the authors see the XGBoost/hand-engineered-feature
   choice as a v1, not a ceiling — consistent with us treating PScore's feature
   set as a floor to extend, not a spec to match exactly.

---

## Appendix: Bonus — champion mastery / archetype draft paper (lighter depth)

**arXiv 2605.18338**, "Robust Player-Conditional Champion Ranking for League of
Legends: Style Similarity, Mastery Priors, and Archetype-Constrained Discovery,"
Min Heo, Pranav Kadiyam, Prasun Panthi, submitted 2026-05-18. **[paper, automated
extraction only — not cloned/code-verified like PandaSkill above; no public repo
found in this session]**.

- **Problem framing**: player-conditional champion *recommendation* (not draft
  win-prediction) under "sparse, noisy, non-stationary" data — i.e. explicitly a
  small-sample-friendly design, relevant to our pro-scene sample-size problem.
- **Mastery score** blends **direct** mastery (`0.55·log(1+points) + 0.15·level +
  0.20·log(1+games) + 0.10·recency`) with **indirect** familiarity (mean of
  top-K cosine-similarity to champions already mastered), combined
  `0.70·direct + 0.30·indirect`.
- **Population-strength proxy**: weighted sum of **median/MAD-normalized**
  (not mean/std) feature z-scores, rank-scaled to [0,1] — robust-statistics choice
  specifically for outlier/sparse-data resilience, directly applicable to any
  small-pro-sample champion-strength estimate we build.
- **Player-style similarity**: weighted cosine over ~10 features (damage/gold/CS
  per minute, deaths/min, kill participation, objective pressure, vision, CC),
  weights adapt to each player's deviation from population average
  (`q_j = σ_j(1+0.75|deviation|)`), blending a recent-game vector (55%) with a
  champion-pool vector (45%).
- **Archetype-constrained discovery**: k-means++ over a 12-feature space (adds
  durability/mitigation) producing labels like "frontline tank"/"scaling
  carry"/"utility support"; archetypes act as a **guardrail**, not a hard filter —
  a champion can still be recommended off mastery alone even with a weak
  archetype match.
- **Validation is specified but not executed** — the paper describes temporal
  train/test splits, next-champion-recovery (Hit@K, MRR), calibration analysis,
  6 baselines and 8 ablations, but reports **no actual metrics**; the only
  empirical content is a single-player case study (~100 games) as a "sanity
  check." **Treat this as a methods proposal, not an evaluated system** — a
  materially different confidence level than PandaSkill, which has full
  quantitative results and open code.
- **Stated limitations** (authors' own): the win-adjacent score isn't a
  calibrated probability; strongly patch-dependent, needs temporal weighting;
  role-label ambiguity; outcome confounding (teammates/enemies/draft
  order/side not modeled); doesn't address pro-play draft interactions
  (matchups, team comp) at all — authors explicitly note extending to a
  partial-draft-state utility function (`argmax_c E[utility|c,D,player]`) as
  future work, not something this paper does.
- **Relevance to rift-quant**: the median/MAD normalization and the direct+
  indirect mastery blend are directly reusable primitives for our mastery-prior
  shrinkage idea (already sketched in round-1's `03-modeling-literature.md` v1
  plan). The archetype-guardrail concept is a reasonable near-zero-sample
  fallback for new/rare pro picks. Because validation wasn't executed, don't cite
  this paper's own numbers anywhere — only borrow the mechanism and validate it
  ourselves.
