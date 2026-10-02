# 07 — Odds-Capture APIs: Kalshi & Polymarket Mechanics for a Read-Only Recorder

Research date: 2026-08-21. All web sources searched/opened with 2025/2026 qualifiers; all API claims below were additionally verified with **live, unauthenticated `curl` calls made today (2026-08-21)** against the production endpoints unless marked otherwise. Confidence tags: **High** (primary doc and/or live-verified today), **Medium** (single good secondary source or doc text that was ambiguous), **Low** (inferred/unconfirmed — flagged as a risk in §5).

---

## 1. Executive Summary

1. **Kalshi REST market data needs zero authentication.** `/series`, `/events`, `/markets`, `/markets/{ticker}/orderbook`, `/markets/trades`, and candlestick history all returned real data with no headers in live tests today. **(High)**
2. **Kalshi WebSocket requires an authenticated (RSA-signed) handshake even to read public channels** (`ticker`, `trade`, `orderbook_delta`) — auth gates the connection, not the data. So a pure-recorder still needs a Kalshi account + API keypair. **(High** for handshake requirement; **Medium** that `orderbook_delta` itself is full public depth, not user-scoped — see §5.)
3. **Three confirmed Kalshi LoL series tickers, verified live today**: `KXLOL` (scope "Future" — season/tournament outright winners), `KXLOLGAME` (scope "Game" — full-match winner, one ticker per competitor), `KXLOLMAP` (scope "Map Winner" — per-map winner). No Kalshi prop markets (kills, first blood, etc.) were found. **(High)**
4. **A real, live Kalshi match ticker as of today**: event `KXLOLGAME-26AUG201200GNGBAAM`, market `KXLOLGAME-26AUG201200GNGBAAM-GNG` — "GnG Amazigh vs. Baam Esports" (Arabian League 2026), with a working orderbook and trade tape pulled directly. **(High, live data)**
5. **Polymarket market data (Gamma + CLOB) is fully public, no auth**, including `/book`, `/price`, `/prices-history`, and the CLOB WebSocket `market` channel. Only order placement needs L2 (wallet) auth. **(High)**
6. **Polymarket structures LoL matches as one Gamma *event* containing many flat binary markets**: full-match winner, Game 1/2/3 winner, total-maps O/U, map handicap, and a long tail of props (first blood, kill totals, penta/quadra kills, baron/dragon/inhibitor props) — confirmed via a live event, `lol-t1-drx-2026-05-20` (T1 vs Kiwoom DRX, LCK). Season-winner futures (e.g. `lol-lck-2026-season-winner`) use `negRisk: true`; match-level markets are `negRisk: false`. **(High, live data)**
7. **Polymarket exposes far more granular LoL markets per match than Kalshi** (10–20+ prop markets vs. Kalshi's match+map only) — a material asymmetry for recorder scope and storage. **(High)**
8. **Rate limits**: Kalshi is a token-bucket, tiered system (Basic 200 read/100 write tokens/sec up to Prime 4000/4000); Polymarket is IP-based/Cloudflare-throttled (Gamma ~400 req/s, CLOB ~900 req/s general). Both are generous for a polling recorder; WebSocket push is still strongly preferred over polling. **(High, primary docs)**
9. **Kalshi's own "Data Terms of Use" (read in full via PDF) explicitly bars scraping/crawling of the *website*, bars using Kalshi Data to train ML/AI without written consent, and bars "providing archived or cached data sets... to another person or entity."** This is a real legal open question for a project whose next phase is contract-pricing/modeling — see §5. It is **not** the same document as the separate, mandatory API Developer Agreement, whose actual text could not be fetched (blocked by Cloudflare 429 on every attempt). **(High for the PDF text itself; Low/open for how it interacts with the API-specific agreement.)**
10. Kalshi's canonical documented host is `external-api.kalshi.com`; the older `api.elections.kalshi.com` host (used by most third-party guides) is **still live and functionally identical today** — both were used interchangeably in this research. **(High, live-verified today)**
11. No confirmed, LoL/esports-specific third-party historical archive was found for either venue — several general Kalshi/Polymarket archive products exist (Lychee, ScoreTape, Telonex, PMData, a GitHub Polymarket dataset) but none advertise esports coverage specifically; treat as **unverified for our niche**. **(Medium)**
12. Mapping a venue market to an internal match ID is workable on both venues but via different mechanisms: Kalshi encodes date/time/team-codes into the ticker string plus an internal `esports_competitor` UUID and free-text rules citing Sofascore/BO3.gg; Polymarket exposes a clean machine-readable `gameStartTime` field plus team names in slugs/questions. **(High, both from live examples)**

---

## 2. Kalshi — API Mechanics

### 2.1 Base URLs

| Surface | Documented (official) | Also live today (legacy/alt host) |
|---|---|---|
| REST | `https://external-api.kalshi.com/trade-api/v2` | `https://api.elections.kalshi.com/trade-api/v2` |
| WebSocket | `wss://external-api-ws.kalshi.com/trade-api/ws/v2` | (same elections.kalshi.com pattern reported by third-party SDKs) |
| Demo REST | `https://external-api.demo.kalshi.co/trade-api/v2` | — |

Despite the `elections` name, the production Trade API serves **all** Kalshi markets, not just elections. [API Environments](https://docs.kalshi.com/getting_started/api_environments) (accessed 2026-08-21). I independently confirmed **both** REST hosts return live, identical-shaped JSON today via direct `curl` (no proxy/browser). **Recommendation: code against `external-api.kalshi.com` as the documented canonical host, but don't be surprised to see `elections.kalshi.com` in older sample code — it still works.**

### 2.2 Authentication

- Full trading actions require an **RSA keypair**: generate in the dashboard, upload the public key, sign each request with RSA-PSS/SHA-256 (MGF1 SHA-256, salt = digest length), base64-encode, and send as three headers: `KALSHI-ACCESS-KEY`, `KALSHI-ACCESS-TIMESTAMP`, `KALSHI-ACCESS-SIGNATURE`. [Kalshi API Guide summaries citing docs.kalshi.com] (Medium — consistent across apidog.com, agentbets.ai, parlay.run, predscope.com, accessed 2026-08-21; the auth flow is standard enough across sources that this is effectively High confidence even though I did not fetch the raw auth doc page directly).
- **Public market-data REST endpoints need none of this.** Verified live today with zero headers:
  - `GET /series/{ticker}`, `GET /markets?event_ticker=...`, `GET /markets/{ticker}/orderbook`, `GET /markets/trades?ticker=...` — all returned real data with a bare `curl -H "Accept: application/json"`.
- **WebSocket is different: the connection handshake itself requires the signed-request auth headers, even though the channels being subscribed to (`ticker`, `trade`, `market_lifecycle_v2`) carry public data.** ["even channels that carry public market data still use the authenticated WebSocket session, but they do not impose additional per-channel authorization checks"] — [Quick Start: WebSockets](https://docs.kalshi.com/getting_started/quick_start_websockets), accessed 2026-08-21 (**High** for "auth required to connect at all"). Practical implication: **a recorder that only ever reads public data still needs a real Kalshi account and an RSA keypair to use the WebSocket feed.** REST-only polling can be done with zero account.

### 2.3 Market discovery endpoints

- `GET /series?category=...` — category is a small closed enum; **`Sports` is the top-level category for esports** (there is no separate `Esports` category value — `category=Esports` and `category=esports` both returned `{"series":null}` in live testing). Esports is a *product line within* Sports, distinguished by series ticker prefix and tags, not the `category` filter.
- `GET /series/{ticker}` — single-series metadata: `category`, `frequency`, `product_metadata.scope`, `contract_terms_url` (PDF), `settlement_sources` (see §4.4), `additional_prohibitions` (insider-trading restrictions for players/coaches/staff — not relevant to a recorder but confirms Kalshi runs these as CFTC-style regulated contracts).
- `GET /events?series_ticker=...&status=open&with_nested_markets=true` — cursor-paginated; confirmed live, returns events with embedded market arrays when `with_nested_markets=true`.
- `GET /markets` — [official param reference](https://docs.kalshi.com/api-reference/market/get-markets.md), accessed 2026-08-21: `limit` (0–1000, default 100), `cursor`, `event_ticker`, `series_ticker` (must pair with `mve_filter=exclude`), `status` (`unopened|open|paused|closed|settled|determined|disputed|amended|finalized`), `tickers` (CSV), plus `min/max_created_ts`, `min/max_close_ts`, `min/max_settled_ts`, `min_updated_ts`. Only one status/timestamp filter combination allowed at a time.

### 2.4 Orderbook & trades (verified live)

`GET /markets/{ticker}/orderbook` — returns **only bid-side depth for each side** (Kalshi's reciprocal-pricing model: a YES ask is implied as `$1 − NO bid`, so there is no separate ask array). Live example (`KXLOLGAME-26AUG201200GNGBAAM-GNG`, captured 2026-08-21):

```json
{"orderbook_fp":{
  "no_dollars":[["0.0100","1374.00"],["0.0200","303.00"], ...],
  "yes_dollars":[["0.0100","854.00"],["0.0200","103.00"], ...]
}}
```
Each entry is `[price_dollars, size_contracts]`.

`GET /markets/trades?ticker={ticker}&limit=N` — flat path with `ticker` as a **query parameter**, not nested under the market (i.e. **not** `/markets/{ticker}/trades`). Live example returned a real fill: `{"trade_id":"...", "yes_price_dollars":"0.7600", "no_price_dollars":"0.2400", "taker_side":"yes", "count_fp":"1.00", "created_time":"2026-08-20T23:45:31Z", ...}`.

### 2.5 Historical candlesticks

`GET /historical/markets/{ticker}/candlesticks?start_ts&end_ts&period_interval` — [official doc](https://docs.kalshi.com/api-reference/historical/get-historical-market-candlesticks.md), accessed 2026-08-21. `period_interval` ∈ `{1, 60, 1440}` minutes. Response: `end_period_ts`, `yes_bid`/`yes_ask` OHLC, `price` OHLC+mean, `volume`, `open_interest`. **I could not confirm any documented cap on time range or row count in the primary doc** — some secondary blog posts claim "100 tickers per request, 10,000 candlesticks total," but that contradicts the documented path (`{ticker}` is singular, in the path, not a batch array), so **I'm excluding that specific claim as likely conflated with the unrelated `/markets?tickers=` batch filter** (Low confidence in the "100/10,000" number — treat any batch-candlestick behavior as unverified until tested).

### 2.6 WebSocket feed

Subscribe message:
```json
{"id":1,"cmd":"subscribe","params":{"channels":["ticker"],"market_tickers":["KXLOLGAME-26AUG201200GNGBAAM-GNG"]}}
```
[Quick Start: WebSockets](https://docs.kalshi.com/getting_started/quick_start_websockets), accessed 2026-08-21.

Channels (per docs.kalshi.com, which labels them "private"/"public" — see caveat below):
- **`ticker`** — [schema](https://docs.kalshi.com/websockets/market-ticker): `market_ticker`, `price_dollars`, `yes_bid_dollars`, `yes_ask_dollars`, `volume_fp`, `open_interest_fp`, `yes_bid_size_fp`, `yes_ask_size_fp`, `last_trade_size_fp`, `ts`/`ts_ms`.
- **`trade`** — [schema](https://docs.kalshi.com/websockets/public-trades): `trade_id`, `market_ticker`, `yes_price_dollars`, `no_price_dollars`, `count_fp`, `taker_side`, `is_block_trade`, `ts`/`ts_ms`.
- **`orderbook_delta`** — sends one `orderbook_snapshot` then incremental `orderbook_delta` messages with monotonic `seq` numbers and built-in gap recovery.
- **`market_lifecycle_v2`, `multivariate_market_lifecycle`, `multivariate`** — status/lifecycle events.
- Account-only (not useful to a recorder): `fill`, `market_positions`, `communications`, `order_group_updates`.

**Caveat worth flagging (Medium confidence):** Kalshi's own docs list `orderbook_delta` under a "private channels" heading, which on its face suggests user-scoped data. However, multiple independent third-party sources — a dedicated tutorial ["Building a Live Order Book Watcher for Kalshi"](https://hackingthemarkets.com/building-a-live-order-book-watcher-for-kalshi/), [quantvps.com's order-book API writeup](https://www.quantvps.com/blog/kalshi-order-book-api-endpoints-explained), and an SSRN paper, ["Reconstructing Full Limit Order Books for Kalshi from WebSocket Streams"](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6583921) — all use `orderbook_delta` generically to reconstruct **any** market's full public book, not just the subscriber's own orders. My read: "private" in Kalshi's taxonomy most likely describes "requires an authenticated connection to subscribe to at all" rather than "data is restricted to your own account." **Recommend a 5-minute live smoke test** (subscribe to a market you hold no position in, with a fresh demo key) before relying on this for the recorder — cheap to verify, expensive to assume wrong.

### 2.7 Rate limits

[Rate Limits and Tiers](https://docs.kalshi.com/getting_started/rate_limits), accessed 2026-08-21 — token-bucket, **separate Read and Write buckets**:

| Tier | Read tok/s | Write tok/s | How to reach it |
|---|---|---|---|
| Basic | 200 | 100 | account signup |
| Advanced | 300 | 300 | call upgrade endpoint |
| Expert | 600 | 600 | trailing-30-day volume share |
| Premier | 1,000 | 1,000 | volume share |
| Paragon | 2,000 | 2,000 | volume share |
| Prime | 4,000 | 4,000 | volume share |
| Prestige | 10,000 | 8,000 | volume share |

Advanced+ read buckets (and Basic write) hold ~2s of burst; higher read/Basic-write hold ~1s. Exceeding limits returns `429` with **no `Retry-After` header** — implement exponential backoff. No separate/lower documented limit specific to WebSocket connections. **A read-only recorder polling a few hundred LoL tickers comfortably fits in Basic (200 read/s)**; prefer WS push over REST poll regardless to avoid burning the budget.

### 2.8 LoL/esports market discovery — confirmed series & real tickers

| Series ticker | `scope` | Meaning | Confirmed live example |
|---|---|---|---|
| `KXLOL` | `Future` | Season/tournament outright winner | title "League of Legends" |
| `KXLOLGAME` | `Game` | **Full match** winner (despite the name, "Game" = the whole Bo-series here, not a map) | `KXLOLGAME-26AUG201200GNGBAAM` |
| `KXLOLMAP` | `Map Winner` | Individual map/game winner within a match | title "League of Legends Map Winner" |

Live event detail (`KXLOLGAME-26AUG201200GNGBAAM`, pulled 2026-08-21): rules text reads *"the full match in the Arabian League 2026: GnG Amazigh vs. Baam Esports League of Legends match originally scheduled for Aug 20, 2026 at 12:00 PM EDT."* Market ticker for one side: `KXLOLGAME-26AUG201200GNGBAAM-GNG` (title "GnG Amazigh wins", `no_sub_title`/`yes_sub_title` give the readable team name). The **event ticker embeds date + time + both team codes** (`26AUG20` + `1200` + `GNG`+`BAAM`); the **market ticker** = event ticker + `-` + 3-letter competitor code for the "Yes" side. Each 2-competitor match/map produces **two** market tickers (one per competitor as the "Yes" side) that are mirrors of each other.

Series-level metadata also includes `contract_terms_url` (`https://assets.kalshi.com/contract_terms/ESPORTSLOL.pdf` — internal product code `ESPORTSLOL`) and `settlement_sources`: **Sofascore** (`sofascore.com/esports/lol`), **BO3.gg** (`bo3.gg/lol/matches/finished`), and **Gamers World** (`egamersworld.com`) — useful as independent resolution-verification sources for our own recorder's outcome-tagging. Category for all three series is `"Sports"` (not a distinct Esports category) with `frequency: "custom"`.

Frontend category pages exist ([kalshi.com/category/sports/esports/league-of-legends](https://kalshi.com/category/sports/esports/league-of-legends), [kalshi.com/tag/lec](https://kalshi.com/tag/lec)) but returned `429` to automated fetches (Cloudflare bot protection on the main site — the API host does not have this problem).

Real-world volume context: Kalshi's LoL markets did **$8.7M across 116 matches in one week** (per [Esports Insider, June 2026](https://esportsinsider.com/2026/06/esports-prediction-markets-on-kalshi-breaking-down-the-36m-by-game), accessed 2026-08-21), spread across LEC/LCK/LPL and smaller regional leagues (e.g. Arabian League) — biggest single match ~$1.02M (Karmine Corp vs. G2), confirming both liquidity and that regional/minor-league matches (like the GnG vs Baam example above) are also listed, just thinner.

### 2.9 Terms of Service — what I could and couldn't verify

I obtained and read in full the **"Kalshi Data Terms of Use"** PDF (`kalshi-public-docs.s3.amazonaws.com/kalshi-data-terms-of-service.pdf`, accessed 2026-08-21, 3 pages). Key clauses, quoted directly:

- Scope: *"Content on the kalshi.com **website**..."* — this document is framed around the **website**, not explicitly the developer API.
- Permitted use: *"You may access content only for your personal use for non-commercial purposes."*
- **Prohibited without prior written consent**: "(1) the development of any software program, including, but not limited to, training a machine learning or artificial intelligence system; or (2) providing archived or cached data sets containing Kalshi Data to another person or entity."
- Also prohibited generally: scraping, "systematic retrieval," bots/crawlers/spiders against the website, and — in bold in the source — **any use of Kalshi Data for ML/AI training or generation "is expressly prohibited"** without consent.

**This is a real, load-bearing risk for rift-quant** given the stated next phase is win-probability modeling / contract pricing (i.e., exactly "training a machine learning system" and likely "archiving" a dataset). However, I could **not** retrieve the text of the separate, mandatory **API Developer Agreement** (`kalshi.com/developer-agreement`) — every fetch attempt (WebFetch and PowerShell with a browser user-agent) was blocked with `429` by Cloudflare on `kalshi.com` (the marketing/docs site has bot protection; the API host `external-api.kalshi.com`/`api.elections.kalshi.com` does not). Kalshi's own docs confirm this agreement is mandatory: *"By continuing to use or access Kalshi's API, you are agreeing to be bound to our Developer Agreement"* ([docs.kalshi.com/welcome](https://docs.kalshi.com/welcome), accessed 2026-08-21). It is plausible the API Developer Agreement supersedes or carves out an exception to the website-scoped Data ToS for programmatic/API use (Kalshi actively documents and promotes bot-building), but **I have not confirmed this** — see §5, this needs a human to read that page directly (logged in, from a normal browser) before any model-training use of captured data.

I found no explicit published rate/robots.txt policy singling out read-only polling as prohibited; the concern above is about *data licensing*, not about *access mechanics*.

---

## 3. Polymarket — API Mechanics

### 3.1 Services & base URLs

[API Introduction](https://docs.polymarket.com/api-reference/introduction), accessed 2026-08-21:

| Service | Base URL | Purpose | Auth for reads |
|---|---|---|---|
| Gamma API | `https://gamma-api.polymarket.com` | Market/event catalog, tags, metadata | None |
| CLOB API | `https://clob.polymarket.com` | Order book, prices, price history | None for market data; L2 (wallet-derived) only for order placement/cancel |
| Data API | `https://data-api.polymarket.com` | Public trade tape, positions | None for public trade queries |
| WebSocket (market) | `wss://ws-subscriptions-clob.polymarket.com/ws/market` | Live book/price/trade stream | **None** |

Gamma is explicitly the catalog ("what's tradeable"); CLOB is the order book/execution layer. [Polymarket/agent-skills market-data.md](https://github.com/Polymarket/agent-skills/blob/main/market-data.md) (official first-party repo), accessed 2026-08-21.

### 3.2 Market discovery (Gamma API)

- `GET /tags` — discover categories/tags (confirmed live; returned a large generic tag list including `league-of-legends` and `esports` slugs).
- `GET /events?tag_slug=league-of-legends&closed=false&limit=N` — **confirmed live today**, returned real LoL events including season-winner futures and individual matches.
- `GET /events?slug={event-slug}` — fetch one event with all nested markets (used to pull the full T1 vs. DRX match below).
- `GET /markets?slug={market-slug}` — per-market lookup (note: takes a **market**-level slug, not the parent event slug — querying with the event slug returned `[]` in testing).
- Per [agent-skills market-data.md]: sports-category events use a `series_id` concept in addition to tags.

### 3.3 CLOB market data endpoints (all public, no auth)

- `GET /book?token_id={id}` → full bids/asks with `tick_size`, `min_order_size`.
- `GET /price?token_id={id}&side=BUY|SELL` → best bid/ask.
- Midpoint endpoint → mid price (falls back to last trade if spread > $0.10, per agent-skills doc).
- Batch variants: `POST /books`, `POST /prices` accept up to (reportedly) 500 token IDs per call — **Medium confidence**, from the agent-skills doc rather than a primary schema page I opened directly.
- `GET /prices-history?market={token_id}&interval=1h|6h|1d|1w|1m|max&fidelity={minutes}` (or `startTs`/`endTs`, mutually exclusive with `interval`) → `{t, p}` series. `fidelity` ∈ roughly `{1, 60, 1440}` minutes (Medium confidence — pieced together from search results plus a known open GitHub issue, [py-clob-client#216](https://github.com/Polymarket/py-clob-client/issues/216), noting `/prices-history` returns **empty data below 12h granularity for already-resolved markets** — i.e., don't rely on fine-grained backfill after a match settles; you must capture live).
- Public trade tape: use the **Data API** `/trades` (not the CLOB `/trades`, which needs L2 auth and returns only the caller's own activity).

### 3.4 WebSocket market channel

[Market Channel](https://docs.polymarket.com/market-data/websocket/market-channel), accessed 2026-08-21 — confirmed **no authentication required**.

Subscribe:
```json
{"assets_ids": ["<token_id>", "..."], "type": "market"}
```
Optionally add `"custom_feature_enabled": true` to also receive `best_bid_ask`, `new_market`, `market_resolved` events.

Event schemas (from the primary doc):
- `book` — full snapshot: `event_type, market, asset_id, timestamp, hash, bids[], asks[]` (bids/asks are `{price, size}`). The `hash` field supports book-integrity verification.
- `price_change` — incremental: `price_changes[]` each with `asset_id, price, size, side, hash, best_bid, best_ask`. Fires on new/cancelled resting orders, not just trades.
- `tick_size_change` — `old_tick_size` → `new_tick_size`.
- `last_trade_price` — `asset_id, price, size, fee_rate_bps, side, timestamp, transaction_hash` — this is the actual executed-trade event (as distinct from `price_change`).

Subscribe using **CLOB token IDs** (`clobTokenIds` from the Gamma market object), not condition IDs or slugs.

### 3.5 Rate limits

[Rate Limits](https://docs.polymarket.com/api-reference/rate-limits), accessed 2026-08-21 — **IP-based**, Cloudflare-enforced, sliding window, **throttled (delayed) rather than hard-rejected** when exceeded:

| Service/endpoint | Limit |
|---|---|
| Gamma API (general) | 4,000 req/10s (~400/s) |
| Gamma `/events` | 500 req/10s |
| Gamma `/markets` | 300 req/10s |
| Gamma `/public-search` | 350 req/10s |
| CLOB API (general) | 9,000 req/10s (~900/s) |
| Data API (general) | 1,000 req/10s |
| Data API `/trades` | 200 req/10s |
| Bridge API | 50 req/10s |

Trading endpoints (`POST /order`, etc.) have separate, much tighter per-signer buckets — irrelevant to a read-only recorder. **These limits are generous relative to anything a LoL-match odds recorder needs**; WebSocket is still preferable for freshness and to avoid needless polling load.

### 3.6 LoL market structure — confirmed live examples

**Season-winner futures (negRisk, multi-outcome)**: event `lol-lck-2026-season-winner` ("LCK 2026 Season Winner"), `negRisk: true`, `negRiskMarketID` present, one binary sub-market per team (e.g. `will-brion-win-the-lck-2026-season-playoffs`, `conditionId 0xd69e599b...`, two `clobTokenIds`). This is Polymarket's standard pattern for N-way outcomes: N flat binary markets wrapped in one neg-risk group so they sum sensibly.

**Single match (simple binary, NOT negRisk)**: event slug `lol-t1-drx-2026-05-20` — *"LoL: T1 vs Kiwoom DRX (BO3) - LCK Rounds 1-2."* Pulled the full nested market list live; every market in the event has **`negRisk: false`**:

| Market slug | Question | conditionId (truncated) |
|---|---|---|
| `lol-t1-drx-2026-05-20` | LoL: T1 vs Kiwoom DRX (BO3) - LCK Rounds 1-2 | `0x8e3fd307...` |
| `lol-t1-drx-2026-05-20-game1` | LoL: T1 vs Kiwoom DRX - Game 1 Winner | `0xff4f64b8...` |
| `lol-t1-drx-2026-05-20-game2` | LoL: T1 vs Kiwoom DRX - Game 2 Winner | `0x065e2afa...` |
| `lol-t1-drx-2026-05-20-total-games-2pt5` | Games Total: O/U 2.5 | `0xdb5e950c...` |
| `lol-t1-drx-2026-05-20-game-handicap-away-1pt5` | Game Handicap: T1 (-1.5) vs Kiwoom DRX (+1.5) | `0x4ef29d6e...` |
| ...plus per-game props | "Game 1: Both Teams Slay Baron Nashor?", "Any Player Penta Kill?", "Odd/Even Total Kills?", etc. | — |

A second real match (`lol-myth-ban2-2026-05-14`, Myth Esports vs The Bandits) and a third (`lol-al-wb-2026-01-20`, Anyone's Legend vs Weibo Gaming) showed the **same template**: full-match + per-game winner + total-games O/U + kill/tower/drake/inhibitor handicaps + per-game props (first blood, kill O/U at many lines, penta/quadra kill, odd/even kills, "both teams slay dragon/baron," "both teams destroy inhibitors"). **This confirms one market per outcome-question, all flat binaries grouped under a shared event — not one market with per-map "legs."** Prop-market density is high: 15–30+ markets observed per single Bo3 match.

Each market also carries a clean **`gameStartTime`** field (e.g. `"2026-05-20 08:00:00+00"`, UTC) separate from `startDate` (when the market was *listed*, days earlier) — this is the reliable field for match-time mapping (see §4.4).

### 3.7 Terms of Service

Polymarket's Terms of Use live at [polymarket.com/tos](https://polymarket.com/tos) (confirmed to exist and be the canonical doc — entity is Forecast Harbor N.V.). I was **not able to extract the specific automated-access/scraping/bot clauses** from this page via WebFetch (it returned only nav/schema markup, not body text — likely client-rendered). Secondary sources describe geoblock-circumvention as a violation (Section 2.1.4) and general anti-manipulation rules, but **I found no equivalent to Kalshi's explicit "no ML training / no archived datasets" language for Polymarket** in anything I could access — this is an **absence of evidence, not evidence of absence**; a human should read `polymarket.com/tos` directly before assuming it's more permissive than Kalshi's. **(Low-Medium confidence on the ToS section specifically — flagged in §5.)**

---

## 4. Recorder Design Recommendation

### 4.1 Per-venue capture strategy

| Need | Kalshi | Polymarket |
|---|---|---|
| Top-of-book + mid, tick-level | Subscribe WS `ticker` channel per market ticker (push, not polling) | Subscribe WS `market` channel per `clobTokenIds`, consume `price_change`/`best_bid_ask` |
| Full book snapshots | WS `orderbook_delta`: snapshot + deltas w/ seq recovery (verify public-scope per §2.6 caveat first) | WS `market` channel `book` event on subscribe + after any `hash` mismatch; periodic `GET /book` as backstop |
| Trades | WS `trade` channel | WS `market` channel `last_trade_price` event, or poll Data API `/trades` |
| Resolution outcome | Poll `GET /markets/{ticker}` for `status`→`settled/finalized` + `result`, or WS `market_lifecycle_v2` | `custom_feature_enabled:true` → `market_resolved` event, or poll Gamma `closed`/`outcomePrices` |
| Backstop / gap-fill | REST `GET /markets/{ticker}/orderbook` every 30–60s during live windows; `GET /historical/.../candlesticks` (1-min) for pre-recorder history | REST `GET /book` every 30–60s; `GET /prices-history` for pre-recorder history (**but empty below 12h fidelity once resolved — capture live, don't rely on backfill**) |
| Auth needed | REST: none. WS: yes (RSA keypair + signed handshake), even for public channels | None anywhere for market data |

**Recommendation: WebSocket-first, REST-as-backstop, on both venues.** Both public REST surfaces are generous enough (Kalshi Basic tier 200 read/s; Polymarket ~400–900 req/s) that a periodic full-snapshot poll (e.g. every 30–60s per live match) is cheap insurance against WS disconnects/gaps, without threatening rate limits even across a full multi-region match day.

### 4.2 Discovery loop (how the recorder finds new matches to watch)

- **Kalshi**: poll `GET /events?series_ticker=KXLOLGAME&status=open&with_nested_markets=true` (and `KXLOLMAP`, `KXLOL`) on a slow cadence (e.g. every 15–30 min) to catch newly-listed matches; cursor-paginate. New tickers get added to the WS subscription set as discovered.
- **Polymarket**: poll `GET /events?tag_slug=league-of-legends&closed=false&limit=100` similarly; watch for new event slugs matching the `lol-{team}-{team}-{date}` pattern, then pull the full event to enumerate all nested market `clobTokenIds` (full match + maps + props) for subscription.
- Both discovery polls are REST GETs against endpoints already confirmed to need no auth and to have ample rate-limit headroom at this cadence.

### 4.3 Storage estimate (explicit assumptions — not measured; validate with a short pilot capture)

Basis: Esports Insider reported **116 Kalshi LoL matches in one week** (≈16–17/day) across LEC/LCK/LPL/regionals — used as the match-day cohort size for both venues.

- **Kalshi tickers to track**: ~6–7 per match (1 full-match event × 2 competitor-tickers + ~2.4 avg maps for a Bo3-weighted mix × 2 tickers) → **~110 active tickers/day** across a multi-region slate, plus a smaller, slow-moving set of standing `KXLOL` futures tickers.
- **Polymarket markets to track**: same 6–7 "core" markets/match **plus** an observed 10–20+ props/match → **~17–22 markets/match**, i.e., roughly **280–370 markets/day** (560–740 token-sides if capturing both outcome tokens per market, recommended for overround/spread analysis rather than assuming perfect complementarity).
- **Per-message size** (measured from live payloads above): Kalshi ticker/orderbook/trade messages ≈ 300–800 bytes JSON; Polymarket book/price_change/trade events are similar, ≈ 200–1,000 bytes depending on book depth.
- **Rough daily raw-JSON volume**: tens of MB per venue for a full active match-day slate (WS tick stream + 30–60s REST backstops during live windows), i.e., **very roughly 50–150 MB/day/venue uncompressed**, compressing 5–10x with gzip or columnar storage (Parquet) → **low tens of MB/day/venue compressed**, on the order of **a few GB/month per venue**. This is small enough that no specialized time-series database is required — flat Parquet files or a single Postgres/SQLite/DuckDB instance is sufficient; a purpose-built TSDB (Timescale, etc.) is a convenience, not a necessity, at this scale.
- **Caveat**: this is order-of-magnitude reasoning from stated assumptions (match count, messages/ticker/lifecycle), not a measured rate. **Recommend instrumenting real capture for 2–3 match-days before sizing any storage/retention policy.**

### 4.4 Mapping venue markets → internal match/game IDs

**Kalshi** — ticker string is self-describing but its exact date/time encoding should be treated as an implementation detail, not a contract:
- Event ticker: `KXLOLGAME-26AUG201200GNGBAAM` → decodes to `{series}-{DDMMMYY}{HHMM}{TEAM1}{TEAM2}`. In the live example, the embedded time (`1200`) didn't exactly match the `expected_expiration_time` (20:00 UTC) — likely because the ticker encodes the *originally scheduled* start while `expected_expiration_time` accounts for match duration/buffer. **Don't parse the ticker as ground truth for kickoff time; use it only as a rough key.**
- **Authoritative fields for mapping**: the market's `rules_primary`/`rules_secondary` free text explicitly states team names and *"originally scheduled for [date] at [time] EDT"*; `open_time` and `expected_expiration_time` give machine-readable bounds; `custom_strike.esports_competitor` is an **internal Kalshi UUID per team** (e.g. `3c05d516-850b-4a85-922a-0cb8cfe8b3e9` for GnG Amazigh) — stable across that team's markets, useful once you've built a team-name↔UUID lookup table from observed markets, but there is no public "list competitors" endpoint found — you'd build the table incrementally from series/market metadata as matches are discovered.
- Cross-check resource: Kalshi cites **Sofascore, BO3.gg, and Gamers World** as its own settlement sources for LoL — these are good independent feeds to reconcile match identity/timing/results against.

**Polymarket** — cleaner machine-readable timing, looser team-name normalization:
- `gameStartTime` (e.g. `"2026-05-20 08:00:00+00"`) is an explicit, clean UTC scheduled-start field on every market — directly usable as a join key against your own match schedule (modulo normal fuzzy-matching for postponements).
- Team identity comes from **slug** (`lol-t1-drx-2026-05-20` → short/lowercased team tokens, not always the full official name — "Kiwoom DRX" → `drx`) and from the **question text** (uses fuller names: "T1", "Kiwoom DRX"). No stable numeric team ID was found in the market object — mapping will rely on fuzzy team-name matching against your own roster of official team names/aliases, same as most odds-aggregation work.
- League/series context appears only in free text (e.g. "LCK Rounds 1-2") — no structured league/split field was found on the market object itself; the **event's tag list** (`league-of-legends`, `lol`, `esports`, `counter-strike-2`, `games`, plus a `series_id`-style sports grouping per the agent-skills doc) is the closest structured signal for league classification.

**Practical mapping recipe for both venues**: normalize on **(team A alias, team B alias, scheduled UTC start ± a few hours tolerance)** as the join key, maintain a manually-curated alias table per venue (Kalshi 3-letter codes / UUIDs; Polymarket slug tokens), and use each venue's own free-text rules/question as a fallback human-auditable cross-check when the fuzzy match is ambiguous (postponements, reschedules, Bo3→Bo5 format changes mid-tournament, etc.).

### 4.5 Third-party archives to benchmark against

No esports-specific archive was confirmed for either venue. General-purpose products found (untested, treat as leads not verified sources):

- **Kalshi**: [Lychee](https://lycheedata.com/kalshi-historical-data) (claims full market/trade/orderbook history since launch), [ScoreTape](https://kalshisportsdata.com/) (full order-book-of-record for Kalshi *sports* markets, ties to final scores), PredictionData.io, SportsGameOdds — all general sports/politics-oriented; esports coverage unconfirmed.
- **Polymarket**: [manja316/polymarket-historical-data](https://github.com/manja316/polymarket-historical-data) (GitHub, 13,964 markets / 10.8M price records claimed, free sample + paid full set), [Telonex](https://telonex.io/) (free tick-level samples, Parquet), [PMData](https://pmdata.dev/) (orderbook/trades API), a "PMXT Archive" (hourly Parquet snapshots) — again general-purpose, esports subset unverified.

**Recommendation**: don't build a benchmarking dependency on any of these until someone manually confirms LoL/esports rows exist in a sample pull — treat our own recorder as the primary source of truth from day one rather than assuming a backfill option exists.

---

## 5. Open Questions / Risks

1. **[Legal — High priority]** Kalshi's "Data Terms of Use" (read in full, §2.9) explicitly restricts using Kalshi Data to "train a machine learning or artificial intelligence system" or to "provide archived or cached data sets... to another person or entity" without written consent — worded around *website* content but broad enough in spirit to raise a question about API-sourced data too, especially once rift-quant moves into modeling/contract-pricing. The separate, mandatory **API Developer Agreement** (`kalshi.com/developer-agreement`) could **not be read** (Cloudflare blocked every automated attempt) and may have different/more permissive terms for API users specifically. **Action: a human needs to log into kalshi.com and read the Developer Agreement directly before this data is used for anything beyond personal/internal research.**
2. **[Legal — Medium]** Polymarket's Terms of Use (`polymarket.com/tos`) could not be read for its automated-access/scraping clauses (client-rendered page, only nav markup returned). Absence of a found restriction is not confirmation none exists.
3. **[Technical — Medium]** Whether Kalshi's `orderbook_delta` WS channel is genuinely subscribable for *any* market's full public depth, or is in some way scoped/limited, is not 100% resolved by the primary docs (which label it "private") versus strong third-party practitioner evidence (which treats it as general-purpose). Cheap to resolve empirically before committing the recorder's book-capture design to it.
4. **[Technical — Low-Medium]** Kalshi candlestick batch limits ("100 tickers/request, 10,000 rows") appearing in some secondary sources could not be corroborated against the primary doc and were excluded — actual behavior (especially any undocumented max time range) should be tested directly against the API rather than assumed.
5. **[Data completeness — Medium]** Polymarket's `/prices-history` reportedly returns empty data below 12-hour fidelity for already-resolved markets ([py-clob-client#216](https://github.com/Polymarket/py-clob-client/issues/216)) — meaning **there is no reliable retroactive fine-grained backfill** on Polymarket once a match ends; the recorder must be running *before* a match starts to get tick-level history at all. Same practical constraint likely applies in spirit to Kalshi (no live-tested evidence either way for candlesticks post-settlement, but the recorder should not assume backfill is a safety net on either venue).
6. **[Scope]** No Kalshi prop markets (kills/first blood/etc.) were found — only match + map winners + season futures. If the eventual pricing model wants prop-level granularity, Polymarket will be the only source for that on LoL, which may bias any cross-venue comparison toward Polymarket's much larger market surface.
7. **[Benchmarking]** No third-party archive was confirmed to include esports data specifically (§4.5) — don't plan around one existing until manually verified.
8. **[Volume/liquidity]** Regional/minor leagues (e.g., the live "Arabian League" example on Kalshi) are listed but likely thin; recorder should capture them anyway (cheap) but downstream modeling should expect sparse/noisy books outside marquee LCK/LPL/LEC/LCS matchups.
