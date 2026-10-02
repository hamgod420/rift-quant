"""Raw livestats frames -> tidy 10s-resolution parquet + objective events.

See docs/specs/M4a-frames-normalizer-brief.md for the full spec. Schema notes
below were learned by reading real archived frames (games 113475493522604199,
which has a genuine mid-game pause, and 113475798006664581, which lacks a
`finished` frame) -- trust these over the brief's prose where they disagree.

Verified live schema (checked across all archived games, not just the two
above):
  - /window frames: exactly 4 top-level keys (`rfc460Timestamp`, `gameState`,
    `blueTeam`, `redTeam`). Each team dict has `totalGold` (CURRENT/spendable
    gold -- equals the sum of that team's participants' own `totalGold`,
    verified), `totalKills`, `towers`, `inhibitors`, `barons` (plain int
    counts), `dragons` (a list of type strings that only ever GROWS across a
    game -- append-only, never shrinks/resets), and `participants` (5 dicts:
    `participantId`, `totalGold`, `level`, `kills`, `deaths`, `assists`,
    `creepScore`, `currentHealth`, `maxHealth`). `gameState` observed values:
    `in_game`, `paused`, `finished`.
  - Dragon type vocabulary observed across the full corpus: infernal, ocean,
    mountain, cloud, hextech, chemtech, elder.
  - NOT present anywhere in the schema (verified by scanning every archived
    game): per-player or per-team `xp`, and any void-grubs/Rift-Herald
    field. The brief's prose mentions "xp_diff if available" and
    "grubs/herald where present" -- neither is ever available/present, so
    both are omitted from the tidy output rather than kept as always-null
    columns. If a future patch/feed version adds them, this is the place to
    add the columns back.
  - Per-player `items` are NOT in /window (despite the brief's context
    prose) -- they live in /details instead, alongside wards/damage-share/
    combat stats. `parse_details` captures these. /window and /details are
    (near-)exactly timestamp-aligned (same `rfc460Timestamp` values, verified
    on real data), but the tidy builder below sources its nested per-player
    column from /window only -- see `downsample_tidy` docstring for why.
  - A real in-game pause (game 113475493522604199) shows up as exactly ONE
    `paused`-state frame, then the feed goes silent and the next frame is a
    normal `in_game` frame possibly minutes later (a real wall-clock gap,
    not a burst of repeated "paused" frames). `game_clock_s` below excludes
    exactly this kind of gap.
  - The feed occasionally emits several frames with near-identical or even
    byte-identical timestamps in a burst (observed: 3 consecutive frames
    all timestamped `09:25:37.281Z` in the pause game). Downsampling must
    not assume distinct timestamps.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime

import polars as pl

from riftquant.store import lake

BUCKET_SECONDS = 10

# Structural/epic-monster objectives only (LoL-standard meaning of
# "objective"). Player kills are intentionally NOT modeled as
# objective_events rows: they are already exposed continuously via tidy's
# blue_kills/red_kills/kill_diff at 10s resolution, and mixing them into
# this table would bury the four true objective types under a much larger
# volume of kill rows (observed ~65% of raw increments in a real game).
_OBJECTIVE_COUNTERS: tuple[tuple[str, str], ...] = (
    ("towers", "tower"),
    ("inhibitors", "inhibitor"),
    ("barons", "baron"),
)

WINDOW_PLAYER_STRUCT = pl.Struct(
    {
        "team": pl.Utf8,
        "participant_id": pl.Int64,
        "total_gold": pl.Int64,
        "level": pl.Int64,
        "kills": pl.Int64,
        "deaths": pl.Int64,
        "assists": pl.Int64,
        "creep_score": pl.Int64,
        "current_health": pl.Int64,
        "max_health": pl.Int64,
    }
)

# Per-frame (native ~1/sec cadence) parsed /window table. `game_clock_s`,
# `is_paused`, the dragon count/soul-point flags, and gold_diff/kill_diff are
# derived once here so both the tidy downsampler and the event extractor
# (which needs full, non-downsampled resolution -- see extract_objective_
# events) share one computation.
WINDOW_SCHEMA: dict[str, pl.PolarsDataType] = {
    "game_id": pl.Utf8,
    "ts": pl.Datetime("us", "UTC"),
    "game_state": pl.Utf8,
    "is_paused": pl.Boolean,
    "game_clock_s": pl.Float64,
    "blue_gold": pl.Int64,
    "blue_kills": pl.Int64,
    "blue_towers": pl.Int64,
    "blue_inhibitors": pl.Int64,
    "blue_barons": pl.Int64,
    "blue_dragon_types": pl.List(pl.Utf8),
    "blue_dragon_count": pl.Int64,
    "blue_soul_point": pl.Boolean,
    "blue_players": pl.List(WINDOW_PLAYER_STRUCT),
    "red_gold": pl.Int64,
    "red_kills": pl.Int64,
    "red_towers": pl.Int64,
    "red_inhibitors": pl.Int64,
    "red_barons": pl.Int64,
    "red_dragon_types": pl.List(pl.Utf8),
    "red_dragon_count": pl.Int64,
    "red_soul_point": pl.Boolean,
    "red_players": pl.List(WINDOW_PLAYER_STRUCT),
    "gold_diff": pl.Int64,
    "kill_diff": pl.Int64,
}

DETAILS_PLAYER_STRUCT = pl.Struct(
    {
        "participant_id": pl.Int64,
        "total_gold_earned": pl.Int64,
        "level": pl.Int64,
        "kills": pl.Int64,
        "deaths": pl.Int64,
        "assists": pl.Int64,
        "creep_score": pl.Int64,
        "kill_participation": pl.Float64,
        "champion_damage_share": pl.Float64,
        "wards_placed": pl.Int64,
        "wards_destroyed": pl.Int64,
        "attack_damage": pl.Int64,
        "ability_power": pl.Int64,
        "critical_chance": pl.Float64,
        "attack_speed": pl.Int64,
        "life_steal": pl.Int64,
        "armor": pl.Int64,
        "magic_resistance": pl.Int64,
        "tenacity": pl.Float64,
        "items": pl.List(pl.Int64),
    }
)

DETAILS_SCHEMA: dict[str, pl.PolarsDataType] = {
    "game_id": pl.Utf8,
    "ts": pl.Datetime("us", "UTC"),
    "players": pl.List(DETAILS_PLAYER_STRUCT),
}

TIDY_SCHEMA: dict[str, pl.PolarsDataType] = {
    k: v
    for k, v in WINDOW_SCHEMA.items()
    if k not in ("blue_players", "red_players")
} | {
    "ts_bucket": pl.Datetime("us", "UTC"),
    "players": pl.List(WINDOW_PLAYER_STRUCT),
}
# players is inserted after game_id/ts/... below via column selection order;
# ts_bucket is the natural leading time index.
_TIDY_COLUMN_ORDER = [
    "game_id",
    "ts_bucket",
    "ts",
    "game_state",
    "is_paused",
    "game_clock_s",
    "blue_gold",
    "red_gold",
    "gold_diff",
    "blue_kills",
    "red_kills",
    "kill_diff",
    "blue_towers",
    "red_towers",
    "blue_inhibitors",
    "red_inhibitors",
    "blue_barons",
    "red_barons",
    "blue_dragon_count",
    "red_dragon_count",
    "blue_dragon_types",
    "red_dragon_types",
    "blue_soul_point",
    "red_soul_point",
    "players",
]

EVENTS_SCHEMA: dict[str, pl.PolarsDataType] = {
    "game_id": pl.Utf8,
    "game_clock_s": pl.Float64,
    "ts": pl.Datetime("us", "UTC"),
    "type": pl.Utf8,
    "killer_team": pl.Utf8,
    "dragon_type": pl.Utf8,
    "count": pl.Int64,
    "simultaneous": pl.Boolean,
}


def _parse_ts(rfc460: str) -> datetime:
    return datetime.fromisoformat(rfc460.replace("Z", "+00:00"))


def _window_players(participants: list[dict], team: str) -> list[dict]:
    return [
        {
            "team": team,
            "participant_id": p["participantId"],
            "total_gold": p["totalGold"],
            "level": p["level"],
            "kills": p["kills"],
            "deaths": p["deaths"],
            "assists": p["assists"],
            "creep_score": p["creepScore"],
            "current_health": p["currentHealth"],
            "max_health": p["maxHealth"],
        }
        for p in participants
    ]


def _details_players(participants: list[dict]) -> list[dict]:
    return [
        {
            "participant_id": p["participantId"],
            "total_gold_earned": p["totalGoldEarned"],
            "level": p["level"],
            "kills": p["kills"],
            "deaths": p["deaths"],
            "assists": p["assists"],
            "creep_score": p["creepScore"],
            "kill_participation": p["killParticipation"],
            "champion_damage_share": p["championDamageShare"],
            "wards_placed": p["wardsPlaced"],
            "wards_destroyed": p["wardsDestroyed"],
            "attack_damage": p["attackDamage"],
            "ability_power": p["abilityPower"],
            "critical_chance": p["criticalChance"],
            "attack_speed": p["attackSpeed"],
            "life_steal": p["lifeSteal"],
            "armor": p["armor"],
            "magic_resistance": p["magicResistance"],
            "tenacity": p["tenacity"],
            "items": list(p["items"]),
        }
        for p in participants
    ]


def parse_window(game_id: str) -> pl.DataFrame:
    """Parse data/raw/livestats/window/<game_id>.jsonl.gz into a per-frame
    DataFrame at the feed's native (~1/sec) cadence -- see WINDOW_SCHEMA and
    the module docstring for column meanings and schema provenance.

    Empty (but correctly typed) DataFrame for a game with zero window
    frames. Streams the gzip via lake.read_jsonl_gz rather than materializing
    the raw text/JSON in bulk first.
    """
    path = lake.raw_path("livestats", "window", f"{game_id}.jsonl.gz")
    rows: list[dict] = []
    for rec in lake.read_jsonl_gz(path):
        ts_raw = rec.get("rfc460Timestamp")
        if not ts_raw:
            continue
        blue = rec["blueTeam"]
        red = rec["redTeam"]
        rows.append(
            {
                "game_id": game_id,
                "ts": _parse_ts(ts_raw),
                "game_state": rec.get("gameState"),
                "blue_gold": blue["totalGold"],
                "blue_kills": blue["totalKills"],
                "blue_towers": blue["towers"],
                "blue_inhibitors": blue["inhibitors"],
                "blue_barons": blue["barons"],
                "blue_dragon_types": list(blue["dragons"]),
                "blue_players": _window_players(blue["participants"], "blue"),
                "red_gold": red["totalGold"],
                "red_kills": red["totalKills"],
                "red_towers": red["towers"],
                "red_inhibitors": red["inhibitors"],
                "red_barons": red["barons"],
                "red_dragon_types": list(red["dragons"]),
                "red_players": _window_players(red["participants"], "red"),
            }
        )

    raw_schema = {
        k: v for k, v in WINDOW_SCHEMA.items() if k not in ("is_paused", "game_clock_s")
    }
    # drop the derived-only columns from the pre-derivation frame
    derived_cols = (
        "blue_dragon_count",
        "blue_soul_point",
        "red_dragon_count",
        "red_soul_point",
        "gold_diff",
        "kill_diff",
    )
    for derived in derived_cols:
        raw_schema.pop(derived, None)

    if not rows:
        return pl.DataFrame(schema=WINDOW_SCHEMA)

    df = pl.DataFrame(rows, schema=raw_schema).sort("ts")
    return _add_derived_window_columns(df)


def _add_derived_window_columns(df: pl.DataFrame) -> pl.DataFrame:
    """Add game_clock_s (cumulative in-game time, pause/gap-excluded),
    is_paused, dragon count/soul flags, and the gold/kill diffs.

    game_clock_s approximation (documented per the brief): walk consecutive
    frames and sum the wall-clock delta between them, EXCEPT when either
    endpoint of that delta is not `in_game` (i.e. the frame itself is
    `paused`, or is the first frame after a pause/gap) -- that delta is
    dropped entirely rather than counted. This is an approximation (the true
    resume instant within a `paused -> in_game` wall gap is unknown -- we
    just treat the whole gap as excluded, verified against a real pause to
    land within ~0.5s of the correct excluded duration), but is the
    documented brief request: "game_clock_s ... so models see game time,
    not wall time."
    """
    df = df.with_columns(
        _prev_ts=pl.col("ts").shift(1),
        _prev_state=pl.col("game_state").shift(1),
    )
    df = df.with_columns(
        _delta_s=(pl.col("ts") - pl.col("_prev_ts")).dt.total_milliseconds() / 1000.0
    )
    df = df.with_columns(
        _counted_delta=pl.when(
            (pl.col("game_state") == "in_game") & (pl.col("_prev_state") == "in_game")
        )
        .then(pl.col("_delta_s"))
        .otherwise(0.0)
        .fill_null(0.0)
    )
    df = df.with_columns(game_clock_s=pl.col("_counted_delta").cum_sum().round(3))
    df = df.drop(["_prev_ts", "_prev_state", "_delta_s", "_counted_delta"])

    df = df.with_columns(
        is_paused=pl.col("game_state") == "paused",
        gold_diff=pl.col("blue_gold") - pl.col("red_gold"),
        kill_diff=pl.col("blue_kills") - pl.col("red_kills"),
        blue_dragon_count=pl.col("blue_dragon_types").list.len().cast(pl.Int64),
        red_dragon_count=pl.col("red_dragon_types").list.len().cast(pl.Int64),
    )
    # Dragon soul: a team keeps a permanent buff once it has taken 4
    # elemental drakes this game -- "elder" doesn't count toward it (elder is
    # only obtainable AFTER a soul is already held, but excluding it from the
    # count is correct either way).
    df = df.with_columns(
        blue_soul_point=(
            pl.col("blue_dragon_types").list.eval(pl.element() != "elder").list.sum() >= 4
        ),
        red_soul_point=(
            pl.col("red_dragon_types").list.eval(pl.element() != "elder").list.sum() >= 4
        ),
    )
    return df.select(list(WINDOW_SCHEMA.keys()))


def parse_details(game_id: str) -> pl.DataFrame:
    """Parse data/raw/livestats/details/<game_id>.jsonl.gz into a per-frame
    DataFrame (native cadence): game_id, ts, players (nested list[struct] of
    the 10 participants' granular stats -- items, wards, damage share, combat
    stats; see DETAILS_PLAYER_STRUCT). Empty (but correctly typed) for a game
    with zero details frames.

    Not currently merged into the tidy 10s output (see downsample_tidy) --
    exposed here as its own DataFrame per the brief's deliverable list, ready
    for a future pass that wants per-frame item/ward/damage data.
    """
    path = lake.raw_path("livestats", "details", f"{game_id}.jsonl.gz")
    rows: list[dict] = []
    for rec in lake.read_jsonl_gz(path):
        ts_raw = rec.get("rfc460Timestamp")
        if not ts_raw:
            continue
        rows.append(
            {
                "game_id": game_id,
                "ts": _parse_ts(ts_raw),
                "players": _details_players(rec.get("participants") or []),
            }
        )
    if not rows:
        return pl.DataFrame(schema=DETAILS_SCHEMA)
    return pl.DataFrame(rows, schema=DETAILS_SCHEMA).sort("ts")


def downsample_tidy(window_df: pl.DataFrame, game_id: str) -> pl.DataFrame:
    """Downsample a full-cadence parse_window() DataFrame to one row per
    (game_id, ts_bucket), ts_bucket = ts truncated to a 10s wall-clock
    boundary.

    Keeps the FIRST frame observed in each new 10s bucket (i.e. "the frame
    whose ts crosses the boundary"), except the final bucket, which always
    gets the true LAST frame of the game regardless of how many frames
    landed in that bucket first (per the brief: "also always keep the final
    frame"). A bucket with no frames at all (e.g. every 10s slot inside a
    real pause gap, where the feed emits nothing) simply has no row -- rows
    are not fabricated for silent gaps.

    Per-player detail is the nested `players` column, concatenating window's
    blue_players + red_players (10 entries/row) -- NOT enriched with
    /details' items/wards/damage here. /window and /details are frame-
    aligned closely enough that an exact-timestamp join would work for most
    rows, but merging fields INTO the nested list-of-struct elements
    (matching by participant_id inside each list) needs a list-level
    zip/join that's fragile to get right in v0; parse_details() remains
    available standalone for a future pass instead of risking a subtly wrong
    merge here.
    """
    if window_df.height == 0:
        return pl.DataFrame(schema=TIDY_SCHEMA).select(_TIDY_COLUMN_ORDER)

    df = window_df.with_columns(pl.col("ts").dt.truncate(f"{BUCKET_SECONDS}s").alias("ts_bucket"))
    kept = df.group_by("ts_bucket", maintain_order=True).agg(pl.all().exclude("ts_bucket").first())

    final_row = df.tail(1)
    final_bucket = final_row["ts_bucket"][0]
    kept = kept.filter(pl.col("ts_bucket") != final_bucket)
    kept = pl.concat([kept, final_row], how="diagonal_relaxed").sort("ts_bucket")

    kept = kept.with_columns(
        players=pl.concat_list(["blue_players", "red_players"]),
        game_id=pl.lit(game_id),
    )
    return kept.select(_TIDY_COLUMN_ORDER)


def extract_objective_events(window_df: pl.DataFrame, game_id: str) -> pl.DataFrame:
    """Infer discrete objective events from count deltas between consecutive
    FULL-resolution /window frames (NOT the downsampled tidy rows -- see
    below for why).

    Scoped to the four structural/epic-monster objectives that exist in this
    feed's schema: dragon, tower, inhibitor, baron (see module docstring:
    grubs/herald are never present in the observed schema, and player kills
    are intentionally excluded -- already covered by tidy's kill_diff).

    Dragon rows always carry the exact flavor taken (dragons is an
    append-only list, so a delta of N new entries is exactly N known type
    strings) and always have count=1 -- one row per dragon, by construction,
    which is what makes "dragon count in the final frame == number of dragon
    event rows" a valid sanity check. Tower/inhibitor/baron rows carry the
    raw magnitude of the observed increment in `count` (usually 1); a
    `simultaneous`=True flag marks any single observed step that jumped by
    more than one (a real double-kill-style burst, or -- for these four
    counters, rare -- two towers falling within the same ~1s poll). Summing
    `count` (not counting rows) is what telescopes exactly to the final
    frame's totals when a burst occurred.

    Approximate by construction (brief-acknowledged): a burst's true
    sub-second ordering/timing is not recoverable from this feed, only that
    it happened within one observed step.

    Runs on the FULL raw-cadence series (not the 10s tidy rows) specifically
    because downsampling can silently drop the frame where an objective was
    actually taken (observed on real data: a dragon picked up mid-bucket,
    with an earlier frame in the same bucket kept as the tidy row, so the
    tidy row alone would show the dragon one bucket "late" and ~2-3s off).
    Full resolution gives the precise game_clock_s of the increment.
    """
    schema = dict(EVENTS_SCHEMA)
    if window_df.height < 2:
        return pl.DataFrame(schema=schema)

    events: list[dict] = []
    prev: dict | None = None
    for row in window_df.iter_rows(named=True):
        if prev is not None:
            for team in ("blue", "red"):
                prev_dragons = prev[f"{team}_dragon_types"]
                cur_dragons = row[f"{team}_dragon_types"]
                if len(cur_dragons) > len(prev_dragons):
                    new_types = cur_dragons[len(prev_dragons):]
                    simultaneous = len(new_types) > 1
                    for dragon_type in new_types:
                        events.append(
                            {
                                "game_id": game_id,
                                "game_clock_s": row["game_clock_s"],
                                "ts": row["ts"],
                                "type": "dragon",
                                "killer_team": team,
                                "dragon_type": dragon_type,
                                "count": 1,
                                "simultaneous": simultaneous,
                            }
                        )
                for field, ev_type in _OBJECTIVE_COUNTERS:
                    delta = row[f"{team}_{field}"] - prev[f"{team}_{field}"]
                    if delta > 0:
                        events.append(
                            {
                                "game_id": game_id,
                                "game_clock_s": row["game_clock_s"],
                                "ts": row["ts"],
                                "type": ev_type,
                                "killer_team": team,
                                "dragon_type": None,
                                "count": delta,
                                "simultaneous": delta > 1,
                            }
                        )
        prev = row

    if not events:
        return pl.DataFrame(schema=schema)
    return pl.DataFrame(events, schema=schema)


def list_archived_game_ids() -> list[str]:
    """Game ids with a raw /window archive on disk (any state -- finished,
    partial, or still growing; existence of the raw file is the only
    criterion, matching normalize-frames' own "archived" definition)."""
    window_dir = lake.raw_path("livestats", "window")
    if not window_dir.exists():
        return []
    return sorted(
        p.name.removesuffix(".jsonl.gz") for p in window_dir.glob("*.jsonl.gz")
    )


def list_normalized_game_ids() -> list[str]:
    """Game ids that already have a tidy frames parquet on disk."""
    frames_dir = lake.processed_path("frames")
    if not frames_dir.exists():
        return []
    return sorted(p.stem for p in frames_dir.glob("*.parquet"))


def games_pending_normalization(limit: int | None = None) -> list[str]:
    """Archived game ids lacking a normalized frames parquet, oldest-id-order
    first. Idempotency is via output existence (a normalize-frames rerun
    never reprocesses a game that already has a frames parquet, even if its
    raw archive has since grown further -- see brief)."""
    normalized = set(list_normalized_game_ids())
    pending = [g for g in list_archived_game_ids() if g not in normalized]
    return pending[:limit] if limit is not None else pending


@dataclass
class NormalizeResult:
    game_id: str
    skipped: bool
    window_frames: int
    details_frames: int
    tidy_rows: int
    event_count: int
    elapsed_s: float


def normalize_game(game_id: str, *, force: bool = False) -> NormalizeResult:
    """Normalize one game's raw livestats archive to
    data/processed/frames/<game_id>.parquet (tidy 10s rows) and
    data/processed/objective_events/<game_id>.parquet.

    Idempotent via output existence: a game whose frames parquet already
    exists is skipped outright unless force=True (matches archive_game's own
    idempotency style in ingest/livestats.py)."""
    frames_path = lake.processed_path("frames", f"{game_id}.parquet")
    events_path = lake.processed_path("objective_events", f"{game_id}.parquet")

    if not force and frames_path.exists():
        tidy = pl.read_parquet(frames_path)
        events = (
            pl.read_parquet(events_path)
            if events_path.exists()
            else pl.DataFrame(schema=EVENTS_SCHEMA)
        )
        return NormalizeResult(
            game_id=game_id,
            skipped=True,
            window_frames=0,
            details_frames=0,
            tidy_rows=tidy.height,
            event_count=events.height,
            elapsed_s=0.0,
        )

    t0 = time.monotonic()
    window_df = parse_window(game_id)
    details_df = parse_details(game_id)
    tidy_df = downsample_tidy(window_df, game_id)
    events_df = extract_objective_events(window_df, game_id)

    frames_path.parent.mkdir(parents=True, exist_ok=True)
    events_path.parent.mkdir(parents=True, exist_ok=True)
    tidy_df.write_parquet(frames_path)
    events_df.write_parquet(events_path)
    elapsed = time.monotonic() - t0

    return NormalizeResult(
        game_id=game_id,
        skipped=False,
        window_frames=window_df.height,
        details_frames=details_df.height,
        tidy_rows=tidy_df.height,
        event_count=events_df.height,
        elapsed_s=elapsed,
    )
