from pathlib import Path

import polars as pl
import pytest

from demandbench.backtest.runner import (
    BacktestResult,
    Forecast,
    Predictor,
    restrict,
    run_backtest,
)
from demandbench.backtest.splitter import make_folds
from demandbench.models.naive import naive_model

from .conftest import LAST


def test_runner_produces_per_fold_and_summary_results(features: pl.LazyFrame) -> None:
    result = run_backtest(naive_model, "naive", features, make_folds(LAST))
    assert result.folds["fold"].to_list() == [1, 2, 3, 4, 5]
    assert result.summary["metric"].to_list() == ["wape", "mape", "rmse", "bias"]
    assert result.series.height == 5 * 3
    assert result.folds["n_series_zero_sales"].to_list() == [1] * 5


def test_perfect_model_scores_zero_error(features: pl.LazyFrame) -> None:
    truth = features.select("item_id", "store_id", "date", "sales").collect()

    def oracle(train: pl.LazyFrame) -> Predictor:
        def predict(test: pl.DataFrame) -> pl.Series:
            return test.join(truth, on=["item_id", "store_id", "date"], how="left")["sales"]

        return predict

    result = run_backtest(oracle, "oracle", features, make_folds(LAST))
    assert result.folds["wape"].to_list() == [0.0] * 5
    assert result.folds["rmse"].to_list() == [0.0] * 5


def test_model_cannot_see_target_in_test_rows(features: pl.LazyFrame) -> None:
    def peeker(train: pl.LazyFrame) -> Predictor:
        return lambda test: test["sales"]

    with pytest.raises(pl.exceptions.ColumnNotFoundError):
        run_backtest(peeker, "peeker", features, make_folds(LAST))


def test_wrong_prediction_length_is_rejected(features: pl.LazyFrame) -> None:
    def short(train: pl.LazyFrame) -> Predictor:
        return lambda test: test["lag_28"].head(5)

    with pytest.raises(ValueError, match="predictions for"):
        run_backtest(short, "short", features, make_folds(LAST))


def test_forecast_quantiles_and_importance_are_recorded(features: pl.LazyFrame) -> None:
    def with_interval(train: pl.LazyFrame) -> Predictor:
        def predict(test: pl.DataFrame) -> Forecast:
            point = test["lag_28"]
            return Forecast(
                point=point,
                quantiles={0.1: point * 0, 0.9: point + 100},
                importance=pl.DataFrame({"feature": ["lag_28"], "gain": [1.0]}),
            )

        return predict

    result = run_backtest(with_interval, "interval", features, make_folds(LAST))
    assert {"q10", "q90"} <= set(result.predictions.columns)
    assert result.folds["interval_coverage"].to_list() == [1.0] * 5
    assert result.folds["interval_coverage_nonzero"].to_list() == [1.0] * 5
    assert result.importance is not None and result.importance.height == 5


def test_series_subset_and_restrict_agree(features: pl.LazyFrame) -> None:
    folds = make_folds(LAST)
    subset = pl.DataFrame({"item_id": ["A", "B"], "store_id": ["S_1", "S_1"]})
    run_on_subset = run_backtest(naive_model, "naive", features, folds, series_subset=subset)
    rescored = restrict(run_backtest(naive_model, "naive", features, folds), subset, "naive")
    assert run_on_subset.folds["n_series"].to_list() == [2] * 5
    for metric in ("wape", "mape", "rmse"):
        assert rescored.folds[metric].to_list() == pytest.approx(
            run_on_subset.folds[metric].to_list()
        )


def test_save_and_load_round_trip(features: pl.LazyFrame, tmp_path: Path) -> None:
    result = run_backtest(naive_model, "naive", features, make_folds(LAST))
    result.save(tmp_path / "naive", total_seconds=1.0)
    loaded = BacktestResult.load(tmp_path / "naive")
    assert loaded.model == "naive"
    assert loaded.folds.equals(result.folds)
    assert loaded.predictions.equals(result.predictions)
