from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Health(BaseModel):
    status: str
    model: str
    trained_through: date
    forecast_start: date
    forecast_end: date
    n_series: int


class ModelInfo(BaseModel):
    model: str
    point_model: str
    tweedie_variance_power: float
    quantiles: list[float]
    train_start: date
    train_end: date
    train_rows: int
    horizon_days: int
    features: list[str]
    created_at: str


class SeriesInfo(BaseModel):
    item_id: str
    store_id: str
    dept_id: str
    cat_id: str
    state_id: str
    total_sales: int = Field(description="Units sold over the full history")
    sales_last_28d: int = Field(description="Units sold in the 28 days before training ended")
    on_sale_since: date | None
    volume_tier: str = Field(
        description="low / medium / high sales tercile within category and state, or new"
    )


class SeriesPage(BaseModel):
    total: int = Field(description="Series matching the filters, before paging")
    limit: int
    offset: int
    items: list[SeriesInfo]


class ForecastPoint(BaseModel):
    date: date
    forecast: float = Field(description="Point forecast (Tweedie model), units")
    lower: float = Field(description="Lower bound (0.1 quantile model)")
    upper: float = Field(description="Upper bound (0.9 quantile model)")


class Interval(BaseModel):
    lower_quantile: float
    upper_quantile: float
    nominal_coverage: float
    note: str


class Forecast(BaseModel):
    item_id: str
    store_id: str
    dept_id: str
    cat_id: str
    state_id: str
    model: str
    trained_through: date
    horizon_days: int
    sell_price: float | None = Field(
        description="Price on the first forecast day (the scenario price for a what-if); "
        "null if the item is not on sale"
    )
    sales_last_28d: int = Field(description="Units sold in the 28 days before training ended")
    interval: Interval
    points: list[ForecastPoint]


class FeatureImportance(BaseModel):
    feature: str
    gain: float
    share: float = Field(description="Share of total gain across all features")


class Importance(BaseModel):
    model: str
    importance_type: str
    scope: str
    features: list[FeatureImportance]


class WhatIfRequest(BaseModel):
    """Overrides applied to every day of the 28-day forecast window."""

    model_config = ConfigDict(extra="forbid")

    has_promo: bool | None = Field(
        None, description="Force the promo flag on or off for every forecast day"
    )
    sell_price: float | None = Field(
        None,
        gt=0,
        allow_inf_nan=False,
        description="Price for every forecast day. Unless has_promo is also given, the promo "
        "flag is recomputed from this price (price below the trailing 90-day median).",
    )

    @model_validator(mode="after")
    def at_least_one_override(self) -> "WhatIfRequest":
        if self.has_promo is None and self.sell_price is None:
            raise ValueError("provide at least one override: has_promo and/or sell_price")
        return self


WHATIF_NOTE = (
    "The models are constrained so that a lower price or an active promo never lowers the "
    "forecast and a higher price never raises it. How much the forecast moves is learned "
    "across all items, not a calibrated price elasticity for this item, and is least "
    "reliable for items whose price has rarely changed."
)


class WhatIfForecast(Forecast):
    scenario: WhatIfRequest
    note: str = WHATIF_NOTE


class HistoryPoint(BaseModel):
    date: date
    sales: int
    rolling_mean: float | None = Field(description="Mean of the 28 previous days")
    rolling_std: float | None = Field(description="Sample std of the 28 previous days")
    z_score: float | None
    anomaly: bool = Field(description="|sales - rolling_mean| > 3 * rolling_std")


class History(BaseModel):
    item_id: str
    store_id: str
    start: date
    end: date
    days: int
    anomaly_rule: str
    n_anomalies: int
    points: list[HistoryPoint]


class FoldBacktest(BaseModel):
    fold: int
    test_start: date
    test_end: date
    actual_units: float
    forecast_units: float
    wape: float | None
    bias: float | None


class SeriesBacktest(BaseModel):
    item_id: str
    store_id: str
    available: bool = Field(description="False when the backtest has no results for this series")
    reason: str | None = Field(description="Why a metric is unavailable or undefined, if it is")
    model: str
    n_folds: int
    window_start: date | None
    window_end: date | None
    actual_units: float | None = Field(description="Units sold across all test windows")
    forecast_units: float | None = Field(description="Units forecast across all test windows")
    wape: float | None = Field(description="sum |forecast - actual| / sum actual, all folds")
    bias: float | None = Field(description="sum forecast / sum actual, all folds")
    overall_wape: float | None = Field(description="The same WAPE across every series")
    overall_bias: float | None = Field(description="The same bias across every series")
    folds: list[FoldBacktest]
