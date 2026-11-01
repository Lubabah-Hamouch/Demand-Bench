"""Build features_daily and features_model_ready from the raw M5 tables."""

import sys
import time
from collections.abc import Callable
from datetime import timedelta

import duckdb
import polars as pl

from demandbench.paths import DUCKDB_PATH, FEATURES_PARQUET, FORECAST_FEATURES_PARQUET

SERIES_ID_COLUMNS = ["id", "item_id", "dept_id", "cat_id", "store_id", "state_id"]
# Direct forecasting at a fixed 28-day horizon: no sales feature may use any day
# inside the 28 days before the target date.
HORIZON = 28
LAGS = (28, 35, 42, 56)
ROLLING_WINDOWS = (7, 28)
PROMO_LOOKBACK_DAYS = 90
SPOT_CHECK_SERIES = ("FOODS_3_090", "CA_1")
MEMORY_LIMIT = "4GB"
# Observed days kept as history when building forecast rows: enough for the longest
# look-back (90-day promo median, 56-day lag, 55-day rolling window).
FORECAST_HISTORY_DAYS = 120


def unpivot_sales(wide: pl.DataFrame) -> pl.DataFrame:
    """Unpivot wide sales to (series_idx, day, sales).

    Only three numeric columns cross into DuckDB, which keeps the handoff cheap; the
    string id columns are joined back in SQL from the small series table.
    """
    d_cols = [c for c in wide.columns if c.startswith("d_")]
    return (
        wide.select("series_idx", *d_cols)
        .unpivot(index="series_idx", on=d_cols, variable_name="d", value_name="sales")
        .select(
            "series_idx",
            pl.col("d").str.strip_prefix("d_").cast(pl.Int16).alias("day"),
            pl.col("sales").cast(pl.Int16),
        )
    )


def future_days(con: duckdb.DuckDBPyConnection, last_day: int) -> list[int]:
    """The HORIZON calendar days after the last day with sales."""
    days = [
        row[0]
        for row in con.execute(
            "SELECT CAST(substr(d, 3) AS SMALLINT) AS day FROM raw_calendar "
            "WHERE day > ? ORDER BY day LIMIT ?",
            [last_day, HORIZON],
        ).fetchall()
    ]
    if len(days) != HORIZON:
        raise ValueError(f"calendar has only {len(days)} days after d_{last_day}, need {HORIZON}")
    return days


def future_sales(wide: pl.DataFrame, days: list[int]) -> pl.DataFrame:
    """(series_idx, day, sales) rows for days not yet observed, with sales null."""
    return (
        wide.select("series_idx")
        .join(pl.DataFrame({"day": days}, schema={"day": pl.Int16}), how="cross")
        .with_columns(pl.lit(None, dtype=pl.Int16).alias("sales"))
    )


def build_features_daily(
    con: duckdb.DuckDBPyConnection,
    stores: list[str],
    table: str = "features_daily",
    future: bool = False,
) -> None:
    """Join daily sales with calendar and prices into `table`.

    With future=True, rows are generated for the HORIZON days after the last observed
    day instead, with sales null, using the same calendar and price joins.
    """
    wide = con.sql("SELECT * FROM raw_sales").pl().with_row_index("series_idx")
    con.register("series", wide.select("series_idx", *SERIES_ID_COLUMNS))
    if future:
        last_day = max(int(c.removeprefix("d_")) for c in wide.columns if c.startswith("d_"))
        days = future_days(con, last_day)

    # Built one store at a time to bound memory; stores and rows within a store are
    # inserted in sorted order, so the table ends up sorted by store_id, item_id, date.
    query = """
        WITH calendar AS (
            SELECT *, CAST(substr(d, 3) AS SMALLINT) AS day FROM raw_calendar
        )
        SELECT
            s.id, s.item_id, s.dept_id, s.cat_id, s.store_id, s.state_id,
            c.d,
            c.date,
            l.sales,
            c.wm_yr_wk,
            c.wday,
            c.month,
            c.year,
            c.event_name_1, c.event_type_1, c.event_name_2, c.event_type_2,
            CASE s.state_id
                WHEN 'CA' THEN c.snap_CA
                WHEN 'TX' THEN c.snap_TX
                WHEN 'WI' THEN c.snap_WI
            END = 1 AS snap,
            p.sell_price
        FROM sales_long l
        JOIN series s USING (series_idx)
        JOIN calendar c USING (day)
        LEFT JOIN (SELECT * FROM raw_prices WHERE store_id = $store_id) p
            ON p.store_id = s.store_id
            AND p.item_id = s.item_id
            AND p.wm_yr_wk = c.wm_yr_wk
        ORDER BY s.item_id, c.date
    """

    for i, store_id in enumerate(stores):
        start = time.perf_counter()
        store_wide = wide.filter(pl.col("store_id") == store_id)
        long = future_sales(store_wide, days) if future else unpivot_sales(store_wide)
        con.register("sales_long", long)
        if i == 0:
            con.execute(f"CREATE OR REPLACE TABLE {table} AS {query}", {"store_id": store_id})
        else:
            con.execute(f"INSERT INTO {table} {query}", {"store_id": store_id})
        con.unregister("sales_long")
        print(f"  {store_id:<6} {time.perf_counter() - start:6.2f}s")

    con.unregister("series")


def rolling_name(stat: str, n: int) -> str:
    return f"roll_{stat}_{n}_h{HORIZON}"


def model_ready_sql(source: str = "features_daily") -> str:
    # Every window is PARTITION BY item_id, store_id, so lags and rolling stats never
    # cross series. Series are gap-free daily (validated below), so a ROWS offset of N
    # is N days. An N-day rolling window for target t covers t-(HORIZON+N-1) through
    # t-HORIZON inclusive, and is null until the full window exists.
    lags = ",\n".join(f"lag(sales, {n}) OVER w AS lag_{n}" for n in LAGS)
    rolling = ",\n".join(
        f"CASE WHEN row_number() OVER w > {HORIZON + n - 1} THEN {agg}(sales) OVER "
        f"(w ROWS BETWEEN {HORIZON + n - 1} PRECEDING AND {HORIZON} PRECEDING) END "
        f"AS {rolling_name(stat, n)}"
        for n in ROLLING_WINDOWS
        for agg, stat in (("avg", "mean"), ("stddev_samp", "std"))
    )
    return f"""
        SELECT
            id, item_id, dept_id, cat_id, store_id, state_id,
            date, d,
            row_number() OVER w AS day_idx,
            sales,
            {lags},
            {rolling},
            wday, month, year,
            (event_name_1 IS NOT NULL OR event_name_2 IS NOT NULL) AS is_event,
            snap,
            sell_price,
            sell_price / lag(sell_price, 28) OVER w - 1 AS sell_price_pct_change_28,
            coalesce(
                sell_price < median(sell_price) OVER (
                    w ROWS BETWEEN {PROMO_LOOKBACK_DAYS} PRECEDING AND 1 PRECEDING
                ),
                false
            ) AS has_promo
        FROM {source}
        WHERE store_id = $store_id
        WINDOW w AS (PARTITION BY item_id, store_id ORDER BY date)
        ORDER BY item_id, date
    """


def build_features_model_ready(con: duckdb.DuckDBPyConnection, stores: list[str]) -> None:
    # Windows never span stores, so building one store at a time gives identical
    # results while keeping the working set to ~1/10 of the data. Stores are inserted
    # in sorted order, so the table ends up sorted by store_id, item_id, date.
    query = model_ready_sql()

    con.execute(
        f"CREATE OR REPLACE TABLE features_model_ready AS {query} LIMIT 0",
        {"store_id": stores[0]},
    )
    for store_id in stores:
        start = time.perf_counter()
        con.execute(f"INSERT INTO features_model_ready {query}", {"store_id": store_id})
        print(f"  {store_id:<6} {time.perf_counter() - start:6.2f}s")


def build_features_forecast(con: duckdb.DuckDBPyConnection, stores: list[str]) -> None:
    """Feature rows for the HORIZON days after the last observed day: the rows a
    production forecast is made for.

    Future dates get calendar and price data from the same daily joins, then the same
    window SQL as features_model_ready is run over recent history plus those rows. Every
    sales feature for a future date only reaches back to observed days, because all
    lags and rolling windows end at least HORIZON days before the target date.
    """
    build_features_daily(con, stores, table="features_daily_future", future=True)
    last_date = con.execute("SELECT max(date) FROM features_daily").fetchone()[0]  # type: ignore[index]
    history_start = last_date - timedelta(days=FORECAST_HISTORY_DAYS)
    source = f"""(
        SELECT * FROM features_daily WHERE date > DATE '{history_start}'
        UNION ALL
        SELECT * FROM features_daily_future
    )"""
    query = f"""
        SELECT * EXCLUDE (day_idx, sales)
        FROM ({model_ready_sql(source)})
        WHERE date > DATE '{last_date}'
        ORDER BY item_id, date
    """
    con.execute(
        f"CREATE OR REPLACE TABLE features_forecast AS {query} LIMIT 0", {"store_id": stores[0]}
    )
    for store_id in stores:
        con.execute(f"INSERT INTO features_forecast {query}", {"store_id": store_id})


def leading_nulls() -> dict[str, int]:
    """Number of leading days per series for which each sales feature must be null."""
    expected = {f"lag_{n}": n for n in LAGS}
    for n in ROLLING_WINDOWS:
        expected[rolling_name("mean", n)] = HORIZON + n - 1
        expected[rolling_name("std", n)] = HORIZON + n - 1
    return expected


def validate(con: duckdb.DuckDBPyConnection) -> bool:
    ok = True

    def check(label: str, passed: bool, detail: str) -> None:
        nonlocal ok
        ok &= passed
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}: {detail}")

    print("\nvalidation")
    n_daily, n_ready, n_series = con.execute(
        """
        SELECT (SELECT count(*) FROM features_daily),
               (SELECT count(*) FROM features_model_ready),
               (SELECT count(*) FROM raw_sales)
        """
    ).fetchone()  # type: ignore[misc]
    check("row counts", n_daily == n_ready, f"features_daily {n_daily:,}, model_ready {n_ready:,}")

    n_bad_series, n_days = con.execute(
        """
        SELECT count(*) FILTER (WHERE n != date_diff('day', first, last) + 1),
               max(n)
        FROM (
            SELECT count(*) AS n, min(date) AS first, max(date) AS last
            FROM features_daily GROUP BY item_id, store_id
        )
        """
    ).fetchone()  # type: ignore[misc]
    check(
        "series contiguity",
        n_bad_series == 0 and n_daily == n_series * n_days,
        f"{n_series:,} series x {n_days:,} days, {n_bad_series} with gaps",
    )

    sizes = leading_nulls()
    violations = ", ".join(
        f"count(*) FILTER (WHERE (day_idx <= {n}) != ({col} IS NULL)) AS {col}"
        for col, n in sizes.items()
    )
    row = con.execute(f"SELECT {violations} FROM features_model_ready").fetchone()
    assert row is not None
    for (col, n), bad in zip(sizes.items(), row, strict=True):
        check(
            f"{col} nulls",
            bad == 0,
            f"null exactly for first {n} days of each series ({bad} violations)",
        )

    price_nulls, pct_nulls, promo_share = con.execute(
        """
        SELECT avg((sell_price IS NULL)::INT), avg((sell_price_pct_change_28 IS NULL)::INT),
               avg(has_promo::INT)
        FROM features_model_ready
        """
    ).fetchone()  # type: ignore[misc]
    print(
        f"  [INFO] sell_price null {price_nulls:.1%} (item not yet on sale), "
        f"pct_change_28 null {pct_nulls:.1%}, has_promo true {promo_share:.1%}"
    )

    item_id, store_id = SPOT_CHECK_SERIES
    spot = (
        con.cursor()
        .sql(
            f"""
        SELECT date, sales, {", ".join(sizes)}
        FROM features_model_ready WHERE item_id = ? AND store_id = ? ORDER BY date
        """,
            params=[item_id, store_id],
        )
        .pl()
    )
    # Independent definition: shift the series forward by the offset, then apply a
    # trailing window. rolling_* with the default min_samples=n leaves partial windows null.
    sales = pl.col("sales").cast(pl.Float64)
    expected = spot.select(
        *[sales.shift(n).alias(f"lag_{n}") for n in LAGS],
        *[
            sales.shift(HORIZON).rolling_mean(n).alias(rolling_name("mean", n))
            for n in ROLLING_WINDOWS
        ],
        *[
            sales.shift(HORIZON).rolling_std(n).alias(rolling_name("std", n))
            for n in ROLLING_WINDOWS
        ],
    )
    null_mismatches = sum((spot[c].is_null() != expected[c].is_null()).sum() for c in sizes)
    max_diff = max((spot[c].cast(pl.Float64) - expected[c]).abs().max() or 0.0 for c in sizes)
    check(
        f"recompute {item_id}/{store_id} in Polars",
        max_diff < 1e-9 and null_mismatches == 0,
        f"max abs diff {max_diff:.2e}, {null_mismatches} null mismatches "
        f"across {spot.height:,} days",
    )

    validate_forecast(con, check, spot, n_series)

    # Days HORIZON+1..HORIZON+10: lag_28 here should equal sales on days 1..10, and the
    # 7-day rolling mean should first appear on day HORIZON+7 as the mean of days 1..7.
    roll_col = rolling_name("mean", 7)
    print(f"\nspot check: {item_id} @ {store_id}, days 1-10 and {HORIZON + 1}-{HORIZON + 10}")
    with pl.Config(
        tbl_formatting="ASCII_MARKDOWN",
        tbl_hide_dataframe_shape=True,
        tbl_hide_column_data_types=True,
    ):
        print(spot.select("date", "sales").head(10))
        print(spot.select("date", "sales", f"lag_{HORIZON}", roll_col).slice(HORIZON, 10))

    return ok


def validate_forecast(
    con: duckdb.DuckDBPyConnection,
    check: Callable[[str, bool, str], None],
    spot: pl.DataFrame,
    n_series: int,
) -> None:
    """Checks on features_forecast. `spot` is the spot-check series' observed history."""
    sizes = leading_nulls()
    null_counts = ", ".join(f"count(*) FILTER (WHERE {c} IS NULL)" for c in sizes)
    row = con.execute(
        f"""
        SELECT count(*), min(date), max(date), count(DISTINCT date),
               (SELECT max(date) FROM features_daily), {null_counts}
        FROM features_forecast
        """
    ).fetchone()
    assert row is not None
    n_rows, first, last, n_dates, observed_end, *nulls = row
    check(
        "forecast rows",
        n_rows == n_series * HORIZON
        and n_dates == HORIZON
        and first == observed_end + timedelta(days=1),
        f"{n_rows:,} rows, {first} -> {last}, starting the day after the last observed day",
    )
    check(
        "forecast sales features",
        sum(nulls) == 0,
        f"no nulls in {len(sizes)} lag/rolling columns ({sum(nulls)} found)",
    )

    # Recompute the spot series' forecast-row features from its observed sales extended
    # with HORIZON unknown days: any use of an unobserved day would produce a null.
    item_id, store_id = SPOT_CHECK_SERIES
    forecast = (
        con.cursor()
        .sql(
            f"SELECT date, {', '.join(sizes)} FROM features_forecast "
            "WHERE item_id = ? AND store_id = ? ORDER BY date",
            params=[item_id, store_id],
        )
        .pl()
    )
    sales = pl.concat(
        [
            spot.select("date", pl.col("sales").cast(pl.Float64)),
            forecast.select("date", pl.lit(None, dtype=pl.Float64).alias("sales")),
        ]
    )["sales"]
    expected = pl.DataFrame(
        {
            **{f"lag_{n}": sales.shift(n) for n in LAGS},
            **{
                rolling_name("mean", n): sales.shift(HORIZON).rolling_mean(n)
                for n in ROLLING_WINDOWS
            },
            **{
                rolling_name("std", n): sales.shift(HORIZON).rolling_std(n) for n in ROLLING_WINDOWS
            },
        }
    ).tail(HORIZON)
    max_diff = max((forecast[c].cast(pl.Float64) - expected[c]).abs().max() or 0.0 for c in sizes)
    null_mismatches = sum((forecast[c].is_null() != expected[c].is_null()).sum() for c in sizes)
    check(
        f"recompute forecast rows for {item_id}/{store_id}",
        max_diff < 1e-9 and null_mismatches == 0,
        f"max abs diff {max_diff:.2e}, {null_mismatches} null mismatches across {HORIZON} days",
    )


def export_parquet(con: duckdb.DuckDBPyConnection) -> None:
    """Write features_model_ready (for the backtest harness, which scans it lazily) and
    features_forecast (the rows the final model forecasts) to Parquet."""
    for table, target in (
        ("features_model_ready", FEATURES_PARQUET),
        ("features_forecast", FORECAST_FEATURES_PARQUET),
    ):
        target.unlink(missing_ok=True)
        path = target.as_posix().replace("'", "''")
        con.execute(f"COPY {table} TO '{path}' (FORMAT parquet, COMPRESSION zstd)")


def main() -> None:
    with duckdb.connect(str(DUCKDB_PATH)) as con:
        con.execute("SET enable_progress_bar = false")
        con.execute(f"SET memory_limit = '{MEMORY_LIMIT}'")
        stores = [
            row[0]
            for row in con.execute(
                "SELECT DISTINCT store_id FROM raw_sales ORDER BY store_id"
            ).fetchall()
        ]

        start = time.perf_counter()
        print("features_daily        building per store (reshape + joins)")
        build_features_daily(con, stores)
        daily_seconds = time.perf_counter() - start
        print(f"features_daily        built in {daily_seconds:6.2f}s")

        step = time.perf_counter()
        print("features_model_ready  building per store (lags, rolling, promo)")
        build_features_model_ready(con, stores)
        ready_seconds = time.perf_counter() - step
        print(f"features_model_ready  built in {ready_seconds:6.2f}s")

        step = time.perf_counter()
        print("features_forecast     building per store (next 28 days)")
        build_features_forecast(con, stores)
        print(f"features_forecast     built in {time.perf_counter() - step:6.2f}s")

        build_seconds = time.perf_counter() - start
        step = time.perf_counter()
        ok = validate(con)
        validate_seconds = time.perf_counter() - step

        if ok:
            step = time.perf_counter()
            export_parquet(con)
            print(f"\nexported Parquet files in {time.perf_counter() - step:.2f}s")

    print(
        f"\nfeature build {build_seconds:.2f}s, validation {validate_seconds:.2f}s, "
        f"total {build_seconds + validate_seconds:.2f}s"
    )
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
