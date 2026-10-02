"""riftquant CLI: typer app wiring the ingest connectors to the data lake."""

from __future__ import annotations

from datetime import date

import numpy as np
import polars as pl
import typer

from riftquant import config
from riftquant.features import pregame as pregame_features
from riftquant.frames import normalize
from riftquant.ingest import leaguepedia, livestats, lolesports
from riftquant.models import pregame as pregame_models
from riftquant.odds import discovery, recorder
from riftquant.ratings import openskill_ratings
from riftquant.store import lake, views

app = typer.Typer(add_completion=False, help="rift-quant data foundation CLI (M1 + M2).")


@app.command("index-games")
def index_games(
    league: str = typer.Option(..., "--league", help="League slug: lck, lpl, lec, lcs."),
    since: int = typer.Option(..., "--since", help="Keep tournaments starting on/after this year."),
) -> None:
    """Build/refresh the game index parquet for a league from lolesports."""
    league = league.lower()
    rows = lolesports.build_game_index(league, since=since)
    if not rows:
        typer.echo(f"No games found for league={league} since={since}.")
        return
    df = pl.DataFrame([r.model_dump() for r in rows])
    path = lake.processed_path("game_index", f"{league}.parquet")
    merged = lake.upsert_parquet(df, path, key_cols=["game_id"])
    typer.echo(f"Indexed {len(rows)} game row(s) this run -> {merged.height} total in {path}")


@app.command("archive-frames")
def archive_frames(
    league: str = typer.Option(..., "--league", help="League slug: lck, lpl, lec, lcs."),
    since: int = typer.Option(..., "--since", help="Only archive games from this year onward."),
    limit: int = typer.Option(..., "--limit", help="Max new games to archive this run."),
) -> None:
    """Archive livestats frames for indexed games not yet archived.

    Idempotent + resumable: already-complete games are skipped; a game
    interrupted mid-archive on a prior run resumes instead of restarting.
    Only rows with has_vod=True are considered (see lolesports.py docstring
    on unplayed placeholder game slots).
    """
    league = league.lower()
    index_path = lake.processed_path("game_index", f"{league}.parquet")
    if not index_path.exists():
        typer.echo(f"No game index at {index_path}. Run index-games first.")
        raise typer.Exit(code=1)

    df = pl.read_parquet(index_path)
    df = df.filter((pl.col("start_time").dt.year() >= since) & pl.col("has_vod"))
    df = df.sort(["start_time", "game_number"])
    if df.height == 0:
        typer.echo(f"No archivable (has_vod) games for league={league} since={since}.")
        return

    archived = 0
    for row in df.iter_rows(named=True):
        if archived >= limit:
            break
        result = livestats.archive_game(row["game_id"])
        if result.skipped:
            status = "skip(done)"
        elif result.finished:
            status = "finished"
        elif result.stale_end:
            status = "ended(no-finish-flag)"
        else:
            status = "partial"
        typer.echo(
            f"{row['game_id']} [{row['league']} {row['tournament']} g{row['game_number']}] "
            f"{row['team1_code']} vs {row['team2_code']}: {status} "
            f"window_frames={result.window_frames} details_frames={result.details_frames}"
        )
        if not result.skipped:
            archived += 1
    typer.echo(f"Archived {archived} new game(s) this run (limit={limit}).")


@app.command("normalize-frames")
def normalize_frames_cmd(
    limit: int | None = typer.Option(
        None, "--limit", help="Max pending games to normalize this run (default: all pending)."
    ),
) -> None:
    """Normalize archived livestats games to tidy 10s parquet + objective
    events (see riftquant/frames/normalize.py, docs/specs/
    M4a-frames-normalizer-brief.md). Idempotent: a game already normalized
    (frames parquet exists) is skipped even if its raw archive keeps
    growing; rerun any time to pick up newly archived games."""
    game_ids = normalize.games_pending_normalization(limit=limit)
    if not game_ids:
        typer.echo("No archived games pending normalization.")
        return

    done = 0
    for game_id in game_ids:
        result = normalize.normalize_game(game_id)
        typer.echo(
            f"{game_id}: window_frames={result.window_frames} "
            f"details_frames={result.details_frames} tidy_rows={result.tidy_rows} "
            f"events={result.event_count} elapsed={result.elapsed_s:.2f}s"
        )
        done += 1
    typer.echo(f"Normalized {done} new game(s) this run.")


@app.command("frames-status")
def frames_status_cmd() -> None:
    """Show archived (raw /window on disk) vs normalized (tidy frames
    parquet on disk) game counts, and list any games still pending."""
    archived = normalize.list_archived_game_ids()
    normalized = normalize.list_normalized_game_ids()
    pending = sorted(set(archived) - set(normalized))
    typer.echo(
        f"archived: {len(archived)} | normalized: {len(normalized)} | pending: {len(pending)}"
    )
    for game_id in pending[:20]:
        typer.echo(f"  pending: {game_id}")
    if len(pending) > 20:
        typer.echo(f"  ... and {len(pending) - 20} more")


@app.command("lp-probe")
def lp_probe() -> None:
    """Smoke-test the Leaguepedia connector: print up to 3 recent LCK 2026 rows."""
    rows = leaguepedia.scoreboard_games("LCK/2026%", max_rows=3)
    if not rows:
        typer.echo("No rows returned (unexpected -- check connectivity/where clause).")
        raise typer.Exit(code=1)
    for row in rows:
        typer.echo(row.model_dump())
    typer.echo(f"lp-probe OK: {len(rows)} row(s).")


@app.command("lp-ingest")
def lp_ingest(
    league: str = typer.Option(
        ..., "--league", help="League slug: lck, lpl, lec, lcs, lta_n, worlds, msi, first_stand."
    ),
    season: int = typer.Option(..., "--season", help="Season year, e.g. 2026."),
    refresh: bool = typer.Option(
        False, "--refresh", help="Re-fetch over the network even if this slice is already on disk."
    ),
) -> None:
    """Bulk-ingest one league/season slice of Leaguepedia (Tournaments,
    ScoreboardGames, ScoreboardPlayers, PicksAndBansS7, TournamentRosters,
    Teams, Players) into the parquet lake under data/processed/leaguepedia/.
    Resumable: rerun any time; already-ingested slices are served from disk
    unless --refresh is passed. See docs/specs/M1c-leaguepedia-entities-brief.md."""
    try:
        counts = leaguepedia.ingest_league_season(league, season, refresh=refresh)
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    typer.echo(f"lp-ingest {league} {season} (refresh={refresh}):")
    for table, count in counts.items():
        typer.echo(f"  {table}: {count} row(s)")


@app.command("build-views")
def build_views_cmd() -> None:
    """Resolve player/team entities, rebuild the patches dimension, and
    (re)create every DuckDB view over the parquet lake at
    data/riftquant.duckdb (v_games, v_game_players, v_draft_actions,
    v_player_champ_history). Safe to rerun after any lp-ingest."""
    result = views.build_views()
    typer.echo(f"patches: {result.patches_rows} row(s)")
    typer.echo(f"team aliases: {result.team_aliases} | player aliases: {result.player_aliases}")
    typer.echo(
        f"unresolved entities: {result.unresolved_entities} | entity dupes: {result.entity_dupes}"
    )
    typer.echo(f"views created: {', '.join(result.views_created) or '(none)'}")
    for warning in result.warnings:
        typer.echo(f"  warning: {warning}")


@app.command("validate-m1")
def validate_m1_cmd() -> None:
    """Print the M1 exit-criteria metrics: LCK/LEC coverage (full 5v5 +
    draft order + patch), entity dupes, and a cross-check join rate against
    the lolesports game index (team-name + start-time match, LPL expected
    low -- see docs/specs/M1c-leaguepedia-entities-brief.md)."""
    try:
        # Always rebuild views first: validating against stale derived state
        # (old alias tables / views) silently reports garbage instead of
        # failing -- observed live 2026-08-21 (0% coverage from stale state,
        # 100% after rebuild). build_views is idempotent and takes seconds.
        views.build_views()
        result = views.run_validate_m1()
    except FileNotFoundError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc

    cov = result.coverage
    typer.echo(
        f"LCK/LEC coverage: {cov['full_coverage']}/{cov['total_games']} games "
        f"({cov['coverage_pct']:.1f}%) have full 5v5 + draft order + parsed patch"
    )
    typer.echo(
        f"  full_5v5={cov['full_5v5']} has_draft_order={cov['has_draft_order']} "
        f"has_patch={cov['has_patch']} date_range={cov['date_min']}..{cov['date_max']}"
    )
    typer.echo(
        f"entity dupes: team={result.entity_dupes.get('team', 0)} "
        f"player={result.entity_dupes.get('player', 0)}"
    )
    typer.echo("cross-check vs lolesports game index (team-name + time match, by league):")
    for row in result.cross_check:
        typer.echo(
            f"  {row['league']}: leaguepedia={row['leaguepedia_games']} "
            f"game_index={row['game_index_games']} joined={row['joined']} "
            f"({row['join_rate_pct']:.1f}%)"
        )


@app.command("discover-odds")
def discover_odds() -> None:
    """One-shot listing of active/upcoming LoL match-winner markets per
    enabled venue (see config.ODDS_VENUES_ENABLED -- kalshi is OFF by
    default per docs/QUESTIONS.md Q27 and is skipped here, not queried)."""
    results = discovery.discover_all()
    for venue, on in config.ODDS_VENUES_ENABLED.items():
        if not on:
            typer.echo(f"{venue}: capture disabled (compliance gate); not queried.")
    if not results:
        typer.echo("No venues enabled.")
        raise typer.Exit(code=1)
    for venue, markets in results.items():
        typer.echo(f"{venue}: {len(markets)} match-winner market(s) found")
        for m in markets:
            start = m.start_time.isoformat() if m.start_time else "?"
            typer.echo(f"  {m.market_id} | {m.team1} vs {m.team2} | start={start}")


@app.command("record-odds")
def record_odds(
    interval: int = typer.Option(
        config.ODDS_RECORD_INTERVAL_SECS, "--interval", help="Seconds between poll ticks."
    ),
    limit: int = typer.Option(
        config.ODDS_DEFAULT_MARKET_LIMIT,
        "--limit",
        help="Max soonest-starting open markets to track, per venue.",
    ),
    hours_ahead: float = typer.Option(
        config.ODDS_DEFAULT_HOURS_AHEAD,
        "--hours-ahead",
        help="Only track markets starting within this many hours.",
    ),
    duration: float | None = typer.Option(
        None, "--duration", help="Stop after this many seconds (omit to run until Ctrl+C)."
    ),
) -> None:
    """Long-running odds capture daemon: top-of-book+mid every --interval,
    a full book snapshot every 5 min, trades since the last poll, and a
    resolution observation once a tracked market settles. Ctrl+C for a
    clean shutdown (flushes and closes every open capture file)."""
    active = [v for v, on in config.ODDS_VENUES_ENABLED.items() if on]
    typer.echo(
        f"record-odds starting: interval={interval}s limit={limit} "
        f"hours_ahead={hours_ahead} venues={active}"
    )
    total = recorder.run(
        interval=interval,
        limit=limit,
        hours_ahead=hours_ahead,
        duration_secs=duration,
        echo=typer.echo,
    )
    typer.echo(f"record-odds stopped. {total} observation(s) written this run.")


@app.command("odds-status")
def odds_status() -> None:
    """Show tracked markets per enabled venue and each one's last capture
    timestamp (today's UTC capture file only)."""
    saw_any_venue = False
    for venue, on in config.ODDS_VENUES_ENABLED.items():
        if not on:
            typer.echo(f"{venue}: capture disabled (compliance gate)")
            continue
        saw_any_venue = True
        markets = discovery.load_tracked(venue)
        typer.echo(f"{venue}: {len(markets)} tracked market(s)")
        for m in markets:
            last = discovery.last_capture_ts(venue, m.market_id)
            typer.echo(
                f"  {m.market_id} | {m.team1} vs {m.team2} | "
                f"last_capture={last.isoformat() if last else 'never'}"
            )
    if not saw_any_venue:
        typer.echo("No venues enabled.")


@app.command("build-ratings")
def build_ratings_cmd(
    ffa: bool = typer.Option(
        config.RATINGS_FFA_DEFAULT,
        "--ffa/--no-ffa",
        help="Use PandaSkill's free-for-all rating mode instead of team-result mode (v0 default).",
    ),
) -> None:
    """Replay every game with a full 5v5 roster (chronological order) into
    per-player OpenSkill ratings (mu_ctx + region mu_meta), writing
    data/processed/ratings/player_ratings.parquet. Requires build-views to
    have been run first. See docs/research/08-pandaskill-method.md and
    docs/specs/M2-pregame-model-brief.md."""
    result = openskill_ratings.build_ratings(ffa=ffa)
    typer.echo(
        f"games processed={result.games_processed} rated={result.games_rated} "
        f"international={result.international_games} new_players={result.new_players_initialized} "
        f"(ffa={ffa})"
    )
    typer.echo(f"wrote {result.player_ratings.height} row(s) -> {config.PLAYER_RATINGS_PARQUET}")

    top = (
        result.player_ratings.sort("as_of")
        .group_by("player_id")
        .last()
        .sort("mu_ctx", descending=True)
        .head(5)
    )
    typer.echo("top-5 mu_ctx (spot-check -- known top-team players should rank here):")
    for row in top.iter_rows(named=True):
        safe_id = row["player_id"].encode("ascii", "replace").decode("ascii")
        typer.echo(
            f"  {safe_id}: mu_ctx={row['mu_ctx']:.2f} sigma={row['sigma']:.2f} "
            f"games={row['games_played']}"
        )


@app.command("build-features")
def build_features_cmd() -> None:
    """Build the pregame (post-draft) feature table -- one row per v_games
    row, columns grouped by prefix (side_/team_/pc_/draft_/meta_) -- and
    write data/processed/features/pregame.parquet. Requires build-views and
    build-ratings to have been run first. See
    docs/specs/M2-pregame-model-brief.md."""
    df = pregame_features.build_features()
    typer.echo(
        f"wrote {df.height} row(s), {len(df.columns)} column(s) -> "
        f"{config.PREGAME_FEATURES_PARQUET}"
    )
    report = pregame_features.null_rate_report(df)
    typer.echo("null rate by feature group:")
    for row in report.iter_rows(named=True):
        typer.echo(
            f"  {row['feature_group']:<8} n_columns={row['n_columns']:>3} "
            f"null_rate={row['null_rate_pct']:.1f}%"
        )
    n_labeled = df.filter(pl.col("blue_win").is_not_null()).height
    typer.echo(f"labeled rows (blue_win resolved): {n_labeled}/{df.height}")


@app.command("train-pregame")
def train_pregame_cmd(
    full_data: bool = typer.Option(
        False, "--full-data", help="Use the full 2020+ split preset instead of the subset preset."
    ),
) -> None:
    """Fit LightGBM (monotonic constraint on team rating diff) on the train
    split, calibrate (isotonic) on the validation split, and persist the
    model to data/processed/models/pregame/ for predict-pregame. Requires
    build-features to have been run first."""
    if not config.PREGAME_FEATURES_PARQUET.exists():
        typer.echo(f"No features at {config.PREGAME_FEATURES_PARQUET}. Run build-features first.")
        raise typer.Exit(code=1)
    df = pl.read_parquet(config.PREGAME_FEATURES_PARQUET)
    preset = config.PREGAME_SPLIT_FULL if full_data else config.PREGAME_SPLIT_ACTIVE
    feature_cols = pregame_models.select_model_feature_columns(df)
    scorecard = pregame_models.train_and_save(df, feature_cols, preset, config.PREGAME_MODEL_DIR)
    typer.echo(f"trained on preset={preset.name} split_sizes={scorecard.split_sizes}")
    typer.echo(f"model written -> {config.PREGAME_MODEL_DIR}")
    if scorecard.test_metrics.get("lgbm_full"):
        m = scorecard.test_metrics["lgbm_full"]
        typer.echo(
            f"test (uncalibrated) brier={m['brier']:.4f} accuracy={m['accuracy']:.4f} "
            f"n={int(m['n'])}"
        )


@app.command("eval-pregame")
def eval_pregame_cmd(
    full_data: bool = typer.Option(
        False, "--full-data", help="Use the full 2020+ split preset instead of the subset preset."
    ),
) -> None:
    """Full scorecard: metrics per split + per league + per season, the
    mandatory baseline table (global/per-league side rate, team-Elo-only
    logistic), calibration curve pre/post isotonic, feature importances,
    and the >65%%-test-accuracy leakage tripwire. Writes
    docs/eval/pregame_v0_<date>.md + a per-game predictions parquet.
    Requires build-features to have been run first."""
    if not config.PREGAME_FEATURES_PARQUET.exists():
        typer.echo(f"No features at {config.PREGAME_FEATURES_PARQUET}. Run build-features first.")
        raise typer.Exit(code=1)
    df = pl.read_parquet(config.PREGAME_FEATURES_PARQUET)
    preset = config.PREGAME_SPLIT_FULL if full_data else config.PREGAME_SPLIT_ACTIVE
    feature_cols = pregame_models.select_model_feature_columns(df)

    scorecard = pregame_models.run_scorecard(df, feature_cols, preset)
    scorecard.rolling_origin_folds = pregame_models.rolling_origin_quarterly_folds(df, feature_cols)
    null_rates = pregame_features.null_rate_report(df)

    config.EVAL_DIR.mkdir(parents=True, exist_ok=True)
    out_path = config.EVAL_DIR / f"pregame_v0_{date.today().isoformat()}.md"
    out_path.write_text(pregame_models.render_markdown(scorecard, null_rates), encoding="utf-8")

    config.PREGAME_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if scorecard.predictions is not None:
        scorecard.predictions.write_parquet(config.PREGAME_PREDICTIONS_PARQUET)

    typer.echo(f"scorecard written -> {out_path}")
    typer.echo(f"split sizes: {scorecard.split_sizes}")
    if scorecard.leakage_investigation_triggered:
        typer.echo(f"LEAKAGE TRIPWIRE FIRED: {scorecard.leakage_message}")
    else:
        typer.echo(f"leakage tripwire: OK ({scorecard.leakage_message})")
    if scorecard.beats_elo_on_test_brier is not None:
        typer.echo(f"beats elo-only baseline on test brier: {scorecard.beats_elo_on_test_brier}")
    model_names = (
        "global_rate",
        "per_league_rate",
        "elo_logistic",
        "lr_full",
        "lgbm_full",
        "lgbm_full_calibrated",
    )
    for model_name in model_names:
        m = scorecard.test_metrics.get(model_name)
        if m:
            typer.echo(
                f"  test/{model_name}: brier={m['brier']:.4f} log_loss={m['log_loss']:.4f} "
                f"ece={m['ece']:.4f} accuracy={m['accuracy']:.4f} n={int(m['n'])}"
            )


@app.command("predict-pregame")
def predict_pregame_cmd(
    game_id: str = typer.Option(..., "--game-id", help="A game_id present in the feature table."),
) -> None:
    """Print P(blue win) for a historical game plus its top LightGBM
    contribution features (pred_contrib, LightGBM's built-in per-feature
    attribution -- no extra SHAP dependency needed). Requires
    build-features and train-pregame to have been run first."""
    if not config.PREGAME_FEATURES_PARQUET.exists():
        typer.echo(f"No features at {config.PREGAME_FEATURES_PARQUET}. Run build-features first.")
        raise typer.Exit(code=1)
    model_path = config.PREGAME_MODEL_DIR / "lgbm_model.txt"
    if not model_path.exists():
        typer.echo(f"No trained model at {config.PREGAME_MODEL_DIR}. Run train-pregame first.")
        raise typer.Exit(code=1)

    df = pl.read_parquet(config.PREGAME_FEATURES_PARQUET)
    row_df = df.filter(pl.col("game_id") == game_id)
    if row_df.height == 0:
        typer.echo(f"game_id {game_id!r} not found in {config.PREGAME_FEATURES_PARQUET}.")
        raise typer.Exit(code=1)

    booster, feature_cols, calibrator = pregame_models.load_model(config.PREGAME_MODEL_DIR)
    x, _cols = pregame_models.prepare_model_matrix(row_df, feature_cols)
    for col in feature_cols:
        if col not in x.columns:
            x = x.with_columns(pl.lit(None).alias(col))
    x = x.select(feature_cols)

    raw_pred = float(booster.predict(x.to_numpy())[0])
    if calibrator is not None:
        # See models/pregame.run_scorecard's isotonic-calibration comment:
        # a val split this small (31 games on the subset preset) can map a
        # whole tail bin to exactly 0.0/1.0 -- clipped for numerical safety.
        calibrated = float(np.clip(calibrator.predict([raw_pred])[0], 0.02, 0.98))
    else:
        calibrated = raw_pred

    contribs = booster.predict(x.to_numpy(), pred_contrib=True)[0]
    pairs = list(zip(feature_cols, contribs[:-1], strict=False))  # last entry is the base value
    pairs.sort(key=lambda p: abs(p[1]), reverse=True)

    row = row_df.row(0, named=True)
    typer.echo(f"game_id={game_id} league={row.get('league')} date={row.get('date')}")
    typer.echo(f"P(blue win): raw={raw_pred:.4f} calibrated={calibrated:.4f}")
    if row.get("blue_win") is not None:
        typer.echo(f"actual blue_win={row['blue_win']}")
    typer.echo("top feature contributions (LightGBM pred_contrib, log-odds space):")
    for name, contrib in pairs[:8]:
        typer.echo(f"  {name}: {contrib:+.4f}")


if __name__ == "__main__":
    app()
