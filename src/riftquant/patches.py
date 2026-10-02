"""Patch string parsing + the patches dimension table (M1c brief, "Patches
dimension"; translation rule per docs/research/06-static-and-soloq-data.md
and docs/QUESTIONS.md Q22).

Leaguepedia's ScoreboardGames.Patch field has used three shapes historically:
  - <=2024 legacy: "14.23" -- the marketing name IS the client version, no
    offset applied.
  - 2025 seasonal (used only in the first few weeks of 2025 before Riot
    dropped it): "25.S1.2" -- year 25, season 1, patch 2 of that season.
  - 2025 flat (from roughly the 4th 2025 patch onward) / 2026+: "25.04",
    "26.16" -- the marketing year is offset by -10 from the client major
    version ("26.16" -> client "16.16"), a scheme Riot introduced partway
    through 2025 and has kept since (verified live 2026-08-21: marketing
    "26.16" == Data Dragon "16.16.1").
Any other shape is returned unparsed (client_version=None) rather than
guessed at -- callers should surface unparsed patches for human review, per
the house rule of never guessing silently on entity/identifier resolution.

Note on the "x" in the brief's "16.NN.x" shorthand: Data Dragon versions
carry a third, per-hotfix point number (e.g. "16.16.1") that Leaguepedia's
Patch field does not encode and this module has no data source to recover,
so client_version here is always the two-part "MAJOR.MINOR" -- the "x" was
the brief's way of flagging that a third component exists elsewhere, not an
instruction to synthesize one.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

import polars as pl
from pydantic import BaseModel

from riftquant.store import lake

_LEGACY_OR_FLAT_RE = re.compile(r"^(\d{2})\.(\d{1,2})$")
_SEASONAL_RE = re.compile(r"^(\d{2})\.S(\d+)\.(\d+)$")

# Riot introduced the marketing/client major-version offset starting with
# 2025 patches (docs/research/06 S2.1, "Patch-name-to-version mapping");
# years before that used an identity mapping. Applies uniformly to both the
# 2025 seasonal shape and the 2025+ flat shape.
_OFFSET_ERA_START_YY = 25

PATCHES_PARQUET = lake.processed_path("patches.parquet")


class PatchTranslation(BaseModel):
    """Result of parsing one raw Leaguepedia patch string."""

    raw: str
    marketing_version: str
    client_version: str | None  # None when `raw` matched no known shape
    year: int | None
    ordinal: int | None  # sortable: client_major * 1000 + client_minor
    parsed: bool


def translate_patch(raw: str) -> PatchTranslation:
    """Parse one Cargo `Patch` string into marketing/client identifiers.

    Unknown shapes come back with parsed=False and client_version=None
    instead of raising -- ingestion should keep moving and let validate-m1
    surface the unparsed count rather than crash on one odd historical row.
    """
    text = raw.strip()

    m = _SEASONAL_RE.match(text)
    if m:
        yy, _season, patch_in_season = m.groups()
        yy_int = int(yy)
        client_major = yy_int - 10
        client_minor = int(patch_in_season)
        return PatchTranslation(
            raw=raw,
            marketing_version=text,
            client_version=f"{client_major}.{client_minor}",
            year=2000 + yy_int,
            ordinal=client_major * 1000 + client_minor,
            parsed=True,
        )

    m = _LEGACY_OR_FLAT_RE.match(text)
    if m:
        yy, nn = m.groups()
        yy_int = int(yy)
        nn_int = int(nn)
        if yy_int < _OFFSET_ERA_START_YY:
            client_major, client_minor = yy_int, nn_int
        else:
            client_major, client_minor = yy_int - 10, nn_int
        return PatchTranslation(
            raw=raw,
            marketing_version=text,
            client_version=f"{client_major}.{client_minor}",
            year=2000 + yy_int,
            ordinal=client_major * 1000 + client_minor,
            parsed=True,
        )

    return PatchTranslation(
        raw=raw, marketing_version=text, client_version=None, year=None, ordinal=None, parsed=False
    )


def era_flags(year: int | None) -> dict[str, bool]:
    """Era flags per the brief: fearless_era >=2025, first_selection_era
    >=2026, atakhan_era 2025 only. `year` is the marketing year (None for an
    unparsed patch, in which case every flag is False -- an unknown patch
    should never silently count toward era-scoped stats)."""
    if year is None:
        return {"fearless_era": False, "first_selection_era": False, "atakhan_era": False}
    return {
        "fearless_era": year >= 2025,
        "first_selection_era": year >= 2026,
        "atakhan_era": year == 2025,
    }


class PatchDim(BaseModel):
    """One row of the patches dimension table."""

    marketing_version: str
    client_version: str | None
    ordinal: int | None
    year: int | None
    season: str | None  # "S<N>" for the seasonal shape, else None
    release_date: date | None  # approx: earliest game date seen on this patch
    fearless_era: bool
    first_selection_era: bool
    atakhan_era: bool
    parsed: bool


def _season_label(raw: str) -> str | None:
    m = _SEASONAL_RE.match(raw.strip())
    return f"S{m.group(2)}" if m else None


def build_patches_table(observations: list[tuple[str, datetime | date]]) -> list[PatchDim]:
    """Build one PatchDim per distinct raw patch string seen in
    `observations` (raw_patch, game_date) pairs -- typically
    (ScoreboardGame.patch, parsed ScoreboardGame.date_time_utc). release_date
    is the earliest game date observed for that patch in THIS batch; see
    `write_patches_parquet` for how repeated/incremental runs merge dates
    across batches instead of letting a later, narrower batch overwrite an
    earlier-seen release date.
    """
    earliest: dict[str, date] = {}
    for raw, when in observations:
        d = when.date() if isinstance(when, datetime) else when
        if raw not in earliest or d < earliest[raw]:
            earliest[raw] = d

    rows: list[PatchDim] = []
    for raw, release_date in sorted(earliest.items()):
        t = translate_patch(raw)
        rows.append(
            PatchDim(
                marketing_version=t.marketing_version,
                client_version=t.client_version,
                ordinal=t.ordinal,
                year=t.year,
                season=_season_label(raw),
                release_date=release_date,
                parsed=t.parsed,
                **era_flags(t.year),
            )
        )
    return rows


def write_patches_parquet(rows: list[PatchDim], path: Path | None = None) -> pl.DataFrame:
    """Upsert `rows` into the patches dimension parquet, keyed on
    marketing_version. Unlike a plain upsert, release_date is merged as a
    MIN across old and new rows for the same patch -- otherwise a later run
    that only ingests a league/season slice not containing a patch's actual
    earliest game would silently push its release_date later.
    """
    path = path or PATCHES_PARQUET
    if not rows:
        return pl.read_parquet(path) if path.exists() else pl.DataFrame()
    new_df = pl.DataFrame([r.model_dump() for r in rows])
    if path.exists() and new_df.height > 0:
        existing = pl.read_parquet(path)
        overlap = existing.select(["marketing_version", "release_date"]).rename(
            {"release_date": "_existing_release_date"}
        )
        new_df = new_df.join(overlap, on="marketing_version", how="left")
        new_df = new_df.with_columns(
            pl.min_horizontal("release_date", "_existing_release_date").alias("release_date")
        ).drop("_existing_release_date")
    return lake.upsert_parquet(new_df, path, key_cols=["marketing_version"])
