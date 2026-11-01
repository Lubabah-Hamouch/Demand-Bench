# DemandBench

DemandBench is a SKU-level demand forecasting system built on the M5 Forecasting Accuracy dataset of Walmart unit sales. Feature engineering is done with DuckDB and Polars, and LightGBM is the primary model, benchmarked against a seasonal naive baseline and Prophet using rolling-origin backtesting. Forecasts are served through a FastAPI service and explored in a React dashboard that supports what-if scenarios, such as toggling a promotion flag and re-scoring.

**Status:** early development.

## Forecasting setup

This project forecasts a fixed 28-day horizon using direct (not recursive) forecasting, and all features are offset accordingly to avoid leakage.

- Sales lags (`lag_28`, `lag_35`, `lag_42`, `lag_56`) and rolling statistics (`roll_*_h28`) only use sales from 28 or more days before the target date.
- Calendar features (day of week, month, events, SNAP) are known in advance.
- Price features (`sell_price`, 28-day price change) and the `has_promo` markdown proxy are treated as plannable, i.e. known for the target date. This is a simplifying assumption: in practice prices and promotions are set ahead of time by the retailer, but the model is not penalised for any uncertainty in them.

## Models and backtesting

All models are evaluated with the same 5-fold rolling-origin backtest: five sequential, non-overlapping 28-day test windows covering the last 140 days of the data, each trained on everything before it. WAPE is the primary metric; MAPE and RMSE are reported for reference.

| Model | Scope | Description |
|---|---|---|
| Naive (seasonal, 28-day) | all 30,490 series | Predicts sales from the same weekday 28 days earlier (`lag_28`) |
| LightGBM (global) | all 30,490 series | One model pooled across series, trained on the most recent 365 days of each fold's training data. A Tweedie-objective model gives the point forecast; quantile models at 0.1 / 0.9 give an 80% interval (a 0.5 quantile model is kept for comparison). All four are monotone-constrained: forecasts never rise with price or with a price increase vs 28 days earlier, and never fall when a promo is on |
| Prophet | 200-series sample | One model per series per fold, with yearly/weekly seasonality and SNAP, event and promo regressors |

**Prophet is benchmarked on a stratified 200-series sample for compute reasons**, while naive and LightGBM run on the full 30,490 series. The sample is stratified by category, state and volume tercile (ranked using sales up to the first fold's cutoff only) and is stored in `backend/src/demandbench/models/prophet_sample.csv`, so every fold and rerun uses the same series. Prophet's WAPE should only be compared with the naive and LightGBM WAPE computed on that same sample, never with their full-dataset WAPE; the comparison output reports both.

Results are also broken down by volume tier (low / medium / high sales terciles within each category and state, ranked on sales before the first test window; "new" for the few series launched too recently to rank).

### Limitations

The global LightGBM model performs much better on high-volume series than on low-volume, intermittent ones, where its WAPE is no better than predicting zero. This is an expected property of a model pooled across series: most days of a slow-moving item have no sales, so the signal the shared model can learn for those series is weak, and an unbiased forecast that spreads expected demand across days is penalised by WAPE on exactly those series. It is not a bug.

## Layout

- `backend/` — Python package (`demandbench`) for data, features, models, backtesting and serving
- `frontend/` — React + TypeScript dashboard (Vite)

## Data setup

The M5 data is downloaded from Kaggle, which requires an account that has accepted the
[competition rules](https://www.kaggle.com/competitions/m5-forecasting-accuracy/rules).
Create a `.env` file in the project root with your Kaggle credentials (generate a token at
https://www.kaggle.com/settings/api):

```
KAGGLE_USERNAME=your-username
KAGGLE_KEY=your-api-key
```

Then, from `backend/`:

```bash
uv sync --extra data
uv run python -m demandbench.data.download   # writes CSVs to data/raw/m5/ (add --force to re-download)
uv run python -m demandbench.data.ingest     # loads raw_sales, raw_calendar, raw_prices into data/processed/demandbench.duckdb
uv run python -m demandbench.features.build_features   # builds features_daily and features_model_ready, exports Parquet
uv sync --extra modeling
uv run python -m demandbench.models.prophet_sample     # selects the Prophet sample (only needed if the CSV is missing)
uv run python -m demandbench.backtest.compare          # runs all models through the backtest, saves to data/processed/backtest/
uv run python -m demandbench.backtest.compare --table-only   # re-prints the comparison from saved results
uv run pytest
```

## Serving API

The API serves forecasts from a final set of LightGBM models (Tweedie point forecast plus 0.1 / 0.5 / 0.9 quantile models) trained on the most recent 365 days of the full dataset. Train them once, then start the server, from `backend/`:

```bash
uv sync --all-extras
uv run python -m demandbench.models.train_final          # writes the model bundle to artifacts/lightgbm/
uv run python -m demandbench.serving --reload             # http://127.0.0.1:8020, interactive docs at /docs
```

The server listens on port 8020 by default (`--port` or `DEMANDBENCH_PORT` to change it; `uvicorn demandbench.serving.app:app --port 8020` also works). The bundle is loaded once at startup (set `DEMANDBENCH_ARTIFACTS_DIR` to load it from elsewhere); requests never retrain. It contains the boosters, the feature order and categorical vocabulary used at training time, the training window, feature importance, per-series metadata, the feature rows for the 28 days after training ends (built by `build_features` with the same SQL as the training features), the recent daily data used by the what-if and history endpoints, and the per-series results of the saved backtest. `train_final --data-only` refreshes that data without retraining.

Browsers may call the API from the origins listed in `DEMANDBENCH_CORS_ORIGINS` (comma-separated; default `http://localhost:5173,http://127.0.0.1:5173`, the Vite dev server). Add a deployed frontend's origin there; no code change is needed.

| Endpoint | Description |
|---|---|
| `GET /health` | Status, training cutoff and forecast window |
| `GET /series` | Series for a picker, with category, department, state, volume tier and sales totals. Filters: `store_id`, `state_id`, `cat_id`, `dept_id`, `volume_tier`, `q` (item_id substring); `sort` (`total_sales`, `sales_last_28d`, `item_id`); `limit`, `offset` |
| `GET /forecast/{item_id}/{store_id}` | 28-day forecast: date, point forecast, lower (q0.1) and upper (q0.9) bound. Unknown series return 404 |
| `POST /forecast/{item_id}/{store_id}/whatif` | The same forecast under a scenario: body `{"has_promo": true}` and/or `{"sell_price": 1.2}`, applied to all 28 days. A price override recomputes the 28-day price change and (unless `has_promo` is given) the promo flag with the feature SQL; sales features are unchanged. At least one override is required; `sell_price` must be positive |
| `GET /series/{item_id}/{store_id}/history` | Daily sales for the last `days` days (default 180, max 730) with each day's prior-28-day mean and standard deviation, z-score, and an anomaly flag (more than 3 standard deviations from the prior-28-day mean) |
| `GET /series/{item_id}/{store_id}/backtest` | How the model did on this series in the 5-fold backtest: WAPE and forecast ÷ actual pooled over the folds and per fold, next to the same figures across all series. `available: false` (with a `reason`) when the backtest has no result for the series; WAPE and bias are null when it sold nothing in the test windows |
| `GET /model/importance` | Gain-based feature importance of the point-forecast model (one global model, so the same for every series) |
| `GET /model` | Training window, features and hyperparameters |

```bash
curl http://127.0.0.1:8020/health
curl "http://127.0.0.1:8020/series?store_id=CA_1&cat_id=FOODS&limit=5"
curl http://127.0.0.1:8020/forecast/FOODS_3_090/CA_1
curl -X POST http://127.0.0.1:8020/forecast/FOODS_3_090/CA_1/whatif \
     -H "Content-Type: application/json" -d '{"has_promo": true}'
curl "http://127.0.0.1:8020/series/FOODS_3_090/CA_1/history?days=90"
curl http://127.0.0.1:8020/model/importance
```

What-if scenarios move the forecast in the expected direction by construction: the models are monotone-constrained, so a lower price or an active promo never lowers the forecast and a higher price never raises it. The size of the response is learned across all items rather than measured for each item, so treat it as indicative, especially for items whose price has rarely changed.
