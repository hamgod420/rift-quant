"""Shared configuration: API endpoints, keys, data-lake paths, politeness."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# Riot's PUBLIC broadcast API key for the lolesports persisted API. This is
# not a secret: it is published in Riot's own broadcast overlay tooling and
# reused by every community project that talks to this API. Safe to hardcode.
DEFAULT_PUBLIC_KEY = "0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z"

LOLESPORTS_BASE = "https://esports-api.lolesports.com/persisted/gw"
LIVESTATS_BASE = "https://feed.lolesports.com/livestats/v1"
LEAGUEPEDIA_API = "https://lol.fandom.com/api.php"

USER_AGENT = "riftquant/0.1 (rift-quant research project; personal use)"
# Leaguepedia's API etiquette asks for a descriptive UA identifying the tool.
LEAGUEPEDIA_USER_AGENT = "riftquant-dev/0.1 (rift-quant research project; personal use)"

# lolesports league ids, verified live 2026-08-21 (docs/specs/M1-build-brief.md).
# lta_n / lta_cross carry the 2025 LCS-lineage games (LTA year); internationals
# are in scope per docs/QUESTIONS.md Q1. lta_s (CBLOL/LLA lineage) is out of
# scope. LPL note: the persisted API has almost no LPL events (verified
# 2026-08-21) -- LPL coverage comes from Leaguepedia instead.
LEAGUE_IDS = {
    "lcs": "98767991299243165",
    "lec": "98767991302996019",
    "lck": "98767991310872058",
    "lpl": "98767991314006698",
    "lta_n": "113470291645289904",
    "lta_cross": "113475149040947852",
    "worlds": "98767975604431411",
    "msi": "98767991325878492",
    "first_stand": "113464388705111224",
}

REPO_ROOT = Path(__file__).resolve().parents[2]
# Overridable so tests (and future deployments) can redirect the lake without
# monkeypatching every call site.
DATA_ROOT = Path(os.environ.get("RIFTQUANT_DATA_DIR", REPO_ROOT / "data"))
DATA_RAW = DATA_ROOT / "raw"
DATA_PROCESSED = DATA_ROOT / "processed"

HTTP_TIMEOUT_SECS = 20.0

# Politeness: livestats has no auth and no documented hard limit, but the
# brief asks for courtesy sleeps; Leaguepedia is a shared community wiki and
# explicitly asks for >=1s between calls.
LIVESTATS_SLEEP_SECS = 0.3
LEAGUEPEDIA_SLEEP_SECS = 1.0
LEAGUEPEDIA_PAGE_SIZE = 500

# --- Odds capture (M1b, docs/specs/M1b-odds-recorder-brief.md) ---
# All three Polymarket surfaces are public/no-auth for market data; verified
# live 2026-08-21 both by docs/research/07-odds-capture-apis.md and again
# with fresh curl calls while building riftquant/odds/ (gamma-api discovery,
# CLOB /book+/price+/midpoint, data-api /trades all returned real data for a
# live LCK match today).
GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"
POLYMARKET_DATA_API_BASE = "https://data-api.polymarket.com"
# Documented canonical host (research doc 2.1); the legacy elections.kalshi.com
# host also works but this is the one Kalshi's own docs point at.
KALSHI_BASE = "https://external-api.kalshi.com/trade-api/v2"

# COMPLIANCE GATE (docs/QUESTIONS.md Q27): Kalshi's Data Terms of Use bars
# using Kalshi Data for ML training or archiving without written consent.
# kalshi MUST stay False here until a human reviews Kalshi's separate API
# Developer Agreement and flips this manually -- do not add a CLI override.
# Kalshi's connector/tests exist and pass, but this project's own tooling
# never calls the live Kalshi API while this is False.
ODDS_VENUES_ENABLED: dict[str, bool] = {
    "polymarket": True,
    "kalshi": False,
}

LOL_TAG_SLUG = "league-of-legends"
KALSHI_LOL_MATCH_SERIES = "KXLOLGAME"  # full-match winner; v0 scope (see brief)

# Courtesy sleep after every HTTP call, keeping us well under the brief's
# "<=1 req/sec sustained per endpoint class" constraint even with several
# tracked markets and several endpoint classes hit per poll tick.
POLYMARKET_SLEEP_SECS = 1.0
KALSHI_SLEEP_SECS = 0.5  # unexercised live until the flag above flips

ODDS_RECORD_INTERVAL_SECS = 30
ODDS_FULL_BOOK_INTERVAL_SECS = 300  # 5 min, per brief
ODDS_DEFAULT_HOURS_AHEAD = 96.0
ODDS_DEFAULT_MARKET_LIMIT = 5

# --- M2 pregame model (docs/specs/M2-pregame-model-brief.md) ---

RATINGS_DIR = DATA_PROCESSED / "ratings"
FEATURES_DIR = DATA_PROCESSED / "features"
MODELS_DIR = DATA_PROCESSED / "models"
EVAL_DIR = REPO_ROOT / "docs" / "eval"
CHAMP_TAGS_PATH = DATA_ROOT / "reference" / "champ_tags.csv"

PLAYER_RATINGS_PARQUET = RATINGS_DIR / "player_ratings.parquet"
PREGAME_FEATURES_PARQUET = FEATURES_DIR / "pregame.parquet"
PREGAME_MODEL_DIR = MODELS_DIR / "pregame"
PREGAME_PREDICTIONS_PARQUET = PREGAME_MODEL_DIR / "predictions.parquet"

# Leagues/tournaments whose OverviewPage-derived `league` column (see
# store/views.py) denotes an international, cross-region event rather than a
# domestic league -- these are the games that update the mu_meta layer
# instead of mu_ctx (docs/research/08-pandaskill-method.md S2.3). Matched
# case-insensitively against v_games.league. lolesports' own slugs for the
# same events are config.LEAGUE_IDS' "worlds"/"msi"/"first_stand"/
# "lta_cross" keys; Leaguepedia's OverviewPage prefixes read like "Worlds",
# "MSI", "First Stand" -- both forms are listed so either naming survives a
# future ingest-side rename.
INTERNATIONAL_LEAGUES: frozenset[str] = frozenset(
    {"worlds", "msi", "first_stand", "lta_cross", "firststand"}
)

# openskill (Weng-Lin Plackett-Luce) cold-start defaults, per
# docs/research/08-pandaskill-method.md S2.2 ("Cold-start init") -- these
# match the openskill library's own PlackettLuce() defaults (mu=25,
# sigma=25/3); kept here as named constants because build-ratings needs the
# same numbers when initializing a brand-new region's meta rating, which the
# library itself has no API for (only per-player `.rating()` cold-starts).
RATING_DEFAULT_MU = 25.0
RATING_DEFAULT_SIGMA = 25.0 / 3.0

# PandaSkill's FFA (free-for-all, all 10 players ranked by performance
# rather than 2 teams ranked by win/loss) rating mode "hurts raw accuracy"
# per report 08's own ablation table -- default OFF; TEAM-RESULT mode is the
# v0 default per the M2 brief. Flag exists so build-ratings can produce a
# comparison run later without a code change.
RATINGS_FFA_DEFAULT = False

# Empirical-Bayes shrinkage strength (in "games") for player-champion
# proficiency, per the M2 brief ("prior = player's overall WR, strength
# ~10 games"): shrunk_wr = (wins + K * prior_wr) / (games + K).
PC_SHRINKAGE_K = 10.0

ROLE_SLOTS: tuple[str, ...] = ("Top", "Jungle", "Mid", "Bot", "Support")


@dataclass(frozen=True)
class PregameSplitPreset:
    """Time-based train/val/test boundaries for the pregame model (M2 brief,
    "Non-negotiable rails" -- time splits only). `train_end`/`val_end` are
    exclusive upper bounds: train = date < train_end, val = train_end <=
    date < val_end, test = date >= val_end.
    """

    name: str
    train_end: datetime
    val_end: datetime


# SUBSET MODE (M2 brief, current reality 2026-08-21): only LCK 2026 + LEC
# 2026 are ingested so far, adapted splits per the brief's SUBSET MODE
# section.
PREGAME_SPLIT_SUBSET = PregameSplitPreset(
    name="subset_2026",
    train_end=datetime(2026, 6, 1),
    val_end=datetime(2026, 7, 15),
)

# Full-data preset for the eventual 2020+ backfill, per the brief's "Rails"
# section: train <= 2025-06-30, validation 2025-07-01..2025-12-31, test
# 2026+. A config-only switch (PREGAME_SPLIT_ACTIVE below) -- no code change
# needed once the backfill lands.
PREGAME_SPLIT_FULL = PregameSplitPreset(
    name="full_2020plus",
    train_end=datetime(2025, 7, 1),
    val_end=datetime(2026, 1, 1),
)

# THE config switch the brief asks for: flip this one line to
# PREGAME_SPLIT_FULL after the 2020+ backfill lands, then rerun
# build-ratings/build-features/train-pregame/eval-pregame. Every consumer
# (features + models) reads this constant, never a hardcoded date.
PREGAME_SPLIT_ACTIVE = PREGAME_SPLIT_SUBSET

# --- M4 in-game model (docs/specs/M4-ingame-model-brief.md) ---

INGAME_FEATURES_PARQUET = FEATURES_DIR / "ingame.parquet"
INGAME_MODEL_DIR = MODELS_DIR / "ingame"

# Row-builder rails (brief "Deliverables" section 1): drop the pre-lane-phase
# noise floor, keep only genuinely-live game state.
INGAME_WARMUP_SECONDS = 60.0
INGAME_EXCLUDED_GAME_STATES: frozenset[str] = frozenset({"paused", "finished"})

# Momentum/tempo features (Q9): gold_diff delta over these trailing windows,
# computed via a game-clock (not wall-clock, not row-count) asof lookup so a
# real in-game pause never corrupts the window -- see features/ingame.py.
INGAME_MOMENTUM_WINDOWS_S: tuple[float, ...] = (60.0, 180.0)

# The S-curve reporting/calibration/blending-weight buckets (brief section 2
# and 4): (lo, hi) in game_clock_s, hi=None means unbounded ("30+min"). Reused
# for three purposes that all want the same coarse time axis: per-bucket
# isotonic calibration, per-bucket blend-weight grid search, and the eval
# scorecard's S-curve table vs Q14's expected accuracy.
INGAME_TIME_BUCKETS: tuple[tuple[float, float | None, str], ...] = (
    (0.0, 600.0, "0-10min"),
    (600.0, 1200.0, "10-20min"),
    (1200.0, 1800.0, "20-30min"),
    (1800.0, None, "30+min"),
)

# Q14's literature-sanity-rail accuracy per bucket (docs/QUESTIONS.md Q14):
# the baseline model's accuracy should land roughly on this S-curve; far
# above is a leakage-investigation trigger, not a win (see models/ingame.py).
INGAME_Q14_EXPECTED_ACCURACY: dict[str, float] = {
    "0-10min": 0.60,
    "10-20min": 0.70,
    "20-30min": 0.80,
    "30+min": 0.90,
}
# "Far above" Q14 tripwire margin (percentage points, as a fraction) -- a
# heuristic guardrail, not a hard threshold: thin per-bucket row counts make
# any single measurement noisy, so this only fires on a large blowout.
INGAME_Q14_TRIPWIRE_MARGIN = 0.15

# Team-name-set + start_time proximity window for joining a frames-archive
# game_id (lolesports numeric id, from game_index/*.parquet) to its v_games
# row (Leaguepedia id space) -- same 12h convention store/views.py's
# cross_check_game_index already uses for the same two id spaces.
INGAME_LABEL_MATCH_WINDOW_HOURS = 12.0

# SUBSET MODE (current reality 2026-08-21): the frames archive spans many
# leagues/years, but Leaguepedia ingestion (the only source of a resolved
# winner_team_id -- see features/ingame.py's module docstring for why) only
# covers LCK 2026 + LEC 2025-2026 so far. Boundaries are hand-picked around
# the actual handful of currently-labeled games' timestamps (not the brief's
# literal dates, which would leave the validation split completely empty
# right now) so train/val/test are all non-empty and train keeps some label
# variance -- see docs/eval/ingame_v0_<date>.md for exactly which games land
# where. Revisit (recompute boundaries) as more Leaguepedia seasons land.
INGAME_SPLIT_SUBSET = PregameSplitPreset(
    name="ingame_subset_current",
    train_end=datetime(2026, 1, 14, 10, 0, 0),
    val_end=datetime(2026, 1, 17, 16, 30, 0),
)

# Full-data preset, per the brief's literal "Rails" section: train before
# 2025-10-01, validation 2025-10-01..2025-12-31, test 2026+. A config-only
# switch (INGAME_SPLIT_ACTIVE below) once Leaguepedia coverage catches up to
# the frames archive.
INGAME_SPLIT_FULL = PregameSplitPreset(
    name="ingame_full_2025h2val",
    train_end=datetime(2025, 10, 1),
    val_end=datetime(2026, 1, 1),
)

# THE config switch: flip this one line to INGAME_SPLIT_FULL once enough
# leagues/seasons are Leaguepedia-ingested to make the val split non-trivial,
# then rerun build-ingame-features/train-ingame/eval-ingame.
INGAME_SPLIT_ACTIVE = INGAME_SPLIT_SUBSET
