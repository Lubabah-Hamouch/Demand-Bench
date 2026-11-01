"""Run the models through the 5-fold backtest, save results, and compare them.

Naive and LightGBM run on all 30,490 series. Prophet runs only on the stratified
sample, so all three are also scored on that sample for a like-for-like comparison.

    python -m demandbench.backtest.compare                     # run all models, then compare
    python -m demandbench.backtest.compare --models naive      # run a subset
    python -m demandbench.backtest.compare --table-only        # compare saved results
"""

import argparse
import time
from collections.abc import Callable
from datetime import UTC, datetime

import polars as pl

from demandbench.backtest.metrics import ACTUAL, SERIES_KEYS
from demandbench.backtest.runner import (
    TABLE_CONFIG,
    BacktestResult,
    ModelFn,
    rescore,
    run_backtest,
)
from demandbench.backtest.segments import TIERS, volume_tiers
from demandbench.backtest.splitter import last_date, make_folds, scan_features
from demandbench.models import lightgbm_model, naive, prophet_model
from demandbench.models.prophet_sample import load_sample
from demandbench.paths import BACKTEST_DIR

MODELS: dict[str, tuple[str, Callable[[], ModelFn], bool]] = {
    # key: (result name, model factory, runs on sample only)
    "naive": (naive.NAME, lambda: naive.naive_model, False),
    "lightgbm": (lightgbm_model.NAME, lightgbm_model.make_lightgbm_model, False),
    "prophet": (prophet_model.NAME, lambda: prophet_model.prophet_model, True),
}
ARCHIVED = {
    # Saved results of earlier model versions, included in the comparison but not rerun.
    # name: runs on sample only
    "lightgbm_global_unconstrained": False,
}


def run(keys: list[str]) -> None:
    features = scan_features()
    folds = make_folds(last_date(features))
    sample = load_sample()

    for key in keys:
        name, factory, sample_only = MODELS[key]
        scope = "sample" if sample_only else "full"
        print(f"\n=== {name} ({scope}, {len(folds)} folds)", flush=True)
        start = time.perf_counter()
        result = run_backtest(
            factory(), name, features, folds, series_subset=sample if sample_only else None
        )
        seconds = time.perf_counter() - start
        result.save(
            BACKTEST_DIR / name,
            scope=scope,
            total_seconds=round(seconds, 1),
            n_series=int(result.folds["n_series"][0]),
            finished_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )
        print(f"{name}: {seconds:.1f}s total -> {BACKTEST_DIR / name}", flush=True)


POINT_LABELS = {"prediction": "", "q50": " [q0.5]"}
"""Point-forecast columns scored in the volume-tier breakdown. q50 is LightGBM's
median forecast, kept to show its bias next to the Tweedie point forecast."""


def load_scored(sample: pl.DataFrame) -> list[tuple[str, str, BacktestResult]]:
    """(model, scope, result) for every saved model, rescored with the current metric
    definitions: on the full dataset (unless the model only ran on the sample) and on
    the sample."""
    scored = []
    saved = [(name, sample_only) for name, _, sample_only in MODELS.values()]
    for name, sample_only in [*saved, *ARCHIVED.items()]:
        directory = BACKTEST_DIR / name
        if not directory.is_dir():
            print(f"(no saved results for {name}, skipping)")
            continue
        result = BacktestResult.load(directory)
        if not sample_only:
            scored.append((name, "full", rescore(result, name=name)))
        scored.append((name, "sample", rescore(result, sample, name)))
    return scored


def fold_table(scored: list[tuple[str, str, BacktestResult]]) -> pl.DataFrame:
    """Long table: one row per (model, scope, fold)."""
    return pl.concat(
        [
            res.folds.with_columns(pl.lit(name).alias("model"), pl.lit(scope).alias("scope"))
            for name, scope, res in scored
        ],
        how="diagonal",
    )


def tier_table(scored: list[tuple[str, str, BacktestResult]], tiers: pl.DataFrame) -> pl.DataFrame:
    """WAPE and bias per (model, scope, fold, volume tier), for each point forecast."""
    frames = []
    for name, scope, res in scored:
        preds = res.predictions.join(tiers, on=SERIES_KEYS, how="left")
        for column, suffix in POINT_LABELS.items():
            if column not in preds.columns:
                continue
            actual = pl.col(ACTUAL).cast(pl.Float64)
            frames.append(
                preds.group_by("fold", "volume_tier")
                .agg(
                    ((pl.col(column) - actual).abs().sum() / actual.sum()).alias("wape"),
                    (pl.col(column).sum() / actual.sum()).alias("bias"),
                    pl.struct(SERIES_KEYS).n_unique().alias("n_series"),
                )
                .with_columns(pl.lit(name + suffix).alias("model"), pl.lit(scope).alias("scope"))
            )
    return pl.concat(frames)


def per_fold(long: pl.DataFrame, metric: str) -> pl.DataFrame:
    wide = long.pivot(on="fold", index=["model", "scope"], values=metric, sort_columns=True)
    fold_cols = [c for c in wide.columns if c not in ("model", "scope")]
    folds = pl.concat_list([f"fold_{c}" for c in fold_cols])
    return (
        wide.rename({c: f"fold_{c}" for c in fold_cols})
        .with_columns(folds.list.mean().alias("mean"), folds.list.std().alias("std"))
        .sort("scope", "mean")
    )


def mean_std(long: pl.DataFrame, metrics: list[str], by: list[str]) -> pl.DataFrame:
    """mean +/- std across folds, formatted, one column per metric."""
    return (
        long.group_by(by, maintain_order=True)
        .agg(
            pl.format("{} ± {}", pl.col(m).mean().round(4), pl.col(m).std().round(4)).alias(m)
            for m in metrics
        )
        .sort(by)
    )


def check_sample_tiers(sample: pl.DataFrame, tiers: pl.DataFrame) -> None:
    """The sample was drawn from series ranked into volume terciles, so every one of
    them must have a ranked tier (not "new" or missing) in the full run."""
    joined = sample.join(tiers, on=SERIES_KEYS, how="left")
    unranked = joined.filter(~pl.col("volume_tier").is_in(["low", "medium", "high"])).height
    if unranked or joined["volume_tier"].null_count():
        raise ValueError(f"{unranked} sample series have no volume tier in the full run")


def table() -> None:
    features = scan_features()
    tiers = volume_tiers(features, make_folds(last_date(features))[0].cutoff)
    sample = load_sample()
    check_sample_tiers(sample, tiers)

    scored = load_scored(sample)
    long = fold_table(scored)
    by_tier = tier_table(scored, tiers)
    long.write_csv(BACKTEST_DIR / "comparison_long.csv")
    by_tier.write_csv(BACKTEST_DIR / "comparison_by_tier_long.csv")
    lgbm = long.filter(pl.col("model") == lightgbm_model.NAME)

    with pl.Config(**TABLE_CONFIG):  # type: ignore[arg-type]
        print("\nSUMMARY (mean ± std over 5 folds; bias = total forecast / total actual)")
        print(mean_std(long, ["wape", "mape", "rmse", "bias"], ["scope", "model"]))

        print("\nWAPE PER FOLD")
        t = per_fold(long, "wape")
        t.write_csv(BACKTEST_DIR / "comparison_wape.csv")
        print(t)

        if lgbm.height:
            print("\nLIGHTGBM POINT FORECAST: TWEEDIE vs q0.5 MEDIAN")
            cols = ["scope", "fold", "wape", "wape_q50", "bias", "bias_q50"]
            print(lgbm.select(cols).sort("scope", "fold"))
            print(mean_std(lgbm, ["wape", "wape_q50", "bias", "bias_q50"], ["scope"]))

            print("\nLIGHTGBM 80% INTERVAL COVERAGE (q0.1-q0.9): all rows vs days with sales")
            cols = ["scope", "fold", "interval_coverage", "interval_coverage_nonzero"]
            print(lgbm.select(cols).sort("scope", "fold"))

        n_tier = tiers.group_by("volume_tier").len().sort("volume_tier")
        counts = ", ".join(f"{t} {n:,}" for t, n in n_tier.iter_rows())
        print(f"\nWAPE BY VOLUME TIER (mean over folds; full-dataset series per tier: {counts})")
        tier_means = by_tier.group_by("scope", "model", "volume_tier").agg(
            pl.col("wape").mean(), pl.col("bias").mean()
        )
        for metric in ("wape", "bias"):
            wide = tier_means.pivot(on="volume_tier", index=["scope", "model"], values=metric)
            ordered = [t for t in TIERS if t in wide.columns]
            wide = wide.select("scope", "model", *ordered).sort("scope", "model")
            wide.write_csv(BACKTEST_DIR / f"comparison_{metric}_by_tier.csv")
            if metric == "bias":
                print("\nBIAS BY VOLUME TIER (total forecast / total actual, mean over folds)")
            print(wide)

    print("\nrun times (all 5 folds)")
    for name in [*(m[0] for m in MODELS.values()), *ARCHIVED]:
        run_json = BACKTEST_DIR / name / "run.json"
        if run_json.is_file():
            meta = pl.read_json(run_json).row(0, named=True)
            scope = f"{meta['scope']}, {meta['n_series']:,} series"
            print(f"  {name:<20} {meta['total_seconds']:>8.1f}s  ({scope})")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--models", nargs="+", choices=list(MODELS), default=list(MODELS))
    parser.add_argument("--table-only", action="store_true", help="only compare saved results")
    args = parser.parse_args()
    if not args.table_only:
        run(args.models)
    table()


if __name__ == "__main__":
    main()
