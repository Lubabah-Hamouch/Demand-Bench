from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import polars as pl
import pytest
from fastapi.testclient import TestClient

from demandbench.features.build_features import model_ready_sql
from demandbench.models.bundle import ModelBundle
from demandbench.models.lightgbm_model import (
    CATEGORICAL,
    FEATURES,
    QUANTILES,
    LightGBMConfig,
    gain_importance,
    train_boosters,
    training_data,
)
from demandbench.paths import ARTIFACTS_DIR
from demandbench.serving.app import create_app

HORIZON = 28
TRAIN_END = date(2020, 3, 1)
HISTORY_DAYS = 300
SERIES = [("A_1", "S_1", 5.0), ("B_2", "S_1", 1.0), ("A_1", "S_2", 3.0)]
SPIKE = ("A_1", "S_1", TRAIN_END - timedelta(days=10), 80)
"""An injected anomaly: series, date, units sold (about 5 a day normally)."""
FOLD_WINDOWS = [(1, date(2020, 1, 1), date(2020, 1, 28)), (2, date(2020, 1, 29), date(2020, 2, 25))]
BACKTEST = pl.DataFrame(
    [
        # A_1/S_1: fold 1 sold 100, forecast 80 (abs error 30); fold 2 sold 50, forecast 70.
        ("A_1", "S_1", *FOLD_WINDOWS[0], 100.0, 80.0, 30.0),
        ("A_1", "S_1", *FOLD_WINDOWS[1], 50.0, 70.0, 25.0),
        # B_2/S_1 sold nothing in either window.
        ("B_2", "S_1", *FOLD_WINDOWS[0], 0.0, 3.0, 3.0),
        ("B_2", "S_1", *FOLD_WINDOWS[1], 0.0, 2.0, 2.0),
        # A_1/S_2 is deliberately absent.
    ],
    schema=[
        "item_id",
        "store_id",
        "fold",
        "test_start",
        "test_end",
        "actual_units",
        "forecast_units",
        "abs_error",
    ],
    orient="row",
)


def daily_rows(item: str, store: str, level: float, rng: np.random.Generator) -> pl.DataFrame:
    """features_daily-shaped rows: HISTORY_DAYS observed days, then HORIZON future days
    with sales null. The price steps down every few weeks, so the promo flag (price
    below its trailing median) is set on some days."""
    start = TRAIN_END - timedelta(days=HISTORY_DAYS - 1)
    dates = [start + timedelta(days=i) for i in range(HISTORY_DAYS + HORIZON)]
    n = len(dates)
    sales: list[int | None] = [int(v) for v in rng.poisson(level, HISTORY_DAYS)]
    sales += [None] * HORIZON
    if (item, store) == SPIKE[:2]:
        sales[dates.index(SPIKE[2])] = SPIKE[3]
    no_event = pl.Series([None] * n, dtype=pl.String)
    return pl.DataFrame(
        {
            "id": f"{item}_{store}_evaluation",
            "item_id": item,
            "dept_id": item[0],
            "cat_id": "FOODS",
            "store_id": store,
            "state_id": "CA",
            "d": [f"d_{i + 1}" for i in range(n)],
            "date": dates,
            "sales": pl.Series(sales, dtype=pl.Int16),
            "wm_yr_wk": [11100 + i // 7 for i in range(n)],
            "wday": [d.isoweekday() % 7 + 1 for d in dates],
            "month": [d.month for d in dates],
            "year": [d.year for d in dates],
            "event_name_1": no_event,
            "event_type_1": no_event,
            "event_name_2": no_event,
            "event_type_2": no_event,
            "snap": [d.day <= 10 for d in dates],
            "sell_price": [2.0 if (i // 21) % 4 == 3 else 2.5 for i in range(n)],
        }
    )


def model_ready(daily: pl.DataFrame) -> pl.DataFrame:
    """Run the production feature SQL over synthetic daily rows."""
    with duckdb.connect() as con:
        con.register("daily", daily)
        return pl.concat(
            con.sql(model_ready_sql("daily"), params={"store_id": store}).pl()
            for store in daily["store_id"].unique().sort()
        )


@pytest.fixture(scope="module")
def bundle_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A small but real model bundle whose features come from the production SQL.

    The boosters are a stand-in: in their training rows has_promo is randomised and
    quadruples sales, so the tests can check that a promo override reaches the model.
    """
    rng = np.random.default_rng(0)
    daily = pl.concat(daily_rows(i, s, lvl, rng) for i, s, lvl in SERIES)
    features = model_ready(daily)

    observed = features.filter(pl.col("date") <= TRAIN_END)
    promo = rng.random(observed.height) < 0.3
    level = observed["roll_mean_28_h28"].fill_null(2.0).to_numpy() + 1
    train_rows = observed.with_columns(
        pl.Series("has_promo", promo),
        pl.Series("sales", rng.poisson(level * np.where(promo, 4.0, 1.0)), dtype=pl.Int16),
    )
    config = LightGBMConfig(
        train_days=HISTORY_DAYS,
        num_boost_round=60,
        params={
            "learning_rate": 0.2,
            "num_leaves": 8,
            "min_data_in_leaf": 20,
            "num_threads": 1,
            "verbose": -1,
        },
    )
    dataset, categories = training_data(train_rows.lazy(), config)
    boosters = train_boosters(dataset, config)

    history = daily.filter(pl.col("date") <= TRAIN_END)
    series = (
        history.group_by("item_id", "store_id", "dept_id", "cat_id", "state_id")
        .agg(pl.col("sales").cast(pl.Int64).sum().alias("total_sales"))
        .with_columns(
            pl.col("total_sales").alias("sales_last_28d"),
            pl.lit(history["date"].min()).alias("on_sale_since"),
            pl.when(pl.col("total_sales") > 1000)
            .then(pl.lit("high"))
            .otherwise(pl.lit("low"))
            .alias("volume_tier"),
        )
    )
    forecast_cols = ["item_id", "store_id", "date"] + [
        c for c in FEATURES if c not in ("item_id", "store_id")
    ]
    bundle = ModelBundle(
        boosters=boosters,
        metadata={
            "model": "lightgbm_global",
            "created_at": "2020-03-02T00:00:00+00:00",
            "train_start": (TRAIN_END - timedelta(days=HISTORY_DAYS - 1)).isoformat(),
            "train_end": TRAIN_END.isoformat(),
            "train_rows": dataset.num_data(),
            "horizon_days": HORIZON,
            "features": FEATURES,
            "categorical_features": CATEGORICAL,
            "categories": categories,
            "point_model": "tweedie",
            "tweedie_variance_power": 1.5,
            "quantiles": list(QUANTILES),
            "quantile_scale": "log1p",
        },
        importance=gain_importance(boosters),
        series=series,
        forecast_features=features.filter(pl.col("date") > TRAIN_END)
        .select(forecast_cols)
        .sort("store_id", "item_id", "date"),
        daily_recent=daily.filter(pl.col("date") > TRAIN_END - timedelta(days=120)).sort(
            "store_id", "item_id", "date"
        ),
        sales_history=history.select("item_id", "store_id", "date", "sales").sort(
            "store_id", "item_id", "date"
        ),
        backtest=BACKTEST,
    )
    directory = tmp_path_factory.mktemp("bundle")
    bundle.save(directory)
    return directory


@pytest.fixture(scope="module")
def client(bundle_dir: Path) -> Iterator[TestClient]:
    with TestClient(create_app(bundle_dir)) as c:
        yield c


def total(body: dict[str, Any]) -> float:
    return float(sum(p["forecast"] for p in body["points"]))


def test_health(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["trained_through"] == "2020-03-01"
    assert body["forecast_start"] == "2020-03-02"
    assert body["n_series"] == 3


def test_forecast_returns_28_days_with_ordered_interval(client: TestClient) -> None:
    response = client.get("/forecast/A_1/S_1")
    assert response.status_code == 200
    body = response.json()
    assert (body["item_id"], body["store_id"], body["cat_id"]) == ("A_1", "S_1", "FOODS")
    assert len(body["points"]) == HORIZON
    assert body["points"][0]["date"] == "2020-03-02"
    assert body["sell_price"] == pytest.approx(2.5)
    assert body["sales_last_28d"] > 0
    assert body["points"][-1]["date"] == "2020-03-29"
    for point in body["points"]:
        assert point["forecast"] >= 0
        assert 0 <= point["lower"] <= point["upper"]


def test_unknown_item_returns_404(client: TestClient) -> None:
    response = client.get("/forecast/B_2/S_2")
    assert response.status_code == 404
    assert "not sold at store 'S_2'" in response.json()["detail"]


def test_unknown_store_returns_404(client: TestClient) -> None:
    response = client.get("/forecast/A_1/NOPE")
    assert response.status_code == 404
    assert "unknown store_id 'NOPE'" in response.json()["detail"]


def test_importance_is_global_and_sums_to_one(client: TestClient) -> None:
    body = client.get("/model/importance").json()
    assert body["model"] == "tweedie"
    assert {f["feature"] for f in body["features"]} == set(FEATURES)
    assert sum(f["share"] for f in body["features"]) == pytest.approx(1.0)


def test_series_filters_and_paging(client: TestClient) -> None:
    body = client.get("/series", params={"store_id": "S_1"}).json()
    assert body["total"] == 2
    assert [s["item_id"] for s in body["items"]] == ["A_1", "B_2"]  # sorted by volume

    body = client.get("/series", params={"q": "b_", "limit": 1}).json()
    assert body["total"] == 1 and body["items"][0]["item_id"] == "B_2"

    assert client.get("/series", params={"limit": 0}).status_code == 422


def test_whatif_promo_on_vs_off_changes_forecast(client: TestClient) -> None:
    on = client.post("/forecast/A_1/S_1/whatif", json={"has_promo": True})
    off = client.post("/forecast/A_1/S_1/whatif", json={"has_promo": False})
    assert on.status_code == off.status_code == 200
    assert len(on.json()["points"]) == HORIZON
    assert on.json()["scenario"] == {"has_promo": True, "sell_price": None}
    repriced = client.post("/forecast/A_1/S_1/whatif", json={"sell_price": 1.75}).json()
    assert repriced["sell_price"] == pytest.approx(1.75)
    # The stand-in model learned that promo quadruples sales, so the difference should be
    # large, far beyond rounding noise.
    assert total(on.json()) > 1.5 * total(off.json())


def test_whatif_requires_an_override(client: TestClient) -> None:
    response = client.post("/forecast/A_1/S_1/whatif", json={})
    assert response.status_code == 422
    assert "at least one override" in response.text


@pytest.mark.parametrize("price", [0, -1.5])
def test_whatif_rejects_non_positive_price(client: TestClient, price: float) -> None:
    assert client.post("/forecast/A_1/S_1/whatif", json={"sell_price": price}).status_code == 422


def test_whatif_unknown_series_returns_404(client: TestClient) -> None:
    assert client.post("/forecast/B_2/S_2/whatif", json={"has_promo": True}).status_code == 404


def test_history_returns_requested_days_and_flags_injected_spike(client: TestClient) -> None:
    item, store, spike_date, units = SPIKE
    body = client.get(f"/series/{item}/{store}/history", params={"days": 60}).json()
    assert body["days"] == len(body["points"]) == 60
    assert body["end"] == TRAIN_END.isoformat()
    flagged = {p["date"]: p for p in body["points"] if p["anomaly"]}
    assert spike_date.isoformat() in flagged
    spike = flagged[spike_date.isoformat()]
    assert spike["sales"] == units and spike["z_score"] > 3
    # Ordinary Poisson noise around a mean of 5 should rarely cross 3 standard deviations.
    assert len(flagged) <= 3


def test_history_default_and_limits(client: TestClient) -> None:
    assert client.get("/series/A_1/S_1/history").json()["days"] == 180
    assert client.get("/series/A_1/S_1/history", params={"days": 731}).status_code == 422
    assert client.get("/series/A_1/NOPE/history").status_code == 404


@pytest.mark.skipif(not (ARTIFACTS_DIR / "metadata.json").is_file(), reason="no trained bundle")
def test_real_bundle_endpoints() -> None:
    with TestClient(create_app(ARTIFACTS_DIR)) as c:
        base = c.get("/forecast/FOODS_3_090/CA_1").json()
        assert len(base["points"]) == HORIZON
        assert c.get("/series").json()["total"] == 30_490
        # Re-pricing at the current price recomputes the same features: same forecast.
        price = 1.6
        same = c.post("/forecast/FOODS_3_090/CA_1/whatif", json={"sell_price": price}).json()
        assert [p["forecast"] for p in same["points"]] == [p["forecast"] for p in base["points"]]
        history = c.get("/series/FOODS_3_090/CA_1/history", params={"days": 730}).json()
        assert history["days"] == 730


def whatif_points(client: TestClient, path: str, body: dict[str, Any]) -> list[dict[str, Any]]:
    response = client.post(f"/forecast/{path}/whatif", json=body)
    assert response.status_code == 200
    points: list[dict[str, Any]] = response.json()["points"]
    return points


@pytest.mark.parametrize("series", ["A_1/S_1", "A_1/S_2"])
def test_whatif_price_direction_is_monotone(client: TestClient, series: str) -> None:
    """Raising the price never raises any day's forecast or bounds (monotone constraints)."""
    by_price = [whatif_points(client, series, {"sell_price": p}) for p in (1.6, 2.5, 3.4)]
    for cheaper, dearer in zip(by_price, by_price[1:], strict=False):
        for a, b in zip(cheaper, dearer, strict=True):
            for field in ("forecast", "lower", "upper"):
                assert b[field] <= a[field], (series, a["date"], field)
    assert sum(p["forecast"] for p in by_price[0]) >= sum(p["forecast"] for p in by_price[-1])


def test_whatif_promo_on_never_below_off(client: TestClient) -> None:
    on = whatif_points(client, "A_1/S_1", {"has_promo": True})
    off = whatif_points(client, "A_1/S_1", {"has_promo": False})
    assert all(a["forecast"] >= b["forecast"] for a, b in zip(on, off, strict=True))


@pytest.mark.skipif(not (ARTIFACTS_DIR / "metadata.json").is_file(), reason="no trained bundle")
@pytest.mark.parametrize("series", ["FOODS_3_090/CA_1", "HOBBIES_2_039/WI_2"])
def test_real_bundle_price_direction(series: str) -> None:
    with TestClient(create_app(ARTIFACTS_DIR)) as c:
        base = c.get(f"/forecast/{series}").json()
        totals = []
        current = _current_price(series)
        for factor in (0.8, 1.0, 1.2):
            points = whatif_points(c, series, {"sell_price": round(current * factor, 2)})
            totals.append(sum(p["forecast"] for p in points))
        assert totals[0] >= totals[1] >= totals[2]
        assert totals[1] == pytest.approx(sum(p["forecast"] for p in base["points"]), rel=1e-6)


def _current_price(series: str) -> float:
    item_id, store_id = series.split("/")
    rows = ModelBundle.load(ARTIFACTS_DIR).forecast_features.filter(
        (pl.col("item_id") == item_id) & (pl.col("store_id") == store_id)
    )
    return float(rows["sell_price"][0])


def test_series_backtest_pools_folds(client: TestClient) -> None:
    body = client.get("/series/A_1/S_1/backtest").json()
    assert body["available"] is True and body["reason"] is None
    assert body["n_folds"] == 2
    assert (body["window_start"], body["window_end"]) == ("2020-01-01", "2020-02-25")
    assert body["wape"] == pytest.approx((30 + 25) / 150)
    assert body["bias"] == pytest.approx(150 / 150)
    assert [f["wape"] for f in body["folds"]] == pytest.approx([0.3, 0.5])
    assert [f["bias"] for f in body["folds"]] == pytest.approx([0.8, 1.4])
    # Overall figures pool every series' rows, including the zero-sales one.
    assert body["overall_wape"] == pytest.approx((30 + 25 + 3 + 2) / 150)
    assert body["overall_bias"] == pytest.approx((150 + 5) / 150)


def test_series_backtest_zero_sales_has_undefined_metrics(client: TestClient) -> None:
    body = client.get("/series/B_2/S_1/backtest").json()
    assert body["available"] is True
    assert body["wape"] is None and body["bias"] is None
    assert "undefined" in body["reason"]
    assert body["folds"][0]["wape"] is None


def test_series_backtest_missing_series_is_not_available(client: TestClient) -> None:
    body = client.get("/series/A_1/S_2/backtest").json()
    assert body["available"] is False
    assert body["wape"] is None and body["folds"] == []
    assert "not in any backtest window" in body["reason"]
    assert client.get("/series/A_1/NOPE/backtest").status_code == 404


def test_bundle_without_backtest_is_not_available(bundle_dir: Path, tmp_path: Path) -> None:
    import shutil

    copy = tmp_path / "bundle"
    shutil.copytree(bundle_dir, copy)
    (copy / "backtest_series.parquet").unlink()
    with TestClient(create_app(copy)) as c:
        body = c.get("/series/A_1/S_1/backtest").json()
    assert body["available"] is False
    assert "no backtest results" in body["reason"]
    assert body["overall_wape"] is None


def test_cors_allows_configured_origin_only(bundle_dir: Path) -> None:
    with TestClient(create_app(bundle_dir, origins=["http://localhost:5173"])) as c:
        preflight = c.options(
            "/forecast/A_1/S_1/whatif",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == "http://localhost:5173"
        allowed = c.get("/health", headers={"Origin": "http://localhost:5173"})
        assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
        other = c.get("/health", headers={"Origin": "https://example.com"})
        assert "access-control-allow-origin" not in other.headers


def test_cors_origins_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    from demandbench.serving.app import cors_origins

    monkeypatch.setenv(
        "DEMANDBENCH_CORS_ORIGINS", "http://localhost:5173, https://demandbench.example "
    )
    assert cors_origins() == ["http://localhost:5173", "https://demandbench.example"]
    monkeypatch.delenv("DEMANDBENCH_CORS_ORIGINS")
    assert "http://localhost:5173" in cors_origins()


def test_port_prefers_platform_port_then_setting_then_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from demandbench.serving.__main__ import default_port

    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv("DEMANDBENCH_PORT", raising=False)
    assert default_port() == 8020
    monkeypatch.setenv("DEMANDBENCH_PORT", "9000")
    assert default_port() == 9000
    monkeypatch.setenv("PORT", "10000")
    assert default_port() == 10000
