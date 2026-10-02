"""Data lake primitives: raw-first gzipped JSONL logs, processed parquet.

Raw-first principle: connectors persist the verbatim API payload here before
any normalization touches it. Everything is designed to be safe to call
repeatedly (idempotent) and safe to resume after an interrupted process.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

from riftquant import config

if TYPE_CHECKING:
    import duckdb


def raw_path(*parts: str) -> Path:
    return config.DATA_RAW.joinpath(*parts)


def processed_path(*parts: str) -> Path:
    return config.DATA_PROCESSED.joinpath(*parts)


class JsonlGzWriter:
    """Append-mode gzip JSONL writer.

    Each open/close cycle writes one gzip member; concatenated gzip members
    decompress transparently via the stdlib `gzip` module, so archiver runs
    that span multiple process invocations can keep appending to the same
    file safely (no read-modify-write of the whole file needed).
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = gzip.open(path, "at", encoding="utf-8")

    def write(self, record: dict) -> None:
        self._fh.write(json.dumps(record, ensure_ascii=True, default=str))
        self._fh.write("\n")

    def close(self) -> None:
        self._fh.close()

    def __enter__(self) -> JsonlGzWriter:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def append_jsonl_gz(path: Path, records: Iterable[dict]) -> int:
    """Append `records` as gzip JSON lines. Returns the count written."""
    n = 0
    with JsonlGzWriter(path) as writer:
        for rec in records:
            writer.write(rec)
            n += 1
    return n


def read_jsonl_gz(path: Path) -> Iterator[dict]:
    """Yield records from a gzipped JSONL file.

    Yields nothing for a missing file. Stops (without raising) at a
    truncated/corrupt tail -- the signature of a process that was killed
    mid-write -- so resume logic just re-fetches the missing tail instead of
    crashing on it.
    """
    if not path.exists():
        return
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    return
    except (EOFError, gzip.BadGzipFile, OSError):
        return


def count_jsonl_gz(path: Path) -> int:
    return sum(1 for _ in read_jsonl_gz(path))


def _align_null_columns(
    left: pl.DataFrame, right: pl.DataFrame
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Cast a shared column that is all-None (dtype Null) on one side to the
    other side's dtype before a vertical concat.

    A column can legitimately be 100% None the first time a table is
    written (e.g. patches.season before any seasonal-shape patch has been
    seen), which polars infers as dtype Null. The next incremental run that
    finally observes a real value for that column produces a typed (e.g.
    Utf8) column, and `pl.concat` raises SchemaError on Null-vs-typed
    mismatches instead of coercing -- this keeps that schema-evolution case
    from crashing every downstream upsert.
    """
    for col in set(left.columns) & set(right.columns):
        lt, rt = left.schema[col], right.schema[col]
        if lt == pl.Null and rt != pl.Null:
            left = left.with_columns(pl.col(col).cast(rt))
        elif rt == pl.Null and lt != pl.Null:
            right = right.with_columns(pl.col(col).cast(lt))
    return left, right


def duckdb_to_polars(con: duckdb.DuckDBPyConnection, sql: str) -> pl.DataFrame:
    """Run `sql` and return the result as a polars DataFrame, without going
    through DuckDB's own `.pl()`/`.df()` (both need pyarrow/pandas, neither
    of which is a project dependency -- store/views.py already fetches via
    plain `.fetchall()` throughout for the same reason; this is the same
    pattern factored out for riftquant.ratings/riftquant.features, which
    need whole result sets as DataFrames rather than scalar/tuple reads).
    """
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    return pl.DataFrame({col: [row[i] for row in rows] for i, col in enumerate(cols)})


def upsert_parquet(df: pl.DataFrame, path: Path, key_cols: list[str]) -> pl.DataFrame:
    """Merge `df` into the parquet table at `path`, de-duplicating on
    `key_cols` (rows from `df` win ties). Creates the table if absent.
    Idempotent: safe to call repeatedly with overlapping data, e.g. re-running
    index-games for a league that already has an index on disk.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = pl.read_parquet(path)
        existing, df = _align_null_columns(existing, df)
        merged = pl.concat([existing, df])
    else:
        merged = df
    merged = merged.unique(subset=key_cols, keep="last")
    merged.write_parquet(path)
    return merged
