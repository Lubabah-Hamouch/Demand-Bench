"""Forecast accuracy metrics, computed per series and then aggregated.

WAPE is the primary metric. M5 is dominated by intermittent demand (many zero-sales
days), and WAPE stays well defined as long as a series sold anything in the window.
MAPE and RMSE are reported alongside for reference only.
"""

import polars as pl

SERIES_KEYS = ["item_id", "store_id"]
ACTUAL = "sales"
PREDICTION = "prediction"


def _error() -> pl.Expr:
    return pl.col(PREDICTION) - pl.col(ACTUAL)


def wape() -> pl.Expr:
    """sum(|error|) / sum(actual); null for a series with zero total sales."""
    total = pl.col(ACTUAL).sum()
    return pl.when(total > 0).then(_error().abs().sum() / total)


def mape() -> pl.Expr:
    """Mean of |error| / actual over days with nonzero sales.

    MAPE is known to be unstable on this data: it is undefined on zero-sales days (which
    are excluded here) and blows up on days with 1-2 units sold, so a handful of
    low-volume days can dominate it. Do not use it to rank models.
    """
    actual = pl.col(ACTUAL)
    return (_error().abs() / actual).filter(actual > 0).mean()


def rmse() -> pl.Expr:
    return _error().pow(2).mean().sqrt()


def series_metrics(scored: pl.DataFrame) -> pl.DataFrame:
    """One row per item_id/store_id with WAPE, MAPE and RMSE over its test days.

    `scored` needs SERIES_KEYS, ACTUAL and PREDICTION columns.
    """
    return scored.group_by(SERIES_KEYS).agg(
        pl.len().alias("n_days"),
        pl.col(ACTUAL).sum().cast(pl.Float64).alias("total_sales"),
        pl.col(PREDICTION).sum().alias("total_prediction"),
        _error().abs().sum().alias("abs_error"),
        wape().alias("wape"),
        mape().alias("mape"),
        rmse().alias("rmse"),
    )


def aggregate(series: pl.DataFrame) -> dict[str, float | int]:
    """Aggregate series-level metrics to one value per metric.

    - wape: volume-weighted across series, i.e. sum of series absolute errors over sum of
      series sales. Series with zero sales still count their errors in the numerator.
    - mape, rmse: unweighted mean across series (series where the metric is undefined,
      e.g. MAPE for a series with no sales, are skipped).
    """
    row = series.select(
        (pl.col("abs_error").sum() / pl.col("total_sales").sum()).alias("wape"),
        pl.col("mape").mean().alias("mape"),
        pl.col("rmse").mean().alias("rmse"),
        pl.len().alias("n_series"),
        (pl.col("total_sales") == 0).sum().alias("n_series_zero_sales"),
    ).row(0, named=True)
    return dict(row)


def pooled_wape(scored: pl.DataFrame, column: str = PREDICTION) -> float:
    """sum(|column - actual|) / sum(actual) over all rows."""
    actual = pl.col(ACTUAL).cast(pl.Float64)
    return float(scored.select((pl.col(column) - actual).abs().sum() / actual.sum()).item())


def total_bias(scored: pl.DataFrame, column: str = PREDICTION) -> float:
    """Total forecast as a share of total actual sales: 1.0 is unbiased, below 1.0 means
    the forecasts under-predict in aggregate."""
    return float(scored.select(pl.col(column).sum() / pl.col(ACTUAL).sum()).item())


def interval_coverage(scored: pl.DataFrame, lower: str, upper: str) -> dict[str, float]:
    """Share of actuals inside [lower, upper], over all rows and over rows with sales.

    On intermittent data the lower bound is usually 0, so every zero-sales day counts as
    covered; coverage on days with sales is the more informative number.
    """
    actual = pl.col(ACTUAL)
    inside = (actual >= pl.col(lower)) & (actual <= pl.col(upper))
    row = scored.select(
        inside.mean().alias("interval_coverage"),
        inside.filter(actual > 0).mean().alias("interval_coverage_nonzero"),
    ).row(0, named=True)
    return {k: float(v) for k, v in row.items()}
