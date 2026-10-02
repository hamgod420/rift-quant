"""Team/player resolver builders over Leaguepedia-shaped rows.

Network-free: rows are hand-built dicts matching the shape
ingest.leaguepedia's Teams/Players/ScoreboardPlayers parquet produce.
"""

from __future__ import annotations

from riftquant.entities.players import build_player_resolver
from riftquant.entities.teams import build_team_resolver, resolve_team_rename_chain


def test_resolve_team_rename_chain_follows_to_terminal_page() -> None:
    renamed_to = {"SK Telecom T1": "T1"}
    assert resolve_team_rename_chain("SK Telecom T1", renamed_to) == "T1"
    assert resolve_team_rename_chain("T1", renamed_to) == "T1"  # no entry -- already terminal


def test_resolve_team_rename_chain_follows_multiple_hops() -> None:
    renamed_to = {"Longzhu Gaming": "Kingzone DragonX", "Kingzone DragonX": "DragonX"}
    assert resolve_team_rename_chain("Longzhu Gaming", renamed_to) == "DragonX"


def test_resolve_team_rename_chain_breaks_a_cycle() -> None:
    renamed_to = {"A": "B", "B": "A"}
    # Must terminate, not loop forever; exact landing page is secondary here.
    assert resolve_team_rename_chain("A", renamed_to) in {"A", "B"}


def test_build_team_resolver_resolves_old_name_short_and_page() -> None:
    team_pages = [
        {
            "overview_page": "SK Telecom T1",
            "name": "SK Telecom T1",
            "short": "SKT",
            "renamed_to": "T1",
        },
        {"overview_page": "T1", "name": "T1", "short": "T1", "renamed_to": ""},
    ]
    resolver = build_team_resolver(team_pages)
    assert resolver.resolve("SK Telecom T1") == "T1"
    assert resolver.resolve("SKT") == "T1"
    assert resolver.resolve("T1") == "T1"


def test_build_team_resolver_tracks_unresolved_observed_names() -> None:
    team_pages = [{"overview_page": "T1", "name": "T1", "short": "T1", "renamed_to": ""}]
    resolver = build_team_resolver(team_pages, observed_names=["Some Unknown Org"])
    assert resolver.resolve("Some Unknown Org") is None
    assert any(u.input_name == "Some Unknown Org" for u in resolver.unresolved)


def test_build_player_resolver_resolves_page_and_observed_link() -> None:
    player_pages = [{"overview_page": "Faker", "player": "Faker", "name": "Faker"}]
    pairs = [("Faker", "Faker"), ("faker (old handle)", "Faker")]
    resolver = build_player_resolver(player_pages, scoreboard_name_link_pairs=pairs)
    assert resolver.resolve("Faker") == "Faker"
    assert resolver.resolve("faker (old handle)") == "Faker"


def test_build_player_resolver_tracks_rows_with_no_link() -> None:
    resolver = build_player_resolver([], scoreboard_name_link_pairs=[("Mystery Sub", "")])
    assert any("no Link" in u.reason for u in resolver.unresolved)


def test_build_player_resolver_reconciles_link_case_mismatch_against_players_table() -> None:
    # Regression test for a real gap found live 2026-08-21: Players.OverviewPage
    # ("Deokdam") and ScoreboardPlayers.Link ("deokdam") disagree on casing.
    # Treating Link as its own canonical id would mint a second entry that
    # collides with "Deokdam" under normalize_name and leaves both unresolved.
    player_pages = [{"overview_page": "Deokdam", "player": "deokdam", "name": "Seo Dae-gil"}]
    resolver = build_player_resolver(
        player_pages, scoreboard_name_link_pairs=[("deokdam", "deokdam")]
    )
    assert resolver.resolve("deokdam") == "Deokdam"
    assert resolver.collision_count() == 0
    assert resolver.unresolved == []


def test_build_player_resolver_falls_back_to_link_when_players_table_lacks_the_page() -> None:
    # No Players-table coverage at all for this page (e.g. the bounded fetch
    # missed it) -- Link is still usable as a best-effort canonical id.
    resolver = build_player_resolver([], scoreboard_name_link_pairs=[("Ghost Sub", "Ghost Sub")])
    assert resolver.resolve("Ghost Sub") == "Ghost Sub"


def test_build_player_resolver_tracks_unresolved_non_empty_link_on_true_collision() -> None:
    # Two distinct canonical ids that happen to share a normalized form is a
    # genuine ambiguity (unlike the case-only mismatch above) and must stay
    # unresolved + reported, not arbitrarily picked.
    player_pages = [
        {"overview_page": "Player A", "player": "", "name": ""},
        {"overview_page": "PlayerA", "player": "", "name": ""},
    ]
    pairs = [("Player A", "Player A")]
    resolver = build_player_resolver(player_pages, scoreboard_name_link_pairs=pairs)
    assert resolver.resolve("Player A") is None
    assert any("ambiguous" in u.reason for u in resolver.unresolved)
