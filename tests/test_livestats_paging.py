"""Paging/rounding/termination logic for the livestats connector.

All network-free: `_paginate` takes a plain callable, so these feed it canned
frame batches instead of hitting feed.lolesports.com.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from riftquant import config
from riftquant.ingest import livestats


def _dt(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def _done_marker(game_id: str) -> Path:
    path = config.DATA_RAW / "livestats" / "window" / f"{game_id}.jsonl.gz"
    return path.with_name(path.name + ".done")


def test_next_starting_time_rounds_down_to_10s() -> None:
    ts = _dt(2026, 1, 1, 0, 0, 21, 438000)
    assert livestats._next_starting_time(ts) == _dt(2026, 1, 1, 0, 0, 30)


def test_next_starting_time_none_when_no_prior_frame() -> None:
    assert livestats._next_starting_time(None) is None


def test_paginate_stops_on_finished_frame() -> None:
    pages = [
        {"frames": [{"rfc460Timestamp": "2026-01-01T00:00:00Z", "gameState": "in_game"}]},
        {"frames": [{"rfc460Timestamp": "2026-01-01T00:00:10Z", "gameState": "finished"}]},
        {"frames": [{"rfc460Timestamp": "2026-01-01T00:00:20Z", "gameState": "in_game"}]},
    ]
    calls: list[datetime | None] = []

    def fetch_page(starting_time: datetime | None) -> dict:
        calls.append(starting_time)
        return pages[len(calls) - 1]

    frames = list(livestats._paginate(fetch_page, None, sleep_secs=0))

    assert [f["rfc460Timestamp"] for f in frames] == [
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:00:10Z",
    ]
    assert len(calls) == 2  # the third (post-finished) page must never be fetched


def test_paginate_stops_when_timestamp_stalls() -> None:
    # A pager that never signals "finished" but also never advances must
    # still terminate (defends against a game that ends without that flag).
    stalled_page = {"frames": [{"rfc460Timestamp": "2026-01-01T00:00:00Z", "gameState": "in_game"}]}

    def fetch_page(_starting_time: datetime | None) -> dict:
        return stalled_page

    frames = list(livestats._paginate(fetch_page, None, sleep_secs=0))
    assert len(frames) == 1


def test_paginate_stops_after_two_empty_pages() -> None:
    def fetch_page(_starting_time: datetime | None) -> dict:
        return {"frames": []}

    assert list(livestats._paginate(fetch_page, None, sleep_secs=0)) == []


def test_paginate_survives_pause_gap() -> None:
    """Regression: an in-game pause leaves a hole in the feed (observed live,
    Worlds 2025 game 113475493522604199 stalled at 126 frames with the old
    two-strike pager). The pager must probe forward through the silence and
    pick the game back up."""
    t0 = "2026-01-01T00:00:00Z"
    resume_ts = "2026-01-01T00:01:30Z"  # 90s hole: 8 empty probes to cross

    def fetch_page(starting_time: datetime | None) -> dict:
        if starting_time is None:
            return {"frames": [{"rfc460Timestamp": t0, "gameState": "in_game"}]}
        if starting_time < _dt(2026, 1, 1, 0, 1, 30):
            return {"frames": []}  # inside the pause hole
        return {
            "frames": [
                {"rfc460Timestamp": resume_ts, "gameState": "in_game"},
                {"rfc460Timestamp": "2026-01-01T00:01:40Z", "gameState": "finished"},
            ]
        }

    frames = list(livestats._paginate(fetch_page, None, sleep_secs=0))
    assert [f["rfc460Timestamp"] for f in frames] == [
        t0,
        resume_ts,
        "2026-01-01T00:01:40Z",
    ]


def test_paginate_gives_up_after_max_gap() -> None:
    """A feed that goes permanently silent (game ended without a `finished`
    frame) must still terminate once the MAX_GAP_SECS patience runs out."""
    def fetch_page(starting_time: datetime | None) -> dict:
        if starting_time is None:
            return {"frames": [{"rfc460Timestamp": "2026-01-01T00:00:00Z", "gameState": "in_game"}]}
        return {"frames": []}

    frames = list(livestats._paginate(fetch_page, None, sleep_secs=0))
    assert len(frames) == 1


def test_paginate_yields_only_new_frames_on_overlap() -> None:
    """Server windows can overlap the resume point; already-seen frames must
    not be re-yielded."""
    def fetch_page(starting_time: datetime | None) -> dict:
        if starting_time == _dt(2026, 1, 1, 0, 0, 10):
            return {
                "frames": [
                    {"rfc460Timestamp": "2026-01-01T00:00:00Z", "gameState": "in_game"},
                    {"rfc460Timestamp": "2026-01-01T00:00:12Z", "gameState": "finished"},
                ]
            }
        return {"frames": []}

    from_ts = _dt(2026, 1, 1, 0, 0, 0)
    frames = list(livestats._paginate(fetch_page, from_ts, sleep_secs=0))
    assert [f["rfc460Timestamp"] for f in frames] == ["2026-01-01T00:00:12Z"]


def test_paginate_resumes_from_from_ts() -> None:
    seen: list[datetime | None] = []

    def fetch_page(starting_time: datetime | None) -> dict:
        seen.append(starting_time)
        return {"frames": []}

    from_ts = _dt(2026, 1, 1, 0, 5, 4)
    list(livestats._paginate(fetch_page, from_ts, sleep_secs=0))

    assert seen[0] == _dt(2026, 1, 1, 0, 5, 10)


def test_paginate_stop_at_truncates_mid_batch() -> None:
    page = {
        "frames": [
            {"rfc460Timestamp": "2026-01-01T00:00:00Z"},
            {"rfc460Timestamp": "2026-01-01T00:00:05Z"},
            {"rfc460Timestamp": "2026-01-01T00:00:09Z"},
        ]
    }
    calls: list[datetime | None] = []

    def fetch_page(starting_time: datetime | None) -> dict:
        calls.append(starting_time)
        return page if len(calls) == 1 else {"frames": []}

    stop_at = _dt(2026, 1, 1, 0, 0, 5)
    frames = list(
        livestats._paginate(fetch_page, None, sleep_secs=0, stop_on_finished=False, stop_at=stop_at)
    )

    assert [f["rfc460Timestamp"] for f in frames] == [
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:00:05Z",
    ]
    assert len(calls) == 1  # stopped mid-batch; the second page is never fetched


def test_archive_game_is_idempotent(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "DATA_RAW", tmp_path / "raw")
    frames = [
        {"rfc460Timestamp": "2026-01-01T00:00:00Z", "gameState": "in_game"},
        {"rfc460Timestamp": "2026-01-01T00:00:10Z", "gameState": "finished"},
    ]
    calls = {"window": 0, "details": 0}

    def fake_window(_game_id: str, from_ts=None):
        calls["window"] += 1
        yield from frames

    def fake_details(_game_id: str, from_ts=None, stop_at=None):
        calls["details"] += 1
        return iter(())

    monkeypatch.setattr(livestats, "fetch_window_frames", fake_window)
    monkeypatch.setattr(livestats, "fetch_details_frames", fake_details)

    result1 = livestats.archive_game("game123")
    assert result1 == livestats.ArchiveResult(
        game_id="game123", skipped=False, finished=True, window_frames=2, details_frames=0
    )
    assert calls["window"] == 1

    result2 = livestats.archive_game("game123")
    assert result2.skipped is True
    assert result2.window_frames == 2
    assert calls["window"] == 1  # unchanged: proves the second run skipped, not re-fetched


def test_archive_game_marks_done_on_stale_end(tmp_path, monkeypatch) -> None:
    """A historical game whose feed ended WITHOUT a `finished` frame (last
    frame older than STALE_END_AGE) must get a done marker, or every future
    run re-spends the full gap-patience budget on it (observed live:
    Worlds 2025 AL vs HLE)."""
    monkeypatch.setattr(config, "DATA_RAW", tmp_path / "raw")
    old_frames = [
        {"rfc460Timestamp": "2025-10-15T10:20:29.303Z", "gameState": "in_game"},
        {"rfc460Timestamp": "2025-10-15T11:01:47.625Z", "gameState": "in_game"},
    ]
    monkeypatch.setattr(livestats, "fetch_window_frames", lambda *a, **k: iter(old_frames))
    monkeypatch.setattr(livestats, "fetch_details_frames", lambda *a, **k: iter(()))

    result = livestats.archive_game("staleend1")
    assert result.finished is False
    assert result.stale_end is True
    assert result.window_frames == 2
    assert _done_marker("staleend1").exists()

    result2 = livestats.archive_game("staleend1")
    assert result2.skipped is True


def test_archive_game_no_done_marker_when_recent_and_unfinished(tmp_path, monkeypatch) -> None:
    """A game whose frames are RECENT (possibly live/paused) and unfinished
    must NOT be marked done -- resuming later is the correct behavior."""
    from datetime import UTC, datetime, timedelta

    monkeypatch.setattr(config, "DATA_RAW", tmp_path / "raw")
    recent = (datetime.now(UTC) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    frames = [{"rfc460Timestamp": recent, "gameState": "in_game"}]
    monkeypatch.setattr(livestats, "fetch_window_frames", lambda *a, **k: iter(frames))
    monkeypatch.setattr(livestats, "fetch_details_frames", lambda *a, **k: iter(()))

    result = livestats.archive_game("liveish1")
    assert result.finished is False
    assert result.stale_end is False
    assert not _done_marker("liveish1").exists()


def test_archive_game_marks_done_when_never_played(tmp_path, monkeypatch) -> None:
    """A game id with zero frames ever (unplayed placeholder) must still get
    a done marker, or archive-frames would retry it forever."""
    monkeypatch.setattr(config, "DATA_RAW", tmp_path / "raw")
    monkeypatch.setattr(livestats, "fetch_window_frames", lambda *a, **k: iter(()))
    monkeypatch.setattr(livestats, "fetch_details_frames", lambda *a, **k: iter(()))

    result = livestats.archive_game("unplayed1")
    assert result.finished is False
    assert result.window_frames == 0
    assert _done_marker("unplayed1").exists()
