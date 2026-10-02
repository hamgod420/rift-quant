"""Entity resolution primitives: normalization, alias overrides, resolver
collision handling, unresolved-entity reporting.

Network-free. The DuckDB-parity test spins up an in-memory DuckDB connection
(no network) purely to check the SQL expression string matches
normalize_name() -- store/views.py relies on that equivalence for its joins.
"""

from __future__ import annotations

import duckdb
import polars as pl

from riftquant.entities.resolve import (
    SQL_NORMALIZE_EXPR,
    EntityResolver,
    UnresolvedRecord,
    find_collisions,
    load_alias_overrides,
    normalize_name,
    write_unresolved_entities,
)


def test_normalize_name_lowercases_and_strips_punctuation() -> None:
    assert normalize_name("SK Telecom T1") == "sktelecomt1"
    assert normalize_name("  Spacey   Name ") == "spaceyname"
    assert normalize_name("Team-Liquid_2026") == "teamliquid2026"
    assert normalize_name("") == ""


def test_sql_normalize_expr_matches_python_normalize_name() -> None:
    con = duckdb.connect()
    samples = ["T1", "SK Telecom T1", "Gen.G Esports", "  Spacey   Name ", "G2 Esports", ""]
    for s in samples:
        sql_val = con.execute(f"SELECT {SQL_NORMALIZE_EXPR.format(col='?')}", [s]).fetchone()[0]
        assert sql_val == normalize_name(s), f"mismatch for {s!r}"


def test_load_alias_overrides_missing_file_is_empty(tmp_path) -> None:
    assert load_alias_overrides(tmp_path / "missing.csv") == []


def test_load_alias_overrides_parses_and_normalizes(tmp_path) -> None:
    path = tmp_path / "overrides.csv"
    path.write_text(
        "entity_type,alias,canonical_id,note\nteam,SK Telecom T1,T1,pre-2019 name\n",
        encoding="utf-8",
    )
    rows = load_alias_overrides(path)
    assert rows == [("team", "sktelecomt1", "T1")]


def test_write_unresolved_entities_overwrites_and_dedupes(tmp_path) -> None:
    path = tmp_path / "unresolved.csv"
    write_unresolved_entities([UnresolvedRecord("team", "Foo", "no match", 0)], path)
    n = write_unresolved_entities(
        [
            UnresolvedRecord("team", "Bar", "no match", 0),
            UnresolvedRecord("team", "Bar", "no match", 0),  # duplicate -- deduped
        ],
        path,
    )
    text = path.read_text(encoding="utf-8")
    assert "Foo" not in text  # overwritten, not appended
    assert text.count("Bar") == 1
    assert n == 1


def test_entity_resolver_resolves_canonical_and_alias() -> None:
    resolver = EntityResolver.build(
        "team",
        canonical_ids=["T1"],
        observed_pairs=[("SK Telecom T1", "T1")],
    )
    assert resolver.resolve("T1") == "T1"
    assert resolver.resolve("sk telecom t1") == "T1"
    assert resolver.resolve("totally unknown team") is None


def test_entity_resolver_flags_collisions_as_unresolvable_without_override() -> None:
    # Two different canonical ids both observed under the same normalized name.
    resolver = EntityResolver.build(
        "team",
        canonical_ids=["Team A", "Team B"],
        observed_pairs=[("Shared Name", "Team A"), ("Shared Name", "Team B")],
    )
    assert resolver.resolve("Shared Name") is None
    assert resolver.collision_count() == 1
    # build() already recorded the collision proactively (so a later
    # validate-m1 run reading unresolved_entities.csv sees it even if
    # nothing ever explicitly queries "Shared Name" again).
    assert len(resolver.unresolved) == 1
    assert "ambiguous" in resolver.unresolved[0].reason

    # resolve_and_track adds a second, reactive record for the exact form
    # queried -- both normalize to the same name, so a distinct-normalized-
    # name count (what entity_dupe_counts() computes) still reads 1.
    result = resolver.resolve_and_track("Shared Name")
    assert result is None
    assert len(resolver.unresolved) == 2
    normalized_names = {u.normalized_name() for u in resolver.unresolved}
    assert normalized_names == {"sharedname"}
    assert all("ambiguous" in u.reason for u in resolver.unresolved)


def test_entity_resolver_override_wins_over_collision() -> None:
    resolver = EntityResolver.build(
        "team",
        canonical_ids=["Team A", "Team B"],
        observed_pairs=[("Shared Name", "Team A"), ("Shared Name", "Team B")],
        overrides=[("team", "sharedname", "Team A")],
    )
    assert resolver.resolve("Shared Name") == "Team A"
    assert resolver.collision_count() == 0


def test_entity_resolver_override_for_other_entity_type_is_ignored() -> None:
    resolver = EntityResolver.build(
        "team", canonical_ids=["T1"], overrides=[("player", "t1", "Some Player")]
    )
    assert resolver.resolve("T1") == "T1"  # not overridden by a player-scoped row


def test_resolve_and_track_records_never_seen_reason() -> None:
    resolver = EntityResolver.build("player", canonical_ids=["Faker"])
    assert resolver.resolve_and_track("Totally Unknown", context="test") is None
    assert len(resolver.unresolved) == 1
    assert resolver.unresolved[0].reason.startswith("no canonical id")
    assert "test" in resolver.unresolved[0].reason


def test_to_alias_frame_shape() -> None:
    resolver = EntityResolver.build("team", canonical_ids=["T1"], observed_pairs=[("SKT", "T1")])
    df = resolver.to_alias_frame()
    assert set(df.columns) == {"normalized_alias", "canonical_id"}
    assert df.filter(df["normalized_alias"] == "skt")["canonical_id"].to_list() == ["T1"]


def test_to_alias_frame_empty_has_correct_dtype_for_parquet_roundtrip(tmp_path) -> None:
    resolver = EntityResolver.build("team", canonical_ids=[])
    df = resolver.to_alias_frame()
    assert df.height == 0
    path = tmp_path / "aliases.parquet"
    df.write_parquet(path)  # would raise if dtype inference produced an unwritable schema
    assert pl.read_parquet(path).height == 0


def test_find_collisions_detects_shared_normalized_alias() -> None:
    df = pl.DataFrame(
        {
            "normalized_alias": ["kt", "kt", "t1"],
            "canonical_id": ["KT Rolster", "KT Interactive", "T1"],
        }
    )
    dupes = find_collisions(df)
    assert dupes.height == 2
    assert set(dupes["normalized_alias"].to_list()) == {"kt"}


def test_find_collisions_empty_frame() -> None:
    df = pl.DataFrame(
        {
            "normalized_alias": pl.Series([], dtype=pl.Utf8),
            "canonical_id": pl.Series([], dtype=pl.Utf8),
        }
    )
    assert find_collisions(df).height == 0
