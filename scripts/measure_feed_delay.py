"""Measure lolesports livestats feed delay vs wall clock during a live game.

Answers docs/research/00-synthesis.md open question 1: is the free feed
delayed like the broadcast (5-10 min) or near-real-time?

Method (v2 -- v1 was wrong): the bare /window call returns frames anchored at
GAME START, not the latest frames (measured live 2026-08-21: bare-call deltas
grew linearly with elapsed game time). The correct measurement is the feed
FRONTIER: the newest frame reachable via startingTime probing. Each sample:
request startingTime = now-50s (server floor is ~45s); if frames return, walk
forward in 10s steps until the feed stops; frontier_lag = now - newest frame.
If frontier_lag sits near ~45-60s the feed is near-real-time (buffer-limited);
if it sits near broadcast delay (300-600s) the feed is delayed too.

Usage: python scripts/measure_feed_delay.py --league lck --max-seconds 570
Writes samples to data/logs/feed_delay_<gameid>.jsonl and prints a summary.
ASCII only. Read-only, polite (1 request / interval).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import time
import urllib.error
import urllib.request
from pathlib import Path

KEY = "0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z"
PERSISTED = "https://esports-api.lolesports.com/persisted/gw"
FEED = "https://feed.lolesports.com/livestats/v1"


def get(url: str, key: bool = True):
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "riftquant-feed-delay-probe/0.1")
    if key:
        req.add_header("x-api-key", KEY)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read().decode()
            return r.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:  # noqa: BLE001
        return f"ERR:{type(e).__name__}", None


def find_live_game(league: str):
    _, d = get(f"{PERSISTED}/getSchedule?hl=en-US")
    events = (d or {}).get("data", {}).get("schedule", {}).get("events", [])
    for ev in events:
        if ev.get("state") != "inProgress":
            continue
        if ev.get("league", {}).get("slug") != league:
            continue
        mid = ev.get("match", {}).get("id")
        if not mid:
            continue
        _, dd = get(f"{PERSISTED}/getEventDetails?hl=en-US&id={mid}")
        event = (dd or {}).get("data", {}).get("event", {}) or {}
        games = event.get("match", {}).get("games", [])
        for g in games:
            if g.get("state") == "inProgress":
                return g.get("id"), " vs ".join(
                    t.get("code", "?") for t in ev.get("match", {}).get("teams", [])
                )
    return None, None


def parse_ts(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def _round10(t: dt.datetime) -> dt.datetime:
    return t.replace(second=(t.second // 10) * 10, microsecond=0)


def _fmt(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _window(game_id: str, starting: dt.datetime | None):
    url = f"{FEED}/window/{game_id}"
    if starting is not None:
        url += f"?startingTime={_fmt(starting)}"
    code, d = get(url, key=False)
    return code, ((d or {}).get("frames") or [])


def measure_frontier(game_id: str, now: dt.datetime):
    """Return (frontier_lag_seconds, newest_ts, calls) or (None, None, calls).

    Finds the newest frame the feed will serve right now by anchoring close
    to `now` and walking forward until the feed runs dry.
    """
    calls = 0
    newest = None
    for back in (50, 80, 120, 180, 300, 600, 900):
        t_try = _round10(now - dt.timedelta(seconds=back))
        calls += 1
        _, frames = _window(game_id, t_try)
        if frames:
            newest = max(parse_ts(f["rfc460Timestamp"]) for f in frames)
            break
        time.sleep(0.2)
    if newest is None:
        return None, None, calls
    for _ in range(30):  # walk to the true frontier
        nxt = _round10(newest + dt.timedelta(seconds=10))
        if nxt >= now:
            break
        calls += 1
        _, frames = _window(game_id, nxt)
        fresh = [
            f for f in frames if parse_ts(f["rfc460Timestamp"]) > newest
        ]
        if not fresh:
            break
        newest = max(parse_ts(f["rfc460Timestamp"]) for f in fresh)
        time.sleep(0.2)
    return (now - newest).total_seconds(), newest, calls


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", default="lck")
    ap.add_argument("--game-id", default=None, help="skip discovery")
    ap.add_argument("--interval", type=float, default=15.0)
    ap.add_argument("--max-seconds", type=float, default=570.0)
    args = ap.parse_args()

    t0 = time.monotonic()
    game_id, label = args.game_id, "manual"
    while game_id is None and time.monotonic() - t0 < args.max_seconds:
        game_id, label = find_live_game(args.league)
        if game_id is None:
            print(f"{dt.datetime.now(dt.UTC).isoformat()} no live {args.league} game yet")
            time.sleep(max(args.interval, 20.0))
    if game_id is None:
        print("EXIT: no live game found within budget")
        return

    out = Path("data/logs") / f"feed_delay_{game_id}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    print(f"live game found: {label} game_id={game_id}; sampling -> {out}")
    deltas: list[float] = []
    while time.monotonic() - t0 < args.max_seconds:
        now = dt.datetime.now(dt.UTC)
        lag, newest, calls = measure_frontier(game_id, now)
        rec = {
            "now": now.isoformat(),
            "frontier_lag_s": round(lag, 1) if lag is not None else None,
            "newest_frame": newest.isoformat() if newest else None,
            "probe_calls": calls,
        }
        if lag is not None:
            deltas.append(lag)
        with out.open("a", encoding="ascii") as f:
            f.write(json.dumps(rec) + "\n")
        print(f"{now.isoformat()} frontier_lag_s={rec['frontier_lag_s']} calls={calls}")
        time.sleep(args.interval)

    if deltas:
        print(
            f"SUMMARY n={len(deltas)} median={statistics.median(deltas):.1f}s "
            f"min={min(deltas):.1f}s max={max(deltas):.1f}s"
        )
        med = statistics.median(deltas)
        if med < 90:
            print("VERDICT: feed is NEAR-REAL-TIME (buffer-limited, faster than broadcast)")
        elif med < 240:
            print("VERDICT: feed moderately delayed (between real-time and broadcast)")
        else:
            print("VERDICT: feed is BROADCAST-DELAYED (no latency edge from free feed)")
    else:
        print("SUMMARY: no frames sampled")


if __name__ == "__main__":
    main()
