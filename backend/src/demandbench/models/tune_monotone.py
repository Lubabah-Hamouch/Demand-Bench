"""Compare monotone-constraint methods for the Tweedie point model, without touching any
test window: same validation split as tune_tweedie (the last 28 days of fold 1's
training data)."""

import time
from dataclasses import replace
from datetime import timedelta

import polars as pl

from demandbench.backtest.metrics import ACTUAL
from demandbench.backtest.splitter import (
    TEST_DAYS,
    Fold,
    last_date,
    make_folds,
    scan_features,
    split,
)
from demandbench.models.lightgbm_model import (
    LightGBMConfig,
    predict_point,
    train_tweedie,
    training_data,
)
from demandbench.paths import BACKTEST_DIR

VARIANTS = {"unconstrained": None, "basic": "basic", "intermediate": "intermediate"}
OUTPUT = BACKTEST_DIR / "monotone_tuning.csv"


def main() -> None:
    features = scan_features()
    first = make_folds(last_date(features))[0]
    validation = Fold(
        index=0,
        cutoff=first.cutoff - timedelta(days=TEST_DAYS),
        test_start=first.cutoff - timedelta(days=TEST_DAYS - 1),
        test_end=first.cutoff,
    )
    print(f"comparing on {validation} (inside fold 1's training data)", flush=True)

    train, valid_lf = split(features, validation)
    valid = valid_lf.collect()
    base = LightGBMConfig()
    dataset, categories = training_data(train, base)
    actual = valid[ACTUAL].cast(pl.Float64).to_numpy()

    rows = []
    for name, method in VARIANTS.items():
        config = replace(base, monotone=method is not None, monotone_method=method or "basic")
        start = time.perf_counter()
        booster = train_tweedie(dataset, config, config.tweedie_variance_power)
        pred = predict_point(booster, valid, categories)
        rows.append(
            {
                "variant": name,
                "wape": float(abs(pred - actual).sum()) / float(actual.sum()),
                "bias": float(pred.sum()) / float(actual.sum()),
                "seconds": round(time.perf_counter() - start, 1),
            }
        )
        print(rows[-1], flush=True)

    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_csv(OUTPUT)
    print(f"-> {OUTPUT}")


if __name__ == "__main__":
    main()
