# rift-quant

Quantitative analysis of professional League of Legends (LCK, LPL, LEC, Americas).

Goal: a model that outputs calibrated win probability for either team at any
point of a pro game (from post-draft through live game state), backed by a
per-player champion-history database and meta analysis. Later phase: price and
trade outcome contracts (Polymarket) off the model.

Status: M0 -- research phase. See `docs/`.

## Layout

```
docs/
  QUESTIONS.md        <- every design question, self-answered, for review
  ARCHITECTURE.md     <- system design draft
  ROADMAP.md          <- milestones M0-M7
  RESEARCH_LOG.md     <- running log of research dispatches and findings
  research/           <- research reports (numbered)
  decisions/          <- ADRs once decisions harden
data/                 <- raw + processed data (gitignored)
src/                  <- python package (starts at M1)
scripts/              <- operational scripts
notebooks/            <- exploration
```

## Non-negotiables

- Point-in-time correctness: every feature computed as-of game start (no leakage).
- Calibration over accuracy: Brier score / log loss are the primary metrics.
- Every model beats documented baselines (side winrate, team Elo) or it does not ship.
- Paper trading before any real order.
