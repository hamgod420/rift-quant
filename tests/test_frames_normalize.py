"""riftquant/frames/normalize.py: game_clock_s (pause exclusion), 10s
downsampling boundary logic, objective-event delta extraction, idempotent
skip.

Fixture frames below are trimmed-but-verbatim excerpts of TWO real spans
from game 113475493522604199 (Worlds 2025, the game with a genuine mid-game
pause -- see docs/specs/M4a-frames-normalizer-brief.md and the normalize.py
module docstring for the full schema notes this was built against):
  - frames at raw archive index 116-128 (a real ~1min stretch spanning the
    actual pause: one 'paused' frame at 09:17:24.472Z, then the feed goes
    silent for ~107s before resuming).
  - frames at raw archive index 1378-1389 (a real dragon pickup: blue's
    dragons list gains 'infernal' between index 1380 and 1381).
Team-level fields (timestamps, gameState, gold/kills/towers/inhibitors/
barons/dragons) are the real observed values. Per-player participant stats
are NOT the real per-player values (10 players x 25 frames of real detail
would dwarf the point of the test) -- they are a constant placeholder shape,
since no test here asserts on individual player stats, only on team-level
deltas/timing and on the nested players list having the right shape/length.
"""

from __future__ import annotations

from datetime import datetime

import polars as pl

from riftquant import config
from riftquant.frames import normalize
from riftquant.store import lake


def _placeholder_participants(start_id: int) -> list[dict]:
    return [
        {
            "participantId": start_id + i,
            "totalGold": 0,
            "level": 1,
            "kills": 0,
            "deaths": 0,
            "assists": 0,
            "creepScore": 0,
            "currentHealth": 100,
            "maxHealth": 100,
        }
        for i in range(5)
    ]


def _frame(
    ts: str,
    state: str,
    blue: tuple[int, int, int, int, int, list[str]],
    red: tuple[int, int, int, int, int, list[str]],
) -> dict:
    """blue/red = (gold, kills, towers, inhibitors, barons, dragons)."""
    bg, bk, bt, bi, bb, bd = blue
    rg, rk, rt, ri, rb, rd = red
    return {
        "rfc460Timestamp": ts,
        "gameState": state,
        "blueTeam": {
            "totalGold": bg,
            "totalKills": bk,
            "towers": bt,
            "inhibitors": bi,
            "barons": bb,
            "dragons": bd,
            "participants": _placeholder_participants(1),
        },
        "redTeam": {
            "totalGold": rg,
            "totalKills": rk,
            "towers": rt,
            "inhibitors": ri,
            "barons": rb,
            "dragons": rd,
            "participants": _placeholder_participants(6),
        },
    }


# Real archive index 116-124: pre-pause, nothing has happened yet (spawn
# gold only). Index 125: the real 'paused' frame. Index 126-128: resume.
_NOTHING_BLUE = (2500, 0, 0, 0, 0, [])
_NOTHING_RED = (2500, 0, 0, 0, 0, [])
PAUSE_SPAN_FRAMES = [
    _frame("2025-10-14T09:17:18.056Z", "in_game", _NOTHING_BLUE, _NOTHING_RED),  # idx116
    _frame("2025-10-14T09:17:18.724Z", "in_game", _NOTHING_BLUE, _NOTHING_RED),  # idx117
    _frame("2025-10-14T09:17:19.025Z", "in_game", _NOTHING_BLUE, _NOTHING_RED),  # idx118
    _frame("2025-10-14T09:17:20.027Z", "in_game", _NOTHING_BLUE, _NOTHING_RED),  # idx119
    _frame("2025-10-14T09:17:20.829Z", "in_game", _NOTHING_BLUE, _NOTHING_RED),  # idx120
    _frame("2025-10-14T09:17:21.030Z", "in_game", _NOTHING_BLUE, _NOTHING_RED),  # idx121
    _frame("2025-10-14T09:17:22.034Z", "in_game", _NOTHING_BLUE, _NOTHING_RED),  # idx122
    _frame("2025-10-14T09:17:23.036Z", "in_game", _NOTHING_BLUE, _NOTHING_RED),  # idx123
    _frame("2025-10-14T09:17:24.038Z", "in_game", _NOTHING_BLUE, _NOTHING_RED),  # idx124
    _frame("2025-10-14T09:17:24.472Z", "paused", _NOTHING_BLUE, _NOTHING_RED),  # idx125, pause
    _frame("2025-10-14T09:19:11.666Z", "in_game", _NOTHING_BLUE, _NOTHING_RED),  # idx126, resume
    _frame("2025-10-14T09:19:12.235Z", "in_game", _NOTHING_BLUE, _NOTHING_RED),  # idx127
    _frame("2025-10-14T09:19:13.237Z", "in_game", _NOTHING_BLUE, _NOTHING_RED),  # idx128
]

# Real archive index 1378-1389: blue picks up the 'infernal' dragon between
# idx1380 (dragons=[]) and idx1381 (dragons=['infernal']). Note the feed's
# real burst behavior: idx1382-1384 share the identical timestamp
# 09:25:37.281Z.
_PRE_DRAGON_BLUE = (11741, 1, 0, 0, 0, [])
_POST_DRAGON_BLUE = (11741, 1, 0, 0, 0, ["infernal"])
_POST_DRAGON_BLUE_1387 = (11779, 1, 0, 0, 0, ["infernal"])
_POST_DRAGON_BLUE_1388 = (11803, 1, 0, 0, 0, ["infernal"])
_DRAGON_RED = (10641, 0, 0, 0, 0, [])
DRAGON_SPAN_FRAMES = [
    _frame("2025-10-14T09:25:37.244Z", "in_game", _PRE_DRAGON_BLUE, _DRAGON_RED),  # idx1378
    _frame("2025-10-14T09:25:37.278Z", "in_game", _PRE_DRAGON_BLUE, _DRAGON_RED),  # idx1379
    _frame("2025-10-14T09:25:37.279Z", "in_game", _PRE_DRAGON_BLUE, _DRAGON_RED),  # idx1380
    _frame("2025-10-14T09:25:37.280Z", "in_game", _POST_DRAGON_BLUE, _DRAGON_RED),  # idx1381 pickup
    _frame("2025-10-14T09:25:37.281Z", "in_game", _POST_DRAGON_BLUE, _DRAGON_RED),  # idx1382
    _frame("2025-10-14T09:25:37.281Z", "in_game", _POST_DRAGON_BLUE, _DRAGON_RED),  # idx1383
    _frame("2025-10-14T09:25:37.281Z", "in_game", _POST_DRAGON_BLUE, _DRAGON_RED),  # idx1384
    _frame("2025-10-14T09:25:37.410Z", "in_game", _POST_DRAGON_BLUE, _DRAGON_RED),  # idx1385
    _frame("2025-10-14T09:25:37.844Z", "in_game", _POST_DRAGON_BLUE, _DRAGON_RED),  # idx1386
    _frame("2025-10-14T09:25:38.246Z", "in_game", _POST_DRAGON_BLUE_1387, _DRAGON_RED),  # idx1387
    _frame("2025-10-14T09:25:39.248Z", "in_game", _POST_DRAGON_BLUE_1388, _DRAGON_RED),  # idx1388
    _frame("2025-10-14T09:25:40.049Z", "in_game", _POST_DRAGON_BLUE_1388, _DRAGON_RED),  # idx1389
]

# One spliced fixture: both real spans, in their real chronological order,
# from the SAME real game -- just omitting the ~1250 real frames between
# them. This is a truthful (if incomplete) real ordered sub-sequence, not a
# fabricated timeline: the omitted middle span is genuinely long (~384s)
# real in-game time, which game_clock_s below correctly counts (contrast
# with the true ~107.6s PAUSE gap inside PAUSE_SPAN_FRAMES, which it must
# NOT count).
ALL_FIXTURE_FRAMES = PAUSE_SPAN_FRAMES + DRAGON_SPAN_FRAMES


def _write_window_fixture(game_id: str, frames: list[dict]) -> None:
    path = lake.raw_path("livestats", "window", f"{game_id}.jsonl.gz")
    lake.append_jsonl_gz(path, frames)


def _dt(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def test_parse_window_missing_file_is_empty_with_correct_schema(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "DATA_RAW", tmp_path / "raw")
    df = normalize.parse_window("nope")
    assert df.height == 0
    assert df.schema == pl.Schema(normalize.WINDOW_SCHEMA)


def test_parse_window_game_clock_excludes_pause_but_counts_omitted_span(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(config, "DATA_RAW", tmp_path / "raw")
    game_id = "pause_dragon_fixture"
    _write_window_fixture(game_id, ALL_FIXTURE_FRAMES)

    df = normalize.parse_window(game_id)
    assert df.height == len(ALL_FIXTURE_FRAMES) == 25

    by_ts = {row["ts"]: row for row in df.iter_rows(named=True)}
    paused_row = by_ts[_dt("2025-10-14T09:17:24.472Z")]
    resume_row = by_ts[_dt("2025-10-14T09:19:11.666Z")]
    assert paused_row["game_state"] == "paused"
    assert paused_row["is_paused"] is True
    # The real ~107.6s pause gap (paused frame -> resumed frame) must be
    # fully excluded from game_clock_s: both endpoints show the same value.
    assert paused_row["game_clock_s"] == resume_row["game_clock_s"]

    last_before_gap = by_ts[_dt("2025-10-14T09:19:13.237Z")]
    first_after_gap = by_ts[_dt("2025-10-14T09:25:37.244Z")]
    wall_gap = (
        _dt("2025-10-14T09:25:37.244Z") - _dt("2025-10-14T09:19:13.237Z")
    ).total_seconds()
    clock_gap = first_after_gap["game_clock_s"] - last_before_gap["game_clock_s"]
    # Contrast case: the ~384s span we spliced OVER is real in_game time on
    # both sides (no pause/gameState change) -- unlike the true pause, this
    # elapsed wall time must be counted, not excluded.
    assert wall_gap == 384.007
    assert abs(clock_gap - wall_gap) < 0.01


def test_parse_window_is_paused_flags_exactly_one_frame(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "DATA_RAW", tmp_path / "raw")
    game_id = "pause_only_fixture"
    _write_window_fixture(game_id, PAUSE_SPAN_FRAMES)

    df = normalize.parse_window(game_id)
    paused = df.filter(pl.col("is_paused"))
    assert paused.height == 1
    assert paused["game_state"][0] == "paused"


def test_parse_window_dragon_count_and_nested_players(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "DATA_RAW", tmp_path / "raw")
    game_id = "dragon_only_fixture"
    _write_window_fixture(game_id, DRAGON_SPAN_FRAMES)

    df = normalize.parse_window(game_id)
    final = df.tail(1).to_dicts()[0]
    assert final["blue_dragon_count"] == 1
    assert final["blue_dragon_types"] == ["infernal"]
    assert final["blue_soul_point"] is False  # needs 4, not 1
    assert len(final["blue_players"]) == 5
    assert len(final["red_players"]) == 5


def test_downsample_tidy_boundary_logic_and_final_frame_override(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "DATA_RAW", tmp_path / "raw")
    game_id = "pause_dragon_fixture"
    _write_window_fixture(game_id, ALL_FIXTURE_FRAMES)
    window_df = normalize.parse_window(game_id)

    tidy = normalize.downsample_tidy(window_df, game_id)

    # 5 distinct 10s wall-clock buckets actually touched by a real frame:
    # 09:17:10, 09:17:20 (absorbs the pause), 09:19:10 (the resume), and
    # 09:25:30 / 09:25:40 for the dragon span. No fabricated rows for the
    # empty buckets inside the pause hole (09:17:30..09:19:00).
    expected_buckets = [
        "2025-10-14T09:17:10Z",
        "2025-10-14T09:17:20Z",
        "2025-10-14T09:19:10Z",
        "2025-10-14T09:25:30Z",
        "2025-10-14T09:25:40Z",
    ]
    assert tidy["ts_bucket"].to_list() == [_dt(t) for t in expected_buckets]

    # "always keep the final frame": the literal last raw frame (idx1389,
    # 09:25:40.049Z) must be the representative row for its bucket, not
    # whatever frame happened to be first in that bucket (there's only one
    # frame in the 09:25:40 bucket here anyway, but this pins the rule).
    final_tidy_row = tidy.tail(1).to_dicts()[0]
    assert final_tidy_row["ts"] == _dt("2025-10-14T09:25:40.049Z")
    assert final_tidy_row["blue_dragon_count"] == 1

    # The 09:25:30 bucket keeps the FIRST frame observed in it (idx1378,
    # ts=09:25:37.244Z) -- which is BEFORE the dragon pickup at idx1381
    # (09:25:37.280Z, same bucket). So the tidy row for that bucket still
    # shows zero dragons, even though a dragon really was taken inside that
    # 10s window. This is real, observed, and is exactly why
    # extract_objective_events runs on the full-resolution series instead
    # of on these downsampled rows (see that function's docstring).
    bucket_25_30 = tidy.filter(pl.col("ts_bucket") == _dt("2025-10-14T09:25:30Z")).to_dicts()[0]
    assert bucket_25_30["ts"] == _dt("2025-10-14T09:25:37.244Z")
    assert bucket_25_30["blue_dragon_count"] == 0

    # nested per-player column: 10 entries (5 blue + 5 red), team-tagged.
    players = tidy["players"][0]
    assert len(players) == 10
    assert {p["team"] for p in players} == {"blue", "red"}


def test_downsample_tidy_empty_input() -> None:
    empty = pl.DataFrame(schema=normalize.WINDOW_SCHEMA)
    tidy = normalize.downsample_tidy(empty, "nope")
    assert tidy.height == 0
    assert tidy.columns == normalize._TIDY_COLUMN_ORDER


def test_extract_objective_events_precise_timing_and_scoped_to_structures(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(config, "DATA_RAW", tmp_path / "raw")
    game_id = "pause_dragon_fixture"
    _write_window_fixture(game_id, ALL_FIXTURE_FRAMES)
    window_df = normalize.parse_window(game_id)

    events = normalize.extract_objective_events(window_df, game_id)

    # Nothing else changes across this fixture (towers/inhibitors/barons/
    # kills are flat throughout both real spans) -- the dragon pickup is the
    # only increment, and player kills are deliberately out of scope (see
    # normalize.py's _OBJECTIVE_COUNTERS comment).
    assert events.height == 1
    event = events.to_dicts()[0]
    assert event["type"] == "dragon"
    assert event["killer_team"] == "blue"
    assert event["dragon_type"] == "infernal"
    assert event["count"] == 1
    assert event["simultaneous"] is False
    # Precise sub-bucket attribution: the true pickup frame (idx1381,
    # 09:25:37.280Z), NOT the 09:25:30 tidy bucket's representative frame
    # (idx1378, 09:25:37.244Z, which still shows zero dragons -- see the
    # downsample_tidy test above).
    assert event["ts"] == _dt("2025-10-14T09:25:37.280Z")


def test_extract_objective_events_flags_simultaneous_multi_increment(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(config, "DATA_RAW", tmp_path / "raw")
    game_id = "double_tower_fixture"
    frames = [
        _frame("2026-01-01T00:00:00Z", "in_game", (0, 0, 0, 0, 0, []), (0, 0, 0, 0, 0, [])),
        # two towers in one observed step
        _frame("2026-01-01T00:00:01Z", "in_game", (0, 0, 2, 0, 0, []), (0, 0, 0, 0, 0, [])),
    ]
    _write_window_fixture(game_id, frames)
    window_df = normalize.parse_window(game_id)

    events = normalize.extract_objective_events(window_df, game_id)
    assert events.height == 1
    row = events.to_dicts()[0]
    assert row["type"] == "tower" and row["killer_team"] == "blue"
    assert row["count"] == 2
    assert row["simultaneous"] is True


def test_extract_objective_events_empty_and_single_row_input(tmp_path, monkeypatch) -> None:
    empty = pl.DataFrame(schema=normalize.WINDOW_SCHEMA)
    assert normalize.extract_objective_events(empty, "nope").height == 0

    monkeypatch.setattr(config, "DATA_RAW", tmp_path / "raw")
    game_id = "single_frame_fixture"
    _write_window_fixture(game_id, PAUSE_SPAN_FRAMES[:1])
    single = normalize.parse_window(game_id)
    assert single.height == 1  # no prior frame to diff against -> no events possible
    assert normalize.extract_objective_events(single, game_id).height == 0


def test_parse_details_reads_items_and_stats(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "DATA_RAW", tmp_path / "raw")
    game_id = "details_fixture"
    frame = {
        "rfc460Timestamp": "2025-10-14T09:25:37.280Z",
        "participants": [
            {
                "participantId": 1,
                "level": 7,
                "kills": 0,
                "deaths": 0,
                "assists": 0,
                "totalGoldEarned": 2240,
                "creepScore": 52,
                "killParticipation": 0.0,
                "championDamageShare": 0.17850881287424636,
                "wardsPlaced": 3,
                "wardsDestroyed": 0,
                "attackDamage": 92,
                "abilityPower": 0,
                "criticalChance": 0.0,
                "attackSpeed": 116,
                "lifeSteal": 0,
                "armor": 81,
                "magicResistance": 41,
                "tenacity": 0.0,
                "items": [1054, 3340, 2031, 3047],
            }
        ],
    }
    path = lake.raw_path("livestats", "details", f"{game_id}.jsonl.gz")
    lake.append_jsonl_gz(path, [frame])

    df = normalize.parse_details(game_id)
    assert df.height == 1
    player = df["players"][0][0]
    assert player["participant_id"] == 1
    assert player["items"] == [1054, 3340, 2031, 3047]
    assert player["total_gold_earned"] == 2240


def test_normalize_game_idempotent_skip(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "DATA_RAW", tmp_path / "raw")
    monkeypatch.setattr(config, "DATA_PROCESSED", tmp_path / "processed")
    game_id = "idempotent_fixture"
    _write_window_fixture(game_id, PAUSE_SPAN_FRAMES)

    calls = {"n": 0}
    real_parse_window = normalize.parse_window

    def counting_parse_window(gid: str) -> pl.DataFrame:
        calls["n"] += 1
        return real_parse_window(gid)

    monkeypatch.setattr(normalize, "parse_window", counting_parse_window)

    result1 = normalize.normalize_game(game_id)
    assert result1.skipped is False
    assert result1.tidy_rows > 0
    assert calls["n"] == 1

    result2 = normalize.normalize_game(game_id)
    assert result2.skipped is True
    assert result2.tidy_rows == result1.tidy_rows
    assert result2.event_count == result1.event_count
    assert calls["n"] == 1  # unchanged: proves the second run never re-parsed

    assert lake.processed_path("frames", f"{game_id}.parquet").exists()
    assert lake.processed_path("objective_events", f"{game_id}.parquet").exists()


def test_games_pending_normalization_and_status_helpers(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "DATA_RAW", tmp_path / "raw")
    monkeypatch.setattr(config, "DATA_PROCESSED", tmp_path / "processed")
    _write_window_fixture("game_a", PAUSE_SPAN_FRAMES)
    _write_window_fixture("game_b", DRAGON_SPAN_FRAMES)

    assert normalize.list_archived_game_ids() == ["game_a", "game_b"]
    assert normalize.list_normalized_game_ids() == []
    assert normalize.games_pending_normalization() == ["game_a", "game_b"]
    assert normalize.games_pending_normalization(limit=1) == ["game_a"]

    normalize.normalize_game("game_a")

    assert normalize.list_normalized_game_ids() == ["game_a"]
    assert normalize.games_pending_normalization() == ["game_b"]
