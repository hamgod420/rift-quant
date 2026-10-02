# Historical Professional LoL Match Data Sources

Research date: 2026-08-21. Findings below come from either (a) direct live queries run
today (curl against Leaguepedia's Cargo API, Oracle's Elixir's WordPress pages, gol.gg,
GRID's site, and acs.leagueoflegends.com) or (b) web search / secondary sources fetched
today. Confidence tags: **High** (directly tested or primary source read in full today),
**Med** (secondary source or partial primary confirmation), **Low** (single weak source
or inference). This document focuses on *historical/archival* match data; see
`02-live-official-feeds.md` for live/in-game data feeds (including the unofficial
`lolesports.com` API, which also serves historical game windows) and
`05-league-landscape-2026.md` for 2026 league structure and Fearless Draft rules
referenced below.

---

## 1. Executive Summary

- **Oracle's Elixir is alive and actively maintained** by Tim "Magic" Sevenhuysen in
  2026, but it is a one-person hobby operation, not stable infrastructure: it suffered a
  **DNS-hijack / malware-phishing incident on April 13, 2026** (resolved within a day),
  and its **LPL/LDL (Chinese) data pipeline went dark from roughly late July to August
  11, 2026** due to an unspecified upstream source problem — both dated, primary-sourced
  events, not inference. **[High]**
- Oracle's Elixir's **current single-file-per-year CSV downloads live behind a
  JavaScript React app** (`oracleselixir.com/tools/downloads`, Cloudflare-protected) that
  could not be scripted or introspected today; the **old S3 bucket**
  (`oracleselixir-downloadable-match-data.s3-us-west-2.amazonaws.com`) referenced in
  older tutorials **no longer exists** (`NoSuchBucket`). A separate, older, fully static
  archive at `lol.timsevenhuysen.com/matchdata/` (2016-2020 per-split files, .xlsx before
  2020 / .csv from 2020) plus its data dictionary **is** directly fetchable and was read
  in full. **[High]**
- Oracle's Elixir's documented schema (from the static dictionary) covers identifiers,
  **ordered bans (ban1-5)** but not an explicit interleaved pick-order field, per-player
  boxscore stats, and **gold/XP/CS snapshots and diffs at 10 and 15 minutes**
  (`goldat10`, `gdat10`, `goldat15`, `gdat15`, `xpat10`, `xpdat10`, etc.) — but that
  dictionary page **has no rune, item, or summoner-spell columns at all**, suggesting OE
  has never covered loadout/build detail. Current-year additions (void grubs, Atakhan,
  20/25-min snapshots) are reported by community users but could not be independently
  confirmed today. **[Med-High]**
- **Leaguepedia's Cargo API is fully live** and was queried directly today. It is the
  only source confirmed to carry **exact pick/ban draft order** (`Team1Pick1..5`,
  `Team1Ban1..5`, `Team1PicksByRoleOrder`, a `Phase` field, and `SwitchedSides`), full
  **runes** (`KeystoneRune`, `PrimaryTree`, `SecondaryTree`, plus a free-text `Runes`
  field), exact **patch** (`Patch`/`LegacyPatch`/`PatchSort`), and **player
  role/position** (`Role`, `IngameRole`, `Side`) — going back to Season 7 (2017) for the
  structured pick/ban table. It does **not** carry gold/XP timeline frames — only
  end-of-game totals. Its crosswalk tables also now carry a `GridSeriesId` field,
  confirming the wiki has adapted to Riot/GRID's exclusive data partnership by
  cross-referencing GRID's official series IDs rather than being cut off by it.
  **[High]**
- `leaguepedia_parser` (the most commonly cited Python client) **was archived
  November 22, 2023 and is unmaintained**; build directly against the Cargo
  `action=cargoquery` / `action=cargofields` HTTP API instead, or use the lower-level
  `mwrogue`/`mwcleric` client libraries, which appear to still be current. **[High]**
- **gol.gg is the only community source confirmed to expose per-player rune trees,
  item-build timing, and a per-game gold/lead timeline graph together on one page**
  (verified today on a live 2026 LEC game page: `/page-game/`, `/page-timeline/`,
  `/page-builds/`). It has no documented public API or written terms of service; its
  `robots.txt` blocks only admin paths and known SEO/AI bots, and does not blanket-forbid
  crawling the stats pages — but there is no formal grant of reuse rights either.
  **[High on structure, Low on legal terms]**
- `acs.leagueoflegends.com` (the old match-history API) **is confirmed fully dead**: the
  League Web Match History site was taken offline September 7, 2021, ACS itself stopped
  ingesting new data and went read-only after September 13, 2021, and a direct request
  to it today returned no connection at all. **[High]**
- **GRID is now the sole official Riot esports-data partner**, and this is a fast-moving
  2025 story: Bayes Esports (the *original* 2020-2022 official partner) had its Riot
  agreement end in 2024, entered insolvency in 2025, and **GRID acquired Bayes's IP
  assets in September 2025** — Bayes no longer exists as an independent access path (see
  `02-live-official-feeds.md` §2.3 for full sourcing). GRID's free "Open Access" tier
  explicitly does **not** include League of Legends (CS2/Dota2 only as of today); its
  branded "League of Legends Data Portal" markets live/current-game data and is not
  confirmed to be a self-serve historical bulk-download product for outside developers.
  **[High]**
- **dpm.lol / rft.gg are downstream consumers, not primary sources**: rft.gg states its
  esports content is "provided courtesy of Leaguepedia and PandaScore" under
  CC-BY-SA 3.0 — i.e., it re-serves Leaguepedia data rather than independently sourcing
  it. Not a priority ingestion target. **[Med]**
- **Kaggle datasets are just re-hosted snapshots of Oracle's Elixir CSVs** (multiple,
  inconsistently updated) — convenient for offline prototyping, not a real pipeline
  input. **[High]**
- **LPL/LDL is confirmed the structurally weakest region across every source**, for a
  concrete reason (LPL runs on Tencent-operated China infrastructure outside Riot's
  global match/acs system) and a concrete 2026 example (Oracle's Elixir's ~2-week LPL/LDL
  outage above, with the maintainer explicitly declining to guarantee backfill of
  advanced stats for prior years). Plan for multi-source reconciliation and a permanent
  LPL data-quality flag rather than assuming parity with LCK/LEC. **[High]**
- **Fearless Draft is confirmed standard across all 2026 leagues** (per
  `05-league-landscape-2026.md`): champions picked in game 1 of a Bo3/Bo5 are locked for
  *both* teams for the rest of the series. This is a plausible root cause for community
  reports of "2026 draft data being wrong" in older tools that assume each game's draft
  is independent — any ingestor we build must model champion legality as a
  **series-level**, not game-level, state machine. **[Med — causal link is our inference,
  not a confirmed statement from any single source]**

---

## 2. Detailed Findings

### 2.1 Oracle's Elixir

**Status in 2026: active, single-maintainer, currently unstable at the edges.**

Tim "Magic" Sevenhuysen still personally runs Oracle's Elixir. Three dated, primary
blog posts fetched directly today (all from `lol.timsevenhuysen.com`, the WordPress
front end of the site) establish the current operational state:

- **"Malicious OE DNS Takeover"** (April 14, 2026): "On April 13, the *Oracle's Elixir*
  domain nameservers settings were compromised for a few hours, and the hacker replaced
  the website with a phishing page that told visitors to download a file. This file most
  likely contained a trojan horse virus. ... The issue with the website has been
  resolved." Source:
  [lol.timsevenhuysen.com/2026/04/malicious-oe-dns-takeover](https://lol.timsevenhuysen.com/2026/04/malicious-oe-dns-takeover/)
  (fetched 2026-08-21). **[High]** — **Practical implication:** never execute a
  downloaded file from this domain; only ever consume the `.csv`/`.xlsx` data files, and
  be alert to future domain-hijack risk given it has happened once already this year.
- **"LPL Data Availability"** (July 27, 2026): "Due to issues / changes with the source
  that I use for Chinese LoL esports data, there is currently no data coming in for LPL
  (or LDL). I'm hoping this is a temporary outage... I can't make any guarantees about
  what I'll be able to do, or on what timeline." Source:
  [lol.timsevenhuysen.com/2026/07/lpl-data-availability](https://lol.timsevenhuysen.com/2026/07/lpl-data-availability/)
  (fetched 2026-08-21). **[High]**
- **"LPL Data is Back and Better"** (August 11, 2026 — ten days before this research):
  "LPL data should all be available for 2026 now, and it should now include full stats,
  like early-game rating etc. I might be able to backfill some of those more complex
  stats for a couple of previous years, but no guarantee." Source:
  [lol.timsevenhuysen.com/2026/08/lpl-data-is-back-and-better](https://lol.timsevenhuysen.com/2026/08/lpl-data-is-back-and-better/)
  (fetched 2026-08-21). **[High]**

This means: **as of today, LPL/LDL 2026 data should be complete going forward, but
backfilled advanced stats for older LPL years are explicitly not guaranteed** by the
maintainer himself.

**Downloads and schema.** `oracleselixir.com/tools/downloads` is a React single-page app
behind Cloudflare (confirmed by fetching it and receiving only the JS-app shell plus a
Cloudflare challenge stub); it cannot be scraped with a plain HTTP client. A community
project's 2022-era link
([jadenoca/LolEsportsData](https://github.com/jadenoca/LolEsportsData), accessed
2026-08-21) shows the historical S3 URL pattern
(`oracleselixir-downloadable-match-data.s3-us-west-2.amazonaws.com/<year>_LoL_esports_match_data_from_OraclesElixir_<date>.csv`);
requesting that bucket directly today returns `NoSuchBucket` — **the old bucket is gone,
do not hardcode it**. Multiple secondary sources (GitHub repos, Kaggle dataset pages,
course project write-ups) consistently describe the live product as **one CSV per
calendar year, covering 2014-present, updated daily, ~12 rows per game (5 players + 1
team row per side)**, with well-known column names including `gameid`, `datacompleteness`,
`url`, `league`, `year`, `split`, `playoffs`, `date`, `patch`, `participantid`, `side`,
`position`, `playername`, `playerid`, `teamname`, `teamid`, `champion`, `ban1`-`ban5`,
`gamelength`, `result`, and per-10/15-minute (and reportedly now 20/25-minute)
gold/xp/cs snapshots and diffs. **[Med — consistent across many secondary sources, not
independently re-verified against the live app today]**. A prior WebSearch summary
(not independently verified against a primary source) claimed "new fields for picks 1-5"
were recently added and that "void grub" and drake-soul columns exist; **[Low — could
not confirm directly]**.

A **separate, older, static archive** at `lol.timsevenhuysen.com/matchdata/` **was**
fetched successfully and read in full. It lists per-split downloads only through
**2020** (2016 Complete, 2017 Complete, 2018/2019/2020 Spring/Summer/Worlds), served via
a WordPress "Download Monitor" plugin, with a notice: *"NOTICE: The match download file
structure has changed as of April 13, 2020."* Files before 2020 are `.xlsx`; 2020 files
are `.csv`. This appears to be a frozen legacy archive superseded by the current
single-CSV-per-year app for 2021+. Source:
[lol.timsevenhuysen.com/matchdata](https://lol.timsevenhuysen.com/matchdata/) (fetched
2026-08-21). **[High]**

Its companion **Match Data Dictionary** page was also fetched and read in full — this is
the fullest primary confirmation available today of OE's schema philosophy (field names
below are exact, taken verbatim from the live page):

| Field | Meaning |
|---|---|
| `gameid`, `url`, `league`, `split`, `week`, `game`, `date` | Identifiers / scheduling |
| `patchno` | Patch number, e.g. patch 6.01 (zero-padded), patch 6.10 |
| `playerid`, `side`, `position`, `player`, `team`, `champion` | Roster/position/champion |
| `ban1`...`ban5` | **Team's bans, in order** |
| `gamelength`, `result`, `k`/`d`/`a`, `teamkills`, `teamdeaths`, `doubles`...`pentas` | Core boxscore |
| `fb`, `fbassist`, `fbvictim`, `fbtime` | First blood (kill/assist/victim/time) |
| `fd`, `fdtime`, `teamdragkills`, `oppdragkills`, `elementals`, `firedrakes`, `waterdrakes`, `earthdrakes`, `airdrakes`, `elders`, `oppelders` | Dragon detail incl. elemental types |
| `herald`, `heraldtime`, `ft`, `fttime`, `firstmidouter`, `firsttothreetowers`, `teamtowerkills`, `opptowerkills`, `fbaron`, `fbarontime`, `teambaronkills`, `oppbaronkills` | Herald/tower/baron |
| `dmgtochamps`, `dmgtochampsperminute`, `dmgshare` | Damage |
| `wards`, `wpm`, `wardshare`, `wardkills`, `wcpm`, `visionwards`, `visionwardbuys`, `visiblewardclearrate`, `invisiblewardclearrate` | Vision |
| `totalgold`, `earnedgpm`, `earnedgoldshare`, `goldspent`, `gspd` | Economy |
| `minionkills`, `monsterkills` (+ own/enemy jungle split), `cspm`, `cssharepost15` | Farm |
| `csat10`/`oppcsat10`/`csdat10`, `goldat10`/`oppgoldat10`/`gdat10`, `goldat15`/`oppgoldat15`/`gdat15`, `xpat10`/`oppxpat10`/`xpdat10` | **10/15-min snapshots and diffs** (table as fetched cuts off at `xpdat10`; a full 15-min XP diff and any 20/25-min columns almost certainly exist in the current live schema per community usage, but were not visible on this static page) |

Source:
[lol.timsevenhuysen.com/matchdata/match-data-dictionary](https://lol.timsevenhuysen.com/matchdata/match-data-dictionary/)
(fetched in full 2026-08-21). **[High for what's shown; Med for completeness relative to
the current live app]**. Notably **absent from this dictionary**: any rune, keystone,
item, trinket, or summoner-spell field. OE appears to be, and always to have been, a
*stats/objectives/economy* dataset, not a build/loadout dataset.

**Licensing.** No formal license or ToS document was found. The landing page states:
*"All data has been aggregated and released by Tim 'Magic' Sevenhuysen of
OraclesElixir.com. It is provided free of charge, and is intended for use by analysts,
commentators, and fans."* Contact is an email (`tsevenhuysen@oracleselixir.com`) and a
Discord server. **[High — this is the complete extent of the license grant found; treat
as an informal permissive grant, not a legal license]**.

**Provenance / GRID relationship.** Tim Sevenhuysen joined GRID as **Senior Business
Data Consultant** (reported March 2024), and Oracle's Elixir's **VALORANT** stats
expansion (August 2024) is explicitly described as "powered by GRID." Source:
[esportsinsider.com/2024/08/oracles-elixir-tool-valorant-grid](https://esportsinsider.com/2024/08/oracles-elixir-tool-valorant-grid)
(fetched in full 2026-08-21). **We found no explicit statement that OE's core LoL
pipeline is itself sourced from GRID's official feed** — the July 2026 LPL outage post's
wording ("the source that I use for Chinese esports data") implies OE still runs its own
patchwork of regional data sources rather than a single unified official feed. **[Med]**

Leagues covered per the site's own copy: *"LCS, LEC, LCK, LPL, PCS, CBLoL, TCL, and
more."* Note this predates the 2026 LTA-to-LCS/CBLOL reversal (see
`05-league-landscape-2026.md`); expect the `league` field to show `LTA` for exactly the
2025 season and `LCS`/`CBLOL` again from 2026 onward — an ingestor must not assume a
static league-name enum.

### 2.2 Leaguepedia (lol.fandom.com) Cargo API

**Status in 2026: fully live.** All endpoints below were queried live today via
`https://lol.fandom.com/api.php?action=cargofields&table=<Table>&format=json` and
returned current schema JSON (not from any cache or secondary source).

**Full cargo table list** (85 tables total; esports-relevant highlights):
`ScoreboardGames`, `ScoreboardPlayers`, `ScoreboardTeams`, `PicksAndBansS7`,
`PicksAndBansCounters`, `MatchSchedule`, `MatchScheduleGame`, `PostgameJsonMetadata`,
`Tournaments`, `TournamentRosters`, `TournamentPlayers`, `Players`, `Teams`,
`RosterChanges`, `Standings`. Source: live `action=cargotables` call, 2026-08-21.
**[High]**

Key fields confirmed by direct query today:

- **`ScoreboardGames`** (one row per game): `Team1`/`Team2`, `WinTeam`/`LossTeam`,
  `Team1Bans`/`Team2Bans` and `Team1Picks`/`Team2Picks` (comma-delimited ordered lists),
  full dragon-type breakdown (`Team1Clouds`, `Infernals`, `Mountains`, `Oceans`,
  `Hextechs`, `Chemtechs`, `Elders`), `Team1Barons`, `Team1Towers`, `Team1RiftHeralds`,
  **`Team1VoidGrubs`** and **`Team1Atakhans`** (confirming the schema is current through
  the 2024 Void Grubs and 2025 Atakhan objective additions), `Team1Inhibitors`,
  `Team1Gold`/`Team2Gold` (end-game totals, **not** a timeline), `Patch`/`LegacyPatch`/
  `PatchSort`, and a Riot crosswalk (`RiotPlatformGameId`, `RiotHash`, `RiotVersion`).
  **No gold/kills/xp-at-N-minutes fields exist here** — Leaguepedia's boxscore table is
  end-of-game only.
- **`ScoreboardPlayers`** (one row per player per game): `Champion`, `Kills`/`Deaths`/
  `Assists`, `SummonerSpells`, `Gold`, `CS`, `DamageToChampions`, `VisionScore`, `Items`
  (semicolon-delimited final build), `Trinket`, `Pentakills`, **`KeystoneMastery`**
  (legacy pre-rework), **`KeystoneRune`**, **`PrimaryTree`**, **`SecondaryTree`**, a
  free-text **`Runes`** field, and **`Role`**, `Role_Number`, `IngameRole`, `Side`. Runes
  and role/position are both directly confirmed present.
- **`PicksAndBansS7`** (one row per game, season-7-schema draft table): explicit
  per-slot fields **`Team1Pick1`...`Team1Pick5`**, **`Team1Ban1`...`Team1Ban5`** (and
  the Team2 equivalents), `Team1PicksByRoleOrder`/`Team2PicksByRoleOrder`, a `Phase`
  field, `SwitchedSides` (boolean), `IsComplete`/`IsFilled`. **This is the only source in
  this research confirmed to carry exact, per-slot pick/ban draft order.**
- **`MatchSchedule`** / **`MatchScheduleGame`**: series- and game-level crosswalk,
  including VOD links, MVP, forfeit/remake flags, and — notably — a **`GridSeriesId`**
  field, confirming Leaguepedia now cross-references GRID's official series IDs.
- **`PostgameJsonMetadata`**: a thin per-game table with `RiotPlatformGameId`,
  `StatsPage`, and **`TimelinePage`** pointers. The existence of a `TimelinePage` concept
  is confirmed; whether it is populated with structured timeline data for a meaningful
  fraction of games was **not** verified today (see Open Questions).
- **`Tournaments`**: `League`, `Region`, `Prizepool`, `Currency`, date fields,
  `TournamentLevel`, `IsQualifier`/`IsPlayoffs`/`IsOfficial`, `Year`.
- **`Players`**: bio/social fields including direct cross-links to `DPMLOL`,
  `Lolpros`, `SoloqueueIds` — useful for building the player-identity crosswalk our
  player-history database will need.

**Client libraries.** `leaguepedia_parser` (mrtolkien) — **archived November 22, 2023**,
read-only on GitHub, last PyPI release 2.0.2 (June 2023). **Do not build on it.**
`mwrogue`/`mwcleric` (RheingoldRiver, with a `Leaguepedia`-org fork) is a lower-level
MediaWiki/Cargo client and appears to be the currently-used foundation for Leaguepedia's
own tooling; a third option, `poro` (pacexy), also exists. Given all wrapper libraries
are thin and/or stale, **the most robust approach is a direct client against
`action=cargoquery`/`action=cargofields`**, which we confirmed works with a plain HTTP
GET and no authentication. **[High]**

**Rate limits / query limits / ToS.** Leaguepedia's `robots.txt` (fetched today)
explicitly `Allow`s `/api.php` for all user-agents while blocking several SEO/AI
crawlers (`GPTBot`, `CCBot`, `OAI-SearchBot`, `SemrushBot`, etc.) from general wiki-page
crawling — i.e., **API access is sanctioned, bulk page-scraping is not**. A Wikimedia
mailing-list thread indicates unauthenticated Cargo queries are informally limited to
**around 1 request/minute**, and the Cargo extension's documented query cap is
**500 rows per request, default 50, with `offset`-based pagination**. **[Med — community
source, not an official rate-limit policy page]**. As a Fandom-hosted wiki, content is
under Fandom's standard **CC BY-SA** license (Fandom platform-wide default); this was
not re-verified against Leaguepedia's specific ToS page today but is a very
well-established, unlikely-to-have-changed fact. **[Med-High]**

**Official sanctioning.** A 2022 Riot/lolesports dev diary (cited independently in
`02-live-official-feeds.md`) states Bayes's original LoL Esports Data Portal was built
for "professional teams, Riot partners, and — eventually — community consumers like
Leaguepedia and Oracle's Elixir" — i.e., both of this document's two central community
sources have (or had) a semi-official data relationship, not a purely scraped one.
Source: [lolesports.com dev diary](https://lolesports.com/en-US/news/dev-diary-introducing-the-new-lol-esports-data-portal)
(article dated 2022-06-10, fetched 2026-08-21). **[High]**

### 2.3 gol.gg (Games of Legends)

Fetched live today: the site's esports home, and a full LEC 2026 game page (game/stats
ID 81487). Per-game pages are organized into tabs identified by URL suffix:
`/page-game/` (main boxscore), `/page-timeline/` (a gold/lead-over-time graph — real
timeline data, not just end totals), and `/page-builds/` (item build order and timing).
The game page HTML directly embeds **rune icons keyed to Riot's numeric perk IDs**
(`.../_img/perkstyle/8008.png` etc.) for full keystone + tree display per player —
**gol.gg is confirmed to expose per-player pro-game runes**, which neither Oracle's
Elixir (no rune fields at all) nor Leaguepedia (only a semi-structured text/keystone
field) present as cleanly. **[High]**

`robots.txt` (fetched today) blocks admin/user/ranking/summoner-lookup paths and a list
of specific bots (`DataForSeoBot`, `MJ12bot`, `SemrushBot`, `AhrefsBot`, `Amazonbot`,
etc.), with a 30-second crawl-delay for a few others (`Yandex`, `PetalBot`) — **it does
not blanket-disallow generic crawling of the game/stats pages**, and no separate public
API or written terms-of-service document was located. **[High on the technical facts,
Low on any legal reuse guarantee — silence is not permission]**. Community practice
(widely visible on GitHub) is to scrape gol.gg specifically for the runes/build detail
that other sources lack; treat this as an accepted-in-practice but legally unconfirmed
norm.

### 2.4 Other sources

- **dpm.lol / rft.gg**: dpm.lol is primarily a solo-queue tracker / pro-builds /
  tier-list site; rft.gg is its esports-specific spin-off. rft.gg's own footer states its
  content is *"provided courtesy of Leaguepedia and PandaScore"* under CC-BY-SA 3.0 —
  i.e., **it is a downstream re-packaging of Leaguepedia (plus PandaScore, a commercial
  paid esports-odds API), not an independent primary source.** Not a priority ingestion
  target; `06-static-and-soloq-data.md` covers dpm.lol's solo-queue-tracking role in
  depth. **[Med]**
- **GRID / GRID Open Access**: GRID is now Riot's sole exclusive official esports-data
  partner. Per `02-live-official-feeds.md` (independently sourced today from
  esports.net, SBC News, and European Gaming, all dated September 2025): Bayes Esports's
  Riot agreement — the *original* official arrangement, announced June 2022 — ended in
  2024, Bayes entered insolvency in 2025, and **GRID acquired Bayes's IP assets in
  September 2025**. GRID's free "Open Access" historical-data program (`grid.gg/open-access`,
  fetched today) covers **CS2 and Dota 2 only** — no League of Legends. GRID's
  LoL-branded page (`grid.gg/get-league-of-legends`, fetched today) markets itself as
  *"the exclusive source of official esports data"* for live data, match history, and
  current-game-state analysis, "powered by GRID Esports," but does not present a visible
  self-serve historical bulk-download product for outside/non-commercial developers as
  of today. **[High, cross-confirmed with 02-live-official-feeds.md]**
- **Bayes Esports**: no longer operates as an independent LoL esports-data company (see
  above). **[High]**
- **Kaggle**: several datasets (e.g. "League of Legends - 2024 Competitive Game
  dataset," "LoL E-sports 2022") are community re-uploads of Oracle's Elixir's CSVs.
  Useful only as an offline/versioned snapshot for prototyping; not a live pipeline
  input, and update cadence is whatever the uploader chose to do. **[High]**
- **PandaScore**: a commercial, paid, live-odds-oriented esports data API (surfaced here
  only via rft.gg's attribution). Not evaluated in depth — flagged as a possible
  commercial fallback if GRID access is unavailable/too expensive, not a research
  priority. **[Low — not independently investigated]**
- **acs.leagueoflegends.com**: **confirmed dead.** The League (web) Match History site
  was permanently taken offline **September 7, 2021**; ACS itself stopped ingesting new
  match data and became read-only after **September 13, 2021**, with developers directed
  to Riot's `match-v5` API (which itself does not cover pro/tournament-realm games).
  Source: official Riot devtracker post
  ["Turning Off Web Match History"](https://devtrackers.gg/leagueoflegends/p/571444a8-turning-off-web-match-history)
  and [leagueoflegends.com news post](https://www.leagueoflegends.com/en-gb/news/game-updates/turning-off-web-match-history/)
  (accessed 2026-08-21). A direct request to `acs.leagueoflegends.com` made today
  returned no connection at all. **[High]**
- **dpm.lol pro coverage / GRID's live unofficial API**: see `02-live-official-feeds.md`
  for the still-functional unofficial `esports-api.lolesports.com` /
  `feed.lolesports.com` endpoints, which that document confirms **also serve historical
  game windows for completed games months old** — a potentially important secondary
  source for frame-level timeline data this document's sources mostly lack. Not
  re-verified independently here; flagged for our ingestor design (§3).

### 2.5 Coverage matrix

| Source | Exact pick/ban order | Runes (pro games) | Gold/XP timeline or frames | Exact patch | Player position/role |
|---|---|---|---|---|---|
| **Oracle's Elixir** | Bans: yes, ordered (`ban1`-`ban5`). Picks: champion-per-player only, no explicit interleaved order. | **No** — no rune/item fields found in the schema | **Snapshots only**, not full frames: diffs at 10/15 min (`gdat10`, `gdat15`, `xpdat10`, ...); reportedly 20/25 min too (unconfirmed) | Yes (`patchno`) | Yes (`position`) |
| **Leaguepedia (Cargo)** | **Yes — full per-slot order** (`Team1Pick1..5`, `Team1Ban1..5`, `Phase`) | **Yes** (`KeystoneRune`, `PrimaryTree`, `SecondaryTree`, `Runes` text) | **No** — `ScoreboardGames` is end-of-game totals only; a `TimelinePage` pointer exists but population is unconfirmed | Yes (`Patch`, `LegacyPatch`, `PatchSort`) | Yes (`Role`, `IngameRole`, `Side`) |
| **gol.gg** | Bans shown in occurrence order on-page (Med confidence on machine-readability); full interleaved pick order not confirmed | **Yes**, confirmed via perk-ID-keyed images per player | **Yes** — dedicated `/page-timeline/` gold/lead graph per game | Yes (standard page header, not independently grepped today) | Yes (standard boxscore layout) |
| **GRID / official LDP** | Unknown — commercial-gated, not evaluated first-hand | Unknown | Likely yes (official feed) — see `02-live-official-feeds.md` | Yes (official feed) | Yes (official feed) |
| **Kaggle mirrors** | Same as whichever OE snapshot was uploaded, often stale | No | Same as OE (10/15-min snapshots) | Yes | Yes |

---

## 3. Recommendations for rift-quant

1. **Build the Leaguepedia Cargo ingestor first.** It is free, live, officially
   sanctioned (robots.txt explicitly allows `/api.php`), requires no scraping, and is
   the *only* source confirmed to carry exact draft order, runes, and role together with
   full season history back to 2017 (and boxscore-only further back). Write a thin
   direct HTTP client against `action=cargoquery` (do not depend on the archived
   `leaguepedia_parser`); paginate with `limit=500`/`offset`; throttle to roughly
   1 req/sec-to-1 req/min pending empirical testing of actual limits, with exponential
   backoff. This becomes the backbone table for draft-phase features (exact pick/ban
   order) and the player/role crosswalk.
2. **Layer in Oracle's Elixir for the derived 10/15-minute (and later) snapshot stats**
   Leaguepedia's Cargo tables don't carry. Because the live download UI is an
   unscriptable React/Cloudflare app, this cannot be a fully unattended nightly cron on
   day one: either (a) budget a small engineering spike to capture the SPA's actual
   backend XHR calls (browser devtools/network tab) and confirm the current schema
   before automating, or (b) start with a **manual/scheduled-human-download** step for
   each year's CSV, landing it in our own storage, until (a) is done. Treat OE as
   best-effort, single-maintainer infrastructure — cross-check its `gameid`/date/teams
   against Leaguepedia before trusting a row, and never execute anything from the domain
   beyond parsing the CSV/XLSX text (see the April 2026 DNS-hijack incident).
3. **Add gol.gg as a targeted, low-volume enrichment scraper**, specifically for runes
   and item-build timing that OE lacks entirely and Leaguepedia only partially
   structures. Keep this scoped and polite (its own robots.txt permits crawling the
   relevant paths but there's no license grant), cache aggressively, and treat it as
   optional enrichment rather than a backbone — if it disappears or blocks us, the
   project should degrade gracefully, not break.
4. **Use Kaggle mirrors only for offline prototyping** of the modeling pipeline before
   the real ingestors exist — never wire them into production given unknown/irregular
   update cadence.
5. **Treat GRID as a parallel commercial-track conversation, not a near-term ingestion
   target for historical data.** Its free tier excludes LoL entirely today, and its
   LoL Data Portal reads as commercial/partner-oriented rather than self-serve. Worth a
   direct outreach to GRID sales in parallel with the above (especially given it's now
   the *sole* official channel post-Bayes), both for eventual low-latency live data
   (see `02-live-official-feeds.md`) and to ask directly whether any non-commercial
   historical bulk-data tier exists that isn't visible on the public marketing site.
6. **Design the draft/champion-pool schema around series-level state, not per-game
   state, from day one.** Fearless Draft (confirmed standard across all 2026 leagues per
   `05-league-landscape-2026.md`) makes a champion's availability depend on what was
   picked earlier in the *series*, not just the current game. Both our own feature
   pipeline and our validation of any ingested draft data (from Leaguepedia or OE) need
   to account for this, and it is a plausible explanation for community reports of
   "incorrect 2026 draft data" in tools not yet updated for the rule.
7. **Build a cross-source reconciliation/QA layer immediately, prioritized on LPL.**
   Given (a) OE's demonstrated multi-week LPL/LDL outage this year, (b) the DNS-hijack
   incident, and (c) LPL's structurally separate infrastructure, do not single-source
   any region — cross-check `gameid`/date/team/patch across at least Leaguepedia + OE
   before trusting a row, with LPL/LDL rows flagged for a stricter/second check (e.g.
   against gol.gg) given the demonstrated fragility.

---

## 4. Open Questions / Risks

- **Oracle's Elixir's current live CSV schema (2021-2026) was not directly verified.**
  The React/Cloudflare app could not be scripted; everything on the modern schema beyond
  what the legacy static dictionary shows (e.g., void grubs, Atakhan, pick1-5, 20/25-min
  snapshots) rests on secondary/community sources. **Action:** do a one-time manual
  browser session, download a current-year file, and diff its header row against the
  legacy dictionary before building any parser.
- **The specific claim that "some 2026 games have incorrect draft/champion-select data"
  on Oracle's Elixir could not be traced to a primary source** despite a direct search of
  the site's own blog archive. It may be a real, narrower issue than the search summary
  implied, may already be fixed, or may be a misread of unrelated content. Our best
  guess — a Fearless Draft series-state modeling gap — is our own inference, not a
  confirmed root cause. **Action:** verify directly against a freshly downloaded 2026
  file rather than trusting either claim.
- **Leaguepedia's `TimelinePage` field's actual population rate is unknown.** We
  confirmed the field exists in the schema but did not sample real GameIds to see what
  fraction resolve to populated, structured timeline data (as opposed to an empty or
  dead link). **Action:** sample ~100-500 recent and older GameIds before assuming this
  is a usable timeline source.
- **Leaguepedia's rate limits (~1 req/min, 500 rows/request) come from a community
  mailing-list thread and the Cargo extension's general documented defaults, not an
  official current policy statement.** **Action:** test empirically with backoff before
  committing to a bulk historical crawl of the full match history (tens of thousands of
  games).
- **gol.gg has no discoverable formal terms of service or API.** Scraping is technically
  unblocked today (per robots.txt) and is common practice, but there is no contractual
  guarantee this continues, and no official rate-limit guidance exists. Build with a
  graceful-degradation fallback if access changes or is revoked.
- **GRID's actual 2026 non-commercial/community terms for LoL are unclear beyond
  marketing copy** ("await the rollout"). This is the single highest-leverage unknown
  for the project's long-term data strategy, since GRID is now the only official channel
  post-Bayes-insolvency. **Action:** direct outreach to GRID, not further web research.
- **Pre-~2021 LPL data quality is a shared weak point across every source**, not just
  Oracle's Elixir — LPL's Tencent-operated infrastructure sat outside Riot's global
  acs/match-v5 system for most of its history, so all community tools ultimately trace
  early LPL rows back to a small number of original manual-entry/scraping efforts.
  Treat early-year LPL rows (and LDL at any point) as lower-confidence than
  LCK/LEC/NA-of-the-same-vintage regardless of which source supplies them, and budget
  for manual spot-checking rather than assuming automated parity.
- **China Super Server solo queue (LPL players' practice-account data) has no
  identified public data path at all** (cross-confirmed with `06-static-and-soloq-data.md`),
  which will limit the player-bias-profile side of the project specifically for LPL
  players, separate from the pro-match-history gaps discussed above.
