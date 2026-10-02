"""livestats feed connector: keyless frame paging + a resumable archiver.

Base https://feed.lolesports.com/livestats/v1. Verified live 2026-08-21 while
building this module:
  - `startingTime` must be RFC3339 rounded DOWN to a multiple of 10 seconds --
    an unaligned value gets HTTP 400.
  - A game id that was never played (see ingest/lolesports.py `has_vod`)
    returns HTTP 204 with no body from /window; http.get_json returns None
    for that.
  - Frame count per call is NOT a fixed 10: the bare (no startingTime) first
    call returned exactly 10 frames clustered at game start, but a later
    startingTime call returned 22 frames spanning ~9.4s of game time. Treat
    /window as returning "the next window of frames", of variable size, not a
    fixed page size. The pager below never assumes a count.
  - /window frames carry `gameState` (`in_game`, `finished`, ...); /details
    frames do not, so /details paging is bounded by `stop_at` (pass /window's
    already-discovered end time) rather than a state check.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from riftquant import config
from riftquant.http import get_json, new_client
from riftquant.store import lake

# Real games run ~180-400 window calls; gap-probing through in-game pauses
# (see _paginate) can add hundreds more on pause-heavy games, so the safety
# cap is generous. It guards against unbounded loops on unexpected server
# behavior, not a normal path.
MAX_PAGES = 5000

# An in-game pause produces a hole in the frame feed. Observed live at
# Worlds 2025 (game 113475493522604199): the feed went silent ~2min into a
# ~30min game and resumed later, which permanently stalled the original
# "two empty pages -> end of feed" pager at 126 frames. Tier-1 pauses can
# run very long (chronobreaks), so we probe forward linearly up to a full
# hour of silence before concluding the feed truly ended.
MAX_GAP_SECS = 3600

_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = new_client(config.USER_AGENT)
    return _client


def _parse_rfc460(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _round_down_10s(dt: datetime) -> datetime:
    return dt.replace(second=(dt.second // 10) * 10, microsecond=0)


def _format_starting_time(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _next_starting_time(last_ts: datetime | None) -> datetime | None:
    """None means 'no startingTime param' (the initial, from-game-start call).
    Otherwise: the next 10s-aligned boundary strictly after `last_ts`."""
    if last_ts is None:
        return None
    return _round_down_10s(last_ts + timedelta(seconds=10))


def _fetch_page(base_url: str, game_id: str, starting_time: datetime | None) -> dict | None:
    params = {"startingTime": _format_starting_time(starting_time)} if starting_time else None
    return get_json(_get_client(), f"{base_url}/{game_id}", params=params)


def _paginate(
    fetch_page: Callable[[datetime | None], dict | None],
    from_ts: datetime | None,
    *,
    sleep_secs: float = config.LIVESTATS_SLEEP_SECS,
    stop_on_finished: bool = True,
    stop_at: datetime | None = None,
) -> Iterator[dict]:
    """Core resumable pager shared by /window and /details.

    Yields frames in order (strictly newer than anything already yielded).
    Terminates when: a frame reports gameState == "finished" (only checked if
    `stop_on_finished`), a yielded frame reaches `stop_at`, the initial bare
    call finds no data at all (unplayed game id), or the feed stays silent
    past MAX_GAP_SECS of probing (true end of feed).

    Pause handling: in-game pauses leave holes in the feed. The server
    anchors each response window AT `startingTime` (verified live), so
    jumping the cursor forward could overshoot and silently drop frames --
    instead the probe anchor steps linearly (+10s per empty probe) until
    frames resume or the MAX_GAP_SECS patience budget runs out.
    """
    last_ts = from_ts  # newest frame actually yielded (or the resume point)
    cursor = from_ts  # probe anchor; advances through pause gaps too
    stalled_secs = 0.0
    bare_strikes = 0
    for _ in range(MAX_PAGES):
        starting_time = _next_starting_time(cursor)
        data = fetch_page(starting_time)
        frames = (data or {}).get("frames") or []
        new_frames = [
            f
            for f in frames
            if last_ts is None or _parse_rfc460(f["rfc460Timestamp"]) > last_ts
        ]
        if new_frames:
            stalled_secs = 0.0
            bare_strikes = 0
            for frame in new_frames:
                yield frame
                if stop_at is not None and _parse_rfc460(frame["rfc460Timestamp"]) >= stop_at:
                    return
            last_ts = max(_parse_rfc460(f["rfc460Timestamp"]) for f in new_frames)
            cursor = last_ts
            if stop_on_finished and any(
                f.get("gameState") == "finished" for f in new_frames
            ):
                return
        elif cursor is None:
            # Bare (no startingTime) call yielded nothing: unplayed/empty
            # game id (HTTP 204 path). One retry, then give up.
            bare_strikes += 1
            if bare_strikes >= 2:
                return
        else:
            cursor = cursor + timedelta(seconds=10)
            stalled_secs += 10.0
            if stalled_secs > MAX_GAP_SECS:
                return
        time.sleep(sleep_secs)


def fetch_window_frames(game_id: str, from_ts: datetime | None = None) -> Iterator[dict]:
    """Yield /window frames for `game_id`, oldest first, resuming after
    `from_ts` if given. Pages until gameState == "finished" or the feed
    stops advancing."""
    yield from _paginate(
        lambda st: _fetch_page(f"{config.LIVESTATS_BASE}/window", game_id, st),
        from_ts,
    )


def fetch_details_frames(
    game_id: str,
    from_ts: datetime | None = None,
    stop_at: datetime | None = None,
) -> Iterator[dict]:
    """Yield /details frames for `game_id`. /details carries no gameState, so
    termination relies on the feed going stale or on `stop_at` (pass the
    final timestamp already found via fetch_window_frames)."""
    yield from _paginate(
        lambda st: _fetch_page(f"{config.LIVESTATS_BASE}/details", game_id, st),
        from_ts,
        stop_on_finished=False,
        stop_at=stop_at,
    )


def _last_timestamp(path: Path) -> datetime | None:
    last = None
    for rec in lake.read_jsonl_gz(path):
        ts = rec.get("rfc460Timestamp")
        if not ts:
            continue
        parsed = _parse_rfc460(ts)
        if last is None or parsed > last:
            last = parsed
    return last


# A historical game whose newest frame is older than this will never grow:
# the feed sometimes ends without a `finished` frame (observed: Worlds 2025
# AL vs HLE, 41min of frames then feed cut; beyond-end startingTime probes
# get clamped to the same tail frames). Treat such archives as terminal so
# future runs skip them instead of re-spending the gap patience budget.
STALE_END_AGE = timedelta(hours=24)


@dataclass
class ArchiveResult:
    game_id: str
    skipped: bool
    finished: bool
    window_frames: int
    details_frames: int
    stale_end: bool = False


def archive_game(game_id: str) -> ArchiveResult:
    """Archive one game's full timeline to
    data/raw/livestats/window/<game_id>.jsonl.gz (+ details variant).

    Idempotent + resumable: a game already fully archived (a `.done` marker
    written once we observe gameState == "finished", or once we confirm the
    game id has no data at all) is skipped outright. A partially archived
    game (process was interrupted) resumes from its last written frame
    instead of restarting.
    """
    window_path = lake.raw_path("livestats", "window", f"{game_id}.jsonl.gz")
    details_path = lake.raw_path("livestats", "details", f"{game_id}.jsonl.gz")
    done_marker = window_path.with_name(window_path.name + ".done")

    if done_marker.exists():
        return ArchiveResult(
            game_id=game_id,
            skipped=True,
            finished=True,
            window_frames=lake.count_jsonl_gz(window_path),
            details_frames=lake.count_jsonl_gz(details_path),
        )

    finished = False
    with lake.JsonlGzWriter(window_path) as writer:
        for frame in fetch_window_frames(game_id, from_ts=_last_timestamp(window_path)):
            writer.write(frame)
            if frame.get("gameState") == "finished":
                finished = True

    window_last_ts = _last_timestamp(window_path)
    with lake.JsonlGzWriter(details_path) as writer:
        for frame in fetch_details_frames(
            game_id, from_ts=_last_timestamp(details_path), stop_at=window_last_ts
        ):
            writer.write(frame)

    stale_end = (
        not finished
        and window_last_ts is not None
        and datetime.now(UTC) - window_last_ts > STALE_END_AGE
    )
    if finished or stale_end or window_last_ts is None:
        # finished => real terminal state; stale_end => historical game whose
        # feed ended without a `finished` frame (see STALE_END_AGE); last_ts
        # is None => confirmed no data at all (unplayed placeholder game, see
        # lolesports.py). Either way there is nothing more to fetch, ever --
        # mark done so future archive-frames runs skip this game id outright.
        done_marker.touch()

    return ArchiveResult(
        game_id=game_id,
        skipped=False,
        finished=finished,
        window_frames=lake.count_jsonl_gz(window_path),
        details_frames=lake.count_jsonl_gz(details_path),
        stale_end=stale_end,
    )
