"""Patch string translation + patches dimension table.

Network-free: everything here is pure parsing/aggregation over literal
strings and in-memory rows.
"""

from __future__ import annotations

from datetime import date, datetime

from riftquant import patches


def test_translate_legacy_identity_mapping() -> None:
    t = patches.translate_patch("14.23")
    assert t.parsed
    assert t.client_version == "14.23"
    assert t.marketing_version == "14.23"
    assert t.year == 2014
    assert t.ordinal == 14 * 1000 + 23


def test_translate_seasonal_2025_offset() -> None:
    t = patches.translate_patch("25.S1.2")
    assert t.parsed
    assert t.client_version == "15.2"
    assert t.year == 2025
    assert t.ordinal == 15 * 1000 + 2


def test_translate_flat_2026_offset() -> None:
    t = patches.translate_patch("26.03")
    assert t.parsed
    assert t.client_version == "16.3"
    assert t.year == 2026


def test_translate_flat_2026_matches_ddragon_16_16() -> None:
    # docs/research/06: marketing "26.16" == Data Dragon "16.16.1" (verified
    # live 2026-08-21). client_version stops at MAJOR.MINOR (see module
    # docstring on the undeterminable third ddragon point-release number).
    t = patches.translate_patch("26.16")
    assert t.parsed
    assert t.client_version == "16.16"
    assert t.year == 2026


def test_translate_unknown_format_fallback_does_not_raise() -> None:
    t = patches.translate_patch("not-a-patch")
    assert t.parsed is False
    assert t.client_version is None
    assert t.year is None
    assert t.ordinal is None
    assert t.marketing_version == "not-a-patch"  # preserved verbatim for review


def test_translate_empty_string_is_unknown() -> None:
    t = patches.translate_patch("")
    assert t.parsed is False


def test_era_flags_by_year() -> None:
    assert patches.era_flags(2024) == {
        "fearless_era": False,
        "first_selection_era": False,
        "atakhan_era": False,
    }
    assert patches.era_flags(2025) == {
        "fearless_era": True,
        "first_selection_era": False,
        "atakhan_era": True,
    }
    assert patches.era_flags(2026) == {
        "fearless_era": True,
        "first_selection_era": True,
        "atakhan_era": False,
    }
    assert patches.era_flags(None) == {
        "fearless_era": False,
        "first_selection_era": False,
        "atakhan_era": False,
    }


def test_build_patches_table_takes_earliest_date_per_patch() -> None:
    rows = patches.build_patches_table(
        [
            ("26.03", datetime(2026, 2, 10, 8, 0, 0)),
            ("26.03", datetime(2026, 2, 5, 8, 0, 0)),  # earlier -- should win
            ("14.23", date(2024, 11, 20)),
        ]
    )
    by_patch = {r.marketing_version: r for r in rows}
    assert by_patch["26.03"].release_date == date(2026, 2, 5)
    assert by_patch["26.03"].client_version == "16.3"
    assert by_patch["26.03"].first_selection_era is True
    assert by_patch["14.23"].release_date == date(2024, 11, 20)
    assert by_patch["14.23"].fearless_era is False


def test_build_patches_table_season_label() -> None:
    rows = patches.build_patches_table([("25.S1.2", date(2025, 1, 20))])
    assert rows[0].season == "S1"


def test_build_patches_table_empty_input() -> None:
    assert patches.build_patches_table([]) == []


def test_write_patches_parquet_merges_release_date_as_min_across_runs(tmp_path) -> None:
    path = tmp_path / "patches.parquet"
    first = patches.build_patches_table([("26.03", date(2026, 2, 10))])
    patches.write_patches_parquet(first, path)

    # A later run only sees a narrower slice that happens to start later --
    # release_date must stay at the earlier date, not jump forward.
    second = patches.build_patches_table([("26.03", date(2026, 3, 1))])
    merged = patches.write_patches_parquet(second, path)

    row = merged.filter(merged["marketing_version"] == "26.03").to_dicts()[0]
    assert row["release_date"] == date(2026, 2, 10)


def test_write_patches_parquet_empty_rows_is_a_noop_without_existing_file(tmp_path) -> None:
    path = tmp_path / "patches.parquet"
    result = patches.write_patches_parquet([], path)
    assert result.height == 0
    assert not path.exists()
