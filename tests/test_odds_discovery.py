"""Market registry persistence: dedup-by-latest-discovery, closed filtering,
hours-ahead window, limit truncation, and last_capture_ts scanning. All
network-free -- these exercise discovery.py's lake plumbing directly."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from riftquant import config
from riftquant.odds import discovery
from riftquant.odds.discovery import MarketMeta


def _market(market_id: str, discovered_at: datetime, start_time=None, closed=False) -> MarketMeta:
    return MarketMeta(
        venue="polymarket",
        market_id=market_id,
        event_id=market_id,
        title=f"LoL: {market_id}",
        team1="A",
        team2="B",
        start_time=start_time,
        discovered_at=discovered_at,
        closed=closed,
    )


def test_load_tracked_dedupes_to_latest_discovery(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "DATA_RAW", tmp_path / "raw")
    older = _market("m1", datetime(2026, 8, 20, tzinfo=UTC), closed=False)
    # re-discovered later, now closed -- the later discovered_at must win
    newer = _market("m1", datetime(2026, 8, 21, tzinfo=UTC), closed=True)
    discovery.persist_discovered("polymarket", [older])
    discovery.persist_discovered("polymarket", [newer])

    tracked = discovery.load_tracked("polymarket")
    assert tracked == []  # the latest record for m1 says closed=True


def test_load_tracked_drops_closed(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "DATA_RAW", tmp_path / "raw")
    discovery.persist_discovered(
        "polymarket",
        [_market("open1", datetime(2026, 8, 21, tzinfo=UTC), closed=False),
         _market("closed1", datetime(2026, 8, 21, tzinfo=UTC), closed=True)],
    )
    tracked = discovery.load_tracked("polymarket")
    assert [m.market_id for m in tracked] == ["open1"]


def test_load_tracked_within_hours_filters_far_future(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "DATA_RAW", tmp_path / "raw")
    now = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
    discovery.persist_discovered(
        "polymarket",
        [
            _market("soon", now, start_time=now + timedelta(hours=10)),
            _market("far", now, start_time=now + timedelta(days=30)),
            _market("unknown_start", now, start_time=None),
        ],
    )
    tracked = discovery.load_tracked("polymarket", within_hours=48, now=now)
    ids = {m.market_id for m in tracked}
    assert ids == {"soon", "unknown_start"}  # unknown start_time is kept, not excluded


def test_load_tracked_sorts_soonest_first_and_respects_limit(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "DATA_RAW", tmp_path / "raw")
    now = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
    discovery.persist_discovered(
        "polymarket",
        [
            _market("later", now, start_time=now + timedelta(hours=20)),
            _market("soonest", now, start_time=now + timedelta(hours=1)),
            _market("middle", now, start_time=now + timedelta(hours=10)),
        ],
    )
    tracked = discovery.load_tracked("polymarket", now=now, limit=2)
    assert [m.market_id for m in tracked] == ["soonest", "middle"]


def test_last_capture_ts_scans_the_right_day(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "DATA_RAW", tmp_path / "raw")
    day = datetime(2026, 8, 21, tzinfo=UTC).date()
    from riftquant.store import lake

    lake.append_jsonl_gz(
        discovery.capture_path("polymarket", day),
        [
            {"market_id": "m1", "capture_ts": "2026-08-21T12:00:00+00:00"},
            {"market_id": "m1", "capture_ts": "2026-08-21T12:00:30+00:00"},
            {"market_id": "m2", "capture_ts": "2026-08-21T12:05:00+00:00"},
        ],
    )
    last = discovery.last_capture_ts("polymarket", "m1", day=day)
    assert last == datetime(2026, 8, 21, 12, 0, 30, tzinfo=UTC)
    assert discovery.last_capture_ts("polymarket", "missing", day=day) is None


def test_discover_all_skips_disabled_venues(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "DATA_RAW", tmp_path / "raw")
    results = discovery.discover_all({"polymarket": False, "kalshi": False})
    assert results == {}
