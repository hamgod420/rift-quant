# Live and Official Professional LoL Esports Data Feeds

Research date: 2026-08-21. All findings below were verified either by direct live API
calls (curl, run 2026-08-21) or by fetching primary/secondary sources on 2026-08-21
unless otherwise noted. Confidence levels: **High** (directly tested or primary-source
confirmed today), **Med** (secondary source, plausible, not independently verified),
**Low** (single weak source or inference).

---

## 1. Executive Summary

- GRID (grid.gg) is now the dominant official esports data platform for LoL: Riot named
  GRID its exclusive partner at end of 2023, Bayes' Riot agreement ended in 2024, Bayes
  went insolvent in 2025, and GRID acquired Bayes' IP assets in Sept 2025. Bayes no
  longer exists as an independent access path. **[High]**
- GRID's free tier ("GRID Open Access") does **not** include League of Legends — as of
  2026-08-21 the Open Access application form only offers CS2, Dota 2, "Other," and the
  program explicitly serves historical (not live) data. LoL is commercial-only. **[High]**
- For LoL, GRID's site instructs non-commercial users to "await the LoL Esports Data
  Portal rollout" — i.e., as marketed today there is no self-serve free/hobbyist LoL
  tier; you must contact GRID sales for a quote. **[High]**
- The legacy unofficial API (`esports-api.lolesports.com/persisted/gw/*` with the public
  key, and `feed.lolesports.com/livestats/v1/{window,details}/{gameId}` with **no key at
  all**) is **still fully functional today** — verified with live curl calls returning
  current 2026-season LCK/LPL/LEC/Americas data. **[High, directly tested]**
- The livestats `window`/`details` endpoints work for **completed games from 3+ months
  ago** (tested on a May 2026 LCK game) — historical backfill via this channel is
  real, not just a live-only feed. **[High, directly tested]**
- Paging via `startingTime` works empirically: each call returns roughly ~8-10 seconds
  of game-time as a burst of sub-second frames (observed 25-58 frames per call); a full
  ~30-35 min game needs on the order of ~180-220 sequential paged calls per endpoint.
  This is reverse-engineered behavior, not documented anywhere officially. **[High,
  directly tested; exact chunking rule unconfirmed]**
- Every community wrapper library for this API is dead: last commits range from 2015 to
  2022 (verified via GitHub API), none touched in 2025/2026. Build a thin custom client
  rather than adopting an existing library. **[High]**
- Public broadcasts (Twitch/YouTube) carry an intentional **5-10 minute delay** industry
  standard, cited specifically with LoL as the motivating MOBA example (fog-of-war /
  stream-sniping risk). No source broke this out per-league (LCK vs LPL vs LEC vs
  Americas); treat 5-10 min as a general planning figure, not a per-league constant.
  **[Med]**
- Licensed bookmakers get an official **undelayed** feed straight from the game server
  via GRID; GRID's own commercial LoL package explicitly bundles "undelayed broadcast
  footage" alongside the live data feed. Marketed latency for official data is sub-200ms
  to sub-second; scraped/broadcast-derived data lags by "tens of seconds to minutes" on
  top of the base delay. **[Med — vendor-claimed numbers, not independently benchmarked]**
- As of June 26, 2025, Riot's official esports-betting-sponsorship policy **mandates any
  betting partner use GRID** ("Any potential betting partner must use GRID to power
  their offerings"), and is currently limited to Tier-1 LoL/VALORANT teams in the
  **Americas and EMEA only — not LCK (Korea) or LPL (China)**. **[High, primary source]**
- Riot's live Developer Portal policy (fetched today) states plainly: **"Your product
  cannot feature betting or gambling functionality"** for anything registered through
  the Developer Portal — a direct tension with rift-quant's Polymarket end goal that
  needs a deliberate compliance decision, independent of which feed is used. **[High,
  directly verified today]**
- There is no official Riot Developer Portal offering for esports data aimed at
  individual developers in 2026; `developer.riotgames.com` covers solo-queue/client data
  (match-v5, spectator-v5, etc.), not pro/esports play. The esports data path runs
  entirely through GRID (commercial) or the unauthorized lolesports.com endpoints.
  **[High]**
- Whether the unofficial `feed.lolesports.com` livestats data is itself subject to the
  same 5-10 minute delay as the public broadcast, or is closer to real-time, is
  **unresolved** — no source addresses this directly, and no live match was in progress
  during this research session to measure it empirically. This is the single most
  important open question for rift-quant's live-trading latency budget. **[Open
  question — see Section 4]**

---

## 2. Detailed Findings

### 2.1 GRID (grid.gg) — Open Access and commercial LoL data

**What GRID is.** GRID is Riot's exclusive official esports data distribution partner
for League of Legends (confirmed as the successor to Bayes Esports; see 2.3). GRID also
holds partnerships with ESL FACEIT Group and BLAST, covering CS2, Dota 2, VALORANT, and
more — grid.gg markets itself as "the League of Legends Data Portal" (co-branded with
Riot at [riotesportsdata.com](https://riotesportsdata.com/en-us/league-of-legends/)).
Source: [grid.gg](https://grid.gg/) (accessed 2026-08-21); [GRID/Riot LoL Esports
Data](https://riotesportsdata.com/en-us/league-of-legends/) (accessed 2026-08-21).

**GRID Open Access — what it actually covers today.** The Open Access program
([grid.gg/open-access/](https://grid.gg/open-access/), accessed 2026-08-21) is free for
"pre-revenue startups, academic institutions, independent developers, and fans" — solo
developers are explicitly named as eligible. However, the actual **application form**
([grid.gg/open-access-application-form/](https://grid.gg/open-access-application-form/),
fetched 2026-08-21) lists only **"CS2 / Dota2 / Other"** as title options — **League of
Legends is not selectable**. The companion history page
([grid.gg/what-is-grid-open-access/](https://grid.gg/what-is-grid-open-access/), fetched
2026-08-21) confirms Open Access launched Feb 2022 as "GRID Open Platform," currently
supports only CS2 and Dota 2, and that data delivered under Open Access is **historical
match data only — not live data** ("live data reserved for commercial partners"). LoL
has never been part of Open Access per available sources. **[High confidence — directly
fetched application form and program history page today]**

**GRID's LoL-specific portal.** The LoL Data Portal page
([grid.gg/get-league-of-legends/](https://grid.gg/get-league-of-legends/), fetched
2026-08-21) segments access into three tiers:
- *Professional Teams* — free/low-cost, but scoped to actual team orgs' scrim +
  tournament analytics consoles, not public data access.
- *Betting & Fantasy* — paid, "contact sales," bundles live data feeds, AV streaming,
  and visualizations across multiple titles.
- *Other* (fan engagement/product integration) — paid, custom quote.

The companion `riotesportsdata.com` page states LoL live data (champion health, gold,
objectives, damage, CS, KDA; fixtures; and **undelayed AV feeds**) is available "for
commercial purposes only," and explicitly tells non-commercial users to **"await the LoL
Esports Data Portal rollout"** — i.e., no current self-serve non-commercial path exists.
**[High confidence]**

**Cost.** No published price list for the commercial LoL tiers; both pages funnel to
"Contact Sales" / `data@grid.gg`. Open Access itself (CS2/Dota2) is free. **[High for
Open Access being free; Med/unknown for LoL commercial pricing — never published]**

**Can a solo developer get LoL access from GRID?** Practically, **no free path exists
today**. A solo developer can get free CS2/Dota2 historical data, or must go through
GRID's sales process for LoL (commercial tier, undisclosed pricing, generally structured
for businesses). The GRID Hackathon program
([grid.gg/hackathon-application-form/](https://grid.gg/hackathon-application-form/))
returned HTTP 404 when fetched today — likely a lapsed/inactive one-off event page, not
an ongoing access path. **[High confidence on "no current free LoL path"; Med on
hackathon being defunct, based on a single 404]**

**Usage restrictions.** No Open Access-specific Terms of Service document could be
located (only referenced, not linked in an accessible form). What is documented:
GRID's general terms prohibit using access "for purposes of competitive analysis,
development of competing services, or other purposes detrimental to GRID." **No explicit
"betting/wagering prohibited" clause was found for Open Access** — if anything, the
opposite is true: GRID operates a dedicated paid product line for betting ("GRID Bet,"
launched 2025, see 2.4) and Riot's own policy *requires* GRID for any licensed betting
partner. The practical restriction is commercial: wagering-adjacent use requires the
paid/licensed commercial relationship, not that betting use is banned outright. **[Med
confidence — inferred from absence of an explicit prohibition plus GRID's own betting
product line, not from reading a full ToS document, which was not accessible]**

**Latency (as marketed).** GRID markets its live feed as "Ultra-Fast, Low-Latency,"
"real time — down to every kill, assist," and elsewhere cites **sub-200ms** official
data latency vs. "tens of seconds, and in some cases, even minutes" for scraped
approaches. No LoL-specific millisecond figure was published anywhere found. Source:
[grid.gg/official-esports-data-why-every-millisecond-matters-for-your-sportsbook/](https://grid.gg/official-esports-data-why-every-millisecond-matters-for-your-sportsbook/)
(fetched 2026-08-21); [grid.gg/live-esports-data/](https://grid.gg/live-esports-data/)
(fetched 2026-08-21). **[Med confidence — vendor marketing claim, not independently
benchmarked]**

**Historical file dumps.** GRID's docs reference a "File Download API"
(`docs.grid.gg/.../grid-file-download-reference`), but `docs.grid.gg` is a
JavaScript-rendered SPA that returned no readable content to either WebFetch or a
plain curl (confirmed 2026-08-21: response body was literally "You need to enable
JavaScript to run this app"). Could not confirm file formats, retention window, or
whether this applies to LoL specifically. **[Low confidence / unresolved — flagged as
an open question in Section 4]**

### 2.2 The unofficial lolesports.com API

**Status: alive and functioning today.** Both documented endpoint families were tested
live on 2026-08-21 and both work with **no errors, no rate-limit response, no
deprecation notice**:

- `https://esports-api.lolesports.com/persisted/gw/*` — requires header
  `x-api-key: 0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z` (the long-standing public key
  documented since ~2014 in community gists/repos, e.g.
  [gist.github.com/Scub3d](https://gist.github.com/Scub3d/0523abc590028ff0e2fd6fda0fb4fa48),
  [kingjakeu/lolesports guide](https://github.com/kingjakeu/lolesports/blob/main/doc/unofficial-riot-api-guide.md)).
  Tested `getLeagues`, `getSchedule` (LCK, `leagueId=98767991310872058`), and
  `getEventDetails` on 2026-08-21 — all returned live, current 2026-season data
  (correctly listed LCK/LPL/LEC/LCS-successor "Americas Cup"/First Stand/Worlds/MSI
  leagues, and today's actual LCK schedule with real, current match IDs).
- `https://feed.lolesports.com/livestats/v1/window/{gameId}` and
  `.../details/{gameId}` — **no API key required at all**. Tested against a real
  completed LCK game from **2026-05-17** (game ID `115548128962971872`, over 3 months
  old at test time) and got full data back — confirming this channel serves historical,
  not just live, games. **[High confidence, directly tested today]**

**What the frames contain (empirically observed today):**
- `window/{gameId}` (no `startingTime`): returns `gameMetadata` first — patch version
  (observed `16.9.771.8052`), and per-team `participantMetadata` mapping
  `participantId` -> `esportsPlayerId`, `summonerName`, `championId`, `role`. Frames
  within a `window` call (once paged with `startingTime`, see below) carry simplified
  per-participant snapshots: `totalGold`, `level`, `kills`, `deaths`, `assists`,
  `creepScore`, `currentHealth`, `maxHealth`.
- `details/{gameId}`: frames carry a fuller per-participant snapshot: `level`, `kills`,
  `deaths`, `assists`, `totalGoldEarned`, `creepScore`, `killParticipation`,
  `championDamageShare`, `wardsPlaced`, `wardsDestroyed`, `attackDamage`,
  `abilityPower`, `criticalChance`, `attackSpeed`, `lifeSteal`, `armor`,
  `magicResistance`, `tenacity`, `items` (item ID array), `perkMetadata` (rune
  page), `abilities`.
- Every frame carries an `rfc460Timestamp` (ISO8601 with milliseconds).

**Paging by `startingTime` for past/completed games — confirmed working, but
undocumented chunking:**
- No `startingTime` param -> returns only a tiny burst of frames clustered at/near game
  start (observed: 10 near-duplicate timestamps spanning only ~20ms, consistent with the
  observer client's pre-game connect burst, not real gameplay ticks).
- With `startingTime=<ISO8601>` set to a specific in-game moment, the endpoint returns a
  **bounded chunk starting at that time**, not the whole rest of the game. Two separate
  mid-game probes on the same test game returned 58 frames spanning ~9.4 seconds and 25
  frames spanning ~10 seconds, respectively — i.e., roughly **8-10 seconds of game-time
  per call**, at sub-second frame density (roughly 3-6 frames/sec, not a clean fixed
  interval). **To reconstruct one full ~30-35 minute game you would need on the order of
  ~180-220 sequential paged calls per endpoint** (window and details are separate
  paginated series). This behavior is not documented anywhere officially or in any
  community doc found — it was reverse-engineered live during this research session and
  should be treated as an empirical observation on a small sample (2 probes), not a
  guaranteed contract. Build defensively (don't assume fixed frame counts). **[High
  confidence that paging works; Med confidence on the exact chunk-size rule generalizing
  across all games/patches]**

**Community libraries — all dead.** Verified via GitHub API commit history
(2026-08-21):

| Repo | Last commit |
|---|---|
| `rigelifland/lolesports_api` (Python) | 2020-03-10 |
| `bgraver/Irelia` (Python) | 2021-03-20 |
| `Pupix/lol-esports-api-module` (JS) | 2015-05-17 |
| `kingjakeu/lolesports` (guide/scraper) | 2021-07-30 |
| `vickz84259/lolesports-api-docs` (OpenAPI docs) | 2022-06-04 |

None have any 2025/2026 activity. The underlying API has clearly outlived every wrapper
built on it. **Recommendation: write a small first-party client** — the endpoints are
plain unauthenticated/single-static-key JSON GETs, so there is little value in adopting
an abandoned dependency versus ~1-2 days of direct implementation with your own
retry/backoff and schema-drift monitoring. **[High confidence]**

**Legal/ToS status — unauthorized, not sanctioned.** This API has never been an official
Riot product: no developer registration, no client ID, no SLA, a single static key
shared publicly for over a decade. GRID's own marketing (see 2.1, "eavesdropping" blog
post) explicitly frames use of *any* unofficial in-game telemetry channel as "abusing
the property of the game developers," warns of "potential legal ramifications," and
argues regulators increasingly require official data for compliance — though notably it
does not name lolesports.com's endpoints specifically. Source:
[grid.gg/no-one-told-you-that-eavesdropping-is-rude.../](https://grid.gg/no-one-told-you-that-eavesdropping-is-rude-the-unofficial-vs-official-in-game-telemetry-data-feeds/)
(fetched 2026-08-21). Practically: it has survived ~12 years of community use
unenforced, but there is zero contractual guarantee of continued availability, no
support channel, and if rift-quant's product becomes wagering-adjacent (Polymarket), it
sits in direct tension with Riot's now-explicit "betting partners must use GRID"
mandate (2.4). **[High confidence on the facts; judgment call on how much risk this
represents — see Section 4]**

### 2.3 Bayes Esports — current status

Bayes Esports signed its Riot data-rights agreement in 2021 and built the official "LoL
Esports Data Portal" (announced June 10, 2022) aimed at professional teams, Riot
partners, and — eventually — community consumers like Leaguepedia and Oracle's Elixir.
Source: [lolesports.com dev diary](https://lolesports.com/en-US/news/dev-diary-introducing-the-new-lol-esports-data-portal)
(fetched 2026-08-21, article dated 2022-06-10).

Riot named **GRID** as its go-forward exclusive partner at the end of 2023; Bayes'
Riot agreement formally ended in 2024. Bayes Esports subsequently entered **insolvency /
liquidation proceedings in 2025**, and **GRID acquired Bayes' intellectual-property
assets in September 2025**. Multiple industry outlets covered this consistently:
[esports.net](https://www.esports.net/news/bayes-esports-insolvency-leaves-grid-dominant-in-esports-data/),
[SBC News](https://sbcnews.co.uk/europe/2025/09/19/grid-acquires-bayes-esports/),
[European Gaming](https://europeangaming.eu/portal/latest-news/2025/09/23/192124/grid-acquires-bayes-esports/)
(search-result summaries reviewed 2026-08-21; full article bodies were blocked by 403s
on direct fetch, so this rests on search-snippet corroboration across three independent
outlets rather than a single full-text read). **[Med-High confidence: consistent across
3 independent outlets, but I was not able to open a full source due to 403 blocks —
flagging per citation-rigor rules]**

**Current relationship to Riot data:** none — Bayes no longer operates as an
independent esports-data company. **Hobbyist access:** not applicable; the company is
defunct. Combined with ESL/BLAST partnerships, GRID is now described as controlling
"the majority of the official esports data industry." **[High confidence on the
end-state; Med on the precise deal mechanics/pricing history, which no source detailed]**

### 2.4 Broadcast delay and who gets the real-time feed

**Broadcast delay figure.** Industry sources consistently cite **5-10 minutes** as the
standard intentional delay applied to public Twitch/YouTube esports broadcasts,
specifically to prevent stream-sniping — and League of Legends is repeatedly used as the
motivating example because of its fog-of-war design (a delayed-stream viewer who could
communicate with a player would otherwise leak vision). Sources:
[Abios/Newzoo newsroom](https://abiosgaming.com/press/stream-delay-esports-betting/),
[PandaScore blog](https://www.pandascore.co/blog/what-role-does-latency-play-in-esports-betting),
[iGaming Future](https://igamingfuture.com/esports-latency-and-delay-what-operators-need-to-know/)
(all fetched 2026-08-21). **None of these sources broke the delay down per league**
(no distinct LCK vs. LPL vs. LEC vs. Americas figures were found anywhere in this
research pass) — treat 5-10 minutes as an industry-wide planning assumption, not a
verified per-league constant, and re-measure directly against each league's stream if
precision matters. **[Med confidence — consistent across 3 sources, but generic/not
League-specific data, and not independently timed by this research]**

**Who gets the real-time feed.** Licensed bookmakers and other GRID commercial
customers receive an **undelayed** feed "directly from the game server" — GRID's LoL
commercial package explicitly lists "Audio/Visual feeds (undelayed broadcast footage)"
as a line item, distinct from the public delayed stream. Source:
[riotesportsdata.com](https://riotesportsdata.com/en-us/league-of-legends/) (fetched
2026-08-21). This is the clearest confirmation found that "real-time" for LoL esports is
a paid/licensed capability, not something obtainable by watching or scraping the public
broadcast. **[High confidence]**

**Riot's official betting-sponsorship policy (directly relevant to feed access).** On
**June 26, 2025**, Riot announced it would allow betting sponsorships for Tier-1 LoL and
VALORANT teams, but **only in the Americas and EMEA** — explicitly **not** LCK (Korea)
or LPL (China) in the initial rollout — and crucially stated: **"Any potential betting
partner must use GRID to power their offerings, ensuring consistency, integrity, and
accountability across the board."** Guardrails include Riot vetting of partners, team
integrity programs, and a ban on betting ads on Riot-owned broadcast channels. Source:
[riotgames.com official announcement](https://www.riotgames.com/en/news/esports-betting-sponsorships)
(fetched 2026-08-21, primary source, dated 2025-06-26). GRID subsequently launched
**"GRID Bet"** as its dedicated betting-vertical product. This means the officially
sanctioned "real-time feed for wagering-adjacent use" pathway for LoL runs exclusively
through GRID, is currently geographically scoped to Americas/EMEA team sponsorships (a
distinct question from data licensing, but indicative of where Riot's institutional
comfort with betting currently sits), and does not extend to LCK/LPL. No update
expanding this to LCK/LPL was found as of 2026-08-21 (see open question in Section 4 —
this could not be re-verified after this session's web-search budget was exhausted).
**[High confidence on the June 2025 policy text itself; open/unverified on whether it
has since been expanded]**

**Whether the unofficial feed is delayed like the broadcast.** Not resolved by this
research. No source discusses whether `feed.lolesports.com`'s livestats data is
synchronized to the delayed public broadcast (likely, if Riot wants to prevent the free
API from being a stream-sniping/live-edge workaround) or reflects the true undelayed
game state (possible, if the endpoint predates or was never brought into that
delay-enforcement design). No live match was in progress during this research window
(next LCK match was ~1.5 hours out) to measure directly. **This is flagged as the top
open question for rift-quant — see Section 4.**

### 2.5 Riot Developer Portal — official policy and 2026 offering for individuals

**No individual-developer esports data product exists.** `developer.riotgames.com`
offers REST APIs for standard player-facing data (match history, ranked, champion
mastery, live spectator data for solo-queue games, tournament-code APIs for amateur
tournaments) — this is a different data domain from professional esports competitive
play, and does not cover LCK/LPL/LEC/Americas pro matches. Source:
[developer.riotgames.com/apis](https://developer.riotgames.com/apis) (search-result
summary, 2026-08-21).

**Policy text, verified live today.** Fetched
`support-developer.riotgames.com/hc/en-us/articles/22698591841939-General-Policies`
directly (WebFetch was blocked with a 403; a plain curl with a browser User-Agent
succeeded, HTTP 200) on 2026-08-21. Verbatim, under "Monetization":

> "Your product cannot feature betting or gambling functionality."

And under "Tournament Policies":

> "Not include any gambling"

This is Riot's general Developer Portal policy (governing products built on the
registered Riot Games API / League Client API), not a lolesports.com-specific
statement — but it is the clearest first-party articulation found of Riot's stance on
gambling-adjacent products, and it directly informs how a Polymarket-facing product
would likely be viewed if it were ever brought to Riot for registration/partnership.
**[High confidence — directly fetched and quoted from the live policy page today]**

**Policy on using lolesports.com data specifically:** not addressed anywhere in the
Developer Portal terms — because those endpoints were never part of the registered
Developer Portal surface in the first place (no client ID, no registration flow covers
them). They exist in a policy vacuum: neither explicitly licensed nor explicitly
forbidden by name, just outside the governed API surface entirely. **[High confidence]**

---

## 3. Concrete Recommendations

**Build the historical/backtesting pipeline against the unofficial lolesports.com API
first.** It is free, live, unauthenticated (for the livestats endpoints), confirmed
working today, and already contains 2026-season LCK/LPL/LEC/Americas match IDs plus
per-frame gold/items/level/objectives data going back at least 3+ months. For rift-quant
goals #1 (win-probability model) and #2 (player champion-history profiles), this is
sufficient and immediately actionable:
1. Use `esports-api.lolesports.com/persisted/gw/getSchedule` +
   `getCompletedEvents`/`getEventDetails` to enumerate leagues -> tournaments ->
   matches -> game IDs.
2. Use `feed.lolesports.com/livestats/v1/details/{gameId}` paged by `startingTime` in
   ~8-10 second increments to reconstruct full per-player, per-frame time series
   (gold/items/level/kills/objectives) for every historical game.
3. Write a first-party thin client (no existing library is maintained); budget for
   ~180-220 paged calls per game per endpoint, so batch/parallelize and cache
   aggressively — this is a bulk-ETL job, not a chatty API.
4. Treat this pipeline as **at-risk, not permanent infrastructure**: it is unauthorized,
   undocumented, and could be rate-limited, paywalled, or shut off without notice now
   that GRID holds the exclusive commercial rights. Design the data layer so a future
   swap to a licensed GRID feed only requires a new ingestion adapter, not a rewrite of
   the modeling pipeline.

**Do not plan on this feed for live/real-money trading latency without first measuring
it against a live match.** The single highest-value next research/engineering task is
an empirical delay measurement: during a live LCK/LPL/LEC game, poll
`feed.lolesports.com/livestats/v1/window/{liveGameId}` (no key needed) and compare frame
`rfc460Timestamp`/arrival time against a wall-clock reference of the actual live game
state (e.g., a low-delay observer POV, or corroborated real-time social-media reactions
from in-venue attendees). Until that number is known, assume the **worst case: the free
feed is delayed in step with the 5-10 minute broadcast delay**, which would make it
useless for live trading and only useful for the modeling/backtesting mission. Do not
assume it is real-time just because it's technically served independently of the video
player.

**Realistic latency budget for a live-trading product:**
- Public broadcast + free unofficial API (unverified sync): **budget 5-10 minutes of
  adverse selection** versus anyone with a licensed feed. Not viable for live trading
  against sharper counterparties if this assumption holds.
- Licensed GRID commercial feed (Betting & Fantasy tier): vendor-claimed **sub-200ms to
  sub-second** from the game server, plus an undelayed AV option. This is the only
  path with a credible claim to near-real-time parity with sportsbooks, but it is
  commercial-only, priced for businesses (contact sales, no published rate card), and
  using it for a wagering-adjacent product would need to reconcile with Riot's
  "must use GRID" / no-gambling-functionality policy tension (Section 4).
- Treat any live-trading roadmap as gated on (a) the empirical delay measurement above,
  and (b) a deliberate compliance decision about Polymarket positioning versus Riot's
  stated gambling policy — not as a pure engineering problem.

**Sequencing:** ship the win-probability model and champion-history profiles (goals #1
and #2) on the free unofficial API now; treat live-trading latency (goal #3) as a
distinct, gated follow-on workstream that starts with the delay measurement, not with
infrastructure build-out.

---

## 4. Open Questions / Risks

1. **Is `feed.lolesports.com` livestats data delayed like the broadcast, or near
   real-time?** Unresolved — no source addresses it, and no live match was available to
   test during this session. This single fact determines whether goal #3 (live trading)
   is viable at all on the free feed. **Action: measure directly during the next live
   LCK/LPL/LEC game** (schedule showed LCK at 08:00 UTC and LPL at 11:00 UTC on
   2026-08-21/22, LEC Summer matches at 15:00/17:15 UTC — all recurring daily/weekly).
2. **How durable is unauthorized access to the unofficial API?** It has survived ~12
   years unenforced, but GRID's 2025 consolidation (Bayes acquisition, GRID Bet launch,
   Riot's explicit "must use GRID" mandate) suggests Riot/GRID have more commercial
   reason than ever to lock this down. No takedown or rate-limiting was observed today,
   but there is no SLA, no support channel, and no advance-notice guarantee. Build with
   a fallback/migration plan to a licensed feed.
3. **Compliance tension with Polymarket end-goal.** Riot's live policy states products
   "cannot feature betting or gambling functionality," and any officially sanctioned
   betting partner "must use GRID." Whether pricing prediction-market/outcome contracts
   on Polymarket counts as "betting or gambling functionality" in Riot's eyes is
   untested and unresolved — this is a legal/business judgment call, not something this
   research can settle. Recommend deliberate legal review before any live/real-money
   product ships, independent of which data feed is used.
4. **GRID's exact LoL pricing and SLA are unknown** — every commercial page routes to
   "Contact Sales" with no published rate card. Unknown whether GRID would even engage
   with a pre-revenue solo project for LoL specifically (Open Access explicitly excludes
   LoL, unlike CS2/Dota2).
5. **GRID's File Download API / historical dumps** could not be evaluated — `docs.grid.gg`
   is a JS-only SPA inaccessible to both WebFetch and curl in this session. Unknown
   whether it offers deeper/cleaner historical data than the unofficial livestats
   endpoints, and whether it's available under Open Access for any title.
6. **Has Riot's Americas/EMEA-only betting policy (June 2025) been expanded to LCK/LPL
   by now (Aug 2026)?** Not confirmed — this session's web-search budget was exhausted
   before this could be re-checked. Worth a quick follow-up search given it directly
   bears on whether Korea/China data can ever be part of a GRID-sanctioned real-time
   wagering-adjacent product.
7. **Bayes/GRID deal specifics** rest on search-snippet corroboration across three
   outlets rather than a fully-read primary source (all three full articles 403'd on
   direct fetch). The high-level narrative (insolvency 2025, GRID acquired IP Sept 2025)
   is consistent across sources and treated as reliable, but exact deal terms are
   unverified.
8. **Empirical paging behavior (~8-10s/chunk) was observed on only 2 probes of 1 game.**
   Treat as a working hypothesis to validate against more games/patches before relying
   on it for production ETL sizing.
