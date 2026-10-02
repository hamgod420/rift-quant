# Round-1 Research Synthesis (2026-08-21)

One page tying together reports 01-06 plus the inline verification spikes.
Read this first; details and citations live in the numbered reports.

## The plan survives contact with reality, with three flips

1. **Leaguepedia, not Oracle's Elixir, is the historical backbone** (01).
   OE is fragile in 2026 (single maintainer, security incident, LPL outage,
   unscriptable downloads, no runes/items). Leaguepedia has draft order,
   runes, patch, roles, and is scriptable -- verified live from this machine.
2. **GRID is out; the unofficial lolesports feed is in** (02). GRID's free
   tier excludes LoL entirely; Bayes is insolvent. The unofficial livestats
   feed is alive, keyless, and serves HISTORICAL frames -- measured walls:
   LCK 2023-08+, LEC 2024+, LPL 2025+. That is thousands of games of
   frame-level training data for the in-game model, for free.
3. **In-play trading is demoted; pregame/draft markets are the strategy**
   (04 + 02). Broadcasts run 5-10 min delayed, bookmakers get sub-200ms
   licensed feeds, and named bots already industrialize broadcast-lag arb on
   Polymarket esports. Our edge must be model quality on pregame/draft
   pricing. Kalshi (US-regulated) measurably out-volumes Polymarket on LoL
   and is likely the realistic venue for a US person -- user's compliance
   call, recorded in Q18.

## What the model will be (03)

- Pregame: LR/Elo baseline -> LightGBM ensemble; v1 rating layer follows
  PandaSkill (2025): per-role performance scores -> OpenSkill with explicit
  region-strength decomposition (solves LCK vs LPL vs LEC calibration;
  67-70% reported on inter-region games).
- In-game: GBM + LR on livestats frames; expected S-curve ~60% @10min ->
  ~70% @15-20 -> ~80% @25 -> 90%+ @30-35. Anything much better = leakage bug.
- Draft-only ceiling is 55-63%; team quality dominates the draft itself.
- "Deserved to win"/throw detection has NO public prior art -- whitespace.

## Structural facts that shape the schema (05, 06)

- LTA dissolved; LCS independent again in 2026 (8 teams). Lineage mapped as
  one league id. All four leagues: 3 splits/yr, Bo3 regular season.
- Hard fearless draft universal 2026 (per-series, both teams). NEW: Right of
  First Selection makes SIDE partly chosen -> side feature needs era
  interaction; historical blue-side baselines (~51.9%, declining) are
  non-stationary.
- Patch 26.1 removed Atakhan + Feats; pro stage runs ~6 weeks behind live
  (26.13 vs 26.16) -> compute meta priors on the PRO patch.
- Patch identity trap: marketing "26.16" = client "16.16.1" (offset -10,
  25.S1.x interlude) -> translation utility, both ids stored.
- LPL soloq is a permanent gap (super server unreachable, no trackers).
  Riot soloq retention ~2yr -> collector starts early. op.gg scraping is a
  ToS violation (hard no); ddragon/cdragon are the clean static sources; no
  buff/nerf API exists -> DIY snapshot diffing.

## Deadline

Worlds 2026: Oct 15 - Nov 14 (Texas/Brooklyn). ~8 weeks. Target: M1 data
foundation + M2 pregame model + all three recorders (odds, frames, soloq)
running BEFORE it starts. MSI 2026 already done (HLE won, Daejeon).

## Recorders are urgent because nothing backfills

- Polymarket/Kalshi publish no free historical order books.
- livestats retention is Riot's whim; local frame archive ends the risk.
- Riot soloq history evaporates past ~2 years.
Every week of delay is data lost forever; all three recorders ship in M1.

## Open questions carried to round 2

1. ANSWERED (2026-08-21, measured live): the free feed is NEAR-REAL-TIME --
   frontier lag median 25.6s during a live LCK game vs 5-10 min broadcast
   delay. Q16 revised: in-play trading upgraded to researchable. Repeat on
   LEC/LCS days for confirmation.
2. LCS frame-retention wall (assumed LEC-like 2024+; probe pending).
3. Kalshi API specifics for the odds recorder (endpoints, auth, esports
   market discovery) -- researching now.
4. Exact Bo1 fearless handling + LPL 2025 soft-fearless residue (era flags
   cover it either way).
5. OE SPA download automation (or accept semi-manual quarterly pulls).
