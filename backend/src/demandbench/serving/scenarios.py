"""What-if scenarios and sales history for a single series."""

from datetime import date

import duckdb
import polars as pl

from demandbench.features.build_features import model_ready_sql

PRICE_FEATURES = ["sell_price", "sell_price_pct_change_28", "has_promo"]
ANOMALY_WINDOW = 28
ANOMALY_THRESHOLD = 3.0


def scenario_rows(
    base_rows: pl.DataFrame,
    daily: pl.DataFrame,
    trained_through: date,
    sell_price: float | None = None,
    has_promo: bool | None = None,
) -> pl.DataFrame:
    """Forecast feature rows for one series under a what-if scenario.

    base_rows are the series' precomputed forecast rows; daily are its features_daily
    rows (recent history plus the forecast days). A sell_price override replaces the
    price on every forecast day, and the price-derived features (28-day price change and
    the promo flag) are recomputed with the same SQL that built the training features.
    An explicit has_promo override is applied last, so it wins over the recomputed flag.
    Sales lags and rolling features are kept from base_rows unchanged: a hypothetical
    price or promo does not change past sales.
    """
    rows = base_rows
    if sell_price is not None:
        forecast_days = pl.col("date") > trained_through
        priced = daily.with_columns(
            pl.when(forecast_days)
            .then(pl.lit(sell_price))
            .otherwise(pl.col("sell_price"))
            .alias("sell_price")
        )
        store_id = priced["store_id"][0]
        with duckdb.connect() as con:
            con.register("daily", priced)
            recomputed = con.sql(
                f"SELECT date, {', '.join(PRICE_FEATURES)} FROM ({model_ready_sql('daily')}) "
                "WHERE date > $start",
                params={"store_id": store_id, "start": trained_through},
            ).pl()
        rows = (
            rows.drop(PRICE_FEATURES)
            .join(recomputed, on="date", how="left", maintain_order="left")
            .select(base_rows.columns)
        )
    if has_promo is not None:
        rows = rows.with_columns(pl.lit(has_promo).alias("has_promo"))
    return rows


def with_anomalies(sales: pl.DataFrame, days: int) -> pl.DataFrame:
    """The last `days` rows of a series' daily sales, with an anomaly flag.

    Each day is compared with the mean and standard deviation of the ANOMALY_WINDOW days
    before it (the day itself is excluded, as in the model's rolling features). A day is
    anomalous when its sales differ from that mean by more than ANOMALY_THRESHOLD
    standard deviations. Days whose prior window has zero variance (e.g. 28 days of no
    sales) are never flagged, since the deviation in standard deviations is undefined;
    days without a full prior window have null statistics and are not flagged.
    """
    actual = pl.col("sales").cast(pl.Float64)
    prior = actual.shift(1)
    mean = prior.rolling_mean(ANOMALY_WINDOW)
    std = prior.rolling_std(ANOMALY_WINDOW)
    return (
        sales.select("date", "sales")
        .with_columns(mean.alias("rolling_mean"), std.alias("rolling_std"))
        .with_columns(
            pl.when(pl.col("rolling_std") > 0)
            .then((actual - pl.col("rolling_mean")) / pl.col("rolling_std"))
            .alias("z_score")
        )
        .with_columns(
            (pl.col("z_score").abs() > ANOMALY_THRESHOLD).fill_null(False).alias("anomaly")
        )
        .tail(days)
    )
