"""Download the M5 Forecasting Accuracy files from Kaggle into data/raw/m5/."""

import argparse
import os
import sys

from dotenv import dotenv_values

from demandbench.paths import ENV_FILE, RAW_M5_DIR

COMPETITION = "m5-forecasting-accuracy"
FILES = ("sales_train_evaluation.csv", "calendar.csv", "sell_prices.csv")
REQUIRED_VARS = ("KAGGLE_USERNAME", "KAGGLE_KEY")


def load_credentials() -> None:
    if not ENV_FILE.is_file():
        sys.exit(f"Missing {ENV_FILE}. Create it with KAGGLE_USERNAME and KAGGLE_KEY set.")

    values = dotenv_values(ENV_FILE)
    missing = [name for name in REQUIRED_VARS if not values.get(name)]
    if missing:
        sys.exit(f"{ENV_FILE} is missing or has empty values for: {', '.join(missing)}")

    for name in REQUIRED_VARS:
        os.environ[name] = values[name]  # type: ignore[assignment]

    # Tokens generated from Kaggle settings since 2025 (prefixed KGAT_) are bearer
    # tokens, which the kaggle library only accepts via KAGGLE_API_TOKEN.
    key = os.environ["KAGGLE_KEY"]
    if key.startswith("KGAT_"):
        os.environ["KAGGLE_API_TOKEN"] = key


def download(force: bool = False) -> None:
    load_credentials()

    # The kaggle package authenticates on import, so it must be imported after
    # the credentials are in the environment.
    from kaggle import api  # type: ignore[import-untyped]

    RAW_M5_DIR.mkdir(parents=True, exist_ok=True)

    for name in FILES:
        target = RAW_M5_DIR / name
        if target.exists() and not force:
            print(f"skip      {name} (already present, use --force to re-download)")
            continue

        print(f"download  {name}")
        try:
            api.competition_download_file(
                COMPETITION, name, path=str(RAW_M5_DIR), force=True, quiet=False, unzip=True
            )
        except Exception as exc:
            sys.exit(
                f"Failed to download {name}: {exc}\n"
                f"If this is a 403, accept the competition rules at "
                f"https://www.kaggle.com/competitions/{COMPETITION}/rules"
            )

        if not target.is_file():
            sys.exit(f"Download of {name} finished but {target} was not found.")

    for name in FILES:
        size_mb = (RAW_M5_DIR / name).stat().st_size / 1024**2
        print(f"{name:<30} {size_mb:>8.1f} MB")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-download files that exist")
    args = parser.parse_args()
    download(force=args.force)


if __name__ == "__main__":
    main()
