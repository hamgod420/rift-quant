"""The central point-in-time ("as-of") toolkit for the M2 pregame feature
builder (docs/specs/M2-pregame-model-brief.md, "POINT-IN-TIME": every
feature for game G uses only games with start_time < G.start_time,
implemented as as-of joins centrally, one feature-builder API, never ad
hoc).

Every lookup in riftquant.features.pregame that answers "what did we know
about <player/team/champion> as of just before this game" routes through
one of the three functions below -- never a hand-rolled join or window.
That makes a leakage bug a 3-function audit instead of an n-features audit,
and is what the brief's leakage tripwire test (tests/test_leakage_tripwire.py)
exercises directly.

All three share one trick for strictness: polars' native `join_asof` /
`cum_sum` / `rolling_mean` are all INCLUSIVE of the current row by default
(a "backward" asof join treats an equal timestamp as a match; a cumulative
sum at row i includes row i). Point-in-time correctness needs STRICT
"before", so every helper here shifts by one row (the per-table cases) or
subtracts a sub-millisecond epsilon from the query timestamp (the
cross-table case) before handing off to the native op, so a row can never
see itself.
"""

from __future__ import annotations

from datetime import timedelta

import polars as pl

_EPSILON = timedelta(microseconds=1)


def asof_join_latest(
    target: pl.DataFrame,
    history: pl.DataFrame,
    *,
    by: list[str],
    target_ts: str,
    history_ts: str,
) -> pl.DataFrame:
    """Attach, to each row of `target`, the columns of the most recent
    `history` row sharing the `by` key(s) with `history[history_ts]`
    STRICTLY LESS THAN `target[target_ts]`.

    Rows of `target` with no qualifying `history` row (e.g. a player's
    first-ever game) get nulls for every `history` column -- callers decide
    how to fill those (a cold-start default, or leave null and let LightGBM
    treat it as "missing", never a silent zero).

    Why strictness needs an epsilon, not just `strategy="backward"`: this
    project's own rating snapshots are written WITH `as_of == that game's
    own date` (riftquant.ratings.openskill_ratings.build_ratings writes one
    row per player per game they played, timestamped at that game's date).
    An inclusive backward-asof join would therefore hand a game its own
    post-game rating as a PREGAME feature -- the textbook leakage bug this
    brief's tripwire test checks for. Subtracting a 1-microsecond epsilon
    from the query timestamp excludes an exact-timestamp self-row without
    excluding any genuinely earlier row (two independent games sharing the
    same microsecond-precision timestamp is not something this codebase's
    date parsing can produce -- see store/views.py).

    Neither input needs to be pre-sorted; `target`'s original row order is
    restored before returning.
    """
    if target.height == 0:
        return target
    order_col = "__asof_row_order__"
    query_col = "__asof_query_ts__"
    t = target.with_row_index(order_col).with_columns(
        (pl.col(target_ts) - _EPSILON).alias(query_col)
    )
    t_sorted = t.sort(query_col)
    h_sorted = history.sort(history_ts)
    joined = t_sorted.join_asof(
        h_sorted,
        left_on=query_col,
        right_on=history_ts,
        by=by,
        strategy="backward",
        # Both sides are explicitly sorted immediately above; polars can't
        # verify sortedness itself when `by` groups are involved and warns
        # on every call otherwise -- silenced because the precondition is
        # actually guaranteed here, not skipped.
        check_sortedness=False,
    )
    return joined.sort(order_col).drop([order_col, query_col])


def strictly_prior_stats(
    df: pl.DataFrame,
    *,
    group_by: list[str],
    order_by: str,
    value_col: str,
    count_alias: str | None = None,
    sum_alias: str | None = None,
) -> pl.DataFrame:
    """Attach a count-before and sum-before column: for each row, the
    count/sum of (non-null) `value_col` over rows STRICTLY earlier (by
    `order_by`, ties broken by input order) in the same `group_by` group.

    The one building block behind every "games so far" / "wins so far" /
    "cumulative pro presence on this patch" feature in pregame.py. Built
    from a cumulative sum SHIFTED by one row within the group -- a shifted
    cumulative sum can never include its own row, so this is point-in-time
    by construction, not by convention.
    """
    count_alias = count_alias or f"{value_col}_n_before"
    sum_alias = sum_alias or f"{value_col}_sum_before"
    d = df.sort(order_by)
    is_valid = pl.col(value_col).is_not_null().cast(pl.Int64)
    filled = pl.col(value_col).cast(pl.Float64).fill_null(0.0)
    return d.with_columns(
        is_valid.cum_sum().shift(1).fill_null(0).over(group_by).alias(count_alias),
        filled.cum_sum().shift(1).fill_null(0.0).over(group_by).alias(sum_alias),
    )


def strictly_prior_last_timestamp(
    df: pl.DataFrame,
    *,
    group_by: list[str],
    order_by: str,
    alias: str | None = None,
) -> pl.DataFrame:
    """Attach the timestamp of the immediately-preceding row in the same
    `group_by` group (by `order_by`) -- e.g. group_by=[player_id, champion]
    gives "when this player last played this champion before this game"
    (null the first time). A plain `.shift(1).over(group_by)` on an
    already-sorted frame is inherently strict: shifting can never surface
    the current row's own value.
    """
    alias = alias or f"{order_by}_prior"
    d = df.sort(order_by)
    return d.with_columns(pl.col(order_by).shift(1).over(group_by).alias(alias))


def strictly_prior_rolling_mean(
    df: pl.DataFrame,
    *,
    group_by: list[str],
    order_by: str,
    value_col: str,
    window_size: int,
    alias: str | None = None,
) -> pl.DataFrame:
    """Attach the trailing `window_size`-row mean of `value_col` over rows
    STRICTLY earlier in the same group (e.g. "win rate over the player's
    last 10 games before this one"). `min_periods=1` so an early-career row
    with fewer than `window_size` prior games still gets a (noisier)
    average rather than a premature null -- only a row with ZERO prior
    games in the group is null.
    """
    alias = alias or f"{value_col}_rolling{window_size}_before"
    d = df.sort(order_by)
    expr = (
        pl.col(value_col)
        .cast(pl.Float64)
        .shift(1)
        .rolling_mean(window_size=window_size, min_samples=1)
        .over(group_by)
    )
    return d.with_columns(expr.alias(alias))


def strictly_prior_ewm_mean(
    df: pl.DataFrame,
    *,
    group_by: list[str],
    order_by: str,
    value_col: str,
    alpha: float,
    alias: str | None = None,
) -> pl.DataFrame:
    """Attach an exponentially-decayed mean of `value_col` over rows
    STRICTLY earlier in the same group -- "recent form, decayed" (M2 brief,
    team_ feature group), weighting the most recent prior games more
    heavily than a flat rolling average does.
    """
    alias = alias or f"{value_col}_ewm_before"
    d = df.sort(order_by)
    expr = (
        pl.col(value_col)
        .cast(pl.Float64)
        .shift(1)
        .ewm_mean(alpha=alpha, min_samples=1, ignore_nulls=True)
        .over(group_by)
    )
    return d.with_columns(expr.alias(alias))
