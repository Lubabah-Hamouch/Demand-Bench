"""Run a model across every rolling-origin fold and collect comparable metrics."""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl

from demandbench.backtest.metrics import (
    ACTUAL,
    PREDICTION,
    SERIES_KEYS,
    aggregate,
    interval_coverage,
    pooled_wape,
    series_metrics,
    total_bias,
)
from demandbench.backtest.splitter import Fold, last_date, make_folds, scan_features, split


@dataclass(frozen=True)
class Forecast:
    """What a predictor may return instead of a bare Series of point forecasts.

    quantiles maps a quantile level (e.g. 0.1) to a Series aligned with the test rows.
    importance is any per-fold feature importance table the model wants recorded.
    """

    point: pl.Series
    quantiles: dict[float, pl.Series] = field(default_factory=dict)
    importance: pl.DataFrame | None = None


Predictor = Callable[[pl.DataFrame], pl.Series | Forecast]
ModelFn = Callable[[pl.LazyFrame], Predictor]
"""The model interface: fit(train) -> predict(test) -> predictions.

A ModelFn is called once per fold with that fold's training rows (target date <= cutoff)
as a LazyFrame, so it can select only the columns and rows it needs before collecting.
It returns a predictor, which is called with the fold's test rows (target column
removed, sorted by store_id, item_id, date) and must return one non-null numeric
prediction per row, in the same order: either a Series of point forecasts, or a
Forecast carrying quantiles and feature importance as well.
"""

TEST_SORT = ["store_id", "item_id", "date"]


@dataclass(frozen=True)
class BacktestResult:
    model: str
    folds: pl.DataFrame
    """One row per fold: boundaries, aggregated metrics, timings."""
    summary: pl.DataFrame
    """One row per metric: mean and std across folds."""
    series: pl.DataFrame
    """One row per fold x series, for analysing where a model does well or badly."""
    predictions: pl.DataFrame
    """One row per fold x series x test day: actual, point forecast, any quantiles."""
    importance: pl.DataFrame | None = None
    """Per-fold feature importance, if the model reports it."""

    def save(self, directory: Path, **metadata: object) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        for name in ("folds", "summary", "series", "predictions", "importance"):
            frame = getattr(self, name)
            if frame is not None:
                frame.write_parquet(directory / f"{name}.parquet")
        (directory / "run.json").write_text(json.dumps({"model": self.model, **metadata}, indent=2))

    @classmethod
    def load(cls, directory: Path) -> "BacktestResult":
        def read(name: str) -> pl.DataFrame | None:
            path = directory / f"{name}.parquet"
            return pl.read_parquet(path) if path.is_file() else None

        meta = json.loads((directory / "run.json").read_text())
        frames = {name: read(name) for name in ("folds", "summary", "series", "predictions")}
        return cls(model=meta["model"], importance=read("importance"), **frames)  # type: ignore[arg-type]


def _check(values: pl.Series, test: pl.DataFrame, fold: Fold, name: str) -> pl.Series:
    if values.len() != test.height:
        raise ValueError(
            f"{fold}: got {values.len():,} {name} predictions for {test.height:,} rows"
        )
    if not values.dtype.is_numeric():
        raise TypeError(f"{fold}: {name} predictions have non-numeric dtype {values.dtype}")
    if values.null_count() or values.is_nan().any():
        raise ValueError(f"{fold}: {name} predictions contain nulls or NaNs")
    return values.cast(pl.Float64).alias(name)


def quantile_column(q: float) -> str:
    return f"q{round(q * 100):02d}"


def _quantile_columns(preds: pl.DataFrame) -> list[str]:
    return sorted(c for c in preds.columns if c.startswith("q") and c[1:].isdigit())


def _fold_row(
    fold_info: dict[str, object], series: pl.DataFrame, preds: pl.DataFrame
) -> dict[str, object]:
    """Fold-level metrics. Besides WAPE/MAPE/RMSE this records total-sales bias of the
    point forecast, the same two numbers for the median (q50) forecast when a model
    provides one, and interval coverage when it provides at least two quantiles."""
    row = {**fold_info, **aggregate(series), "bias": total_bias(preds)}
    q_cols = _quantile_columns(preds)
    if "q50" in q_cols:
        row["wape_q50"] = pooled_wape(preds, "q50")
        row["bias_q50"] = total_bias(preds, "q50")
    if len(q_cols) >= 2:
        row.update(interval_coverage(preds, q_cols[0], q_cols[-1]))
    return row


SUMMARY_METRICS = [
    "wape",
    "mape",
    "rmse",
    "bias",
    "wape_q50",
    "bias_q50",
    "interval_coverage",
    "interval_coverage_nonzero",
]


def _summarise(folds: pl.DataFrame) -> pl.DataFrame:
    metrics = [m for m in SUMMARY_METRICS if m in folds.columns]
    return pl.DataFrame(
        {
            "metric": metrics,
            "mean": [folds[m].mean() for m in metrics],
            "std": [folds[m].std() for m in metrics],
        }
    )


def run_backtest(
    model_fn: ModelFn,
    name: str,
    features: pl.LazyFrame | None = None,
    folds: list[Fold] | None = None,
    series_subset: pl.DataFrame | None = None,
) -> BacktestResult:
    """Run model_fn on every fold. If series_subset (item_id, store_id) is given, both
    training and test rows are restricted to those series."""
    features = scan_features() if features is None else features
    folds = make_folds(last_date(features)) if folds is None else folds
    if series_subset is not None:
        features = features.join(
            series_subset.lazy().select(SERIES_KEYS), on=SERIES_KEYS, how="semi"
        )

    fold_rows = []
    series_frames = []
    prediction_frames = []
    importance_frames = []
    for fold in folds:
        train, test_lf = split(features, fold)
        test = test_lf.sort(TEST_SORT).collect()

        start = time.perf_counter()
        predict = model_fn(train)
        fit_seconds = time.perf_counter() - start

        start = time.perf_counter()
        output = predict(test.drop(ACTUAL))
        predict_seconds = time.perf_counter() - start

        forecast = output if isinstance(output, Forecast) else Forecast(point=output)
        columns = [_check(forecast.point, test, fold, PREDICTION)]
        for q, values in sorted(forecast.quantiles.items()):
            columns.append(_check(values, test, fold, quantile_column(q)))

        preds = test.select(*SERIES_KEYS, "date", ACTUAL).with_columns(columns)
        series = series_metrics(preds)
        fold_tag = pl.lit(fold.index).alias("fold")
        series_frames.append(series.with_columns(fold_tag))
        prediction_frames.append(preds.with_columns(fold_tag))
        if forecast.importance is not None:
            importance_frames.append(forecast.importance.with_columns(fold_tag))

        fold_info = {
            "fold": fold.index,
            "cutoff": fold.cutoff,
            "test_start": fold.test_start,
            "test_end": fold.test_end,
        }
        fold_rows.append(
            {
                **_fold_row(fold_info, series, preds),
                "fit_s": fit_seconds,
                "predict_s": predict_seconds,
            }
        )

    folds_df = pl.DataFrame(fold_rows)
    return BacktestResult(
        model=name,
        folds=folds_df,
        summary=_summarise(folds_df),
        series=pl.concat(series_frames).select("fold", pl.exclude("fold")),
        predictions=pl.concat(prediction_frames).select("fold", pl.exclude("fold")),
        importance=(
            pl.concat(importance_frames).select("fold", pl.exclude("fold"))
            if importance_frames
            else None
        ),
    )


def rescore(
    result: BacktestResult,
    series_subset: pl.DataFrame | None = None,
    name: str | None = None,
) -> BacktestResult:
    """Recompute all metrics from a result's stored predictions, without re-running the
    model, optionally restricted to a subset of series.

    This keeps saved results comparable when metric definitions change, and lets a model
    run on the full dataset be compared on the same series as a model that was only run
    on a subset. Fit and predict timings are carried over from the original run.
    """
    predictions = result.predictions
    if series_subset is not None:
        predictions = predictions.join(
            series_subset.select(SERIES_KEYS), on=SERIES_KEYS, how="semi"
        )

    info_cols = ["fold", "cutoff", "test_start", "test_end"]
    fold_rows = []
    series_frames = []
    for info in result.folds.select(info_cols).iter_rows(named=True):
        preds = predictions.filter(pl.col("fold") == info["fold"]).drop("fold")
        series = series_metrics(preds)
        series_frames.append(series.with_columns(pl.lit(info["fold"]).alias("fold")))
        fold_rows.append(_fold_row(info, series, preds))

    timings = [c for c in ("fit_s", "predict_s") if c in result.folds.columns]
    folds_df = pl.DataFrame(fold_rows).join(result.folds.select("fold", *timings), on="fold")
    return BacktestResult(
        model=name or result.model,
        folds=folds_df,
        summary=_summarise(folds_df),
        series=pl.concat(series_frames).select("fold", pl.exclude("fold")),
        predictions=predictions,
        importance=result.importance,
    )


def restrict(result: BacktestResult, series_subset: pl.DataFrame, name: str) -> BacktestResult:
    """Re-score an existing result on a subset of series (see rescore)."""
    return rescore(result, series_subset, name)


TABLE_CONFIG = {
    "tbl_formatting": "ASCII_MARKDOWN",
    "tbl_hide_dataframe_shape": True,
    "tbl_hide_column_data_types": True,
    "float_precision": 4,
    "tbl_cols": -1,
    "tbl_rows": -1,
    "tbl_width_chars": 250,
}


def print_result(result: BacktestResult) -> None:
    with pl.Config(**TABLE_CONFIG):  # type: ignore[arg-type]
        print(f"\nmodel: {result.model}\n\nper fold")
        print(result.folds)
        print("\nacross folds (std is sample std over folds)")
        print(result.summary)
