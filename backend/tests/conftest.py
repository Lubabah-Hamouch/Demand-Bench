from datetime import date, timedelta

import polars as pl
import pytest

N_DAYS = 200
START = date(2020, 1, 1)
LAST = START + timedelta(days=N_DAYS - 1)


@pytest.fixture
def features() -> pl.LazyFrame:
    """Three gap-free daily series shaped like features_model_ready (minimal columns)."""
    dates = pl.date_range(START, LAST, eager=True)
    frames = [
        pl.DataFrame(
            {
                "item_id": item,
                "store_id": "S_1",
                "date": dates,
                "sales": [(i * mult) % 5 for i in range(N_DAYS)],
            }
        )
        for item, mult in (("A", 1), ("B", 3), ("C", 0))
    ]
    return (
        pl.concat(frames)
        .with_columns(pl.col("sales").shift(28).over("item_id", "store_id").alias("lag_28"))
        .lazy()
    )
