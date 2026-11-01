"""Stratified sample of series for the Prophet benchmark.

Prophet fits one model per series, which is too slow for all 30,490 series x 5 folds.
The sample is stratified by cat_id x state_id x volume tercile so it spans the range of
series (slow movers as well as big sellers), and it is saved so every fold and every
rerun uses the same series. Only the series keys (item_id, store_id) are saved, no
sales figures, because the CSV is committed and the M5 data is not.
"""

import argparse
from datetime import date
from pathlib import Path

import polars as pl

from demandbench.backtest.metrics import SERIES_KEYS
from demandbench.backtest.segments import eligible_series
from demandbench.backtest.splitter import last_date, make_folds, scan_features

SAMPLE_PATH = Path(__file__).with_name("prophet_sample.csv")
SAMPLE_SIZE = 200
SEED = 20160103
STRATA = ["cat_id", "state_id", "volume_tercile"]


def allocate(sizes: pl.DataFrame, total: int) -> pl.DataFrame:
    """Proportional allocation per stratum (largest remainder), at least one each."""
    n = sizes["n"].sum()
    exact = sizes["n"] * total / n
    alloc = sizes.with_columns(exact.floor().cast(pl.Int64).clip(lower_bound=1).alias("take"))
    remaining = int(total - alloc["take"].sum())
    order = (exact - exact.floor()).arg_sort(descending=True).to_list()
    takes = alloc["take"].to_list()
    for i in order[: max(remaining, 0)]:
        takes[i] += 1
    return alloc.with_columns(pl.Series("take", takes))


def select_sample(features: pl.LazyFrame, as_of: date, size: int = SAMPLE_SIZE) -> pl.DataFrame:
    candidates = eligible_series(features, as_of)
    strata = allocate(candidates.group_by(STRATA).len("n").sort(STRATA), size)
    parts = [
        candidates.filter(
            (pl.col("cat_id") == row["cat_id"])
            & (pl.col("state_id") == row["state_id"])
            & (pl.col("volume_tercile") == row["volume_tercile"])
        ).sample(row["take"], seed=SEED)
        for row in strata.iter_rows(named=True)
    ]
    return pl.concat(parts).sort("store_id", "item_id")


def load_sample(path: Path = SAMPLE_PATH) -> pl.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"{path} not found. Run demandbench.models.prophet_sample first.")
    return pl.read_csv(path).select(SERIES_KEYS)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="overwrite an existing sample")
    args = parser.parse_args()
    if SAMPLE_PATH.exists() and not args.force:
        print(f"{SAMPLE_PATH.name} already exists, use --force to resample")
        return

    features = scan_features()
    # Volume terciles use only data up to the earliest fold's cutoff, so selecting the
    # sample never looks at any fold's test window.
    as_of = make_folds(last_date(features))[0].cutoff
    sample = select_sample(features, as_of)
    sample.select(SERIES_KEYS).write_csv(SAMPLE_PATH)
    print(f"wrote {sample.height} series to {SAMPLE_PATH} (volume terciles as of {as_of})")
    with pl.Config(tbl_formatting="ASCII_MARKDOWN", tbl_rows=-1, tbl_hide_column_data_types=True):
        print(sample.group_by(STRATA).len().sort(STRATA))


if __name__ == "__main__":
    main()
