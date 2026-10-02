# M1b Build Brief -- odds-capture recorder (read-only)

Self-contained spec. DO NOT DISPATCH until the M1 builder has finished (same
repo/package; serialize). Extends the riftquant package created by
docs/specs/M1-build-brief.md.

## Context

We must accumulate LoL match-market price history forward (no venue publishes
free historical books). Purpose: closing-line-value benchmarking for the model
(M6). Read-only capture. NO order placement of any kind.

COMPLIANCE GATE (Q27 in docs/QUESTIONS.md): per-venue enable flags in config.
Default: polymarket=true, kalshi=false. Kalshi stays OFF until the user
reviews Kalshi's Data Terms (their terms prohibit ML-training/archiving
without consent). Do not flip the default. Implement Kalshi support behind
the flag anyway (code ready, disabled).

## Verified API facts (from docs/research/07-odds-capture-apis.md; re-verify
shapes with 1-2 live calls before coding against them)

Polymarket:
- gamma-api for market discovery (esports/LoL events; each match = one event
  with multiple flat binary markets: match winner, per-map, totals, handicaps,
  props). Filter to match-winner markets first; store event+market metadata.
- CLOB V2 REST for book/prices/trades -- public, no auth for market data.
- WSS market channel -- no auth. Prefer WSS with REST snapshot backstop.
Kalshi (behind flag):
- REST trade-api/v2 public for series/events/markets/orderbook/trades.
  Series: KXLOL (futures), KXLOLGAME (match winner), KXLOLMAP (per map).
- WSS requires RSA-signed auth handshake -- SKIP WSS for Kalshi; REST polling
  only (it is disabled by default anyway).

## Deliverables

1. riftquant/odds/{discovery.py, polymarket.py, kalshi.py, recorder.py}
   - discovery: find active + upcoming LoL match markets per venue; persist
     market metadata (venue, market id/ticker, title, teams-as-written,
     start time, discovered_at) to data/raw/odds/markets/.
   - recorder daemon (CLI: `riftquant record-odds --interval 30`):
     for each enabled venue and each tracked market: top-of-book + mid every
     interval; full book snapshot every 5 min; trades since last poll;
     resolution/settlement state when market closes. Append-only gzipped
     jsonl per venue per day: data/raw/odds/<venue>/<YYYY-MM-DD>.jsonl.gz
     (one json object per observation, with capture_ts).
   - Graceful: survives venue downtime (log + continue), clock uses UTC,
     idempotent restarts (append-only design makes this trivial), SIGINT
     clean shutdown flushes buffers.
2. Market-to-game mapping stub: riftquant/odds/mapping.py with
   map_market_to_game(market_meta, game_index) -> best-effort match on team
   names + start time window; emit unmatched to a review file. (Full entity
   resolution comes later; keep this simple and log-everything.)
3. CLI additions: record-odds (daemon), discover-odds (one-shot listing),
   odds-status (what is tracked, last capture ts per market).
4. Tests: mapping heuristics unit tests; recorder loop logic with a fake
   venue client; no live network in default pytest run.
5. Update README-DEV.md with recorder ops (how to run long-lived under
   Windows: plain console + optional Task Scheduler note).

## Constraints

Same as M1 brief: ASCII only, no AI attribution, no commits, raw-first,
polite rates (Polymarket REST <= 1 req/sec sustained per endpoint class; obey
429s with backoff), ~500-800 new lines excluding tests. WSS optional in v0 --
a clean 15-30s REST poller that never dies beats a fancy WSS client that
does; if WSS is straightforward with plain websockets lib, add it for
Polymarket only.

## Verification loop

1. discover-odds finds >=1 real upcoming/active LoL market on Polymarket
   (there are LCK/LPL games most weeks; if literally none active, verify
   discovery against any esports market and note it).
2. record-odds runs 3+ minutes against real Polymarket markets; show captured
   jsonl line count + a sample line.
3. Kalshi path: unit-tested with fixtures only (flag off) -- do NOT poll
   Kalshi live.
4. pytest green, ruff clean.
Report: files+lines, verification output pasted, deviations, limitations.
