"""Rolling-origin folds over features_model_ready, with explicit leakage checks."""

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import polars as pl

from demandbench.features.build_features import HORIZON
from demandbench.paths import FEATURES_PARQUET

N_FOLDS = 5
TEST_DAYS = 28
SERIES_KEYS = ["item_id", "store_id"]
ONE_DAY = timedelta(days=1)


class LeakageError(Exception):
    """A fold's train/test split could let information from the test window leak."""


@dataclass(frozen=True)
class Fold:
    index: int
    cutoff: date
    test_start: date
    test_end: date

    def __str__(self) -> str:
        return (
            f"fold {self.index}: train <= {self.cutoff}, test {self.test_start} -> {self.test_end}"
        )


def make_folds(last_date: date, n_folds: int = N_FOLDS, test_days: int = TEST_DAYS) -> list[Fold]:
    """Sequential, non-overlapping test windows ending at last_date.

    Fold n_folds tests the final test_days days, fold n_folds-1 the test_days before
    that, and so on. Each fold trains on everything up to the day before its test window.
    """
    if test_days > HORIZON:
        raise LeakageError(
            f"test window of {test_days} days exceeds the feature horizon of {HORIZON} days: "
            f"lag/rolling features for later test days would use sales inside the window"
        )

    folds = []
    for k in range(n_folds):
        test_end = last_date - timedelta(days=k * test_days)
        test_start = test_end - timedelta(days=test_days - 1)
        folds.append(Fold(n_folds - k, test_start - ONE_DAY, test_start, test_end))
    folds.sort(key=lambda f: f.index)
    check_folds(folds, test_days)
    return folds


def check_folds(folds: list[Fold], test_days: int = TEST_DAYS) -> None:
    """Fold definitions must be well-formed, sequential and non-overlapping."""
    for fold in folds:
        if fold.test_start != fold.cutoff + ONE_DAY:
            raise LeakageError(f"{fold}: test window does not start the day after the cutoff")
        if (fold.test_end - fold.test_start).days + 1 != test_days:
            raise LeakageError(f"{fold}: test window is not exactly {test_days} days")
    for earlier, later in zip(folds, folds[1:], strict=False):
        if later.test_start != earlier.test_end + ONE_DAY:
            raise LeakageError(
                f"test windows are not sequential and non-overlapping: {earlier} / {later}"
            )


def check_split(
    train: pl.LazyFrame, test: pl.LazyFrame, fold: Fold, test_days: int = TEST_DAYS
) -> None:
    """Verify an actual train/test split against its fold, from the data itself.

    Raises LeakageError if any training row has a target date inside or after the test
    window, or if the test rows do not cover exactly test_days consecutive days, every
    series, and nothing else.
    """
    check_folds([fold], test_days)

    train_max = train.select(pl.col("date").max()).collect().item()
    if train_max is not None and train_max >= fold.test_start:
        raise LeakageError(
            f"{fold}: training data contains target date {train_max}, "
            f"inside or after the test window"
        )

    stats = (
        test.select(
            pl.col("date").min().alias("first"),
            pl.col("date").max().alias("last"),
            pl.col("date").n_unique().alias("n_dates"),
            pl.struct(SERIES_KEYS).n_unique().alias("n_series"),
            pl.len().alias("n_rows"),
        )
        .collect()
        .row(0, named=True)
    )

    if (stats["first"], stats["last"]) != (fold.test_start, fold.test_end):
        raise LeakageError(
            f"{fold}: test rows span {stats['first']} -> {stats['last']}, "
            f"expected {fold.test_start} -> {fold.test_end}"
        )
    if stats["n_dates"] != test_days:
        raise LeakageError(f"{fold}: test rows cover {stats['n_dates']} days, expected {test_days}")
    if stats["n_rows"] != stats["n_series"] * test_days:
        raise LeakageError(
            f"{fold}: {stats['n_rows']:,} test rows for {stats['n_series']:,} series, "
            f"expected one row per series per day"
        )


def split(features: pl.LazyFrame, fold: Fold) -> tuple[pl.LazyFrame, pl.LazyFrame]:
    train = features.filter(pl.col("date") <= fold.cutoff)
    test = features.filter(pl.col("date").is_between(fold.test_start, fold.test_end))
    check_split(train, test, fold)
    return train, test


def scan_features(path: Path = FEATURES_PARQUET) -> pl.LazyFrame:
    if not path.is_file():
        raise FileNotFoundError(f"{path} not found. Run demandbench.features.build_features first.")
    return pl.scan_parquet(path)


def last_date(features: pl.LazyFrame) -> date:
    value = features.select(pl.col("date").max()).collect().item()
    assert isinstance(value, date)
    return value
