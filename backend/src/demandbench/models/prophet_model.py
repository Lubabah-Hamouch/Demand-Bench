"""Per-series Prophet models, run on the stratified sample only.

Each series gets its own Prophet fit per fold, with yearly and weekly seasonality and
binary regressors for SNAP days, calendar events and the promo proxy (all known for
the target dates). Fits run in parallel worker processes.
"""

import logging
import os
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import polars as pl

from demandbench.backtest.runner import Predictor

NAME = "prophet"
REGRESSORS = ["snap", "is_event", "has_promo"]
MIN_DAYS_FOR_YEARLY = 730
WORKERS = int(os.environ.get("DEMANDBENCH_PROPHET_WORKERS", "4"))

_KEY = ["item_id", "store_id"]


def _fit_predict(task: tuple[dict[str, list[object]], dict[str, list[object]]]) -> list[float]:
    """Fit one series and forecast its test days. Runs in a worker process.

    pandas is used here only because Prophet requires it.
    """
    logging.getLogger("prophet.plot").setLevel(logging.CRITICAL)
    import pandas as pd  # type: ignore[import-untyped]
    from prophet import Prophet

    # cmdstanpy resets its own log level on each fit; fit failures still raise.
    logging.getLogger("cmdstanpy").disabled = True

    history, future = (pd.DataFrame(part) for part in task)
    # A regressor that never varies in the history cannot be fitted.
    regressors = [r for r in REGRESSORS if history[r].nunique() > 1]
    span_days = (history["ds"].max() - history["ds"].min()).days

    model = Prophet(
        # Yearly seasonality is not identifiable with under two years of history.
        yearly_seasonality=span_days >= MIN_DAYS_FOR_YEARLY,
        weekly_seasonality=True,
        daily_seasonality=False,
        uncertainty_samples=0,
    )
    for name in regressors:
        model.add_regressor(name, standardize=False)
    model.fit(history[["ds", "y", *regressors]])
    forecast = model.predict(future[["ds", *regressors]])
    return list(np.clip(forecast["yhat"].to_numpy(), 0, None))


def _as_columns(frame: pl.DataFrame) -> dict[str, list[object]]:
    return frame.with_columns(pl.col(REGRESSORS).cast(pl.Float64)).to_dict(as_series=False)


def prophet_model(train: pl.LazyFrame) -> Predictor:
    # History starts on the first day each item was on sale; the all-zero stretch
    # before launch would otherwise distort Prophet's trend.
    history = (
        train.filter(pl.col("sell_price").is_not_null().cum_max().over(_KEY))
        .select(
            *_KEY,
            pl.col("date").alias("ds"),
            pl.col("sales").cast(pl.Float64).alias("y"),
            *REGRESSORS,
        )
        .sort(*_KEY, "ds")
        .collect()
    )

    def predict(test: pl.DataFrame) -> pl.Series:
        future = test.select(*_KEY, pl.col("date").alias("ds"), *REGRESSORS)
        keys = future.select(_KEY).unique(maintain_order=True)
        history_by_key = history.partition_by(_KEY, as_dict=True, include_key=False)
        future_by_key = future.partition_by(_KEY, as_dict=True, include_key=False)
        tasks = [
            (_as_columns(history_by_key[key]), _as_columns(future_by_key[key]))
            for key in keys.iter_rows()
        ]
        with ProcessPoolExecutor(max_workers=WORKERS) as pool:
            results = list(pool.map(_fit_predict, tasks))

        predicted = pl.concat(
            future_by_key[key]
            .select("ds")
            .with_columns(
                pl.lit(key[0]).alias("item_id"),
                pl.lit(key[1]).alias("store_id"),
                pl.Series("prediction", values, dtype=pl.Float64),
            )
            for key, values in zip(keys.iter_rows(), results, strict=True)
        )
        aligned = future.join(predicted, on=[*_KEY, "ds"], how="left", maintain_order="left")
        return aligned["prediction"]

    return predict
