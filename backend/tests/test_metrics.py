import math

import polars as pl
import pytest

from demandbench.backtest.metrics import (
    aggregate,
    interval_coverage,
    pooled_wape,
    series_metrics,
    total_bias,
)


def scored(rows: list[tuple[str, int, float]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=["item_id", "sales", "prediction"], orient="row").with_columns(
        pl.lit("S_1").alias("store_id")
    )


def metrics_for(item: str, df: pl.DataFrame) -> dict[str, float]:
    return series_metrics(df).filter(pl.col("item_id") == item).row(0, named=True)


def test_series_metrics_with_zero_sales_days() -> None:
    df = scored([("A", 0, 1.0), ("A", 2, 1.0), ("A", 4, 4.0)])
    m = metrics_for("A", df)
    assert m["wape"] == pytest.approx(2 / 6)
    assert m["mape"] == pytest.approx((1 / 2 + 0) / 2)  # zero-sales day excluded
    assert m["rmse"] == pytest.approx(math.sqrt(2 / 3))


def test_all_zero_series_has_undefined_wape_and_mape() -> None:
    m = metrics_for("Z", scored([("Z", 0, 1.0), ("Z", 0, 0.0)]))
    assert m["wape"] is None
    assert m["mape"] is None
    assert m["rmse"] == pytest.approx(math.sqrt(1 / 2))


def test_aggregate_wape_is_volume_weighted_and_counts_zero_series_errors() -> None:
    df = scored(
        [
            ("A", 10, 8.0),  # abs error 2 on 10 sales
            ("B", 1, 2.0),  # abs error 1 on 1 sale
            ("Z", 0, 3.0),  # abs error 3 on 0 sales
        ]
    )
    agg = aggregate(series_metrics(df))
    assert agg["wape"] == pytest.approx((2 + 1 + 3) / 11)
    assert agg["n_series"] == 3
    assert agg["n_series_zero_sales"] == 1


def test_total_bias_and_pooled_wape() -> None:
    df = scored([("A", 10, 5.0), ("A", 0, 1.0), ("B", 2, 2.0)])
    assert total_bias(df) == pytest.approx(8 / 12)
    assert pooled_wape(df) == pytest.approx((5 + 1 + 0) / 12)


def test_interval_coverage_conditional_on_sales() -> None:
    df = pl.DataFrame(
        {
            "sales": [0, 0, 0, 3, 5],
            "lo": [0.0, 0.0, 0.0, 0.0, 0.0],
            "hi": [1.0, 1.0, 1.0, 4.0, 4.0],
        }
    )
    coverage = interval_coverage(df, "lo", "hi")
    assert coverage["interval_coverage"] == pytest.approx(4 / 5)
    assert coverage["interval_coverage_nonzero"] == pytest.approx(1 / 2)
