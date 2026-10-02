"""riftquant.features.pregame -- the M2 pregame (post-draft) feature
builder (docs/specs/M2-pregame-model-brief.md, "features/" layer). One row
per v_games row, columns grouped by prefix:

  side_  : blue/red context -- league, era flags, series game number.
  team_  : per-side aggregates of player rating (mu_ctx, mu_meta), roster
           continuity, recent form -- blue/red + a diff column each.
  pc_    : player-champion proficiency PER SLOT (role x side, 10 slots) --
           empirical-Bayes shrunk win rate, games-on-champ, days since last
           played, fearless-series champ-reuse sanity flag.
  draft_ : pick-order context -- first/second pick meta strength, damage
           mix, series champs-burned count.
  meta_  : champion pro presence + win rate on this patch and the prior
           patch (computed point-in-time from pro games only), composition
           damage mix / scaling proxy from the static champ_tags table.

Every point-in-time lookup goes through riftquant.features.asof -- see that
module's docstring for why (the brief's POINT-IN-TIME rail + leakage
tripwire). Nothing in here does an ad hoc "WHERE date < X" join; if a new
feature needs "as of this game", it calls one of asof.py's three helpers.

Vectorized throughout (polars group-by/window/join_asof) -- no per-row
Python loop over games, per the brief's runtime constraint (full feature
build over ~5-8k games must stay under ~5 minutes).
"""

from __future__ import annotations

import csv
from pathlib import Path

import duckdb
import polars as pl

from riftquant import config
from riftquant.features import asof
from riftquant.store.lake import duckdb_to_polars

_RECENT_FORM_WINDOW = 10
# ~10-game half-life: alpha solved from 0.5 = (1-alpha)^10.
_RECENT_FORM_EWM_ALPHA = 1.0 - 0.5 ** (1.0 / _RECENT_FORM_WINDOW)


# --- loading -----------------------------------------------------------


def load_games(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    return duckdb_to_polars(
        con,
        """
        SELECT game_id, match_id, league, date, patch_client, patch_ordinal,
               blue_team_id, red_team_id, winner_team_id,
               fearless_era, first_selection_era, game_num_in_series, best_of_observed
        FROM v_games
        """,
    )


def load_game_players(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    return duckdb_to_polars(
        con,
        """
        SELECT game_id, player_id, team_id, side, role, champion, won
        FROM v_game_players
        WHERE player_id IS NOT NULL AND side IN ('1', '2')
        """,
    )


def load_draft_actions(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    return duckdb_to_polars(
        con,
        """
        SELECT game_id, order_index, action, champion, team_id, side
        FROM v_draft_actions
        """,
    )


def load_player_ratings(path: Path | None = None) -> pl.DataFrame:
    path = path or config.PLAYER_RATINGS_PARQUET
    if not path.exists():
        return pl.DataFrame(
            schema={
                "player_id": pl.Utf8,
                "as_of": pl.Datetime,
                "mu_ctx": pl.Float64,
                "mu_meta_region": pl.Float64,
                "sigma": pl.Float64,
                "games_played": pl.Int64,
            }
        )
    return pl.read_parquet(path)


def load_champ_tags(path: Path | None = None) -> pl.DataFrame:
    path = path or config.CHAMP_TAGS_PATH
    rows: list[dict] = []
    with path.open("r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            rows.append(
                {
                    "champion": row["champion"],
                    "damage_mix": row["damage_mix"],
                    "attack": float(row["attack"]),
                    "magic": float(row["magic"]),
                    "defense": float(row["defense"]),
                    "difficulty": float(row["difficulty"]),
                    "scaling_proxy": float(row["scaling_proxy"]),
                }
            )
    return pl.DataFrame(rows)


# --- shrinkage -----------------------------------------------------------


def eb_shrunk_rate(
    wins: pl.Expr, games: pl.Expr, prior: pl.Expr, k: float = config.PC_SHRINKAGE_K
) -> pl.Expr:
    """Empirical-Bayes shrunk win rate (M2 brief, pc_ group): blends the
    observed rate `wins/games` toward `prior` with strength `k` "games" --
    `(wins + k*prior) / (games + k)`. At games=0 this collapses exactly to
    `prior` (a player/champion pair never seen before gets the prior, not
    an undefined 0/0); as `games` grows the observed rate dominates.
    """
    return (wins + k * prior) / (games + k)


# --- side_ ----------------------------------------------------------------


def build_side_features(games: pl.DataFrame) -> pl.DataFrame:
    """Static, known-at-draft-time context -- no as-of join needed (these
    facts belong to the game row itself, not to any player/team history)."""
    return games.select(
        "game_id",
        pl.col("league").alias("side_league"),
        pl.col("fearless_era").alias("side_fearless_era"),
        pl.col("first_selection_era").alias("side_first_selection_era"),
        pl.col("game_num_in_series").alias("side_game_num_in_series"),
        pl.col("best_of_observed").alias("side_best_of_observed"),
    )


# --- team_ ------------------------------------------------------------


def build_team_features(
    games: pl.DataFrame,
    game_players: pl.DataFrame,
    player_ratings: pl.DataFrame,
) -> pl.DataFrame:
    roster = game_players.join(games.select("game_id", "date"), on="game_id", how="inner")

    # 1) as-of join each roster row's rating snapshot (strictly prior game).
    rated = asof.asof_join_latest(
        roster,
        player_ratings,
        by=["player_id"],
        target_ts="date",
        history_ts="as_of",
    )

    # 2) recent form: needs the player's OWN chronological win history
    # (v_game_players.won), independent of the ratings table.
    player_history = game_players.join(
        games.select("game_id", "date"), on="game_id", how="inner"
    ).select("player_id", "game_id", "date", pl.col("won").cast(pl.Int64))
    player_history = asof.strictly_prior_rolling_mean(
        player_history,
        group_by=["player_id"],
        order_by="date",
        value_col="won",
        window_size=_RECENT_FORM_WINDOW,
        alias="recent_form10",
    )
    player_history = asof.strictly_prior_ewm_mean(
        player_history,
        group_by=["player_id"],
        order_by="date",
        value_col="won",
        alpha=_RECENT_FORM_EWM_ALPHA,
        alias="recent_form_ewm",
    )
    rated = rated.join(
        player_history.select("game_id", "player_id", "recent_form10", "recent_form_ewm"),
        on=["game_id", "player_id"],
        how="left",
    )

    # 3) roster continuity: how many prior games has THIS exact 5-stack
    # (same team_id, same 5 player_ids) played together, before this game.
    stacks = (
        rated.group_by(["game_id", "team_id", "side", "date"])
        .agg(pl.col("player_id").sort().alias("roster"))
        .with_columns(
            pl.col("roster").list.join("|").alias("roster_key"), pl.lit(1).alias("_present")
        )
    )
    stacks = asof.strictly_prior_stats(
        stacks,
        group_by=["team_id", "roster_key"],
        order_by="date",
        value_col="_present",
        count_alias="roster_continuity",
        sum_alias="_unused_roster_sum",
    ).drop("_unused_roster_sum", "_present")

    per_side = (
        rated.group_by(["game_id", "side"])
        .agg(
            # NOTE: plain `.sum()` on an all-null group (every starter is a
            # brand-new player with zero rating history) silently returns
            # 0.0 in polars, not null -- indistinguishable from "5 known,
            # terrible players" to a downstream model. Guard explicitly so
            # a genuinely-unknown team reads as missing, not as the worst
            # possible team.
            pl.when(pl.col("mu_ctx").count() == 0)
            .then(None)
            .otherwise(pl.col("mu_ctx").sum())
            .alias("mu_ctx_sum"),
            pl.col("mu_ctx").mean().alias("mu_ctx_mean"),
            pl.col("mu_ctx").min().alias("mu_ctx_min"),
            pl.col("mu_meta_region").mean().alias("mu_meta_mean"),
            pl.col("sigma").mean().alias("sigma_mean"),
            pl.col("games_played").mean().alias("games_played_mean"),
            pl.col("recent_form10").mean().alias("recent_form10_mean"),
            pl.col("recent_form_ewm").mean().alias("recent_form_ewm_mean"),
        )
        .join(
            stacks.select("game_id", "side", "roster_continuity"),
            on=["game_id", "side"],
            how="left",
        )
    )

    metrics = [
        "mu_ctx_sum",
        "mu_ctx_mean",
        "mu_ctx_min",
        "mu_meta_mean",
        "sigma_mean",
        "games_played_mean",
        "recent_form10_mean",
        "recent_form_ewm_mean",
        "roster_continuity",
    ]
    wide = _pivot_side_wide(per_side, metrics, prefix="team_")
    return wide


def _pivot_side_wide(per_side: pl.DataFrame, metrics: list[str], prefix: str) -> pl.DataFrame:
    """`per_side` has one row per (game_id, side in {'1','2'}) and the given
    `metrics` columns; pivot to one row per game_id with
    `<prefix><metric>_blue`, `<prefix><metric>_red`, `<prefix><metric>_diff`
    (blue - red) for each metric -- the wide, model-ready shape every
    team_/pc_ builder converges to.
    """
    game_ids = per_side.select("game_id").unique()
    out = game_ids
    side_label = {"1": "blue", "2": "red"}
    for side_code, side_name in side_label.items():
        side_df = per_side.filter(pl.col("side") == side_code).select(
            "game_id", *[pl.col(m).alias(f"{prefix}{m}_{side_name}") for m in metrics]
        )
        out = out.join(side_df, on="game_id", how="left")
    for m in metrics:
        out = out.with_columns(
            (pl.col(f"{prefix}{m}_blue") - pl.col(f"{prefix}{m}_red")).alias(f"{prefix}{m}_diff")
        )
    return out


# --- pc_ (player-champion proficiency, per slot) --------------------------


def build_pc_features(games: pl.DataFrame, game_players: pl.DataFrame) -> pl.DataFrame:
    long = game_players.join(
        games.select("game_id", "date", "match_id", "game_num_in_series"), on="game_id", how="inner"
    )
    long = long.with_columns(pl.col("won").cast(pl.Int64))

    # Overall (all-champion) win rate as-of, used as the EB shrinkage prior.
    overall = asof.strictly_prior_stats(
        long.select("player_id", "game_id", "date", "won"),
        group_by=["player_id"],
        order_by="date",
        value_col="won",
        count_alias="overall_n_before",
        sum_alias="overall_wins_before",
    )
    overall = overall.with_columns(
        (
            pl.col("overall_wins_before")
            / pl.when(pl.col("overall_n_before") > 0).then(pl.col("overall_n_before")).otherwise(1)
        )
        .fill_null(0.5)
        .alias("overall_wr_before")
    )

    # Per (player, champion) history.
    champ_hist = asof.strictly_prior_stats(
        long.select("player_id", "champion", "game_id", "date", "won"),
        group_by=["player_id", "champion"],
        order_by="date",
        value_col="won",
        count_alias="champ_n_before",
        sum_alias="champ_wins_before",
    )
    champ_hist = asof.strictly_prior_last_timestamp(
        champ_hist,
        group_by=["player_id", "champion"],
        order_by="date",
        alias="champ_last_played_before",
    )

    joined = long.join(
        overall.select("game_id", "player_id", "overall_wr_before"),
        on=["game_id", "player_id"],
        how="left",
    ).join(
        champ_hist.select(
            "game_id",
            "player_id",
            "champion",
            "champ_n_before",
            "champ_wins_before",
            "champ_last_played_before",
        ),
        on=["game_id", "player_id", "champion"],
        how="left",
    )

    joined = joined.with_columns(
        eb_shrunk_rate(
            pl.col("champ_wins_before"), pl.col("champ_n_before"), pl.col("overall_wr_before")
        ).alias("pc_shrunk_wr"),
        pl.col("champ_n_before").log1p().alias("pc_games_on_champ_log"),
        (pl.col("date") - pl.col("champ_last_played_before"))
        .dt.total_days()
        .alias("pc_days_since_last"),
    )

    # Fearless-series sanity/context feature: how many EARLIER games in this
    # same series did this exact team already play this exact champion --
    # should be 0 under correctly-enforced fearless rules; a same-series,
    # same-team, earlier-game-number self join (not history-table based, so
    # it needs its own explicit strictly-earlier-in-series condition).
    series_long = long.select("game_id", "match_id", "game_num_in_series", "team_id", "champion")
    reused = (
        series_long.join(series_long, on=["match_id", "team_id", "champion"], suffix="_prior")
        .filter(pl.col("game_num_in_series_prior") < pl.col("game_num_in_series"))
        .group_by("game_id", "team_id", "champion")
        .agg(pl.len().alias("pc_champ_reused_in_series"))
    )
    joined = joined.join(reused, on=["game_id", "team_id", "champion"], how="left").with_columns(
        pl.col("pc_champ_reused_in_series").fill_null(0)
    )

    per_slot = joined.select(
        "game_id",
        "side",
        "role",
        "pc_shrunk_wr",
        "pc_games_on_champ_log",
        "pc_days_since_last",
        "pc_champ_reused_in_series",
    )

    side_label = {"1": "blue", "2": "red"}
    metrics = [
        "pc_shrunk_wr",
        "pc_games_on_champ_log",
        "pc_days_since_last",
        "pc_champ_reused_in_series",
    ]
    out = games.select("game_id").unique()
    for side_code, side_name in side_label.items():
        for role in config.ROLE_SLOTS:
            slot = per_slot.filter((pl.col("side") == side_code) & (pl.col("role") == role)).select(
                "game_id", *[pl.col(m).alias(f"{m}_{side_name}_{role.lower()}") for m in metrics]
            )
            out = out.join(slot, on="game_id", how="left")

    for role in config.ROLE_SLOTS:
        out = out.with_columns(
            (
                pl.col(f"pc_shrunk_wr_blue_{role.lower()}")
                - pl.col(f"pc_shrunk_wr_red_{role.lower()}")
            ).alias(f"pc_shrunk_wr_diff_{role.lower()}")
        )
    return out


# --- meta_ (champion pro presence/WR by patch, damage mix, scaling) -------


def _champion_patch_asof_stats(games: pl.DataFrame, game_players: pl.DataFrame) -> pl.DataFrame:
    """Per (game_id, player_id) row: this champion's point-in-time pro
    presence/win-rate on the CURRENT patch and the PRIOR patch (patch_ordinal
    - 1), computed only from pro games strictly before this game's date.
    """
    long = game_players.join(
        games.select("game_id", "date", "patch_ordinal"), on="game_id", how="inner"
    ).with_columns(pl.col("won").cast(pl.Int64))

    cur_patch = asof.strictly_prior_stats(
        long.select("champion", "patch_ordinal", "game_id", "player_id", "date", "won"),
        group_by=["champion", "patch_ordinal"],
        order_by="date",
        value_col="won",
        count_alias="meta_cur_patch_n",
        sum_alias="meta_cur_patch_wins",
    )

    # Prior-patch reference: a per-(champion, patch_ordinal) snapshot table
    # of cumulative (games, wins) AS OF (i.e. including) each contributing
    # game, tagged with patch_ordinal + 1 so it can be equi-"by"-joined
    # against a target row's OWN patch_ordinal via the central as-of API --
    # this answers "the latest known tally for (champion, patch_ordinal-1)
    # strictly before this game's date", which is point-in-time safe even
    # across leagues that adopt a new patch on slightly different dates.
    running = cur_patch.select(
        "champion",
        "patch_ordinal",
        "date",
        (pl.col("meta_cur_patch_n") + 1).alias("_n_incl"),
        (pl.col("meta_cur_patch_wins") + pl.col("won")).alias("_wins_incl"),
    ).with_columns((pl.col("patch_ordinal") + 1).alias("_next_patch_ordinal"))

    target = long.select("champion", "patch_ordinal", "game_id", "player_id", "date").rename(
        {"patch_ordinal": "_next_patch_ordinal"}
    )
    prior_patch = asof.asof_join_latest(
        target,
        running.select("champion", "_next_patch_ordinal", "date", "_n_incl", "_wins_incl"),
        by=["champion", "_next_patch_ordinal"],
        target_ts="date",
        history_ts="date",
    ).select(
        "game_id",
        "player_id",
        pl.col("_n_incl").fill_null(0).alias("meta_prior_patch_n"),
        pl.col("_wins_incl").fill_null(0.0).alias("meta_prior_patch_wins"),
    )

    out = cur_patch.select("game_id", "player_id", "meta_cur_patch_n", "meta_cur_patch_wins").join(
        prior_patch, on=["game_id", "player_id"], how="left"
    )
    out = out.with_columns(
        (
            pl.col("meta_cur_patch_wins")
            / pl.when(pl.col("meta_cur_patch_n") > 0).then(pl.col("meta_cur_patch_n")).otherwise(1)
        )
        .fill_null(0.5)
        .alias("meta_cur_patch_wr"),
        (
            pl.col("meta_prior_patch_wins")
            / pl.when(pl.col("meta_prior_patch_n") > 0)
            .then(pl.col("meta_prior_patch_n"))
            .otherwise(1)
        )
        .fill_null(0.5)
        .alias("meta_prior_patch_wr"),
    )
    return out.select(
        "game_id",
        "player_id",
        "meta_cur_patch_n",
        "meta_cur_patch_wr",
        "meta_prior_patch_n",
        "meta_prior_patch_wr",
    )


def build_meta_features(
    games: pl.DataFrame, game_players: pl.DataFrame, champ_tags: pl.DataFrame
) -> pl.DataFrame:
    patch_stats = _champion_patch_asof_stats(games, game_players)

    long = game_players.join(games.select("game_id"), on="game_id", how="inner").join(
        champ_tags, on="champion", how="left"
    )
    long = long.join(patch_stats, on=["game_id", "player_id"], how="left")

    per_side = long.group_by(["game_id", "side"]).agg(
        pl.col("meta_cur_patch_n").mean().alias("champ_presence_cur_patch_mean"),
        pl.col("meta_cur_patch_wr").mean().alias("champ_wr_cur_patch_mean"),
        pl.col("meta_prior_patch_n").mean().alias("champ_presence_prior_patch_mean"),
        pl.col("meta_prior_patch_wr").mean().alias("champ_wr_prior_patch_mean"),
        (pl.col("damage_mix") == "AD").sum().alias("ad_count"),
        (pl.col("damage_mix") == "AP").sum().alias("ap_count"),
        pl.col("scaling_proxy").mean().alias("scaling_proxy_mean"),
    )
    metrics = [
        "champ_presence_cur_patch_mean",
        "champ_wr_cur_patch_mean",
        "champ_presence_prior_patch_mean",
        "champ_wr_prior_patch_mean",
        "ad_count",
        "ap_count",
        "scaling_proxy_mean",
    ]
    return _pivot_side_wide(per_side, metrics, prefix="meta_")


# --- draft_ (pick order / series context) ---------------------------------


def build_draft_features(
    games: pl.DataFrame, draft_actions: pl.DataFrame, champ_tags: pl.DataFrame
) -> pl.DataFrame:
    """Pick-order context: each side's first pick (order_index 7 blue / 8
    red) and "counterpick" second pick (order_index 10 blue / 9 red, per
    store/views.py's fixed tournament draft order -- both teams' picks
    after having seen at least one opponent pick), plus a fearless-era
    series champs-burned count. Purely structural/static lookups (no as-of
    join needed: a draft pick is known at draft time by definition, and
    champ_tags is a static reference table)."""
    out = games.select("game_id")
    if draft_actions.height == 0:
        return out

    picks = draft_actions.filter(pl.col("action") == "pick")
    first_pick = {"blue": 7, "red": 8}
    second_pick = {"blue": 10, "red": 9}

    for side_name, order_idx in first_pick.items():
        sel = (
            picks.filter(pl.col("order_index") == order_idx)
            .select("game_id", pl.col("champion").alias(f"draft_pick1_champ_{side_name}"))
            .join(
                champ_tags.select("champion", "damage_mix"),
                left_on=f"draft_pick1_champ_{side_name}",
                right_on="champion",
                how="left",
            )
            .rename({"damage_mix": f"draft_pick1_damage_mix_{side_name}"})
        )
        out = out.join(sel, on="game_id", how="left")

    for side_name, order_idx in second_pick.items():
        sel = picks.filter(pl.col("order_index") == order_idx).select(
            "game_id", pl.col("champion").alias(f"draft_pick2_champ_{side_name}")
        )
        out = out.join(sel, on="game_id", how="left")

    # Champs burned so far this series (fearless context): distinct
    # champions picked by EITHER team in strictly earlier games of the same
    # match_id.
    series_picks = picks.join(
        games.select("game_id", "match_id", "game_num_in_series"), on="game_id", how="inner"
    )
    burned = (
        series_picks.join(series_picks, on="match_id", suffix="_prior")
        .filter(pl.col("game_num_in_series_prior") < pl.col("game_num_in_series"))
        .group_by("game_id")
        .agg(pl.col("champion_prior").n_unique().alias("draft_champs_burned_count"))
    )
    out = out.join(burned, on="game_id", how="left").with_columns(
        pl.col("draft_champs_burned_count").fill_null(0)
    )
    return out


# --- top-level build -------------------------------------------------------


def build_pregame_features(duckdb_path: Path | None = None) -> pl.DataFrame:
    duckdb_path = duckdb_path or (config.DATA_ROOT / "riftquant.duckdb")
    con = duckdb.connect(str(duckdb_path), read_only=True)
    try:
        games = load_games(con)
        game_players = load_game_players(con)
        draft_actions = load_draft_actions(con)
    finally:
        con.close()

    player_ratings = load_player_ratings()
    champ_tags = load_champ_tags()

    side = build_side_features(games)
    team = build_team_features(games, game_players, player_ratings)
    pc = build_pc_features(games, game_players)
    meta = build_meta_features(games, game_players, champ_tags)
    draft = build_draft_features(games, draft_actions, champ_tags)

    label = games.select(
        "game_id",
        "league",
        "date",
        pl.col("patch_client"),
        "blue_team_id",
        "red_team_id",
        "winner_team_id",
        (pl.col("winner_team_id") == pl.col("blue_team_id")).alias("blue_win"),
    )

    out = label
    for part in (side, team, pc, meta, draft):
        out = out.join(part, on="game_id", how="left")
    return out


def build_features(duckdb_path: Path | None = None, out_path: Path | None = None) -> pl.DataFrame:
    out_path = out_path or config.PREGAME_FEATURES_PARQUET
    df = build_pregame_features(duckdb_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(out_path)
    return df


def null_rate_report(df: pl.DataFrame) -> pl.DataFrame:
    """Null rate per feature GROUP (prefix before the first underscore),
    per the M2 brief's "report null rates per feature group" exit criterion.
    """
    id_cols = {
        "game_id",
        "league",
        "date",
        "patch_client",
        "blue_win",
        "blue_team_id",
        "red_team_id",
        "winner_team_id",
    }
    groups: dict[str, list[str]] = {}
    for col in df.columns:
        if "_" not in col or col in id_cols:
            continue
        prefix = col.split("_")[0] + "_"
        groups.setdefault(prefix, []).append(col)

    rows = []
    n = df.height
    for prefix, cols in sorted(groups.items()):
        total_cells = n * len(cols)
        null_cells = sum(df[c].null_count() for c in cols)
        rows.append(
            {
                "feature_group": prefix,
                "n_columns": len(cols),
                "n_rows": n,
                "null_rate_pct": (null_cells / total_cells * 100.0) if total_cells else 0.0,
            }
        )
    return pl.DataFrame(rows)
