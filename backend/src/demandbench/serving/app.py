"""FastAPI service for the production LightGBM forecasts.

Run locally from backend/:

    uv run python -m demandbench.serving --reload       # http://127.0.0.1:8020

The model bundle (see demandbench.models.bundle) is loaded once at startup from
artifacts/lightgbm/, or from DEMANDBENCH_ARTIFACTS_DIR if set. Each forecast request
scores that series' precomputed feature rows with the loaded boosters.

Browsers may call the API from the origins in DEMANDBENCH_CORS_ORIGINS (comma-separated;
default: the Vite dev server).
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import polars as pl
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

from demandbench.models.bundle import ModelBundle
from demandbench.models.lightgbm_model import predict_all
from demandbench.models.train_final import MAX_HISTORY_DAYS
from demandbench.paths import ARTIFACTS_DIR
from demandbench.serving import schemas
from demandbench.serving.scenarios import (
    ANOMALY_THRESHOLD,
    ANOMALY_WINDOW,
    scenario_rows,
    with_anomalies,
)

# 8000 and 8010 are used by another project on the development machine.
DEFAULT_PORT = 8020
DEFAULT_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
LOWER_Q, UPPER_Q = 0.1, 0.9
INTERVAL_NOTE = (
    "In backtesting this interval covered about 80% of all days but only about 74% of "
    "days with nonzero sales, so treat it as optimistic for days when the item sells."
)


@dataclass(frozen=True)
class ServingState:
    bundle: ModelBundle
    series: pl.DataFrame
    row_offsets: dict[tuple[str, str], int]
    horizon: int
    backtest_overall: tuple[float | None, float | None]
    """WAPE and bias across every series in the bundle's backtest results."""


def _ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator > 0 else None


def load_state(directory: Path) -> ServingState:
    bundle = ModelBundle.load(directory)
    horizon = int(bundle.metadata["horizon_days"])
    rows = bundle.forecast_features
    # forecast_features is sorted by store_id, item_id, date with exactly `horizon` rows
    # per series, so each series is one contiguous slice.
    counts = rows.group_by("item_id", "store_id").len()
    if counts["len"].min() != horizon or counts["len"].max() != horizon:
        raise ValueError(f"forecast_features must have exactly {horizon} rows per series")
    starts = rows.with_row_index("offset").filter(pl.col("offset") % horizon == 0)
    offsets = {
        (item, store): int(offset)
        for offset, item, store in starts.select("offset", "item_id", "store_id").iter_rows()
    }
    overall: tuple[float | None, float | None] = (None, None)
    if bundle.backtest is not None:
        actual, forecast, error = bundle.backtest.select(
            pl.col("actual_units").sum(), pl.col("forecast_units").sum(), pl.col("abs_error").sum()
        ).row(0)
        overall = (_ratio(error, actual), _ratio(forecast, actual))
    return ServingState(
        bundle=bundle,
        series=bundle.series,
        row_offsets=offsets,
        horizon=horizon,
        backtest_overall=overall,
    )


def cors_origins() -> list[str]:
    raw = os.environ.get("DEMANDBENCH_CORS_ORIGINS", DEFAULT_CORS_ORIGINS)
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def _state(request: Request) -> ServingState:
    state: ServingState = request.app.state.serving
    return state


def _forecast_rows(s: ServingState, item_id: str, store_id: str) -> pl.DataFrame:
    """The series' precomputed forecast feature rows, or a 404 for an unknown series."""
    offset = s.row_offsets.get((item_id, store_id))
    if offset is None:
        stores = set(s.series["store_id"].unique().to_list())
        hint = (
            f"unknown store_id {store_id!r} (valid: {', '.join(sorted(stores))})"
            if store_id not in stores
            else f"item_id {item_id!r} is not sold at store {store_id!r}"
        )
        raise HTTPException(
            status_code=404,
            detail=f"No series for item_id={item_id!r}, store_id={store_id!r}: {hint}. "
            "Use GET /series to list available series.",
        )
    return s.bundle.forecast_features.slice(offset, s.horizon)


def _forecast_fields(
    s: ServingState, item_id: str, store_id: str, rows: pl.DataFrame
) -> dict[str, Any]:
    """Score feature rows with the loaded models; the fields of a Forecast response."""
    point, quantiles = predict_all(
        s.bundle.boosters, rows, s.bundle.categories, s.bundle.quantile_scale
    )
    lower, upper = quantiles[LOWER_Q], quantiles[UPPER_Q]
    meta = s.series.filter((pl.col("item_id") == item_id) & (pl.col("store_id") == store_id)).row(
        0, named=True
    )
    return {
        "item_id": item_id,
        "store_id": store_id,
        "dept_id": meta["dept_id"],
        "cat_id": meta["cat_id"],
        "state_id": meta["state_id"],
        "model": s.bundle.metadata["model"],
        "trained_through": s.bundle.trained_through,
        "horizon_days": s.horizon,
        "sell_price": rows["sell_price"][0],
        "sales_last_28d": meta["sales_last_28d"],
        "interval": schemas.Interval(
            lower_quantile=LOWER_Q,
            upper_quantile=UPPER_Q,
            nominal_coverage=round(UPPER_Q - LOWER_Q, 2),
            note=INTERVAL_NOTE,
        ),
        "points": [
            schemas.ForecastPoint(
                date=d, forecast=round(p, 3), lower=round(lo, 3), upper=round(hi, 3)
            )
            for d, p, lo, hi in zip(
                rows["date"].to_list(), point.tolist(), lower.tolist(), upper.tolist(), strict=True
            )
        ],
    }


def create_app(artifacts_dir: Path | None = None, origins: list[str] | None = None) -> FastAPI:
    directory = artifacts_dir or Path(os.environ.get("DEMANDBENCH_ARTIFACTS_DIR", ARTIFACTS_DIR))

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.serving = load_state(directory)
        yield

    app = FastAPI(
        title="DemandBench",
        description="28-day SKU-level demand forecasts for the M5 (Walmart) dataset.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins() if origins is None else origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.get("/health", response_model=schemas.Health)
    def health(request: Request) -> schemas.Health:
        s = _state(request)
        dates = s.bundle.forecast_features["date"]
        return schemas.Health(
            status="ok",
            model=s.bundle.metadata["model"],
            trained_through=s.bundle.trained_through,
            forecast_start=dates.min(),  # type: ignore[arg-type]
            forecast_end=dates.max(),  # type: ignore[arg-type]
            n_series=s.series.height,
        )

    @app.get("/model", response_model=schemas.ModelInfo)
    def model_info(request: Request) -> schemas.ModelInfo:
        return schemas.ModelInfo.model_validate(_state(request).bundle.metadata)

    @app.get(
        "/model/importance",
        response_model=schemas.Importance,
        summary="Feature importance of the point-forecast model",
        description=(
            "Gain-based importance of the Tweedie model. There is one global model for "
            "all series, so this is the same for every item and store."
        ),
    )
    def importance(request: Request) -> schemas.Importance:
        table = (
            _state(request)
            .bundle.importance.filter(pl.col("model") == "tweedie")
            .with_columns((pl.col("gain") / pl.col("gain").sum()).alias("share"))
            .sort("gain", descending=True)
        )
        return schemas.Importance(
            model="tweedie",
            importance_type="gain",
            scope="global (one model for all series)",
            features=[
                schemas.FeatureImportance(**row)
                for row in table.select("feature", "gain", "share").iter_rows(named=True)
            ],
        )

    @app.get("/series", response_model=schemas.SeriesPage)
    def list_series(
        request: Request,
        store_id: str | None = None,
        state_id: str | None = None,
        cat_id: str | None = None,
        dept_id: str | None = None,
        volume_tier: Literal["low", "medium", "high", "new"] | None = None,
        q: str | None = Query(None, description="Case-insensitive substring of item_id"),
        sort: Literal["total_sales", "sales_last_28d", "item_id"] = "total_sales",
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
    ) -> schemas.SeriesPage:
        series = _state(request).series
        for column, value in (
            ("store_id", store_id),
            ("state_id", state_id),
            ("cat_id", cat_id),
            ("dept_id", dept_id),
            ("volume_tier", volume_tier),
        ):
            if value is not None:
                series = series.filter(pl.col(column) == value)
        if q:
            series = series.filter(
                pl.col("item_id").str.to_lowercase().str.contains(q.lower(), literal=True)
            )
        series = series.sort(
            [sort, "store_id", "item_id"], descending=[sort != "item_id", False, False]
        )
        page = series.slice(offset, limit)
        return schemas.SeriesPage(
            total=series.height,
            limit=limit,
            offset=offset,
            items=[schemas.SeriesInfo(**row) for row in page.iter_rows(named=True)],
        )

    @app.get(
        "/forecast/{item_id}/{store_id}",
        response_model=schemas.Forecast,
        responses={404: {"description": "Unknown item_id/store_id combination"}},
    )
    def forecast(item_id: str, store_id: str, request: Request) -> schemas.Forecast:
        s = _state(request)
        rows = _forecast_rows(s, item_id, store_id)
        return schemas.Forecast(**_forecast_fields(s, item_id, store_id, rows))

    @app.post(
        "/forecast/{item_id}/{store_id}/whatif",
        response_model=schemas.WhatIfForecast,
        responses={404: {"description": "Unknown item_id/store_id combination"}},
        summary="Re-score the 28-day forecast under a price and/or promo scenario",
        description=(
            "Starts from the same feature rows as GET /forecast, applies the overrides to "
            "every forecast day, recomputes the features derived from them (28-day price "
            "change, and the promo flag unless has_promo is given), and re-scores with the "
            "loaded models. Sales lags and rolling features are not changed."
        ),
    )
    def whatif(
        item_id: str, store_id: str, body: schemas.WhatIfRequest, request: Request
    ) -> schemas.WhatIfForecast:
        s = _state(request)
        rows = scenario_rows(
            _forecast_rows(s, item_id, store_id),
            s.bundle.read_daily_recent(item_id, store_id),
            s.bundle.trained_through,
            sell_price=body.sell_price,
            has_promo=body.has_promo,
        )
        return schemas.WhatIfForecast(**_forecast_fields(s, item_id, store_id, rows), scenario=body)

    @app.get(
        "/series/{item_id}/{store_id}/history",
        response_model=schemas.History,
        responses={404: {"description": "Unknown item_id/store_id combination"}},
        summary="Actual daily sales with anomaly flags",
    )
    def history(
        item_id: str,
        store_id: str,
        request: Request,
        days: int = Query(180, ge=1, le=MAX_HISTORY_DAYS, description="Days to return"),
    ) -> schemas.History:
        s = _state(request)
        _forecast_rows(s, item_id, store_id)  # 404 for unknown series
        points = with_anomalies(s.bundle.read_sales_history(item_id, store_id), days)
        return schemas.History(
            item_id=item_id,
            store_id=store_id,
            start=points["date"].min(),  # type: ignore[arg-type]
            end=points["date"].max(),  # type: ignore[arg-type]
            days=points.height,
            anomaly_rule=(
                f"|sales - mean| > {ANOMALY_THRESHOLD:g} * std, where mean and std are over "
                f"the {ANOMALY_WINDOW} previous days (the day itself excluded); not flagged "
                "when that window has zero variance or is incomplete"
            ),
            n_anomalies=int(points["anomaly"].sum()),
            points=[schemas.HistoryPoint(**row) for row in points.iter_rows(named=True)],
        )

    @app.get(
        "/series/{item_id}/{store_id}/backtest",
        response_model=schemas.SeriesBacktest,
        responses={404: {"description": "Unknown item_id/store_id combination"}},
        summary="How the model did on this series in the saved backtest",
        description=(
            "WAPE and bias for this series, pooled over the backtest's rolling-origin "
            "folds and per fold, next to the same figures across all series. "
            "available is false when the backtest has no results for the series; WAPE "
            "and bias are null when it sold nothing in the test windows."
        ),
    )
    def series_backtest(item_id: str, store_id: str, request: Request) -> schemas.SeriesBacktest:
        s = _state(request)
        _forecast_rows(s, item_id, store_id)  # 404 for unknown series
        overall_wape, overall_bias = s.backtest_overall
        empty = schemas.SeriesBacktest(
            item_id=item_id,
            store_id=store_id,
            available=False,
            reason=None,
            model=s.bundle.metadata["model"],
            n_folds=0,
            window_start=None,
            window_end=None,
            actual_units=None,
            forecast_units=None,
            wape=None,
            bias=None,
            overall_wape=overall_wape,
            overall_bias=overall_bias,
            folds=[],
        )
        if s.bundle.backtest is None:
            return empty.model_copy(update={"reason": "This model bundle has no backtest results."})
        rows = s.bundle.backtest.filter(
            (pl.col("item_id") == item_id) & (pl.col("store_id") == store_id)
        ).sort("fold")
        if rows.height == 0:
            return empty.model_copy(
                update={"reason": "This series was not in any backtest window."}
            )

        actual, forecast, error = rows.select(
            pl.col("actual_units").sum(), pl.col("forecast_units").sum(), pl.col("abs_error").sum()
        ).row(0)
        return empty.model_copy(
            update={
                "available": True,
                "reason": (
                    None
                    if actual > 0
                    else "No units were sold in the backtest windows, so WAPE and bias "
                    "are undefined for this series."
                ),
                "n_folds": rows.height,
                "window_start": rows["test_start"].min(),
                "window_end": rows["test_end"].max(),
                "actual_units": actual,
                "forecast_units": forecast,
                "wape": _ratio(error, actual),
                "bias": _ratio(forecast, actual),
                "folds": [
                    schemas.FoldBacktest(
                        fold=r["fold"],
                        test_start=r["test_start"],
                        test_end=r["test_end"],
                        actual_units=r["actual_units"],
                        forecast_units=r["forecast_units"],
                        wape=_ratio(r["abs_error"], r["actual_units"]),
                        bias=_ratio(r["forecast_units"], r["actual_units"]),
                    )
                    for r in rows.iter_rows(named=True)
                ],
            }
        )

    return app


app = create_app()
