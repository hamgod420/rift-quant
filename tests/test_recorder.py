"""Recorder loop logic against a fake venue client -- no live network in the
default pytest run (brief requirement). `poll_market` is tested directly for
precise cadence control (full-book-every-5-min, trade dedup, resolution
gating); one `run()` test exercises the full wiring end to end (discovery
registry -> load_tracked -> DayWriter -> a real gzip file on disk)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from riftquant import config
from riftquant.odds import discovery, recorder
from riftquant.odds.discovery import MarketMeta
from riftquant.store import lake


class ListWriter:
    """Stands in for lake.JsonlGzWriter -- poll_market only ever calls
    .write(dict), so an in-memory list is enough for fine-grained assertions."""

    def __init__(self) -> None:
        self.records: list[dict] = []

    def write(self, record: dict) -> None:
        self.records.append(record)


class FakeVenueClient:
    """Canned snapshot/trades/resolution with call-count tracking, so the
    recorder's cadence/dedup/gating logic can be asserted precisely."""

    def __init__(self) -> None:
        self.snapshot_calls: list[bool] = []
        self.trade_calls: list[float] = []
        self.resolution_calls = 0
        self._pending_trades: list[tuple[float, dict]] = [
            (100.0, {"id": "t1"}),
            (200.0, {"id": "t2"}),
        ]
        self._resolved = False

    def snapshot(self, market: MarketMeta, want_full_book: bool) -> tuple[list[dict], list[dict]]:
        self.snapshot_calls.append(want_full_book)
        quotes = [
            {"outcome": market.team1, "token_id": "tokA", "bid": 0.5, "ask": 0.52, "mid": 0.51}
        ]
        books = (
            [{"outcome": market.team1, "token_id": "tokA", "raw": {"bids": [], "asks": []}}]
            if want_full_book
            else []
        )
        return quotes, books

    def trades(self, market: MarketMeta, since_ts: float) -> list[tuple[float, dict]]:
        self.trade_calls.append(since_ts)
        return [(ts, raw) for ts, raw in self._pending_trades if ts > since_ts]

    def resolution(self, market: MarketMeta) -> dict | None:
        self.resolution_calls += 1
        return {"closed": True} if self._resolved else None

    def resolve_next_call(self) -> None:
        self._resolved = True


def _market(start_time: datetime | None = None) -> MarketMeta:
    return MarketMeta(
        venue="polymarket",
        market_id="lol-a-b-2026-08-23",
        event_id="lol-a-b-2026-08-23",
        title="LoL: A vs B",
        team1="A",
        team2="B",
        start_time=start_time,
        discovered_at=datetime(2026, 8, 21, tzinfo=UTC),
    )


def test_poll_market_writes_one_quote_per_tick() -> None:
    writer = ListWriter()
    client = FakeVenueClient()
    state = recorder.MarketState()
    now = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)

    n = recorder.poll_market(writer, client, _market(), state, now)

    quote_rows = [r for r in writer.records if r["obs_type"] == "quote"]
    assert len(quote_rows) == 1
    assert quote_rows[0]["bid"] == 0.5
    assert quote_rows[0]["market_id"] == "lol-a-b-2026-08-23"
    assert n == len(writer.records)


def test_poll_market_full_book_only_every_5_minutes() -> None:
    writer = ListWriter()
    client = FakeVenueClient()
    market = _market()
    state = recorder.MarketState()
    t0 = datetime(2026, 8, 21, 12, 0, 0, tzinfo=UTC)

    # first tick: baseline ts=0 -> always a full book
    recorder.poll_market(writer, client, market, state, t0)
    assert client.snapshot_calls == [True]
    assert len([r for r in writer.records if r["obs_type"] == "book"]) == 1

    t1 = t0 + timedelta(seconds=30)
    recorder.poll_market(writer, client, market, state, t1)  # too soon for another full book
    assert client.snapshot_calls == [True, False]

    t2 = t0 + timedelta(seconds=config.ODDS_FULL_BOOK_INTERVAL_SECS + 1)
    recorder.poll_market(writer, client, market, state, t2)  # 5 min elapsed -> full book again
    assert client.snapshot_calls == [True, False, True]


def test_poll_market_trades_advance_since_ts_and_dedupe() -> None:
    writer = ListWriter()
    client = FakeVenueClient()
    market = _market()
    state = recorder.MarketState()
    now = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)

    recorder.poll_market(writer, client, market, state, now)
    trade_rows = [r for r in writer.records if r["obs_type"] == "trade"]
    assert [r["trade"]["id"] for r in trade_rows] == ["t1", "t2"]
    assert state.last_trade_ts == 200.0

    writer.records.clear()
    recorder.poll_market(writer, client, market, state, now)  # second poll: nothing new
    assert [r for r in writer.records if r["obs_type"] == "trade"] == []
    assert client.trade_calls == [0.0, 200.0]


def test_poll_market_skips_resolution_check_before_start_time() -> None:
    writer = ListWriter()
    client = FakeVenueClient()
    now = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
    market = _market(start_time=now + timedelta(days=2))
    state = recorder.MarketState()

    recorder.poll_market(writer, client, market, state, now)

    assert client.resolution_calls == 0
    assert state.resolved is False


def test_poll_market_checks_resolution_after_start_and_stops_polling_once_resolved() -> None:
    writer = ListWriter()
    client = FakeVenueClient()
    now = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
    market = _market(start_time=now - timedelta(hours=1))
    state = recorder.MarketState()

    recorder.poll_market(writer, client, market, state, now)
    assert client.resolution_calls == 1
    assert state.resolved is False  # still open

    client.resolve_next_call()
    recorder.poll_market(writer, client, market, state, now)
    assert state.resolved is True
    assert len([r for r in writer.records if r["obs_type"] == "resolution"]) == 1


def test_run_writes_a_real_capture_file_for_a_seeded_market(tmp_path, monkeypatch) -> None:
    """End-to-end wiring: discovery registry -> load_tracked -> DayWriter ->
    an actual gzip file on disk, driven entirely by a fake client (no
    network)."""
    monkeypatch.setattr(config, "DATA_RAW", tmp_path / "raw")
    start_time = datetime.now(UTC) + timedelta(hours=5)
    discovery.persist_discovered("polymarket", [_market(start_time=start_time)])

    fake = FakeVenueClient()
    monkeypatch.setattr(recorder, "_client_for", lambda venue: fake)

    total = recorder.run(
        venues={"polymarket": True, "kalshi": False},
        discover_first=False,
        duration_secs=0,
        interval=0,
        limit=5,
        echo=lambda _msg: None,
    )

    assert total > 0
    today = datetime.now(UTC).date()
    rows = list(lake.read_jsonl_gz(discovery.capture_path("polymarket", today)))
    assert rows
    assert {r["market_id"] for r in rows} == {"lol-a-b-2026-08-23"}
    assert {r["obs_type"] for r in rows} == {"quote", "book", "trade"}


def test_run_skips_kalshi_by_default_config() -> None:
    assert config.ODDS_VENUES_ENABLED["kalshi"] is False
    assert config.ODDS_VENUES_ENABLED["polymarket"] is True
