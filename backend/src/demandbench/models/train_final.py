"""Train the production LightGBM models on the most recent data and save the bundle.

Uses the same configuration as the backtest (365-day training window, Tweedie power
1.5, same hyperparameters), trained on everything through the last observed day. The
saved bundle is what the API loads; nothing is retrained on request.
"""

import argparse
import time
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import duckdb
import lightgbm as lgb
import polars as pl

from demandbench.backtest.runner import BacktestResult
from demandbench.backtest.segments import volume_tiers
from demandbench.backtest.splitter import last_date, scan_features
from demandbench.features.build_features import FORECAST_HISTORY_DAYS, HORIZON
from demandbench.models.bundle import BACKTEST_FILE, DATA_FILES, ModelBundle
from demandbench.models.lightgbm_model import (
    CATEGORICAL,
    FEATURES,
    MONOTONE,
    NAME,
    QUANTILES,
    LightGBMConfig,
    gain_importance,
    quantile_scale,
    train_boosters,
    training_data,
)
from demandbench.paths import ARTIFACTS_DIR, BACKTEST_DIR, DUCKDB_PATH, FORECAST_FEATURES_PARQUET

SERIES_META = ["item_id", "store_id", "dept_id", "cat_id", "state_id"]
# Longest lookback the history endpoint allows, plus the 28 prior days its anomaly check
# needs for the first returned day.
MAX_HISTORY_DAYS = 730
ANOMALY_WINDOW_DAYS = 28


def series_metadata(features: pl.LazyFrame) -> pl.DataFrame:
    """Per-series metadata for the API's picker: ids, total and recent sales, the date
    the item went on sale, and its volume tier as of the end of training."""
    end = last_date(features)
    stats = (
        features.group_by(SERIES_META)
        .agg(
            pl.col("sales").cast(pl.Int64).sum().alias("total_sales"),
            pl.col("sales")
            .filter(pl.col("date") > end - timedelta(days=HORIZON))
            .cast(pl.Int64)
            .sum()
            .alias("sales_last_28d"),
            pl.col("date").filter(pl.col("sell_price").is_not_null()).min().alias("on_sale_since"),
        )
        .collect()
    )
    return stats.join(volume_tiers(features, end), on=["item_id", "store_id"]).sort(
        "store_id", "item_id"
    )


def forecast_rows(train_end: date) -> pl.DataFrame:
    rows = pl.read_parquet(FORECAST_FEATURES_PARQUET).select(
        "item_id", "store_id", "date", *[c for c in FEATURES if c not in ("item_id", "store_id")]
    )
    first, n_dates = rows.select(
        pl.col("date").min().alias("first"), pl.col("date").n_unique().alias("n_dates")
    ).row(0)
    if first != train_end + timedelta(days=1) or n_dates != HORIZON:
        raise ValueError(
            f"{FORECAST_FEATURES_PARQUET.name} starts {first} with {n_dates} dates; expected "
            f"{HORIZON} dates starting the day after training ends ({train_end}). "
            "Rebuild features first."
        )
    return rows.sort("store_id", "item_id", "date")


def daily_recent_rows(train_end: date) -> pl.DataFrame:
    """features_daily rows for the last FORECAST_HISTORY_DAYS observed days plus the
    forecast days (features_daily_future): the input the feature SQL needs to recompute
    a series' forecast-day features under a what-if scenario."""
    start = train_end - timedelta(days=FORECAST_HISTORY_DAYS)
    with duckdb.connect(str(DUCKDB_PATH), read_only=True) as con:
        rows: pl.DataFrame = con.sql(
            f"""
            SELECT * FROM features_daily WHERE date > DATE '{start}'
            UNION ALL
            SELECT * FROM features_daily_future
            ORDER BY store_id, item_id, date
            """
        ).pl()
    return rows


def sales_history_rows(features: pl.LazyFrame, train_end: date) -> pl.DataFrame:
    start = train_end - timedelta(days=MAX_HISTORY_DAYS + ANOMALY_WINDOW_DAYS)
    return (
        features.filter(pl.col("date") > start)
        .select("item_id", "store_id", "date", "sales")
        .sort("store_id", "item_id", "date")
        .collect()
    )


def backtest_rows() -> pl.DataFrame | None:
    """Per-fold, per-series results of the saved LightGBM backtest, or None (with a
    warning) if it has not been run."""
    directory = BACKTEST_DIR / NAME
    if not (directory / "series.parquet").is_file():
        print(f"warning: no backtest results in {directory}; the bundle will have none")
        return None
    result = BacktestResult.load(directory)
    return (
        result.series.join(result.folds.select("fold", "test_start", "test_end"), on="fold")
        .select(
            "item_id",
            "store_id",
            "fold",
            "test_start",
            "test_end",
            pl.col("total_sales").alias("actual_units"),
            pl.col("total_prediction").alias("forecast_units"),
            "abs_error",
        )
        .sort("store_id", "item_id", "fold")
    )


def refresh_data_files() -> None:
    """Rewrite the bundle's per-request data files without retraining the boosters."""
    bundle = ModelBundle.load(ARTIFACTS_DIR, require_data_files=False)
    features = scan_features()
    train_end = last_date(features)
    if train_end != bundle.trained_through:
        raise ValueError(
            f"features end {train_end} but the bundle was trained through "
            f"{bundle.trained_through}; retrain instead"
        )
    replace(
        bundle,
        daily_recent=daily_recent_rows(train_end),
        sales_history=sales_history_rows(features, train_end),
        backtest=backtest_rows(),
    ).save_data_files(ARTIFACTS_DIR)
    print(f"refreshed {', '.join([*DATA_FILES, BACKTEST_FILE])} in {ARTIFACTS_DIR}")


def train() -> None:
    config = LightGBMConfig()
    features = scan_features()
    train_end = last_date(features)
    train_start = train_end - timedelta(days=config.train_days - 1)
    print(f"training on {train_start} -> {train_end} (all series)", flush=True)

    # Prepared before training so a data problem fails fast, not after a long fit.
    series = series_metadata(features)
    forecast_features = forecast_rows(train_end)
    daily_recent = daily_recent_rows(train_end)
    sales_history = sales_history_rows(features, train_end)

    start = time.perf_counter()
    dataset, categories = training_data(features, config)
    n_rows = dataset.num_data()
    boosters = train_boosters(dataset, config)
    del dataset
    train_seconds = time.perf_counter() - start
    print(
        f"trained {len(boosters)} boosters on {n_rows:,} rows in {train_seconds:.1f}s", flush=True
    )

    bundle = ModelBundle(
        boosters=boosters,
        metadata={
            "model": NAME,
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "lightgbm_version": lgb.__version__,
            "train_start": train_start.isoformat(),
            "train_end": train_end.isoformat(),
            "train_rows": n_rows,
            "train_seconds": round(train_seconds, 1),
            "horizon_days": HORIZON,
            "features": FEATURES,
            "categorical_features": CATEGORICAL,
            "categories": categories,
            "point_model": "tweedie",
            "tweedie_variance_power": config.tweedie_variance_power,
            "monotone_constraints": MONOTONE if config.monotone else {},
            "monotone_constraints_method": config.monotone_method if config.monotone else None,
            "quantile_scale": quantile_scale(config),
            "quantiles": list(QUANTILES),
            "num_boost_round": config.num_boost_round,
            "params": config.params,
        },
        importance=gain_importance(boosters),
        series=series,
        forecast_features=forecast_features,
        daily_recent=daily_recent,
        sales_history=sales_history,
        backtest=backtest_rows(),
    )
    bundle.save(ARTIFACTS_DIR)

    reloaded = ModelBundle.load(ARTIFACTS_DIR)
    print(f"saved and reloaded bundle at {ARTIFACTS_DIR}")
    n_series, n_rows = reloaded.series.height, reloaded.forecast_features.height
    print(f"  series: {n_series:,}, forecast rows: {n_rows:,}")
    top = (
        reloaded.importance.filter(pl.col("model") == "tweedie")
        .with_columns((pl.col("gain") / pl.col("gain").sum()).alias("share"))
        .sort("gain", descending=True)
        .head(5)
    )
    print("  top Tweedie features by gain share:")
    for feature, share in top.select("feature", "share").iter_rows():
        print(f"    {feature:<26} {share:.1%}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-only",
        action="store_true",
        help="rewrite the per-request data files of an existing bundle without retraining",
    )
    args = parser.parse_args()
    refresh_data_files() if args.data_only else train()


if __name__ == "__main__":
    main()
