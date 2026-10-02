"""Data lake primitives: gzip JSONL append/read/resume, parquet upsert."""

from __future__ import annotations

import gzip

import polars as pl

from riftquant.store import lake


def test_append_and_read_roundtrip_across_two_runs(tmp_path) -> None:
    path = tmp_path / "x.jsonl.gz"
    lake.append_jsonl_gz(path, [{"a": 1}, {"a": 2}])
    lake.append_jsonl_gz(path, [{"a": 3}])  # simulates a second, later process run

    assert list(lake.read_jsonl_gz(path)) == [{"a": 1}, {"a": 2}, {"a": 3}]
    assert lake.count_jsonl_gz(path) == 3


def test_read_jsonl_gz_missing_file_is_empty(tmp_path) -> None:
    assert list(lake.read_jsonl_gz(tmp_path / "missing.jsonl.gz")) == []


def test_read_jsonl_gz_survives_truncated_tail(tmp_path) -> None:
    path = tmp_path / "partial.jsonl.gz"
    lake.append_jsonl_gz(path, [{"a": 1}, {"a": 2}])
    with gzip.open(path, "ab") as fh:
        fh.write(b'{"a": 3, "unterm')  # simulates a process killed mid-write

    assert list(lake.read_jsonl_gz(path)) == [{"a": 1}, {"a": 2}]


def test_read_jsonl_gz_survives_non_gzip_garbage(tmp_path) -> None:
    path = tmp_path / "garbage.jsonl.gz"
    path.write_bytes(b"not actually gzip data")
    assert list(lake.read_jsonl_gz(path)) == []


def test_upsert_parquet_dedupes_on_key_new_wins(tmp_path) -> None:
    path = tmp_path / "idx.parquet"
    key_cols = ["id"]
    df1 = pl.DataFrame({"id": ["a", "b"], "v": [1, 2]})
    df2 = pl.DataFrame({"id": ["b", "c"], "v": [20, 3]})
    lake.upsert_parquet(df1, path, key_cols=key_cols)
    merged = lake.upsert_parquet(df2, path, key_cols=key_cols)

    result = {row["id"]: row["v"] for row in merged.iter_rows(named=True)}
    assert result == {"a": 1, "b": 20, "c": 3}
    assert pl.read_parquet(path).height == 3  # re-running index-games must not duplicate rows


def test_upsert_parquet_survives_a_column_going_from_all_null_to_typed(tmp_path) -> None:
    # Regression: a column that is 100% None the first time a table is
    # written (e.g. patches.season before any seasonal-shape patch exists)
    # is inferred as dtype Null; the next run that finally observes a real
    # value for that column must not crash pl.concat with a SchemaError.
    path = tmp_path / "patches.parquet"
    df1 = pl.DataFrame({"marketing_version": ["14.23"], "season": pl.Series([None], dtype=pl.Null)})
    df2 = pl.DataFrame({"marketing_version": ["25.S1.2"], "season": ["S1"]})
    lake.upsert_parquet(df1, path, key_cols=["marketing_version"])
    merged = lake.upsert_parquet(df2, path, key_cols=["marketing_version"])

    result = {row["marketing_version"]: row["season"] for row in merged.iter_rows(named=True)}
    assert result == {"14.23": None, "25.S1.2": "S1"}
