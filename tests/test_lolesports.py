"""lolesports connector: response model parsing + game index flattening.

Network-free: list_tournaments/completed_events are monkeypatched.
"""

from __future__ import annotations

from riftquant import config
from riftquant.ingest import lolesports


def _make_event() -> lolesports.CompletedEvent:
    return lolesports.CompletedEvent.model_validate(
        {
            "startTime": "2026-01-14T08:00:00Z",
            "match": {
                "id": "M1",
                "teams": [
                    {"name": "Team A", "code": "TA"},
                    {"name": "Team B", "code": "TB"},
                ],
                "strategy": {"type": "bestOf", "count": 3},
            },
            "games": [
                {"id": "G1", "vods": [{"parameter": "abc"}]},
                {"id": "G2", "vods": [{"parameter": "def"}]},
                {"id": "G3", "vods": []},  # never played: series ended 2-0
            ],
        }
    )


def test_completed_event_parses_nested_shape() -> None:
    event = _make_event()
    assert event.match.strategy.count == 3
    assert [g.id for g in event.games] == ["G1", "G2", "G3"]
    assert event.games[2].vods == []


def test_build_game_index_flattens_games_and_computes_has_vod(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "DATA_RAW", tmp_path / "raw")
    tournament = lolesports.Tournament.model_validate(
        {"id": "T1", "slug": "lck_test_2026", "startDate": "2026-01-01", "endDate": "2026-02-01"}
    )
    monkeypatch.setattr(lolesports, "list_tournaments", lambda league, since=None: [tournament])
    monkeypatch.setattr(lolesports, "completed_events", lambda tournament_id: [_make_event()])

    rows = lolesports.build_game_index("lck", since=2026)

    assert [r.game_id for r in rows] == ["G1", "G2", "G3"]
    assert [r.game_number for r in rows] == [1, 2, 3]
    assert [r.has_vod for r in rows] == [True, True, False]
    assert rows[0].series_best_of == 3
    assert rows[0].strategy_type == "bestOf"
    assert rows[0].team1_code == "TA"
    assert rows[0].team2_code == "TB"
    assert rows[0].match_id == "M1"
    assert rows[0].tournament == "lck_test_2026"


def test_build_game_index_empty_completed_events_is_not_an_error(tmp_path, monkeypatch) -> None:
    # Mirrors docs/QUESTIONS.md Q26: LCK <=2022 / LEC <=2023 / LPL <=2024
    # legitimately return zero completed events -- must not raise.
    monkeypatch.setattr(config, "DATA_RAW", tmp_path / "raw")
    monkeypatch.setattr(lolesports, "list_tournaments", lambda league, since=None: [])

    assert lolesports.build_game_index("lck", since=2020) == []


def test_list_tournaments_rejects_unknown_league() -> None:
    try:
        lolesports.list_tournaments("not-a-league")
    except ValueError as exc:
        assert "unknown league slug" in str(exc)
    else:
        raise AssertionError("expected ValueError for an unknown league slug")
