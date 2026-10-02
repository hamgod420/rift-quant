"""Kalshi connector: exercised ONLY against fixtures built from the verified
live examples quoted in docs/research/07-odds-capture-apis.md SS2.4/2.8 --
this module (and this test file) never make a real network call, per the
M1b brief's compliance gate (docs/QUESTIONS.md Q27, kalshi capture stays
disabled by default). httpx.MockTransport intercepts at the transport layer
so the real get_json/new_client/retry code in http.py is still exercised."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from riftquant.odds import kalshi


def _fake_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _events_fixture() -> dict:
    # Ticker/title/sub_title shape transcribed from the research doc's own
    # live-captured KXLOLGAME-26AUG201200GNGBAAM example (SS2.8).
    return {
        "events": [
            {
                "event_ticker": "KXLOLGAME-26AUG201200GNGBAAM",
                "markets": [
                    {
                        "ticker": "KXLOLGAME-26AUG201200GNGBAAM-GNG",
                        "event_ticker": "KXLOLGAME-26AUG201200GNGBAAM",
                        "title": "GnG Amazigh wins",
                        "yes_sub_title": "GnG Amazigh",
                        "no_sub_title": "Baam Esports",
                        "status": "open",
                        "expected_expiration_time": "2026-08-20T20:00:00Z",
                    },
                    {
                        "ticker": "KXLOLGAME-26AUG201200GNGBAAM-BAAM",
                        "event_ticker": "KXLOLGAME-26AUG201200GNGBAAM",
                        "title": "Baam Esports wins",
                        "yes_sub_title": "Baam Esports",
                        "no_sub_title": "GnG Amazigh",
                        "status": "settled",
                        "expected_expiration_time": "2026-08-20T20:00:00Z",
                    },
                ],
            }
        ]
    }


def test_discover_lol_markets_keeps_only_open(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/trade-api/v2/events"
        assert request.url.params["series_ticker"] == "KXLOLGAME"
        assert request.url.params["status"] == "open"
        assert request.url.params["with_nested_markets"] == "true"
        return httpx.Response(200, json=_events_fixture())

    monkeypatch.setattr(kalshi, "_client", _fake_client(handler))
    now = datetime(2026, 8, 20, tzinfo=UTC)

    found = kalshi.discover_lol_markets(now=now)

    assert [m.market_id for m in found] == ["KXLOLGAME-26AUG201200GNGBAAM-GNG"]
    market = found[0]
    assert market.team1 == "GnG Amazigh"
    assert market.team2 == "Baam Esports"
    assert market.event_id == "KXLOLGAME-26AUG201200GNGBAAM"
    assert market.start_time == datetime(2026, 8, 20, 20, 0, tzinfo=UTC)
    assert market.discovered_at == now


def test_quote_from_orderbook_matches_research_doc_example() -> None:
    # Verbatim shape from the research doc's live KXLOLGAME-...-GNG capture.
    book = {
        "orderbook_fp": {
            "no_dollars": [["0.0100", "1374.00"], ["0.0200", "303.00"]],
            "yes_dollars": [["0.0100", "854.00"], ["0.0200", "103.00"]],
        }
    }
    quote = kalshi.quote_from_orderbook(book)
    assert quote["bid"] == 0.02  # best (highest) yes bid
    assert quote["ask"] == 0.98  # implied: 1 - best no bid (0.02)
    assert quote["mid"] == 0.5


def test_quote_from_orderbook_accepts_plain_orderbook_key() -> None:
    book = {"orderbook": {"yes_dollars": [["0.30", "10"]], "no_dollars": [["0.40", "5"]]}}
    quote = kalshi.quote_from_orderbook(book)
    assert quote["bid"] == 0.30
    assert quote["ask"] == 0.6


def test_quote_from_orderbook_handles_empty_book() -> None:
    assert kalshi.quote_from_orderbook({}) == {"bid": None, "ask": None, "mid": None}


def test_fetch_trades_hits_flat_trades_path_with_ticker_param(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/trade-api/v2/markets/trades"
        assert request.url.params["ticker"] == "KXLOLGAME-26AUG201200GNGBAAM-GNG"
        return httpx.Response(
            200,
            json={
                "trades": [
                    {
                        "trade_id": "abc",
                        "yes_price_dollars": "0.7600",
                        "no_price_dollars": "0.2400",
                        "taker_side": "yes",
                        "count_fp": "1.00",
                        "created_time": "2026-08-20T23:45:31Z",
                    }
                ]
            },
        )

    monkeypatch.setattr(kalshi, "_client", _fake_client(handler))
    trades = kalshi.fetch_trades("KXLOLGAME-26AUG201200GNGBAAM-GNG")
    assert len(trades) == 1
    assert trades[0]["trade_id"] == "abc"


def test_trade_epoch_parses_created_time() -> None:
    epoch = kalshi.trade_epoch({"created_time": "2026-08-20T23:45:31Z"})
    assert epoch == datetime(2026, 8, 20, 23, 45, 31, tzinfo=UTC).timestamp()
    assert kalshi.trade_epoch({}) == 0.0


def test_is_terminal_covers_settled_finalized_determined() -> None:
    assert kalshi.is_terminal({"status": "settled"}) is True
    assert kalshi.is_terminal({"status": "finalized"}) is True
    assert kalshi.is_terminal({"status": "determined"}) is True
    assert kalshi.is_terminal({"status": "open"}) is False
    assert kalshi.is_terminal({}) is False


def test_fetch_market_status_unwraps_market_key(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/trade-api/v2/markets/KXLOLGAME-26AUG201200GNGBAAM-GNG"
        return httpx.Response(200, json={"market": {"status": "settled", "result": "yes"}})

    monkeypatch.setattr(kalshi, "_client", _fake_client(handler))
    status = kalshi.fetch_market_status("KXLOLGAME-26AUG201200GNGBAAM-GNG")
    assert status == {"status": "settled", "result": "yes"}
