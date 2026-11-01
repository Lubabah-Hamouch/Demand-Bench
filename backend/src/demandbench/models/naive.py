"""Seasonal naive baseline at the 28-day horizon.

Predicts each target day's sales as the sales on the same weekday 28 days earlier
(lag_28), the most recent value available to a direct forecast made 28 days ahead.
"""

import polars as pl

from demandbench.backtest.runner import Predictor

NAME = "naive_seasonal_28"


def naive_model(train: pl.LazyFrame) -> Predictor:
    def predict(test: pl.DataFrame) -> pl.Series:
        return test["lag_28"]

    return predict
