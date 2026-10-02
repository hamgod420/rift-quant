"""Shared canonical-id normalization + alias resolution for players/teams
(M1c brief, "Entity resolution").

Canonical id = normalized Leaguepedia page name (OverviewPage), which
Leaguepedia already treats as a unique key across its own tables. Resolution
never guesses: a name that does not match a known canonical id or alias
after normalization is left unresolved and (by the caller) written to
data/reference/unresolved_entities.csv for a human to adjudicate, rather
than being assigned a best-guess canonical id.

`normalize_name` intentionally does NOT strip sponsor/org tokens (e.g. "SK
Telecom" in "SK Telecom T1") -- there is no deterministic, safe rule for
which tokens are a stripped sponsor and which are load-bearing (e.g. "KT" in
"KT Rolster" is part of the identity, not a sponsor prefix on some other
name). Cases like that are handled explicitly via
data/reference/alias_overrides.csv instead, seeded with exactly that example
-- a human decision recorded once, not a heuristic applied blindly to every
name.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl

from riftquant import config

_PUNCT_RE_SOURCE = r"[^a-z0-9]+"

# DuckDB SQL equivalent of normalize_name, used by store/views.py to join
# raw scoreboard team/player name columns against the alias parquet without
# a Python round-trip. Kept in sync by test_entities_resolve.py, which
# evaluates this exact expression through DuckDB and compares it against
# normalize_name() for a shared set of sample names.
SQL_NORMALIZE_EXPR = "lower(regexp_replace({col}, '[^a-z0-9]+', '', 'gi'))"

ALIAS_OVERRIDES_PATH = config.DATA_ROOT / "reference" / "alias_overrides.csv"
UNRESOLVED_ENTITIES_PATH = config.DATA_ROOT / "reference" / "unresolved_entities.csv"

ALIAS_OVERRIDES_FIELDS = ["entity_type", "alias", "canonical_id", "note"]
UNRESOLVED_FIELDS = ["entity_type", "input_name", "normalized_name", "reason", "candidate_count"]


def normalize_name(name: str) -> str:
    """Lowercase + strip everything but ascii letters/digits. Deterministic
    and total (never raises), so it is always safe to call on raw,
    occasionally-messy wiki text."""
    out = []
    for ch in name.lower():
        if ("a" <= ch <= "z") or ("0" <= ch <= "9"):
            out.append(ch)
    return "".join(out)


@dataclass
class UnresolvedRecord:
    entity_type: str
    input_name: str
    reason: str
    candidate_count: int = 0

    def normalized_name(self) -> str:
        return normalize_name(self.input_name)


def load_alias_overrides(path: Path | None = None) -> list[tuple[str, str, str]]:
    """Read data/reference/alias_overrides.csv. Returns
    (entity_type, normalized_alias, canonical_id) triples. Missing file (or
    header-only) is valid and yields an empty list -- not every deployment
    needs overrides yet."""
    path = path or ALIAS_OVERRIDES_PATH
    if not path.exists():
        return []
    out: list[tuple[str, str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            alias = (row.get("alias") or "").strip()
            canonical_id = (row.get("canonical_id") or "").strip()
            entity_type = (row.get("entity_type") or "").strip()
            if not alias or not canonical_id:
                continue
            out.append((entity_type, normalize_name(alias), canonical_id))
    return out


def write_unresolved_entities(records: list[UnresolvedRecord], path: Path | None = None) -> int:
    """Overwrite data/reference/unresolved_entities.csv with the current
    unresolved set (a derived report, not raw/append-only data -- each
    build-views run recomputes it fresh so it always reflects the current
    lake, never accumulates stale rows from prior runs). Sorted for a stable
    diff across reruns. Returns the row count written."""
    path = path or UNRESOLVED_ENTITIES_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted({(r.entity_type, r.input_name, r.reason, r.candidate_count) for r in records})
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(UNRESOLVED_FIELDS)
        for entity_type, input_name, reason, candidate_count in rows:
            writer.writerow(
                [entity_type, input_name, normalize_name(input_name), reason, candidate_count]
            )
    return len(rows)


@dataclass
class EntityResolver:
    """Resolves raw observed names to canonical ids for one entity type.

    Build order (later steps win): (1) every canonical id maps to itself;
    (2) observed (raw_name -> canonical_id) pairs from ingested data, e.g.
    ScoreboardPlayers' Name/Link columns or Teams' RenamedTo chains -- a
    normalized name seen pointing at more than one distinct canonical id at
    this stage is a collision and is NOT resolvable (ambiguous) unless (3)
    an explicit data/reference/alias_overrides.csv row exists for it, which
    always wins.
    """

    entity_type: str
    _map: dict[str, str] = field(default_factory=dict)
    _collisions: dict[str, set[str]] = field(default_factory=dict)
    unresolved: list[UnresolvedRecord] = field(default_factory=list)

    @classmethod
    def build(
        cls,
        entity_type: str,
        canonical_ids: Iterable[str],
        observed_pairs: Iterable[tuple[str, str]] = (),
        overrides: Iterable[tuple[str, str, str]] = (),
    ) -> EntityResolver:
        resolver = cls(entity_type=entity_type)
        candidates: dict[str, set[str]] = {}

        def add(raw_name: str, canonical_id: str) -> None:
            norm = normalize_name(raw_name)
            if not norm or not canonical_id:
                return
            candidates.setdefault(norm, set()).add(canonical_id)

        for cid in canonical_ids:
            add(cid, cid)
        for raw_name, cid in observed_pairs:
            add(raw_name, cid)

        for norm, targets in candidates.items():
            if len(targets) == 1:
                resolver._map[norm] = next(iter(targets))
            else:
                resolver._collisions[norm] = targets

        for etype, norm_alias, canonical_id in overrides:
            if etype and etype != entity_type:
                continue
            resolver._map[norm_alias] = canonical_id
            resolver._collisions.pop(norm_alias, None)

        # Record every collision that survives overrides right away, not
        # only reactively when something later tries to resolve that exact
        # name (resolve_and_track) -- a collision between two canonical ids
        # that no observed row happens to query for would otherwise be
        # detected internally (collision_count()) but never make it into
        # unresolved_entities.csv, which is what a separate later
        # `validate-m1` process actually reads.
        for norm, targets in resolver._collisions.items():
            ids = ", ".join(sorted(targets))
            reason = f"ambiguous: {len(targets)} canonical ids share this normalized name ({ids})"
            resolver.unresolved.append(UnresolvedRecord(entity_type, norm, reason, len(targets)))

        return resolver

    def resolve(self, name: str) -> str | None:
        return self._map.get(normalize_name(name))

    def resolve_and_track(self, name: str, *, context: str = "") -> str | None:
        """Like resolve(), but records an UnresolvedRecord (reachable via
        `.unresolved`) whenever `name` doesn't map to a canonical id --
        distinguishing "never seen" from "ambiguous" in the reason text."""
        if not name:
            return None
        norm = normalize_name(name)
        hit = self._map.get(norm)
        if hit is not None:
            return hit
        if norm in self._collisions:
            n = len(self._collisions[norm])
            reason = f"ambiguous: {n} canonical ids share this normalized name"
            if context:
                reason += f" ({context})"
            self.unresolved.append(
                UnresolvedRecord(self.entity_type, name, reason, len(self._collisions[norm]))
            )
        else:
            reason = "no canonical id or alias matches this normalized name"
            if context:
                reason += f" ({context})"
            self.unresolved.append(UnresolvedRecord(self.entity_type, name, reason, 0))
        return None

    def collision_count(self) -> int:
        return len(self._collisions)

    def to_alias_frame(self) -> pl.DataFrame:
        """The resolvable (normalized_alias -> canonical_id) map as a
        DataFrame, ready to write to data/processed/entities/*.parquet."""
        if not self._map:
            return pl.DataFrame(
                {
                    "normalized_alias": pl.Series([], dtype=pl.Utf8),
                    "canonical_id": pl.Series([], dtype=pl.Utf8),
                }
            )
        items = sorted(self._map.items())
        return pl.DataFrame(
            {"normalized_alias": [k for k, _ in items], "canonical_id": [v for _, v in items]}
        )


def find_collisions(alias_df: pl.DataFrame) -> pl.DataFrame:
    """Given ANY (normalized_alias, canonical_id) table, return the rows
    where one normalized_alias maps to more than one distinct canonical_id.
    General-purpose collision detector for alias tables built by hand or by
    some path other than EntityResolver -- NOT what store/views.py uses for
    the "entity dupes" validate-m1 metric, since EntityResolver's own
    to_alias_frame() output is collision-free by construction (colliding
    normalized names are excluded, not arbitrarily picked -- see
    resolve_and_track), so running this against it always returns 0 rows
    regardless of how many collisions were actually detected during
    resolution. See store.views.entity_dupe_counts, which instead reads the
    "ambiguous" rows already recorded in unresolved_entities.csv."""
    if alias_df.height == 0:
        return alias_df.clear()
    counts = alias_df.group_by("normalized_alias").agg(pl.col("canonical_id").n_unique().alias("n"))
    dupe_keys = counts.filter(pl.col("n") > 1).select("normalized_alias")
    return alias_df.join(dupe_keys, on="normalized_alias", how="inner").sort("normalized_alias")
