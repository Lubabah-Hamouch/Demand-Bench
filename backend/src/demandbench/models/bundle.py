"""The production model bundle: trained boosters plus everything needed to serve them.

A bundle directory holds:

- {tweedie,q10,q50,q90}.txt   LightGBM boosters (text format)
- metadata.json               feature order, categorical vocabulary, training window,
                              hyperparameters
- importance.csv              gain-based feature importance for every booster
- series.parquet              one row per series, with metadata for the API's picker
- forecast_features.parquet   feature rows for the HORIZON days after training ends
- daily_recent.parquet        features_daily rows (calendar, prices, sales) for the
                              recent history plus the forecast days, used to recompute
                              price-derived features for what-if scenarios
- sales_history.parquet       daily sales for the history endpoint
- backtest_series.parquet     optional: per-fold, per-series results of the saved
                              backtest (actual and forecast units, absolute error), so
                              the API can report how the model did on each series

daily_recent and sales_history are read per request, one series at a time (they are
sorted by store_id, item_id, date, so a series' rows are adjacent); everything else is
loaded into memory.
"""

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import lightgbm as lgb
import polars as pl

from demandbench.models.lightgbm_model import BOOSTER_NAMES, QuantileScale

DATA_FILES = ["daily_recent.parquet", "sales_history.parquet"]
BACKTEST_FILE = "backtest_series.parquet"


@dataclass(frozen=True)
class ModelBundle:
    boosters: dict[str, lgb.Booster]
    metadata: dict[str, Any]
    importance: pl.DataFrame
    series: pl.DataFrame
    forecast_features: pl.DataFrame
    daily_recent: pl.DataFrame | None = field(default=None, repr=False)
    """Only set when building a bundle to save; a loaded bundle scans the file instead."""
    sales_history: pl.DataFrame | None = field(default=None, repr=False)
    """Only set when building a bundle to save; a loaded bundle scans the file instead."""
    backtest: pl.DataFrame | None = field(default=None, repr=False)
    """Per-fold, per-series backtest results, or None if the bundle has none."""
    directory: Path | None = None

    @property
    def categories(self) -> dict[str, list[str]]:
        return dict(self.metadata["categories"])

    @property
    def quantile_scale(self) -> QuantileScale:
        """Scale the quantile models predict on; bundles from before monotone
        constraints were added used raw sales."""
        scale: QuantileScale = self.metadata.get("quantile_scale", "raw")
        return scale

    @property
    def trained_through(self) -> date:
        return date.fromisoformat(self.metadata["train_end"])

    def _scan(self, name: str, item_id: str, store_id: str) -> pl.DataFrame:
        if self.directory is None:
            raise ValueError("bundle was not loaded from disk")
        return (
            pl.scan_parquet(self.directory / name)
            .filter((pl.col("store_id") == store_id) & (pl.col("item_id") == item_id))
            .collect()
            .sort("date")
        )

    def read_daily_recent(self, item_id: str, store_id: str) -> pl.DataFrame:
        return self._scan("daily_recent.parquet", item_id, store_id)

    def read_sales_history(self, item_id: str, store_id: str) -> pl.DataFrame:
        return self._scan("sales_history.parquet", item_id, store_id)

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        for name, booster in self.boosters.items():
            booster.save_model(str(directory / f"{name}.txt"))
        (directory / "metadata.json").write_text(json.dumps(self.metadata, indent=2))
        self.importance.write_csv(directory / "importance.csv")
        self.series.write_parquet(directory / "series.parquet")
        self.forecast_features.write_parquet(directory / "forecast_features.parquet")
        self.save_data_files(directory)

    def save_data_files(self, directory: Path) -> None:
        if self.daily_recent is None or self.sales_history is None:
            raise ValueError("daily_recent and sales_history are required to save a bundle")
        # Small row groups keep per-series reads cheap: Parquet statistics let a scan
        # skip every row group that cannot contain the requested series.
        self.daily_recent.write_parquet(directory / "daily_recent.parquet", row_group_size=50_000)
        self.sales_history.write_parquet(directory / "sales_history.parquet", row_group_size=50_000)
        if self.backtest is not None:
            self.backtest.write_parquet(directory / BACKTEST_FILE)

    @classmethod
    def load(cls, directory: Path, require_data_files: bool = True) -> "ModelBundle":
        required = [
            *(f"{n}.txt" for n in BOOSTER_NAMES),
            "metadata.json",
            "importance.csv",
            "series.parquet",
            "forecast_features.parquet",
            *(DATA_FILES if require_data_files else []),
        ]
        missing = [f for f in required if not (directory / f).is_file()]
        if missing:
            raise FileNotFoundError(
                f"model bundle at {directory} is incomplete (missing {', '.join(missing)}). "
                "Run demandbench.models.train_final first."
            )
        metadata = json.loads((directory / "metadata.json").read_text())
        boosters = {n: lgb.Booster(model_file=str(directory / f"{n}.txt")) for n in BOOSTER_NAMES}
        for name, booster in boosters.items():
            if booster.feature_name() != metadata["features"]:
                raise ValueError(f"{name} booster features do not match metadata.json")
        return cls(
            boosters=boosters,
            metadata=metadata,
            importance=pl.read_csv(directory / "importance.csv"),
            series=pl.read_parquet(directory / "series.parquet"),
            forecast_features=pl.read_parquet(directory / "forecast_features.parquet"),
            backtest=(
                pl.read_parquet(directory / BACKTEST_FILE)
                if (directory / BACKTEST_FILE).is_file()
                else None
            ),
            directory=directory,
        )
