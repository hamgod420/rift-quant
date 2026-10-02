"""Team entity resolution: canonical ids + alias table built from
Leaguepedia's Teams cargo table (RenamedTo chains, e.g. "SK Telecom T1" ->
"T1") plus any team names observed in already-ingested scoreboard/draft/
roster rows that the Teams fetch didn't cover (M1c brief, "Entity
resolution")."""

from __future__ import annotations

from collections.abc import Iterable

from riftquant.entities.resolve import EntityResolver, load_alias_overrides
from riftquant.store import lake

TEAM_ALIASES_PARQUET = lake.processed_path("entities", "team_aliases.parquet")

_MAX_RENAME_HOPS = 10  # generous bound against a malformed/cyclic RenamedTo chain


def resolve_team_rename_chain(overview_page: str, renamed_to_by_page: dict[str, str]) -> str:
    """Follow Teams.RenamedTo forward until it terminates (empty/missing, a
    self-reference, or a cycle), returning the final page name. RenamedTo on
    Leaguepedia points from a superseded org-name page to the current one."""
    seen = {overview_page}
    current = overview_page
    for _ in range(_MAX_RENAME_HOPS):
        nxt = renamed_to_by_page.get(current)
        if not nxt or nxt == current or nxt in seen:
            return current
        seen.add(nxt)
        current = nxt
    return current


def build_team_resolver(
    team_pages: list[dict],
    observed_names: Iterable[str] = (),
) -> EntityResolver:
    """`team_pages` are dict rows with overview_page/name/short/renamed_to
    keys (the shape ingest.leaguepedia's Teams parquet produces).
    `observed_names` are extra raw team names seen in scoreboard/draft/
    roster data (e.g. Team1/Team2), tracked as unresolved if they don't
    match anything the Teams table produced."""
    renamed_to_by_page = {
        row["overview_page"]: row["renamed_to"]
        for row in team_pages
        if row.get("overview_page") and row.get("renamed_to")
    }

    canonical_ids: set[str] = set()
    observed_pairs: list[tuple[str, str]] = []
    for row in team_pages:
        page = row.get("overview_page")
        if not page:
            continue
        canonical = resolve_team_rename_chain(page, renamed_to_by_page)
        canonical_ids.add(canonical)
        observed_pairs.append((page, canonical))
        if row.get("name"):
            observed_pairs.append((row["name"], canonical))
        if row.get("short"):
            observed_pairs.append((row["short"], canonical))

    overrides = [o for o in load_alias_overrides() if o[0] == "team"]
    resolver = EntityResolver.build("team", canonical_ids, observed_pairs, overrides)
    for name in observed_names:
        if name:
            resolver.resolve_and_track(name, context="observed in scoreboard/draft/roster rows")
    return resolver
