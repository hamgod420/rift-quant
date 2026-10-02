"""Mapping heuristics: normalized team-name overlap + start-time tolerance,
unmatched/ambiguous cases logged to the review file. All network-free."""

from __future__ import annotations

from datetime import UTC, datetime

from riftquant import config
from riftquant.odds import mapping
from riftquant.odds.discovery import MarketMeta
from riftquant.store import lake


def _market(team1: str, team2: str, start_time: datetime | None) -> MarketMeta:
    return MarketMeta(
        venue="polymarket",
        market_id="lol-a-b-2026-08-23",
        event_id="lol-a-b-2026-08-23",
        title=f"LoL: {team1} vs {team2}",
        team1=team1,
        team2=team2,
        start_time=start_time,
        discovered_at=datetime(2026, 8, 21, tzinfo=UTC),
    )


def test_normalize_team_strips_punctuation_and_case() -> None:
    assert mapping.normalize_team("Hanwha Life Esports") == "hanwhalifeesports"
    assert mapping.normalize_team("T1") == mapping.normalize_team("t1 ")


def test_map_market_to_game_unique_match() -> None:
    market = _market("Hanwha Life Esports", "T1", datetime(2026, 8, 23, 8, 0, tzinfo=UTC))
    game_index = [
        {
            "game_id": "game123",
            "team1_name": "Hanwha Life Esports",
            "team1_code": "HLE",
            "team2_name": "T1",
            "team2_code": "T1",
            "start_time": datetime(2026, 8, 23, 8, 5, tzinfo=UTC),
        }
    ]
    result = mapping.map_market_to_game(market, game_index)
    assert result.matched is True
    assert result.game_id == "game123"


def test_map_market_to_game_no_start_time_is_unmatched(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "DATA_RAW", tmp_path / "raw")
    market = _market("Hanwha Life Esports", "T1", None)
    result = mapping.map_market_to_game(market, [])
    assert result.matched is False
    assert "start_time" in result.reason


def test_map_market_to_game_outside_time_window_is_unmatched(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "DATA_RAW", tmp_path / "raw")
    market = _market("Hanwha Life Esports", "T1", datetime(2026, 8, 23, 8, 0, tzinfo=UTC))
    game_index = [
        {
            "game_id": "game999",
            "team1_name": "Hanwha Life Esports",
            "team2_name": "T1",
            "start_time": datetime(2026, 8, 20, 8, 0, tzinfo=UTC),  # 3 days off
        }
    ]
    result = mapping.map_market_to_game(market, game_index)
    assert result.matched is False
    assert result.game_id is None


def test_map_market_to_game_ambiguous_is_unmatched_and_logged(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "DATA_RAW", tmp_path / "raw")
    market = _market("Hanwha Life Esports", "T1", datetime(2026, 8, 23, 8, 0, tzinfo=UTC))
    game_index = [
        {"game_id": "g1", "team1_name": "Hanwha Life Esports", "team2_name": "T1",
         "start_time": datetime(2026, 8, 23, 8, 0, tzinfo=UTC)},
        {"game_id": "g2", "team1_name": "Hanwha Life Esports", "team2_name": "T1",
         "start_time": datetime(2026, 8, 23, 9, 0, tzinfo=UTC)},
    ]
    result = mapping.map_market_to_game(market, game_index)
    assert result.matched is False

    review_path = lake.raw_path("odds", "unmatched_review.jsonl.gz")
    rows = list(lake.read_jsonl_gz(review_path))
    assert len(rows) == 1
    assert rows[0]["market_id"] == "lol-a-b-2026-08-23"
    assert "ambiguous" in rows[0]["reason"]


def test_unmatched_logging_never_raises_on_repeated_calls(tmp_path, monkeypatch) -> None:
    """log-everything must be safe to call every discovery run, not just once."""
    monkeypatch.setattr(config, "DATA_RAW", tmp_path / "raw")
    market = _market("Nobody FC", "Nowhere GC", datetime(2026, 8, 23, 8, 0, tzinfo=UTC))
    mapping.map_market_to_game(market, [])
    mapping.map_market_to_game(market, [])
    rows = list(lake.read_jsonl_gz(lake.raw_path("odds", "unmatched_review.jsonl.gz")))
    assert len(rows) == 2
