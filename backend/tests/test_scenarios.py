from datetime import date, timedelta

import numpy as np
import polars as pl

from demandbench.serving.scenarios import scenario_rows, with_anomalies

from .test_api import HORIZON, TRAIN_END, daily_rows, model_ready

SALES_FEATURES = [
    "lag_28",
    "lag_35",
    "lag_42",
    "lag_56",
    "roll_mean_7_h28",
    "roll_std_7_h28",
    "roll_mean_28_h28",
    "roll_std_28_h28",
]


FORECAST_PRICE = 2.5


def series_rows() -> tuple[pl.DataFrame, pl.DataFrame]:
    """One series' precomputed forecast rows and its daily rows, with a constant price
    over the forecast window (as in the real data's planned prices)."""
    daily = daily_rows("A_1", "S_1", 5.0, np.random.default_rng(1)).with_columns(
        pl.when(pl.col("date") > TRAIN_END)
        .then(pl.lit(FORECAST_PRICE))
        .otherwise(pl.col("sell_price"))
        .alias("sell_price")
    )
    forecast = model_ready(daily).filter(pl.col("date") > TRAIN_END)
    return forecast, daily


def test_promo_override_only_changes_the_flag() -> None:
    base, daily = series_rows()
    rows = scenario_rows(base, daily, TRAIN_END, has_promo=True)
    assert rows["has_promo"].all()
    assert rows.drop("has_promo").equals(base.drop("has_promo"))


def test_price_override_recomputes_derived_features_and_keeps_sales_features() -> None:
    base, daily = series_rows()
    same = scenario_rows(base, daily, TRAIN_END, sell_price=FORECAST_PRICE)
    assert same.equals(base)  # the feature SQL reproduces the precomputed rows exactly

    cut = scenario_rows(base, daily, TRAIN_END, sell_price=1.0)
    assert cut["sell_price"].to_list() == [1.0] * HORIZON
    assert cut["has_promo"].all()  # well below the trailing median price
    price_28_days_earlier = daily.filter(
        pl.col("date").is_between(TRAIN_END - timedelta(days=27), TRAIN_END)
    )["sell_price"]
    expected = (1.0 / price_28_days_earlier - 1).to_list()
    assert cut["sell_price_pct_change_28"].to_list() == expected
    assert cut.select(SALES_FEATURES).equals(base.select(SALES_FEATURES))


def test_explicit_promo_wins_over_recomputed_flag() -> None:
    base, daily = series_rows()
    rows = scenario_rows(base, daily, TRAIN_END, sell_price=1.0, has_promo=False)
    assert not rows["has_promo"].any()


def test_anomaly_uses_only_prior_days() -> None:
    sales = [5, 6, 4, 5] * 10 + [60]
    days = [date(2020, 1, 1) + timedelta(days=i) for i in range(len(sales))]
    out = with_anomalies(pl.DataFrame({"date": days, "sales": sales}), days=len(sales))
    assert out["anomaly"].to_list() == [False] * 40 + [True]
    assert out["rolling_mean"][-1] == 5.0  # the spike is not part of its own window
    assert out["rolling_mean"][:28].is_null().all()  # no full prior window yet
