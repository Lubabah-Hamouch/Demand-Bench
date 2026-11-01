from dataclasses import replace
from datetime import date, timedelta

import polars as pl
import pytest

from demandbench.backtest.splitter import (
    Fold,
    LeakageError,
    check_folds,
    check_split,
    make_folds,
    split,
)

from .conftest import LAST

DAY = timedelta(days=1)


def test_m5_fold_boundaries() -> None:
    folds = make_folds(date(2016, 5, 22))
    assert [(f.index, f.cutoff, f.test_start, f.test_end) for f in folds] == [
        (1, date(2016, 1, 3), date(2016, 1, 4), date(2016, 1, 31)),
        (2, date(2016, 1, 31), date(2016, 2, 1), date(2016, 2, 28)),
        (3, date(2016, 2, 28), date(2016, 2, 29), date(2016, 3, 27)),
        (4, date(2016, 3, 27), date(2016, 3, 28), date(2016, 4, 24)),
        (5, date(2016, 4, 24), date(2016, 4, 25), date(2016, 5, 22)),
    ]


def test_valid_splits_pass(features: pl.LazyFrame) -> None:
    for fold in make_folds(LAST):
        train, test = split(features, fold)
        assert train.select(pl.col("date").max()).collect().item() == fold.cutoff
        assert test.select(pl.len()).collect().item() == 3 * 28


# Deliberately broken cases: each must be caught by the leakage checks.


def test_train_row_inside_test_window_is_caught(features: pl.LazyFrame) -> None:
    fold = make_folds(LAST)[-1]
    leaky_train = features.filter(pl.col("date") <= fold.cutoff + 3 * DAY)
    test = features.filter(pl.col("date").is_between(fold.test_start, fold.test_end))
    with pytest.raises(LeakageError, match="inside or after the test window"):
        check_split(leaky_train, test, fold)


def test_single_leaked_row_after_test_window_is_caught(features: pl.LazyFrame) -> None:
    fold = make_folds(LAST)[0]
    train = features.filter(pl.col("date") <= fold.cutoff)
    future_row = features.filter(pl.col("date") == LAST).head(1)
    test = features.filter(pl.col("date").is_between(fold.test_start, fold.test_end))
    with pytest.raises(LeakageError, match="inside or after the test window"):
        check_split(pl.concat([train, future_row]), test, fold)


def test_test_window_missing_a_day_is_caught(features: pl.LazyFrame) -> None:
    fold = make_folds(LAST)[-1]
    train = features.filter(pl.col("date") <= fold.cutoff)
    short_test = features.filter(
        pl.col("date").is_between(fold.test_start, fold.test_end)
        & (pl.col("date") != fold.test_start + 10 * DAY)
    )
    with pytest.raises(LeakageError, match="cover 27 days"):
        check_split(train, short_test, fold)


def test_test_rows_outside_window_are_caught(features: pl.LazyFrame) -> None:
    fold = make_folds(LAST)[-1]
    train = features.filter(pl.col("date") <= fold.cutoff)
    shifted_test = features.filter(
        pl.col("date").is_between(fold.test_start - DAY, fold.test_end - DAY)
    )
    with pytest.raises(LeakageError, match="test rows span"):
        check_split(train, shifted_test, fold)


def test_test_window_longer_than_28_days_is_caught() -> None:
    fold = Fold(1, date(2016, 1, 3), date(2016, 1, 4), date(2016, 2, 1))
    with pytest.raises(LeakageError, match="not exactly 28 days"):
        check_folds([fold])


def test_gap_between_cutoff_and_test_window_is_caught() -> None:
    fold = make_folds(date(2016, 5, 22))[-1]
    with pytest.raises(LeakageError, match="does not start the day after the cutoff"):
        check_folds([replace(fold, cutoff=fold.cutoff - DAY)])


def test_overlapping_test_windows_are_caught() -> None:
    first, second = make_folds(date(2016, 5, 22), n_folds=2)
    overlapping = replace(
        second,
        cutoff=second.cutoff - DAY,
        test_start=second.test_start - DAY,
        test_end=second.test_end - DAY,
    )
    with pytest.raises(LeakageError, match="not sequential and non-overlapping"):
        check_folds([first, overlapping])


def test_test_window_longer_than_feature_horizon_is_rejected() -> None:
    with pytest.raises(LeakageError, match="exceeds the feature horizon"):
        make_folds(date(2016, 5, 22), test_days=35)
