# Professional League of Legends Competitive Landscape — 2026 Season

Research date: 2026-08-21. All web sources accessed 2026-08-21 unless noted. Today falls inside the LCK Rounds 3-4 / LEC Summer / LCS Summer window, after First Stand 2026 and MSI 2026 have concluded, and before Worlds 2026 (Oct 15-Nov 14, 2026) has started.

Confidence key: **High** = corroborated by 2+ independent sources incl. Wikipedia/official/primary; **Med** = corroborated by secondary sources or a single strong source; **Low** = single weak/unclear source, flagged for verification.

---

## 1. Executive Summary

- The **LTA (League of Legends Championship of the Americas)** — the 2025 merger of LCS + CBLOL + LLA into one 16-team, two-conference (North/South) league — was **dissolved after a single season**. **LCS and CBLOL returned as fully independent leagues for 2026**; LLA does not return standalone, its teams/players folded into LCS/CBLOL via partner and guest slots (LYON in LCS; Leviatán and LOS in CBLOL). **High confidence.**
- 2026 top-tier league sizes: **LCK 10 teams, LPL 14 teams (12 in Split 3), LEC 10 teams (12 in the Versus opening split), LCS 8 teams, CBLOL 8 teams, LCP 8 teams.** All run **3 splits/stages per year** and use **Bo3 for regular season, Bo5 for playoffs** (LEC Versus and any Bo1-round-robin stage being the notable exception at Bo1). **High confidence.**
- **Fearless Draft ("Full/Hard Fearless") is confirmed standard for the 2026 season** across LCK, LPL, LEC, LCS, CBLOL, LCP, First Stand, MSI, and Worlds — Riot confirmed continuation on the Worlds 2025 broadcast. Rule: once either team plays a champion in a Bo3/Bo5 **series**, it is locked for **both** teams for the rest of that series (cumulative per game). **High confidence.**
- Fearless Draft applies **only within a single Bo3/Bo5 series** — it does **not** carry over across a round-robin stage or between series. **Bo1 matches/stages (e.g., LEC Versus regular season, Worlds Swiss-stage games) draft normally** with no champion lockout, since a Bo1 is a one-game "series." A discredited "Soft Fearless" variant (lockout only for the picking team) was an early LPL experiment, not used at tier-1 level since the 2025 standardization. **High confidence** on the hard-fearless standard and per-series scope; **Med** on precisely dismissing all Bo1-carryover claims (one low-quality secondary snippet suggested otherwise for LEC Versus; multiple higher-quality sources contradict it).
- **New for 2026: "Right of First Selection"** decouples side choice (Blue/Red) from draft-order priority (pick first/second) — previously bundled as one advantage tied to seeding/coin flip. The team with priority picks either side-choice or draft-order; the opponent gets the other. This changes what "blue side" correlates with statistically starting in 2026. **High confidence.**
- **Atakhan and Feats of Strength were removed entirely from the game** as of Patch 26.1 (start of 2026 season) to reduce "objective fatigue." Void Grubs' gold was restructured (all-local reward, no global share) and epic monsters became 15% more durable; Baron's spawn timer reverted to 20 minutes. **High confidence.**
- **Patch naming changed**: 2026 uses simple sequential `YY.NN` numbering (e.g., **26.01, 26.13, 26.16**) on a locked **biweekly** cadence, superseding the split-qualified scheme used in 2025. **High confidence on 2026 scheme; Med confidence on exact 2025 predecessor naming** (not independently re-confirmed this session; consistent with the premise in our own research brief and general knowledge).
- As of today (2026-08-21), **pro play (LCK Rounds 3-4, LEC Summer) runs on Patch 26.13 while the live client is on Patch 26.16** — a **3-patch / ~6-week gap**, consistent with the standard practice of locking a patch per split/stage for competitive stability while live servers keep patching biweekly. **High confidence on the observed gap; Med on generalizing it as "typical."**
- International 2026 results so far: **First Stand 2026** (Mar 16-22, São Paulo) won by **Bilibili Gaming (LPL)** over G2 Esports 3-1; **MSI 2026** (Jun 28-Jul 12, Daejeon, South Korea) won by **Hanwha Life Esports (LCK)** over Bilibili Gaming 3-2. **Worlds 2026** (Oct 15-Nov 14: LA -> Allen, TX -> Brooklyn, NYC) has **not yet happened** — 19 teams, slots driven partly by MSI 2026 results (LCK and LPL each get a 4th bonus Worlds slot from winning/runner-up at MSI). **High confidence.**
- Ground-truth historical results for pipeline validation: **Worlds 2025** (Chengdu, China; final Nov 9, 2025) won by **T1** over KT Rolster 3-2 — T1's 6th world title and 3rd consecutive (three-peat), MVP Gumayusi. **MSI 2025** won by **Gen.G** over T1 3-2 (Gen.G's 2nd straight MSI). **High confidence.**
- **Leaguepedia (lol.fandom.com)** is the community-canonical, machine-queryable source for rosters, roster changes, and match/scoreboard data, via its **Cargo tables** (Teams, Players, ScoreboardGames, Tournaments, Roster Swaps, etc.), reachable through the MediaWiki+Cargo query API and wrapper libraries (Python `mwclient`-based tools, JS `poro`, R `rlolesports`). **Liquipedia** mirrors similar structured data independently. **High confidence** the tables exist and are the community standard; **note:** our WebFetch tooling could not directly load lol.fandom.com pages this session (HTTP 402 from the fetch proxy) — verify direct/API reachability from the project's own infrastructure before depending on it.
- The de-facto standard **schedule API** is Riot's `esports-api.lolesports.com/persisted/gw/{getLeagues,getSchedule}` (long-standing public shared key), which backs lolesports.com itself and covers every active league plus Worlds/MSI/First Stand with match state, best-of format, scores and VOD links. **High confidence** it still functions and includes Worlds 2026 (per current 2026-dated wrapper docs), though it is an unofficial/reverse-engineered integration, not a documented Riot product — treat as **Med confidence for long-term stability**.
- **Priority-league regular-season volume is large but uneven by format complexity**: LEC and LCS have clean single-round-robin splits (LEC: 45 Bo3 series/split + 66 Bo1 in Versus; LCS: 28 Bo3 series/split); LCK and LPL use double-round-robin/grouped formats that are harder to hand-total (LCK Rounds 1-2 alone: 90 Bo3 series). A full-season exact game count needs to be computed from the schedule API/Leaguepedia directly — see Open Questions. **Med confidence** on the component numbers, **Low** on any single "total games/year" figure until computed programmatically.

---

## 2. Detailed Findings

### 2.1 League structure 2026

#### The LTA experiment and its reversal
The **League of Legends Championship of the Americas (LTA)** launched for the 2025 season as a merger of the LCS (North America), CBLOL (Brazil) and LLA (Latin America) into a single 16-team, two-conference structure: **LTA North** (8 teams, including 100 Thieves as a provisional guest) and **LTA South** (8 teams). It ran three splits with varying formats (double-elimination per conference in Split 1; positioning + groups + double-elim in Split 2; pick-and-play + elimination + Americas Regional Championship in Split 3). Split champions: Team Liquid (Split 1), FlyQuest (Split 2 North) / FURIA (Split 2 South), FlyQuest (LTA Championship).
[2025 LTA season – Wikipedia](https://en.wikipedia.org/wiki/2025_LTA_season) (accessed 2026-08-21)

Riot announced at the **2025 LTA Finals** that the LCS and CBLOL would return as **independent leagues in 2026**, ending the merged format after one year. Cited reasons: loss of regional identity, an overly complex/compressed calendar, a stark **North-vs-South competitive gap** (North American teams won 8 of 9 cross-conference matches), and weak viewership (the cross-conference grand final drew only ~166,000 viewers — far below historical LCS/CBLOL numbers).
[Riot bids farewell to the LTA as LCS and CBLOL return in 2026 – Esports Insider](https://esportsinsider.com/2025/09/lcs-cblol-return-riot-games-lta) (accessed 2026-08-21); [Riot Games explains why League of Legends LTA did not work – Esports News UK](https://esports-news.co.uk/2025/09/30/riot-games-explains-why-league-of-legends-lta-rebrand-did-not-work/) (accessed 2026-08-21); [2026 LCS season – Wikipedia](https://en.wikipedia.org/wiki/2026_LCS_season) (accessed 2026-08-21)

The official Riot/lolesports recap confirms: cross-regional playoffs are removed, each league runs an independent season, and **LLA does not return as a standalone league** — Latin American teams/orgs continue via Partner Team slots (**LYON** in LCS) and Guest Team slots (**Leviatán**, **LOS** in CBLOL).
[LoL Esports – "LCS and CBLOL Return" official article](https://lolesports.com/en-US/news/lcs-and-cblol-return) (accessed 2026-08-21)

#### LCK 2026 (10 teams)
Teams: **Gen.G, T1, Hanwha Life Esports, KT Rolster, Dplus KIA, BNK FearX, KIWOOM DRX, Nongshim RedForce, DN SOOPers, Hanjin Brion.**
Format:
- **Rounds 1-2** (main regular season): double round-robin, all **Bo3**, Fearless Draft. Top 6 advance to the "Road to MSI" event.
- **Rounds 3-4**: teams split into **Legend** (top 5) and **Rise** (bottom 5) groups carrying over Round 1-2 records; each group plays another double round-robin, **Bo3**. This was **shortened from an originally-planned triple round-robin to a double round-robin** specifically to free calendar space around South Korea's national-team commitments for the **2026 Asian Games**. Top 2 Legend teams go straight to playoffs round 2; 3rd-4th Legend to playoffs round 1; 5th-place Legend + top 3 Rise teams go to play-ins.
- **Playoffs**: 6 teams, full double-elimination bracket, all **Bo5**, Fearless Draft. Top 4 finishers qualify for Worlds.
[2026 LCK season – Wikipedia](https://en.wikipedia.org/wiki/2026_LCK_season) (accessed 2026-08-21); [LCK 2026 Season – Liquipedia](https://liquipedia.net/leagueoflegends/LCK/2026/Rounds_3-4) (accessed 2026-08-21); [Every confirmed LCK roster for 2026 – Esports Insider](https://esportsinsider.com/2025/11/every-confirmed-lck-roster-2026-league-of-legends) (accessed 2026-08-21)

#### LPL 2026 (14 teams in Splits 1-2, 12 in Split 3)
Teams: Anyone's Legend, Bilibili Gaming, EDward Gaming, Invictus Gaming, JD Gaming, LGD Gaming, LNG Esports, Ninjas in Pyjamas, Oh My God, Team WE, ThunderTalk Gaming, Top Esports, Ultra Prime, Weibo Gaming. **FunPlus Phoenix withdrew Jan 1, 2026** and **Royal Never Give Up confirmed full exit Jan 8, 2026**, shrinking the league from its historical count.
Format: all matches **Bo3** with Fearless Draft.
- **Split 1**: 3 groups — Ascend (6 teams), Perseverance (4), Nirvana (4) — double round-robin; top 4 Ascend teams advance directly to playoffs; a "Knights Rivals" play-in (hybrid double-elimination, **Bo5**) determines the rest; playoffs are 8 teams, double-elimination, **Bo5**.
- **Split 2**: reseeded into 2 groups (Ascend 8 teams playing double round-robin; Nirvana 6 teams playing single round-robin per one source, though exact RR type for Nirvana was inconsistently reported — **Med confidence** on Nirvana's exact round-robin type); same knights-rivals/playoffs structure.
- **Split 3**: 12 teams, reseeded into 2 groups (top 8 from Split 2 -> Ascend, next 4 -> Nirvana); playoffs **Bo5**.
[2026 LPL season – Wikipedia](https://en.wikipedia.org/wiki/2026_LPL_season) (accessed 2026-08-21); [LPL 2026 Split 1/2/3 – Liquipedia](https://liquipedia.net/leagueoflegends/LPL/2026/Split_1) (accessed 2026-08-21); [Every confirmed LPL roster for 2026 – Esports Insider](https://esportsinsider.com/2025/12/every-confirmed-lpl-league-of-legends-roster-2026) (accessed 2026-08-21)

#### LEC 2026 (10 teams; 12 in the opening Versus split)
Teams: Fnatic, G2 Esports, GIANTX, Karmine Corp, Team Vitality, Team Heretics, Shifters, Movistar KOI, SK Gaming, Natus Vincere.
- **LEC Versus** (Jan 17-Feb 8, 2026; 12 teams = the 10 above + 2 invited ERL teams; Berlin, Riot Games Arena): single round-robin, all **Bo1** (each team plays 11 games = 66 games total), then an 8-team double-elimination playoff (first rounds Bo3, later rounds Bo5). **Winner is the sole LEC representative at First Stand 2026.** Fearless Draft was reported as "in effect" for this split by one secondary source, but per the general Fearless ruleset a Bo1 stage should draft fresh each game since each match is a one-game "series" — **flagged as a discrepancy, Low-Med confidence, needs primary-source confirmation** (see Open Questions).
- **Spring & Summer splits**: 10 teams, single round-robin, all **Bo3** (9 series/team = 45 series/split); top 6 to a double-elimination playoff, all **Bo5**. Summer's top 3 playoff finishers qualify for Worlds.
- 2026 marks the **first time since 2022 that LCS and LEC run structurally identical formats** (per secondary reporting).
[2026 LEC season – Wikipedia](https://en.wikipedia.org/wiki/2026_LEC_season) (accessed 2026-08-21); [LEC 2026 Versus – Liquipedia](https://liquipedia.net/leagueoflegends/LEC/2026/Versus) (accessed 2026-08-21); [LCS and CBLOL regions are coming back in the 2026 season – esports.gg](https://esports.gg/news/league-of-legends/lcs-cblol-formats-2026-season/) (accessed 2026-08-21)

#### LCS 2026 (8 teams)
Teams: Cloud9, Dignitas, FlyQuest, Shopify Rebellion, Team Liquid, **Sentinels** (new — replaced 100 Thieves, which left after 8 years, announced Oct 10, 2025), **LYON** (LLA partner slot), **Disguised** (guest team).
Format — 3 splits:
- **Lock-In**: Swiss stage, **Bo3**, then double-elimination playoffs, **Bo5**.
- **Spring**: single round-robin, **Bo3** (regular season), double-elimination playoffs, **Bo5**. Spring finals held at Mullett Arena, Phoenix.
- **Summer**: single round-robin, **Bo3** — **28 series total** (8 teams, full round robin) — then an extended double-elimination playoff bracket, **Bo5**. Summer finals at Gas South Arena, Atlanta.
International slots: First Stand 1, MSI 2 (3 if an LCS team reaches the MSI final), Worlds 3.
[2026 LCS season – Wikipedia](https://en.wikipedia.org/wiki/2026_LCS_season) (accessed 2026-08-21); [LCS 2026: New format, road shows, bootcamps, and more – esports.gg](https://esports.gg/news/league-of-legends/lcs-2026-format-updates/) (accessed 2026-08-21); [Every confirmed LCS roster for 2026 – Esports Insider](https://esportsinsider.com/2025/12/every-confirmed-lcs-roster-2026-league-of-legends) (accessed 2026-08-21)

#### CBLOL 2026 (8 teams)
Teams: Fluxo W7M, FURIA, Keyd Stars, LOUD, paiN Gaming, RED Canids, **Leviatán** (LLA partner slot), **LOS** (guest team, promotion/relegation-eligible against Tier 2).
Format: single round-robin regular season; top 4 go directly to playoffs, bottom 4 play a knockout mini-bracket (5th-vs-6th, 7th-vs-8th, **Bo3**) for the remaining playoff spots. **CBLOL received a 2nd Worlds slot for 2026** (previously 1) — its Split 2 champion and runner-up both qualify for Worlds.
[2026 CBLOL season – Wikipedia](https://en.wikipedia.org/wiki/2026_CBLOL_season) (accessed 2026-08-21); [CBLOL Receives One Additional Slot At Worlds 2026 – Hotspawn](https://www.hotspawn.com/league-of-legends/news/cblol-receives-additional-slot-worlds-2026) (accessed 2026-08-21)

#### LCP 2026 (8 teams) — League of Legends Championship Pacific (Vietnam/Taiwan/Japan/SEA)
Teams: 3 partner teams — **CTBC Flying Oyster, GAM Esports, Fukuoka SoftBank HAWKS** — plus 5 guest teams — **Secret Whales, DetonatioN FocusMe, MVK Esports (Vietnam), Deep Cross Gaming, Ground Zero Gaming**. **PSG Talon was removed from the league in Nov 2025** for failing to meet league operating standards; Ground Zero Gaming filled the vacated slot.
Format: single round-robin regular season, **Bo3**; top 6 advance to a hybrid knockout stage (seeds 3-6 play single-elimination, winners join top-2 seeds in a double-elimination bracket), **Bo5**. Now in its 2nd season as the merged LCP.
[LCP unveils full 2026 format ahead of Split 1 – Esports Insider](https://esportsinsider.com/2026/01/lcp-unveils-full-2026-format-ahead-of-split-1) (accessed 2026-08-21); [2026 LCP season – Wikipedia](https://en.wikipedia.org/wiki/2026_LCP_season) (accessed 2026-08-21)

---

### 2.2 Fearless Draft

**Core rule (Full/Hard Fearless, the 2025-2026 standard):** In a Bo3/Bo5 series, once a champion has been played by **either** team, it becomes unavailable to **both** teams for the remainder of that series. The effect is cumulative game-on-game: by Game 5 of a Bo5, up to 40-50 champions (out of ~170 total) can be locked out league-wide for that series. Each individual game still runs a full normal draft otherwise (2 ban phases, 5 bans + 5 picks per team); the Fearless lockout is an *additional* restriction layered on top, not a replacement for the ban phase.
[LoL Fearless Draft explained – TheSpike.gg](https://www.thespike.gg/league-of-legends/beginner-guides/fearless-draft-guide) (accessed 2026-08-21); [Fearless Draft in LoL: Full vs. Soft Rules Explained – loltheory.gg](https://blog.loltheory.gg/what-is-fearless-draft/) (accessed 2026-08-21)

**Soft Fearless (historical/deprecated variant):** champion lockout applies only to the team that played it; the opponent may still pick it once before it locks for them too. This was an **early LPL experiment** prior to 2025 standardization and is **not used at tier-1 level in 2025 or 2026** — Full/Hard Fearless is now the uniform standard across LCK, LPL, LEC, LCS, CBLOL, LCP, First Stand, MSI, and Worlds. [Med-High confidence — one secondary snippet described a residual "LPL variant" that sounded soft-fearless-like, but the balance of sourcing, including the official Riot recap below, supports full/hard fearless being universal by 2025-2026; flagged for verification against LPL's own official rulebook.]
[Fearless Draft returns in the League of Legends 2026 season – Esports Insider](https://esportsinsider.com/2025/11/fearless-draft-returns-league-of-legends-2026) (accessed 2026-08-21); [What is Fearless Draft in LoL Esports? Soft vs Hard Fearless explained – esports.gg](https://esports.gg/news/league-of-legends/fearless-draft-in-lol-esports-explained/) (accessed 2026-08-21, via search snippet only — direct fetch returned HTTP 403)

**Scope — per series, not per stage:** Fearless resets between series. It does **not** persist across a round-robin group stage or across different series in a bracket. A **Bo1** is, by definition, a one-game series, so there is nothing to carry forward — Bo1 matches (Worlds Swiss-stage games, and by the general rule LEC Versus's Bo1 round robin) draft with a completely fresh, unrestricted champion pool each game.
[LoL Esports – "Fearless Draft Takes Over 2025" (official)](https://lolesports.com/en-US/news/fearless-draft-takes-over-2025) (accessed 2026-08-21); [Worlds 2025: How Fearless Draft May Decide LoL's Biggest Stage – esports.net](https://www.esports.net/wiki/tournaments/worlds-2025-fearless-draft/) (accessed 2026-08-21, via search snippet)

**Timeline:**
- **2025**: rolled out to regional leagues starting **Split 2**, then used at **MSI 2025** (all Bo5s) and **Worlds 2025** (Bo3/Bo5 stages; the 16-team Swiss stage's Bo1 round-robin portion was not fearless, consistent with the per-series rule above).
- **Worlds 2025 grand final broadcast**: Riot confirmed Fearless Draft **returns for the 2026 season**.
- **2026**: confirmed in force for LCK, LPL, LEC, LCS, CBLOL, LCP regular seasons/playoffs, **First Stand 2026** (explicitly confirmed: "As with the previous competitive season, Fearless Draft was implemented"), **MSI 2026**, and will apply at **Worlds 2026** (not yet held).
[Fearless Draft confirmed to stay throughout Season 2025 – GosuGamers](https://www.gosugamers.net/lol/news/74517-fearless-draft-confirmed-to-stay-throughout-season-2025) (accessed 2026-08-21); [T1 defeats KT Rolster to win League of Legends Worlds 2025 – Esports Insider](https://esportsinsider.com/2025/11/t1-wins-league-of-legends-lol-worlds-2025) (accessed 2026-08-21); [2026 First Stand Tournament – Wikipedia](https://en.wikipedia.org/wiki/2026_First_Stand_Tournament) (accessed 2026-08-21)

One lower-quality secondary source claimed MSI 2025 used the "original" (non-fearless) draft format — this **contradicts** multiple stronger sources (AltChar, GosuGamers, Esports Insider, Tips.gg, GGBoost) that explicitly confirm Fearless Draft at MSI 2025. We treat the majority position (**Fearless was used at MSI 2025**) as correct at **High confidence** and disregard the outlier.

**New for 2026 — "Right of First Selection":** a pre-game priority system that **decouples side selection (Blue/Red) from draft-order priority (pick first/second)**. Historically the higher seed got Blue side, which *also* carried first pick — a compounded advantage. Now, the team with priority chooses *either* side *or* draft order; the opponent receives whichever the first team didn't take. Riot's stated rationale is to further reduce structural/side advantages, following what it considered a successful Fearless Draft rollout. First Stand 2026 debuted this rule alongside an unusually **Bo5-heavy format** (every match, including group stage, was Bo5).
[League of Legends Esports' new "First Selection" explained – esports.gg](https://esports.gg/news/league-of-legends/first-selection-explained/) (accessed 2026-08-21); [League of Legends revamps esports side selection and draft order – Esports Insider](https://esportsinsider.com/2026/01/league-of-legends-side-selection-draft-order-revamp) (accessed 2026-08-21); [LoL Esports 2026 introduces new draft rule First Selection and a BO5-heavy First Stand – GosuGamers](https://www.gosugamers.net/lol/news/77812-lol-esports-2026-introduces-new-draft-rule-first-selection-and-a-bo5-heavy-first-stand) (accessed 2026-08-21)

---

### 2.3 2026 game/patch changes relevant to modeling

**Patch naming:** 2026 patches use a simplified, sequential **`YY.NN`** scheme (e.g., **Patch 26.01**, the season-opener; **26.13**, current pro-play patch as of today; **26.16**, current live-client patch) on a **locked biweekly cadence** (every 2 weeks, Wednesday or Thursday releases). This supersedes 2025's split-qualified naming convention referenced in our research brief. **High confidence on the 2026 scheme (multiple citations); Medium confidence on precisely characterizing the 2025 predecessor**, which we did not re-verify with a fresh citation this session.
[League of Legends patch schedule (2026) – Dot Esports](https://dotesports.com/league-of-legends/news/lol-patch-schedule) (accessed 2026-08-21); [Patch/2026 Annual Cycle – League of Legends Wiki](https://wiki.leagueoflegends.com/en-us/Patch/2026_Annual_Cycle) (accessed 2026-08-21)

**Objective/map changes (Patch 26.1, start of 2026 season):**
- **Atakhan removed entirely** — no longer spawns; its Blood Roses/Petals mechanic removed with it. Cited rationale: reducing "objective fatigue."
- **Feats of Strength removed.**
- **Void Grubs reworked**: gold restructured from "20 local + 50 global" (210g total for 3 grubs) to **30g local-only** (90g total for 3) — concentrating reward on the killing team rather than sharing globally; grubs' buff effects made slightly stronger.
- **All epic monsters (Dragons, Baron, Rift Herald, Void Grubs) made 15% more durable** (longer to kill, higher-risk contests).
- **Baron Nashor's spawn timer reverted to 20 minutes.**
[Atakhan, Feats of Strength removed in League of Legends 2026 – esports.gg](https://esports.gg/news/league-of-legends/atakhan-feats-of-strength-league-of-legends-2026/) (accessed 2026-08-21); [League of Legends patch 26.1 notes – Sportskeeda](https://www.sportskeeda.com/esports/league-legends-patch-26-1-notes) (accessed 2026-08-21); [League of Legends 26.1 kicks off the new year with huge changes – Esports News UK](https://esports-news.co.uk/2026/01/07/league-of-legends-patch-26-1-kicks-off-the-new-year-with-huge-changes/) (accessed 2026-08-21)

**Mid-year "Season 2" update (~April 2026, around Patch 26.9):** reintroduced two legacy keystone runes — **Deathfire Touch** (AP/AD-scaling DoT) and **Stormraider's Surge** (burst-reward movement speed, replacing Phase Rush's slot in the Sorcery tree) — plus an Arena game-mode overhaul and other client/meta changes. These are mostly relevant to solo-queue meta rather than pro play directly, but keystone rune availability affects champion viability/pick rates that feed draft-phase features.
[League of Legends Season 2 2026: Vayne story, Arena overhaul and major gameplay changes – AltChar](https://www.altchar.com/game-news/league-of-legends-season-2-2026-vayne-story-arena-overhaul-and-major-gameplay-changes-a63FS9d40pA1) (accessed 2026-08-21); [League of Legends Patch 26.9 lands with Season 2 2026 competitive changes – Esports News UK](https://esports-news.co.uk/2026/04/16/lol-patch-26-9-competitive/) (accessed 2026-08-21)

**Pro-play patch lag behind live:** As of **2026-08-21**, **LCK Rounds 3-4** and **LEC Summer** matches are being played on **Patch 26.13**, while the **live retail client has been on Patch 26.16 since Aug 12, 2026** — a **3-patch (~6-week) gap**. This is consistent with the standard industry practice of locking a single patch at the start of each split/stage for the duration of that competitive stage (for draft/balance stability and fairness), while the live client continues its normal biweekly cadence. We could not find an explicit Riot policy statement quantifying "always N patches behind" as a general rule — this is an **empirical snapshot**, not a documented policy, so treat any fixed "N patches" assumption in the model as an approximation to be re-derived per split from Leaguepedia's per-match patch field.
[Patch 26.13 – Leaguepedia (via search snippet)](https://lol.fandom.com/wiki/Patch_26.13) (accessed 2026-08-21); [League of Legends Patch 26.5 - First Stand 2026 patch analysis – esports.gg](https://esports.gg/news/league-of-legends/league-of-legends-patch-26-5-first-stand-2026-patch-analysis/) (accessed 2026-08-21)

---

### 2.4 International events

#### First Stand 2026 (completed)
- **Dates/venue**: March 16-22, 2026, Riot Games Arena, **São Paulo, Brazil** (~140-seat venue).
- **Slots (8 teams)**: LPL x2, LCK x2, LEC x1, LCS x1, CBLOL x1, LCP x1.
- **Format**: 2 GSL-style double-elimination groups (one team per region per group), top 2 per group advance; single-elimination knockout semifinals + final. **Every match was Bo5** ("Bo5-heavy" format). Debuted the "First Selection" side/draft-order rule. Fearless Draft in effect.
- **Prize pool**: $1,000,000.
- **Result**: **Bilibili Gaming (LPL) defeated G2 Esports (LEC) 3-1** in the final — the first LPL international title since the 2023 MSI.
[2026 First Stand Tournament – Wikipedia](https://en.wikipedia.org/wiki/2026_First_Stand_Tournament) (accessed 2026-08-21); [Bilibili Gaming are the 2026 League of Legends First Stand Champions – GosuGamers](https://www.gosugamers.net/lol/news/78154-g2-esports-bilibili-gaming-are-the-2026-lol-first-stand-champions) (accessed 2026-08-21)

#### MSI 2026 (completed)
- **Dates/venue**: June 28-July 12, 2026, Daejeon Convention Center II, **Daejeon, South Korea** (first LoL esports event hosted in that city). Play-In June 28-Jul 1; Bracket Stage Jul 3-12.
- **Slots (11 teams)**: LCK x2, LPL x2, LEC x2, LCS x2, LCP x2, CBLOL x1.
- **Format**: Play-In now a **4-team double-elimination Bo5 bracket** (expanded from prior years), with only **1** team advancing to the Bracket Stage. Bracket Stage: 8 teams, double-elimination, Bo5. The 7 direct bracket-stage qualifiers were the 5 regional #1 seeds + CBLOL's seed + LPL's #2 seed (which earned a bonus direct slot by winning First Stand); the remaining 4 (#2 seeds of LCK, LEC, LCS, LCP) contested the Play-In for the 8th bracket slot.
- **Prize pool**: $2,000,000 ($500k / $300k / $240k / $200k for 1st-4th).
- **Result**: **Hanwha Life Esports (LCK) defeated Bilibili Gaming (LPL) 3-2** in the final.
[2026 Mid-Season Invitational – Wikipedia](https://en.wikipedia.org/wiki/2026_Mid-Season_Invitational) (accessed 2026-08-21); [MSI & Worlds 2026 dates, venues, format & changes revealed – Esports Charts](https://escharts.com/news/msi-worlds-2026-format-cities-dates) (accessed 2026-08-21); [LCK and LPL secure fourth Worlds 2026 spot after top two result at MSI 2026 – Sheep Esports](https://www.sheepesports.com/en/all/articles/lck-and-lpl-secures-fourth-worlds-2026-seed-after-top-two-result-at-msi-2026/en) (accessed 2026-08-21)

#### Worlds 2026 (upcoming — NOT yet played as of 2026-08-21)
- **Dates**: October 15-November 14, 2026. Play-In Oct 15-18; Swiss Stage Oct 23-31; Knockouts Nov 3-8; Grand Final Nov 14.
- **Venues**: Play-In at Riot Games Arena, **Los Angeles**; Swiss Stage and Knockouts at Credit Union of Texas Event Center, **Allen, TX**; Grand Final at Barclays Center, **Brooklyn, New York City**.
- **Slots (19 teams total)**: LCK, LPL, LEC, LCS, LCP get **3 base slots each**; **CBLOL gets 2** (its Split 2 champion + runner-up, an increase from 1 in prior years); **+1 bonus slot to the MSI 2026 champion's region and +1 to the MSI 2026 runner-up's region**. Because Hanwha Life Esports (LCK) won MSI 2026 and Bilibili Gaming (LPL) was runner-up, **LCK and LPL each effectively get 4 Worlds 2026 slots**, LEC/LCS/LCP get 3, CBLOL gets 2 (4+4+3+3+3+2 = 19).
- No results exist yet — do not treat any "2026 World Championship final" content as historical fact; it is a scheduled future event.
[2026 League of Legends World Championship – Wikipedia](https://en.wikipedia.org/wiki/2026_League_of_Legends_World_Championship) (accessed 2026-08-21); [Every Team Qualified For LoL Worlds 2026 – Hotspawn](https://www.hotspawn.com/league-of-legends/news/worlds-2026-teams) (accessed 2026-08-21)

#### Worlds 2025 and MSI 2025 (ground truth for pipeline validation)
- **Worlds 2025**: Chengdu, China (Dong'an Lake Sports Park Multifunctional Gymnasium); Grand Final **November 9, 2025**. 17 teams: LCK 3, LPL 3 (+1 bonus as MSI's 2nd-best-performing region), LEC 3, **LTA 3** (its only Worlds appearance, split as LTA North champion FlyQuest + LTA South champion Vivo Keyd Stars + a 3rd seed, 100 Thieves), LCP 3, +1 auto slot for the MSI 2025 champion. Format: Play-In feeds a **16-team, 5-round Swiss Stage**, then knockouts.
  **Result: T1 defeated KT Rolster 3-2** — T1's **6th** World Championship title and **3rd consecutive** (a three-peat, the first in Worlds history). MVP: Lee "Gumayusi" Min-hyeong. Peak viewership 6.7M (Esports Charts).
  [2025 League of Legends World Championship qualification – Wikipedia](https://en.wikipedia.org/wiki/2025_League_of_Legends_World_Championship_qualification) (accessed 2026-08-21); [T1 defeats KT Rolster to win League of Legends Worlds 2025 – Esports Insider](https://esportsinsider.com/2025/11/t1-wins-league-of-legends-lol-worlds-2025) (accessed 2026-08-21); [T1 Makes History: Worlds 2025 Peaks at 6.7M Viewers – Esports Charts](https://escharts.com/news/t1-makes-history-winning-worlds-2025-event-reached-over-67m-peak-viewers) (accessed 2026-08-21)
- **MSI 2025**: **Gen.G (LCK) defeated T1 (LCK) 3-2** in the final — an all-LCK final; Gen.G's **2nd consecutive** MSI title, completed with an undefeated run; $500,000 first prize.
  [Gen.G are the 2025 League of Legends Mid-Season Invitational champions – GosuGamers](https://www.gosugamers.net/lol/news/76104-are-the-2025-league-of-legends-mid-season-invitational-champions) (accessed 2026-08-21)

---

### 2.5 Rosters and canonical data sources

**2026 team counts by league** (see 2.1 for full team-name lists and per-league citations):

| League | Teams (main) | Notes |
|---|---|---|
| LCK | 10 | Gen.G, T1, Hanwha Life, KT Rolster, Dplus KIA, BNK FearX, KIWOOM DRX, Nongshim RedForce, DN SOOPers, Hanjin Brion |
| LPL | 14 (12 in Split 3) | FPX and RNG exited between seasons |
| LEC | 10 (12 in Versus) | +2 invited ERL teams for the Versus opening split only |
| LCS | 8 | Incl. LYON (LLA slot) and Disguised (guest) |
| CBLOL | 8 | Incl. Leviatán and LOS (LLA/guest slots) |
| LCP | 8 | 3 partner + 5 guest teams; PSG Talon removed Nov 2025 |

**Canonical machine-readable source: Leaguepedia** (`lol.fandom.com`), the community wiki-of-record for LoL esports, backed by **Cargo tables** — structured, SQL-queryable data including `Teams`, `Players`, `TournamentPlayers`, `ScoreboardGames`, `Tournaments`, and dedicated "Roster Swaps" pages tracking every roster change by region. Data is queried via:
- The wiki's own `Special:CargoTables` / `Special:CargoQuery` interface,
- The underlying MediaWiki + Cargo HTTP API (what community tools use),
- Wrapper libraries: Python (`mwclient`-based clients, e.g. `lol-esports-parser`), JavaScript (`poro` npm package), R (`rlolesports`).
**Liquipedia** (`liquipedia.net/leagueoflegends`) independently mirrors similar structured tournament/roster data with its own API and is a good cross-check source.
**Caveat**: our WebFetch tool returned **HTTP 402 (Payment Required)** on every attempt to load `lol.fandom.com` pages directly this session (Fandom likely blocking/challenging this particular fetch proxy) — this is a tooling-side issue, not evidence the site or its API is unavailable. Confirm reachability of Leaguepedia's Cargo API from the project's actual scraping/ingestion environment before committing to it as a dependency.
[Module:CargoQuery – Leaguepedia](https://lol.fandom.com/wiki/Module:CargoQuery) (title only, via search snippet — direct fetch failed); [poro – npm](https://www.npmjs.com/package/poro) (accessed 2026-08-21); [Gathering LoLEsports data – Hextech Docs](https://hextechdocs.dev/gathering-lolesports-data/) (accessed 2026-08-21)

---

### 2.6 Broadcast cadence and schedule data

**Schedule API**: the de-facto standard, used by lolesports.com itself and virtually every third-party scraper/stats site, is Riot's unofficial-but-stable REST API:
- `GET https://esports-api.lolesports.com/persisted/gw/getLeagues`
- `GET https://esports-api.lolesports.com/persisted/gw/getSchedule`
- Auth header: `x-api-key: 0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z` (a long-standing publicly-known shared key).
It covers every active league/tournament — including Worlds, MSI, First Stand, and all regional splits — with match state, team scores, best-of format, and VOD links. Community docs current as of 2026 confirm it already includes the Worlds 2026 schedule. This is **not an officially documented/supported Riot developer product**; treat it as **Medium confidence for long-term stability** (it has persisted for years but could change without notice) and have a Leaguepedia/Liquipedia fallback for schedule ingestion.
[Riot LoL eSports Unofficial API Documentation – GitHub Gist](https://gist.github.com/levi/e7e5e808ac0119e154ce) (accessed 2026-08-21); [Unofficial Lolesports Api docs](https://vickz84259.github.io/lolesports-api-docs/) (accessed 2026-08-21); [LoL Esports Schedule & Results Scraper (2026) – Apify](https://apify.com/jungle_synthesizer/lol-esports-worlds-2026-schedule-results-scraper) (accessed 2026-08-21)

**Per-league regular-season volume (2026), from confirmed formats above:**

| League / stage | Teams | RR type | Bo | Series/split (computed) |
|---|---|---|---|---|
| LEC Versus | 12 | single RR | Bo1 | 66 games (12×11/2) |
| LEC Spring/Summer | 10 | single RR | Bo3 | 45 series (10×9/2) each |
| LCS Spring/Summer | 8 | single RR | Bo3 | 28 series (8×7/2) each |
| LCK Rounds 1-2 | 10 | double RR | Bo3 | 90 series (10×9) |
| LCK Rounds 3-4 (per group) | 5+5 | double RR | Bo3 | 20 series/group, 40 total |
| CBLOL / LCP (per split) | 8 | single RR | Bo3 | ~28 series (approx.; CBLOL's exact regular-season Bo count not independently confirmed this session — **Med confidence**) |
| LPL (per split) | 14 or 12, grouped | mixed RR | Bo3 | grouped/reseeded — not cleanly reducible to one number this session |

Broadcast cadence example: **LEC Summer 2026** broadcasts 2 Bo3 series/day, across 3-4 days/week (Fri-Sun, occasionally Mon) for its ~6-7 week regular season — roughly 6-8 series (13-18 games) per week during that window.

**Bottom line for sample-size planning**: summing regular season + playoffs + Lock-In/Versus + international appearances, the 4 priority leagues (LCK, LPL, LEC, LCS) likely generate on the order of **several hundred Bo3/Bo5 series and roughly 700-900+ individual games per year combined** — this is a **rough planning estimate (Med-Low confidence)** built from the components above, not an audited total. **The team should compute an exact figure directly from the schedule API or Leaguepedia's `ScoreboardGames` table** once ingestion exists, since LPL's and LCK's grouped/reseeded formats are error-prone to hand-count.
[LEC Summer 2026 Moves To Four-Day Weeks With No Mid-Season Break – Hotspawn](https://www.hotspawn.com/league-of-legends/news/lec-summer-2026) (accessed 2026-08-21); [2026 LCS Summer Primer – lolesports.com](https://lolesports.com/en-US/news/2026-lcs-summer-primer) (accessed 2026-08-21, via search snippet)

---

## 3. Implications for Our Data Schema and Model

**Era/regime flags (structural breaks the model must know about):**
- `era_lta` (2025 only, Americas region) vs `era_lcs_cblol_v2` (2026+) — team identity, region grouping, and conference context are **not comparable** across this boundary for NA/BR/LATAM teams. Any team-strength prior trained on 2025 LTA data for an LTA-North/South team needs explicit region-remapping before reuse in 2026 LCS/CBLOL models.
- `fearless_draft_flag` at the **match/series** grain (not season grain): true for Bo3/Bo5 series since each region's 2025-Split-2 rollout date; false for all Bo1s regardless of era. This flag should be derived from `(best_of > 1)` AND `(date >= region-specific fearless start date)`, not from a single global date.
- `first_selection_flag`: true from the start of the 2026 season onward — changes what "blue side" means as a feature (it's no longer bundled with first-pick priority), so **side and pick-priority should become two separate categorical features** in 2026+ data rather than one combined "blue side advantage" feature as used pre-2026.
- `patch_version` and `patch_regime` (e.g., pre/post Atakhan removal, pre/post Void Grub rework, pre/post Baron-timer change) should be stored per-game (not per-split) from Leaguepedia's `ScoreboardGames.Patch` field, since pro play locks a patch per stage while balance context still shifts meaningfully split-to-split.

**Fearless-draft-derived features** (now feasible given full-fearless is universal at tier 1):
- Running champion-pool-exhaustion state per team *within a series* (games remaining vs. champions already burned) — a natural live/in-series feature for Bo3/Bo5 win-probability, not applicable to Bo1s.
- Champion "priority value" should be modeled as **series-relative scarcity**, not just global pick/ban rate, since fearless changes optimal draft strategy (banks strong champions for must-win games).
- Because fearless resets between series, cross-series champion-pool features must be scoped to `series_id`, never leak across a round-robin stage.

**League-priority weighting** (per the user's stated priority LCK > LPL > LEC > LCS):
- Data volume favors this ordering naturally for training-set size: LPL (14/12 teams, most series) and LCK (10 teams, double round-robin) generate the most regular-season games; LEC and LCS are comparably sized with cleaner single-round-robin formats (easier to reason about strength-of-schedule).
- Recommend `league_tier` and `league` as first-class categorical features, plus a `cross_league` flag for International events (First Stand/MSI/Worlds), since draft pools, patch familiarity, and even side-selection meta can differ by region at the time of an international event (regional patch lag differs by region, not just pro-vs-live).
- CBLOL/LCP/Americas-adjacent (LYON/Leviatán/LOS) data is thinner (8 teams, single round-robin) — useful mainly for International-event opponent modeling rather than as a primary training population, consistent with the stated league priority.

**Schema fields worth adding explicitly**, given this research:
- `region_conference` (nullable) — only meaningful for the 2025 LTA North/South era; keep for historical backtests, unused going forward.
- `worlds_bonus_slot_flag` / `slot_type` (base / MSI-champion-bonus / MSI-runner-up-bonus / CBLOL-2nd-slot) — international-event seeding is no longer a flat "N per region," and slot type may correlate with recent form (MSI results directly determine bonus Worlds slots for that region).
- `objective_ruleset_version` keyed to patch, to cleanly separate pre-2026 Atakhan-era games from post-26.1 games in any objective-timing or gold-curve feature.

---

## 4. Open Questions

1. **LEC Versus Bo1 + Fearless discrepancy**: one secondary source claimed Fearless Draft was "in effect" during the Bo1 round-robin portion of LEC Versus 2026, which conflicts with the general per-series/Bo1-exempt rule confirmed elsewhere (including the official Riot recap). Needs direct confirmation from the official 2026 LEC rulebook or Leaguepedia's picks-and-bans page for that split before the model assumes either way.
2. **LPL "soft fearless" residue**: one source implied a lingering LPL-specific variant where only same-team repeat picks are restricted ("soft" fearless) even after 2025 standardization. Needs a direct check against LPL's official 2026 competitive ruleset (Chinese-language primary source ideally) since this directly affects whether champion-exhaustion features can be computed identically across LPL vs. other leagues.
3. **Exact 2025 patch-naming predecessor scheme**: we did not re-verify the precise "25.S1.x"-style format with a fresh citation this session (search budget was exhausted); worth a quick confirmation pass since our own research brief asserted it as background.
4. **Full-season exact game/series counts** per league (especially LPL's grouped/reseeded splits and CBLOL's exact regular-season best-of) should be computed programmatically from the schedule API or Leaguepedia `ScoreboardGames`, not hand-derived from round-robin arithmetic as done here.
5. **CBLOL regular-season best-of** (Bo1 vs Bo3) was not independently confirmed with a strong citation — the knockout mini-bracket for seeds 5-8 was confirmed Bo3, but the main round-robin's best-of format for the top-4-direct-qualifiers portion should be double-checked.
6. **Leaguepedia/Fandom reachability from our own infrastructure**: WebFetch failed with HTTP 402 on every `lol.fandom.com` attempt this session. Before architecting ingestion around Leaguepedia's Cargo API, do a direct reachability test (curl/requests, not this research tool) from wherever the pipeline will actually run.
7. **Stability of the unofficial lolesports schedule API** (`esports-api.lolesports.com`): it has worked for years and is documented as current for 2026, but it is unofficial. Worth checking whether Riot now offers (or plans) a formal partner/developer API given the scale of a quant modeling use case, versus building resilience against silent breakage of the reverse-engineered endpoint.
8. **"SOOPers" / "DN SOOPers" and other recently-responsored team names**: several LCK/LCP orgs carry title-sponsor names that change year to year (e.g., DN SOOPers, Hanjin Brion, KIWOOM DRX). The schema should key entities on a stable internal `team_id`/franchise identity separate from the display name, with a name-history table, since Leaguepedia itself models this via redirect/rename tracking.

---

## Sources Consulted (primary list)

- Wikipedia: [2026 LCS](https://en.wikipedia.org/wiki/2026_LCS_season), [2025 LTA](https://en.wikipedia.org/wiki/2025_LTA_season), [2026 LCK](https://en.wikipedia.org/wiki/2026_LCK_season), [2026 LPL](https://en.wikipedia.org/wiki/2026_LPL_season), [2026 LEC](https://en.wikipedia.org/wiki/2026_LEC_season), [2026 CBLOL](https://en.wikipedia.org/wiki/2026_CBLOL_season), [2026 LCP](https://en.wikipedia.org/wiki/2026_LCP_season), [2026 First Stand Tournament](https://en.wikipedia.org/wiki/2026_First_Stand_Tournament), [2026 Mid-Season Invitational](https://en.wikipedia.org/wiki/2026_Mid-Season_Invitational), [2026 League of Legends World Championship](https://en.wikipedia.org/wiki/2026_League_of_Legends_World_Championship), [2025 League of Legends World Championship qualification](https://en.wikipedia.org/wiki/2025_League_of_Legends_World_Championship_qualification), [League of Legends Championship of The Americas](https://en.wikipedia.org/wiki/League_of_Legends_Championship_of_The_Americas)
- Official Riot/Riot-adjacent: [lolesports.com – "LCS and CBLOL Return"](https://lolesports.com/en-US/news/lcs-and-cblol-return), [lolesports.com – "Fearless Draft Takes Over 2025"](https://lolesports.com/en-US/news/fearless-draft-takes-over-2025), [League of Legends Wiki – Patch/2026 Annual Cycle](https://wiki.leagueoflegends.com/en-us/Patch/2026_Annual_Cycle)
- Liquipedia: LCK/LPL/LEC/LCS/CBLOL/LCP 2026 season, split, and roster pages under `liquipedia.net/leagueoflegends/`
- News/analysis: Esports Insider, esports.gg, GosuGamers, Esports Charts (escharts.com), Hotspawn, Dot Esports, Sheep Esports, Sportskeeda, Esports News UK, TheSpike.gg, loltheory.gg
- Data-tooling references: Leaguepedia Module:CargoQuery, `poro` npm package, Hextech Docs "Gathering LoLEsports data", unofficial lolesports API docs/gists

All access dates 2026-08-21 (this research session) unless a page's own dateline is quoted.
