"""Opt-in live smoke test (real network). Excluded by default (see pyproject
addopts); run explicitly with: pytest -m live
"""

from __future__ import annotations

import pytest

from riftquant.ingest import lolesports


@pytest.mark.live
def test_list_leagues_live_includes_the_four_target_leagues() -> None:
    leagues = lolesports.list_leagues()
    slugs = {league.slug for league in leagues}
    assert {"lck", "lpl", "lec", "lcs"}.issubset(slugs)
