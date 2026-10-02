"""Player entity resolution: canonical ids from Leaguepedia's Players cargo
table plus observed (display Name -> Link) pairs from already-ingested
ScoreboardPlayers rows. `Link` is the wiki page a display name resolved to
at query time -- i.e. Leaguepedia has already walked its own redirects for
us -- which is exactly the "redirects and observed name variants" alias
source the brief asks for, with no extra API calls needed (M1c brief,
"Entity resolution")."""

from __future__ import annotations

from collections.abc import Iterable

from riftquant.entities.resolve import EntityResolver, load_alias_overrides, normalize_name
from riftquant.store import lake

PLAYER_ALIASES_PARQUET = lake.processed_path("entities", "player_aliases.parquet")


def build_player_resolver(
    player_pages: list[dict],
    scoreboard_name_link_pairs: Iterable[tuple[str, str]] = (),
) -> EntityResolver:
    """`player_pages` are dict rows with overview_page/player/name keys (the
    shape ingest.leaguepedia's Players parquet produces).
    `scoreboard_name_link_pairs` are (Name, Link) pairs straight off ingested
    ScoreboardPlayers rows."""
    canonical_ids = {row["overview_page"] for row in player_pages if row.get("overview_page")}
    norm_to_canonical = {normalize_name(cid): cid for cid in canonical_ids}

    observed_pairs: list[tuple[str, str]] = []
    for row in player_pages:
        page = row.get("overview_page")
        if not page:
            continue
        if row.get("player"):
            observed_pairs.append((row["player"], page))
        if row.get("name"):
            observed_pairs.append((row["name"], page))

    for display_name, link in scoreboard_name_link_pairs:
        if not link:
            continue
        # ScoreboardPlayers.Link isn't always cased identically to the
        # Players table's OverviewPage (observed live 2026-08-21: Link
        # "deokdam" vs OverviewPage "Deokdam"). Resolve to the already-known
        # canonical casing when normalization identifies one, instead of
        # accidentally minting "deokdam" as a second canonical id that
        # collides with "Deokdam" under normalize_name and leaves both
        # unresolved.
        target = norm_to_canonical.get(normalize_name(link), link)
        canonical_ids.add(target)
        observed_pairs.append((display_name, target))
        observed_pairs.append((link, target))

    overrides = [o for o in load_alias_overrides() if o[0] == "player"]
    resolver = EntityResolver.build("player", canonical_ids, observed_pairs, overrides)
    for display_name, link in scoreboard_name_link_pairs:
        if not link:
            resolver.resolve_and_track(display_name, context="ScoreboardPlayers row with no Link")
        elif resolver.resolve(display_name) is None:
            resolver.resolve_and_track(display_name, context="observed in ScoreboardPlayers")
    return resolver
