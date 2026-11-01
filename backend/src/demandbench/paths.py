from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
RAW_M5_DIR = DATA_DIR / "raw" / "m5"
PROCESSED_DIR = DATA_DIR / "processed"
DUCKDB_PATH = PROCESSED_DIR / "demandbench.duckdb"
FEATURES_PARQUET = PROCESSED_DIR / "features_model_ready.parquet"
BACKTEST_DIR = PROCESSED_DIR / "backtest"
FORECAST_FEATURES_PARQUET = PROCESSED_DIR / "features_forecast.parquet"
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts" / "lightgbm"
ENV_FILE = PROJECT_ROOT / ".env"
