"""Global LightGBM model: one model pooled across all series, per fold.

Four models are trained per fold on the same data:

- a Tweedie-objective model, which is the point forecast. Tweedie suits sparse,
  non-negative counts and targets the mean, so its forecasts sum to roughly the
  actual total;
- quantile-objective models at 0.1, 0.5 and 0.9. The 0.1 and 0.9 models give an 80%
  prediction interval. The 0.5 model is kept for comparison: it minimises absolute
  error, which WAPE rewards, but on intermittent series the median is often zero, so
  its forecasts sum to well below actual sales.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Literal

import lightgbm as lgb
import numpy as np
import polars as pl

from demandbench.backtest.runner import Forecast, ModelFn, Predictor

NAME = "lightgbm_global"
QuantileScale = Literal["raw", "log1p"]

CATEGORICAL = ["item_id", "dept_id", "cat_id", "store_id", "state_id"]
NUMERIC = [
    "lag_28",
    "lag_35",
    "lag_42",
    "lag_56",
    "roll_mean_7_h28",
    "roll_std_7_h28",
    "roll_mean_28_h28",
    "roll_std_28_h28",
    "wday",
    "month",
    "is_event",
    "snap",
    "has_promo",
    "sell_price",
    "sell_price_pct_change_28",
]
FEATURES = CATEGORICAL + NUMERIC
QUANTILES = (0.1, 0.5, 0.9)
# Chosen by tune_tweedie on a validation window inside fold 1's training data (no test
# window of any fold is used); see data/processed/backtest/tweedie_tuning.csv.
TWEEDIE_VARIANCE_POWER = 1.5
# Economic direction enforced in every model, so what-if price and promo scenarios
# move the forecast the right way: demand never rises with price or with a price
# increase vs 28 days earlier, and never falls when a promo is on. All other features
# are unconstrained. A global model otherwise learns price effects mostly *across*
# items, which can make a price cut lower one item's forecast.
MONOTONE = {"sell_price": -1, "sell_price_pct_change_28": -1, "has_promo": 1}
MONOTONE_METHOD = "basic"


@dataclass(frozen=True)
class LightGBMConfig:
    # Most recent days of each fold's training data to train on. The full history is
    # ~55M rows per fold, which does not fit comfortably in memory; recent data is also
    # the most relevant for a 28-day-ahead forecast.
    train_days: int = 365
    num_boost_round: int = 300
    tweedie_variance_power: float = TWEEDIE_VARIANCE_POWER
    monotone: bool = True
    monotone_method: str = MONOTONE_METHOD
    params: dict[str, object] = field(
        default_factory=lambda: {
            "learning_rate": 0.08,
            "num_leaves": 127,
            "min_data_in_leaf": 200,
            "feature_fraction": 0.8,
            "bagging_fraction": 0.7,
            "bagging_freq": 1,
            "lambda_l2": 1.0,
            "cat_smooth": 10,
            "max_bin": 255,
            "num_threads": 8,
            "seed": 42,
            "verbose": -1,
        }
    )


def _encode(frame: pl.DataFrame, categories: dict[str, list[str]]) -> np.ndarray:
    """Feature matrix as float32. Categoricals become integer codes from the training
    vocabulary (unseen values become NaN, which LightGBM treats as missing)."""
    return (
        frame.select(
            *[
                pl.col(c)
                .replace_strict(cats, list(range(len(cats))), default=None, return_dtype=pl.Int32)
                .alias(c)
                for c, cats in categories.items()
            ],
            *[pl.col(c).cast(pl.Float32) for c in NUMERIC],
        )
        .to_numpy()
        .astype(np.float32, copy=False)
    )


def training_data(
    train: pl.LazyFrame, config: LightGBMConfig
) -> tuple[lgb.Dataset, dict[str, list[str]]]:
    """Binned LightGBM dataset of the most recent config.train_days of training data,
    plus the categorical vocabulary used to encode it."""
    cutoff = train.select(pl.col("date").max()).collect().item()
    # Rows where the item is not yet on sale (no price) are excluded: their sales are
    # always zero and they would only teach the model the launch date.
    rows = (
        train.filter(
            (pl.col("date") > cutoff - timedelta(days=config.train_days))
            & pl.col("sell_price").is_not_null()
        )
        .select(*FEATURES, "sales")
        .collect()
    )
    categories = {c: rows[c].unique().sort().to_list() for c in CATEGORICAL}
    x = _encode(rows, categories)
    y = rows["sales"].cast(pl.Float32).to_numpy()
    del rows
    dataset = lgb.Dataset(
        x, label=y, feature_name=FEATURES, categorical_feature=CATEGORICAL, free_raw_data=True
    ).construct()
    return dataset, categories


def booster_params(config: LightGBMConfig, **objective: object) -> dict[str, object]:
    """config.params plus the objective, and the monotone constraints if enabled."""
    params = {**config.params, **objective}
    if config.monotone:
        params["monotone_constraints"] = [MONOTONE.get(f, 0) for f in FEATURES]
        params["monotone_constraints_method"] = config.monotone_method
    return params


def train_tweedie(dataset: lgb.Dataset, config: LightGBMConfig, power: float) -> lgb.Booster:
    params = booster_params(config, objective="tweedie", tweedie_variance_power=power)
    return lgb.train(params, dataset, num_boost_round=config.num_boost_round)


def predict_point(
    booster: lgb.Booster,
    test: pl.DataFrame,
    categories: dict[str, list[str]],
    scale: QuantileScale = "raw",
) -> np.ndarray:
    """Predictions in units sold: clipped at zero, and zero for items not yet on sale.
    scale="log1p" is for models trained on log1p(sales) (see train_quantile)."""
    raw = booster.predict(_encode(test, categories))
    if scale == "log1p":
        raw = np.expm1(raw)
    return np.where(test["sell_price"].is_null().to_numpy(), 0.0, np.clip(raw, 0, None))


def quantile_name(q: float) -> str:
    return f"q{round(q * 100):02d}"


BOOSTER_NAMES = ["tweedie", *(quantile_name(q) for q in QUANTILES)]


def quantile_scale(config: LightGBMConfig) -> QuantileScale:
    return "log1p" if config.monotone else "raw"


def pinball_objective(
    alpha: float,
) -> Callable[[np.ndarray, lgb.Dataset], tuple[np.ndarray, np.ndarray]]:
    """Gradient and hessian of the pinball (quantile) loss, as a custom objective."""

    def objective(preds: np.ndarray, data: lgb.Dataset) -> tuple[np.ndarray, np.ndarray]:
        label = data.get_label()
        grad = np.where(preds >= label, 1.0 - alpha, -alpha)
        return grad, np.ones_like(preds)

    return objective


def train_quantile(dataset: lgb.Dataset, config: LightGBMConfig, q: float) -> lgb.Booster:
    """One quantile model.

    LightGBM's built-in quantile objective cannot be combined with monotone constraints
    (it re-estimates leaf values after each tree, which can break them). With
    constraints enabled, the pinball loss is used as a custom objective instead, on
    log1p(sales): without that re-estimation each round moves predictions by a bounded
    step, which suits the compact log scale, and quantiles are unchanged by the
    increasing log1p transform, so expm1 of the prediction is the quantile of sales.
    The caller must have set the dataset's label to log1p(sales).
    """
    if quantile_scale(config) == "raw":
        params = booster_params(config, objective="quantile", alpha=q)
    else:
        params = booster_params(config, objective=pinball_objective(q))
    return lgb.train(params, dataset, num_boost_round=config.num_boost_round)


def train_boosters(dataset: lgb.Dataset, config: LightGBMConfig) -> dict[str, lgb.Booster]:
    """The Tweedie point model plus one quantile model per QUANTILES level. Changes the
    dataset's label when the quantile models train on log1p(sales)."""
    boosters = {"tweedie": train_tweedie(dataset, config, config.tweedie_variance_power)}
    if quantile_scale(config) == "log1p":
        dataset.set_label(np.log1p(dataset.get_label()))
    for q in QUANTILES:
        boosters[quantile_name(q)] = train_quantile(dataset, config, q)
    return boosters


def gain_importance(boosters: dict[str, lgb.Booster]) -> pl.DataFrame:
    return pl.concat(
        pl.DataFrame(
            {
                "feature": booster.feature_name(),
                "model": name,
                "gain": booster.feature_importance(importance_type="gain"),
            }
        )
        for name, booster in boosters.items()
    )


def predict_all(
    boosters: dict[str, lgb.Booster],
    rows: pl.DataFrame,
    categories: dict[str, list[str]],
    scale: QuantileScale,
) -> tuple[np.ndarray, dict[float, np.ndarray]]:
    """Point forecast and ordered quantile forecasts for `rows`. Used by the backtest and
    by the serving API, so both score feature rows identically. `scale` is the scale the
    quantile models were trained on."""
    point = predict_point(boosters["tweedie"], rows, categories)
    lo, mid, hi = (
        predict_point(boosters[quantile_name(q)], rows, categories, scale) for q in QUANTILES
    )
    # Quantile models are trained independently and can cross; enforce order.
    lo, hi = np.minimum(lo, mid), np.maximum(hi, mid)
    return point, dict(zip(QUANTILES, (lo, mid, hi), strict=True))


def make_lightgbm_model(config: LightGBMConfig | None = None) -> ModelFn:
    config = config or LightGBMConfig()

    def fit(train: pl.LazyFrame) -> Predictor:
        dataset, categories = training_data(train, config)
        boosters = train_boosters(dataset, config)
        del dataset
        importance = gain_importance(boosters)

        def predict(test: pl.DataFrame) -> Forecast:
            point, quantiles = predict_all(boosters, test, categories, quantile_scale(config))
            return Forecast(
                point=pl.Series(point),
                quantiles={q: pl.Series(v) for q, v in quantiles.items()},
                importance=importance,
            )

        return predict

    return fit
