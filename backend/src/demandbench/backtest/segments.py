"""Series segments used to break down backtest results.

Volume tiers rank each series by total sales up to the earliest fold's cutoff, within
its cat_id x state_id cell, so no test window ever influences a series' tier. The
Prophet sample is stratified on exactly these tiers.
"""

from datetime import date

import polars as pl

from demandbench.backtest.metrics import SERIES_KEYS

MIN_HISTORY_DAYS = 90
TIERS = ["low", "medium", "high", "new"]


def eligible_series(features: pl.LazyFrame, as_of: date) -> pl.DataFrame:
    """Series on sale for at least MIN_HISTORY_DAYS by as_of, with their total sales up
    to as_of and a volume tercile ranked within their cat_id x state_id cell."""
    history = (
        features.filter(pl.col("date") <= as_of)
        .group_by(*SERIES_KEYS, "cat_id", "state_id")
        .agg(
            pl.col("sales").cast(pl.Int64).sum().alias("total_sales"),
            pl.col("sell_price").is_not_null().sum().alias("days_on_sale"),
        )
        .filter(pl.col("days_on_sale") >= MIN_HISTORY_DAYS)
        .collect()
    )
    rank = pl.col("total_sales").rank("ordinal").over("cat_id", "state_id")
    size = pl.len().over("cat_id", "state_id")
    tercile = ((rank - 1) * 3 // size).cast(pl.Int8)
    return history.with_columns(
        tercile.replace_strict([0, 1, 2], ["low", "medium", "high"]).alias("volume_tercile")
    ).sort(*SERIES_KEYS)


def volume_tiers(features: pl.LazyFrame, as_of: date) -> pl.DataFrame:
    """One row per series: item_id, store_id, volume_tier.

    Series with too little sales history by as_of to rank (launched recently) get the
    tier "new".
    """
    ranked = eligible_series(features, as_of).select(
        *SERIES_KEYS, pl.col("volume_tercile").alias("volume_tier")
    )
    return (
        features.select(SERIES_KEYS)
        .unique()
        .collect()
        .join(ranked, on=SERIES_KEYS, how="left")
        .with_columns(pl.col("volume_tier").fill_null("new"))
        .sort(*SERIES_KEYS)
    )
