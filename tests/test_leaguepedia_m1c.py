"""M1c additions to ingest.leaguepedia: league/season OverviewPage patterns,
the new Cargo table mappings (Tournaments/ScoreboardPlayers/PicksAndBansS7/
TournamentRosters/Players/Teams), and ingest_league_season's resumability.

Network-free: cargo_query itself is monkeypatched (same technique the
existing ScoreboardGames tests in test_leaguepedia.py use), so no call
reaches lol.fandom.com.
"""

from __future__ import annotations

import pytest

from riftquant import config
from riftquant.ingest import leaguepedia


def test_overview_page_pattern_known_leagues() -> None:
    assert leaguepedia.overview_page_pattern("lck", 2026) == "LCK/2026%"
    assert leaguepedia.overview_page_pattern("LEC", 2026) == "LEC/2026%"  # case-insensitive
    assert leaguepedia.overview_page_pattern("worlds", 2026) == "2026 Season World Championship%"


def test_overview_page_pattern_unknown_league_raises() -> None:
    with pytest.raises(ValueError, match="unknown league"):
        leaguepedia.overview_page_pattern("not-a-league", 2026)


def test_sql_quote_escapes_apostrophes() -> None:
    assert leaguepedia._sql_quote("O'Fallon") == "O''Fallon"


def test_split_list_strips_and_drops_empties() -> None:
    assert leaguepedia._split_list("Faker, Zeus ,,  Oner") == ["Faker", "Zeus", "Oner"]
    assert leaguepedia._split_list("") == []


def _pb_row(team1: str = "T1", team2: str = "T2", winner: str = "T1") -> dict:
    row = {
        "UniqueLine": "PB1",
        "GameId": "G1",
        "MatchId": "M1",
        "OverviewPage": "LCK/2026 Season/Spring",
        "Team1": team1,
        "Team2": team2,
        "Winner": winner,
    }
    for i in range(1, 6):
        row[f"Team1Ban{i}"] = f"T1Ban{i}"
        row[f"Team2Ban{i}"] = f"T2Ban{i}"
        row[f"Team1Pick{i}"] = f"T1Pick{i}"
        row[f"Team2Pick{i}"] = f"T2Pick{i}"
    return row


def test_picks_and_bans_groups_slots_in_order(monkeypatch) -> None:
    monkeypatch.setattr(leaguepedia, "cargo_query", lambda *a, **k: [_pb_row()])
    rows = leaguepedia.picks_and_bans("LCK/2026%")
    assert len(rows) == 1
    pb = rows[0]
    assert pb.game_id == "G1"
    assert pb.team1_bans == ["T1Ban1", "T1Ban2", "T1Ban3", "T1Ban4", "T1Ban5"]
    assert pb.team2_bans == ["T2Ban1", "T2Ban2", "T2Ban3", "T2Ban4", "T2Ban5"]
    assert pb.team1_picks == ["T1Pick1", "T1Pick2", "T1Pick3", "T1Pick4", "T1Pick5"]
    assert pb.team2_picks == ["T2Pick1", "T2Pick2", "T2Pick3", "T2Pick4", "T2Pick5"]


def test_scoreboard_players_maps_fields(monkeypatch) -> None:
    def fake_cargo_query(table, fields, where=None, **kwargs):
        assert table == "ScoreboardPlayers"
        return [
            {
                "UniqueLine": "SP1",
                "GameId": "G1",
                "MatchId": "M1",
                "OverviewPage": "LCK/2026 Season/Spring",
                "Name": "Faker",
                "Link": "Faker",
                "Team": "T1",
                "Side": "1",
                "Role": "Mid",
                "Role_Number": "2",
                "Champion": "Azir",
                "Kills": "3",
                "Deaths": "1",
                "Assists": "5",
                "Gold": "12000",
                "CS": "250",
                "PrimaryTree": "Sorcery",
                "SecondaryTree": "Resolve",
                "KeystoneRune": "Arcane Comet",
                "PlayerWin": "Yes",
                "DateTime_UTC": "2026-01-14 08:00:00",
            }
        ]

    monkeypatch.setattr(leaguepedia, "cargo_query", fake_cargo_query)
    rows = leaguepedia.scoreboard_players("LCK/2026%")
    assert len(rows) == 1
    assert rows[0].link == "Faker"
    assert rows[0].champion == "Azir"
    assert rows[0].player_win == "Yes"


def test_tournament_rosters_splits_comma_lists(monkeypatch) -> None:
    def fake_cargo_query(table, fields, where=None, **kwargs):
        assert table == "TournamentRosters"
        return [
            {
                "UniqueLine": "R1",
                "OverviewPage": "LCK/2026 Season/Spring",
                "Team": "T1",
                "Tournament": "LCK 2026 Spring",
                "Region": "Korea",
                "IsUsed": "Yes",
                "IsComplete": "Yes",
                "RosterLinks": "Faker, Zeus ,Oner",
                "Roles": "Mid,Top,Jungle",
            }
        ]

    monkeypatch.setattr(leaguepedia, "cargo_query", fake_cargo_query)
    rows = leaguepedia.tournament_rosters("LCK/2026%")
    assert rows[0].roster_links == ["Faker", "Zeus", "Oner"]
    assert rows[0].roles == ["Mid", "Top", "Jungle"]


def test_fetch_team_pages_chunks_in_list_queries(monkeypatch) -> None:
    monkeypatch.setattr(leaguepedia, "_IN_LIST_CHUNK_SIZE", 2)
    monkeypatch.setattr(config, "LEAGUEPEDIA_SLEEP_SECS", 0.0)
    where_clauses: list[str] = []

    def fake_cargo_query(table, fields, where=None, **kwargs):
        assert table == "Teams"
        where_clauses.append(where)
        return [
            {
                "OverviewPage": "A",
                "Name": "A",
                "Short": "A",
                "Region": "",
                "IsDisbanded": "",
                "RenamedTo": "",
            }
        ]

    monkeypatch.setattr(leaguepedia, "cargo_query", fake_cargo_query)
    rows = leaguepedia.fetch_team_pages(["A", "B", "C"])
    assert len(where_clauses) == 2  # 3 pages / chunk size 2 -> 2 chunks
    assert len(rows) == 2


def test_fetch_player_pages_empty_input_makes_no_calls(monkeypatch) -> None:
    called = False

    def fake_cargo_query(*a, **k):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(leaguepedia, "cargo_query", fake_cargo_query)
    assert leaguepedia.fetch_player_pages([]) == []
    assert called is False


def _fake_cargo_query_for_ingest(call_log: list[str]):
    def fake(table, fields, where=None, **kwargs):
        call_log.append(table)
        if table == "Tournaments":
            return [
                {
                    "OverviewPage": "LCK/2026 Season/Spring",
                    "Name": "LCK 2026 Spring",
                    "League": "LCK",
                    "Region": "Korea",
                    "Year": "2026",
                    "DateStart": "2026-01-01",
                }
            ]
        if table == "ScoreboardGames":
            return [
                {
                    "GameId": "G1",
                    "MatchId": "M1",
                    "DateTime_UTC": "2026-01-14 08:00:00",
                    "Patch": "26.03",
                    "Team1": "T1",
                    "Team2": "T2",
                    "WinTeam": "T1",
                    "OverviewPage": "LCK/2026 Season/Spring",
                }
            ]
        if table == "ScoreboardPlayers":
            return [
                {
                    "UniqueLine": "SP1",
                    "GameId": "G1",
                    "MatchId": "M1",
                    "OverviewPage": "LCK/2026 Season/Spring",
                    "Name": "Faker",
                    "Link": "Faker",
                    "Team": "T1",
                    "Side": "1",
                    "Role": "Mid",
                    "Role_Number": "2",
                    "Champion": "Azir",
                    "Kills": "3",
                    "Deaths": "1",
                    "Assists": "5",
                    "Gold": "12000",
                    "CS": "250",
                    "PrimaryTree": "Sorcery",
                    "SecondaryTree": "Resolve",
                    "KeystoneRune": "Arcane Comet",
                    "PlayerWin": "Yes",
                    "DateTime_UTC": "2026-01-14 08:00:00",
                }
            ]
        if table == "PicksAndBansS7":
            return [_pb_row()]
        if table == "TournamentRosters":
            return [
                {
                    "UniqueLine": "R1",
                    "OverviewPage": "LCK/2026 Season/Spring",
                    "Team": "T1",
                    "Tournament": "LCK 2026 Spring",
                    "Region": "Korea",
                    "IsUsed": "Yes",
                    "IsComplete": "Yes",
                    "RosterLinks": "Faker,Zeus",
                    "Roles": "Mid,Top",
                }
            ]
        if table == "Teams":
            team_row = {"Region": "Korea", "IsDisbanded": "No", "RenamedTo": ""}
            return [
                {"OverviewPage": "T1", "Name": "T1", "Short": "T1", **team_row},
                {"OverviewPage": "T2", "Name": "T2", "Short": "T2", **team_row},
            ]
        if table == "Players":
            return [
                {
                    "OverviewPage": "Faker",
                    "ID": "Faker",
                    "Player": "Faker",
                    "Name": "Faker",
                    "NameFull": "Lee Sang-hyeok",
                    "Country": "South Korea",
                    "Team": "T1",
                    "TeamLast": "T1",
                    "Role": "Mid",
                    "IsRetired": "No",
                }
            ]
        raise AssertionError(f"unexpected table {table!r}")

    return fake


def test_ingest_league_season_row_counts(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "DATA_RAW", tmp_path / "raw")
    monkeypatch.setattr(config, "DATA_PROCESSED", tmp_path / "processed")
    monkeypatch.setattr(config, "LEAGUEPEDIA_SLEEP_SECS", 0.0)
    call_log: list[str] = []
    monkeypatch.setattr(leaguepedia, "cargo_query", _fake_cargo_query_for_ingest(call_log))

    counts = leaguepedia.ingest_league_season("lck", 2026)

    assert counts == {
        "tournaments": 1,
        "scoreboard_games": 1,
        "scoreboard_players": 1,
        "picks_and_bans": 1,
        "tournament_rosters": 1,
        "teams": 2,
        "players": 1,
    }
    assert set(call_log) == {
        "Tournaments",
        "ScoreboardGames",
        "ScoreboardPlayers",
        "PicksAndBansS7",
        "TournamentRosters",
        "Teams",
        "Players",
    }


def test_ingest_league_season_skips_network_on_rerun_without_refresh(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "DATA_RAW", tmp_path / "raw")
    monkeypatch.setattr(config, "DATA_PROCESSED", tmp_path / "processed")
    monkeypatch.setattr(config, "LEAGUEPEDIA_SLEEP_SECS", 0.0)
    call_log: list[str] = []
    monkeypatch.setattr(leaguepedia, "cargo_query", _fake_cargo_query_for_ingest(call_log))

    leaguepedia.ingest_league_season("lck", 2026)
    call_log.clear()

    counts = leaguepedia.ingest_league_season("lck", 2026)

    assert call_log == []  # every table served from disk -- zero network calls
    assert counts == {
        "tournaments": 1,
        "scoreboard_games": 1,
        "scoreboard_players": 1,
        "picks_and_bans": 1,
        "tournament_rosters": 1,
        "teams": 2,
        "players": 1,
    }


def test_ingest_league_season_refresh_forces_a_real_refetch(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "DATA_RAW", tmp_path / "raw")
    monkeypatch.setattr(config, "DATA_PROCESSED", tmp_path / "processed")
    monkeypatch.setattr(config, "LEAGUEPEDIA_SLEEP_SECS", 0.0)
    call_log: list[str] = []
    monkeypatch.setattr(leaguepedia, "cargo_query", _fake_cargo_query_for_ingest(call_log))

    leaguepedia.ingest_league_season("lck", 2026)
    call_log.clear()

    leaguepedia.ingest_league_season("lck", 2026, refresh=True)

    assert set(call_log) == {
        "Tournaments",
        "ScoreboardGames",
        "ScoreboardPlayers",
        "PicksAndBansS7",
        "TournamentRosters",
        "Teams",
        "Players",
    }
