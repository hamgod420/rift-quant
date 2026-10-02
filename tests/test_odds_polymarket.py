"""Polymarket connector: gamma discovery filtering, CLOB book math, and
gamma's stringified-array quirk. All network-free via httpx.MockTransport
(the module's module-level `_client` singleton is monkeypatched, and `_sleep`
is stubbed so tests don't pay the real courtesy delay)."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from riftquant.odds import polymarket


def _events_fixture() -> list[dict]:
    return [
        {
            "slug": "lol-hle1-t1-2026-08-23",
            "title": "LoL: Hanwha Life Esports vs T1",
            "markets": [
                {
                    # a per-game market: slug != event slug -> must be filtered out
                    "slug": "lol-hle1-t1-2026-08-23-game1",
                    "question": "Game 1 Winner",
                    "gameStartTime": "2026-08-23 08:00:00+00",
                    "outcomes": '["Hanwha Life Esports", "T1"]',
                    "clobTokenIds": '["tok1", "tok2"]',
                    "conditionId": "0xgame1",
                    "closed": False,
                },
                {
                    # the full-match-winner market: slug == event slug -> kept
                    "slug": "lol-hle1-t1-2026-08-23",
                    "question": "LoL: Hanwha Life Esports vs T1 (BO3)",
                    "gameStartTime": "2026-08-23 08:00:00+00",
                    "outcomes": '["Hanwha Life Esports", "T1"]',
                    "clobTokenIds": '["tokA", "tokB"]',
                    "conditionId": "0xmatch",
                    "closed": False,
                },
            ],
        },
        {
            # a season-winner future: slug matches but no gameStartTime -> filtered out
            "slug": "lol-lck-2026-season-winner",
            "title": "LCK 2026 Season Winner",
            "markets": [
                {
                    "slug": "lol-lck-2026-season-winner",
                    "question": "Will T1 win the LCK 2026 season playoffs?",
                    "gameStartTime": None,
                    "outcomes": '["Yes", "No"]',
                    "clobTokenIds": '["tokY", "tokN"]',
                    "conditionId": "0xfuture",
                    "closed": False,
                }
            ],
        },
        {
            # an already-closed match: filtered out
            "slug": "lol-old-match-2026-01-01",
            "title": "LoL: Old vs Match",
            "markets": [
                {
                    "slug": "lol-old-match-2026-01-01",
                    "question": "LoL: Old vs Match",
                    "gameStartTime": "2026-01-01 08:00:00+00",
                    "outcomes": '["Old", "Match"]',
                    "clobTokenIds": '["tokO", "tokM"]',
                    "conditionId": "0xold",
                    "closed": True,
                }
            ],
        },
    ]


def _fake_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_json_list_decodes_gamma_stringified_array() -> None:
    assert polymarket.json_list('["a", "b"]') == ["a", "b"]


def test_json_list_passes_through_real_list() -> None:
    assert polymarket.json_list(["a", "b"]) == ["a", "b"]


def test_json_list_handles_none_and_garbage() -> None:
    assert polymarket.json_list(None) == []
    assert polymarket.json_list("not json") == []
    assert polymarket.json_list(42) == []
    assert polymarket.json_list('{"not": "a list"}') == []


def test_discover_lol_markets_filters_to_match_winner_only(monkeypatch) -> None:
    monkeypatch.setattr(polymarket, "_sleep", lambda: None)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/events"
        assert request.url.params["tag_slug"] == "league-of-legends"
        return httpx.Response(200, json=_events_fixture())

    monkeypatch.setattr(polymarket, "_client", _fake_client(handler))
    now = datetime(2026, 8, 21, tzinfo=UTC)

    found = polymarket.discover_lol_markets(now=now)

    assert [m.market_id for m in found] == ["lol-hle1-t1-2026-08-23"]
    market = found[0]
    assert market.team1 == "Hanwha Life Esports"
    assert market.team2 == "T1"
    assert market.clob_token_ids == ["tokA", "tokB"]
    assert market.condition_id == "0xmatch"
    assert market.discovered_at == now
    assert market.start_time == datetime(2026, 8, 23, 8, 0, tzinfo=UTC)


def test_quote_from_book_computes_top_of_book_and_mid() -> None:
    book = {
        "bids": [{"price": "0.50", "size": "10"}, {"price": "0.48", "size": "5"}],
        "asks": [{"price": "0.53", "size": "8"}, {"price": "0.55", "size": "2"}],
    }
    quote = polymarket.quote_from_book(book)
    assert quote == {"bid": 0.50, "ask": 0.53, "mid": 0.515}


def test_quote_from_book_handles_empty_sides() -> None:
    empty_quote = {"bid": None, "ask": None, "mid": None}
    assert polymarket.quote_from_book({"bids": [], "asks": []}) == empty_quote


def test_fetch_book_hits_clob_with_token_id(monkeypatch) -> None:
    monkeypatch.setattr(polymarket, "_sleep", lambda: None)
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["token_id"] = request.url.params["token_id"]
        return httpx.Response(200, json={"bids": [], "asks": []})

    monkeypatch.setattr(polymarket, "_client", _fake_client(handler))
    polymarket.fetch_book("tokA")
    assert seen == {"path": "/book", "token_id": "tokA"}


def test_fetch_trades_returns_list(monkeypatch) -> None:
    monkeypatch.setattr(polymarket, "_sleep", lambda: None)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["market"] == "0xmatch"
        return httpx.Response(200, json=[{"timestamp": 1787296096, "price": 0.51}])

    monkeypatch.setattr(polymarket, "_client", _fake_client(handler))
    trades = polymarket.fetch_trades("0xmatch")
    assert trades == [{"timestamp": 1787296096, "price": 0.51}]


def test_trade_epoch_parses_numeric_timestamp() -> None:
    assert polymarket.trade_epoch({"timestamp": 1787296096}) == 1787296096.0
    assert polymarket.trade_epoch({}) == 0.0
    assert polymarket.trade_epoch({"timestamp": "not-a-number"}) == 0.0


def test_fetch_market_status_uses_market_level_slug(monkeypatch) -> None:
    monkeypatch.setattr(polymarket, "_sleep", lambda: None)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/markets"
        assert request.url.params["slug"] == "lol-hle1-t1-2026-08-23"
        return httpx.Response(200, json=[{"closed": True, "outcomePrices": '["1", "0"]'}])

    monkeypatch.setattr(polymarket, "_client", _fake_client(handler))
    status = polymarket.fetch_market_status("lol-hle1-t1-2026-08-23")
    assert status["closed"] is True


def test_fetch_market_status_returns_none_when_empty(monkeypatch) -> None:
    monkeypatch.setattr(polymarket, "_sleep", lambda: None)
    monkeypatch.setattr(polymarket, "_client", _fake_client(lambda r: httpx.Response(200, json=[])))
    assert polymarket.fetch_market_status("missing-slug") is None
