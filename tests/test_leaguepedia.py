"""Leaguepedia connector: cargo response parsing, field aliasing, pagination.

Network-free: `_cargo_request` is monkeypatched so no call reaches
lol.fandom.com.
"""

from __future__ import annotations

import pytest

from riftquant import config
from riftquant.ingest import leaguepedia


def test_parse_cargo_response_raises_on_ratelimit() -> None:
    with pytest.raises(leaguepedia.CargoRateLimited):
        leaguepedia._parse_cargo_response({"error": {"code": "ratelimited", "info": "slow down"}})


def test_parse_cargo_response_raises_on_other_error() -> None:
    with pytest.raises(leaguepedia.CargoError):
        leaguepedia._parse_cargo_response({"error": {"code": "boom", "info": "bad table"}})


def test_parse_cargo_response_passthrough_on_success() -> None:
    ok = {"cargoquery": [{"title": {"A": "1"}}]}
    assert leaguepedia._parse_cargo_response(ok) == ok


def test_parse_cargo_response_treats_none_as_empty() -> None:
    assert leaguepedia._parse_cargo_response(None) == {}


def test_cargo_query_aliases_fields_and_paginates(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "DATA_RAW", tmp_path / "raw")
    seen_params: list[dict] = []
    page1 = {"cargoquery": [{"title": {"GameId": "0"}}, {"title": {"GameId": "1"}}]}
    page2 = {"cargoquery": []}

    def fake_request(params: dict) -> dict:
        seen_params.append(params)
        return page1 if len(seen_params) == 1 else page2

    monkeypatch.setattr(leaguepedia, "_cargo_request", fake_request)

    rows = leaguepedia.cargo_query("ScoreboardGames", ["GameId"], where="X=1", limit=2)

    assert rows == [{"GameId": "0"}, {"GameId": "1"}]
    assert len(seen_params) == 2  # a full page (2/2) triggers one more page to confirm the end
    assert seen_params[0]["fields"] == "GameId=GameId"  # self-aliased: avoids "_" -> " " mangling
    assert seen_params[0]["where"] == "X=1"
    assert seen_params[0]["offset"] == 0
    assert seen_params[1]["offset"] == 2


def test_cargo_query_max_rows_avoids_unneeded_extra_page(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "DATA_RAW", tmp_path / "raw")
    seen_params: list[dict] = []
    page = {"cargoquery": [{"title": {"GameId": str(i)}} for i in range(3)]}

    def fake_request(params: dict) -> dict:
        seen_params.append(params)
        return page

    monkeypatch.setattr(leaguepedia, "_cargo_request", fake_request)

    rows = leaguepedia.cargo_query("ScoreboardGames", ["GameId"], limit=3, max_rows=3)

    assert len(rows) == 3
    assert len(seen_params) == 1  # max_rows already satisfied; no probing page issued


def test_scoreboard_games_maps_cargo_names_to_python_names(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "DATA_RAW", tmp_path / "raw")

    def fake_cargo_query(table, fields, where=None, **kwargs):
        assert table == "ScoreboardGames"
        assert where == "OverviewPage LIKE 'LCK/2026%'"
        return [
            {
                "GameId": "G1",
                "MatchId": "M1",
                "DateTime_UTC": "2026-01-14 08:00:00",
                "Patch": "16.1",
                "Team1": "T1",
                "Team2": "T2",
                "WinTeam": "T1",
                "OverviewPage": "LCK/2026 Season/Split 1",
            }
        ]

    monkeypatch.setattr(leaguepedia, "cargo_query", fake_cargo_query)

    games = leaguepedia.scoreboard_games("LCK/2026%")

    assert len(games) == 1
    assert games[0].game_id == "G1"
    assert games[0].patch == "16.1"
    assert games[0].overview_page == "LCK/2026 Season/Split 1"
