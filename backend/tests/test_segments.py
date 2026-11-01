from datetime import date

import polars as pl

from demandbench.backtest.segments import volume_tiers


def test_volume_tiers_rank_within_cell_and_mark_new_series() -> None:
    dates = pl.date_range(date(2020, 1, 1), date(2020, 6, 30), eager=True)
    n = len(dates)
    rows = []
    for item, daily, launched in [("A", 1, True), ("B", 2, True), ("C", 3, True), ("N", 9, False)]:
        rows.append(
            pl.DataFrame(
                {
                    "item_id": item,
                    "store_id": "S_1",
                    "cat_id": "FOODS",
                    "state_id": "CA",
                    "date": dates,
                    "sales": [daily] * n,
                    # N only goes on sale 30 days before the as-of date.
                    "sell_price": [1.0] * n if launched else [None] * (n - 30) + [1.0] * 30,
                }
            )
        )
    tiers = volume_tiers(pl.concat(rows).lazy(), date(2020, 6, 30))
    assert dict(tiers.select("item_id", "volume_tier").iter_rows()) == {
        "A": "low",
        "B": "medium",
        "C": "high",
        "N": "new",
    }
