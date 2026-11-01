"""Choose the LightGBM Tweedie variance power without touching any test window.

Fold 1's training data (everything up to the earliest cutoff) is split again: the last
28 days become a validation window and the rest is used for training. Each candidate
power is scored on that window by WAPE; total-sales bias is reported alongside.
"""

import time
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

POWERS = (1.1, 1.2, 1.3, 1.4, 1.5)
OUTPUT = BACKTEST_DIR / "tweedie_tuning.csv"


def main() -> None:
    features = scan_features()
    first = make_folds(last_date(features))[0]
    validation = Fold(
        index=0,
        cutoff=first.cutoff - timedelta(days=TEST_DAYS),
        test_start=first.cutoff - timedelta(days=TEST_DAYS - 1),
        test_end=first.cutoff,
    )
    print(f"tuning on {validation} (inside fold 1's training data)")

    train, valid_lf = split(features, validation)
    valid = valid_lf.collect()
    config = LightGBMConfig()
    dataset, categories = training_data(train, config)

    rows = []
    actual = valid[ACTUAL].cast(pl.Float64).to_numpy()
    for power in POWERS:
        start = time.perf_counter()
        pred = predict_point(train_tweedie(dataset, config, power), valid, categories)
        rows.append(
            {
                "tweedie_variance_power": power,
                "wape": float(abs(pred - actual).sum()) / float(actual.sum()),
                "bias": float(pred.sum()) / float(actual.sum()),
                "seconds": round(time.perf_counter() - start, 1),
            }
        )
        print(rows[-1], flush=True)

    results = pl.DataFrame(rows)
    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    results.write_csv(OUTPUT)
    best = results.sort("wape").row(0, named=True)
    print(f"\nbest power {best['tweedie_variance_power']} (WAPE {best['wape']:.4f}) -> {OUTPUT}")


if __name__ == "__main__":
    main()
