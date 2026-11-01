"""Load the raw M5 CSVs into DuckDB and run basic sanity checks."""

import sys
import time
from pathlib import Path

import duckdb

from demandbench.paths import DUCKDB_PATH, RAW_M5_DIR

TABLES = {
    "raw_sales": "sales_train_evaluation.csv",
    "raw_calendar": "calendar.csv",
    "raw_prices": "sell_prices.csv",
}


SALES_ID_COLUMNS = ("id", "item_id", "dept_id", "cat_id", "store_id", "state_id")


def sql_path(path: Path) -> str:
    return "'" + path.as_posix().replace("'", "''") + "'"


def sales_columns(csv_path: Path) -> str:
    """Explicit schema for the wide sales file, so DuckDB skips type sniffing
    across ~1,947 columns. Daily unit sales top out well under SMALLINT's range."""
    with csv_path.open() as f:
        header = f.readline().strip().split(",")
    types = {col: "VARCHAR" if col in SALES_ID_COLUMNS else "SMALLINT" for col in header}
    return "{" + ", ".join(f"'{col}': '{typ}'" for col, typ in types.items()) + "}"


def read_csv_sql(table: str, csv_path: Path) -> str:
    if table == "raw_sales":
        return f"read_csv({sql_path(csv_path)}, header = true, columns = {sales_columns(csv_path)})"
    return f"read_csv_auto({sql_path(csv_path)}, header = true)"


def load(con: duckdb.DuckDBPyConnection) -> None:
    for table, filename in TABLES.items():
        csv_path = RAW_M5_DIR / filename
        if not csv_path.is_file():
            sys.exit(f"Missing {csv_path}. Run demandbench.data.download first.")

        start = time.perf_counter()
        con.execute(
            f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM {read_csv_sql(table, csv_path)}"
        )
        print(f"loaded {table:<13} from {filename:<28} in {time.perf_counter() - start:6.2f}s")


def fully_null_columns(con: duckdb.DuckDBPyConnection, table: str) -> list[str]:
    columns = [row[0] for row in con.execute(f"DESCRIBE {table}").fetchall()]
    counts = con.execute(f"SELECT count(COLUMNS(*)) FROM {table}").fetchone()
    assert counts is not None
    return [col for col, n in zip(columns, counts, strict=True) if n == 0]


def sanity_checks(con: duckdb.DuckDBPyConnection) -> bool:
    ok = True

    print("\nrow counts")
    for table in TABLES:
        n_rows, n_cols = con.execute(
            f"SELECT (SELECT count(*) FROM {table}), "
            f"(SELECT count(*) FROM information_schema.columns WHERE table_name = '{table}')"
        ).fetchone()  # type: ignore[misc]
        print(f"  {table:<13} {n_rows:>12,} rows  {n_cols:>5,} columns")

    first, last, n_days = con.execute(
        "SELECT min(date), max(date), count(DISTINCT date) FROM raw_calendar"
    ).fetchone()  # type: ignore[misc]
    print(f"\ncalendar date range\n  {first} -> {last} ({n_days:,} distinct days)")

    n_series, n_rows = con.execute(
        "SELECT count(DISTINCT (item_id, store_id)), count(*) FROM raw_sales"
    ).fetchone()  # type: ignore[misc]
    print(f"\nsales item/store combinations\n  {n_series:,} distinct ({n_rows:,} rows)")
    if n_series != n_rows:
        print("  FAIL: item/store combinations are not unique per row")
        ok = False

    print("\nfully-null columns")
    for table in TABLES:
        null_cols = fully_null_columns(con, table)
        if null_cols:
            print(f"  {table:<13} FAIL: {', '.join(null_cols)}")
            ok = False
        else:
            print(f"  {table:<13} none")

    return ok


def main() -> None:
    DUCKDB_PATH.parent.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    with duckdb.connect(str(DUCKDB_PATH)) as con:
        load(con)
        load_seconds = time.perf_counter() - start
        ok = sanity_checks(con)
    total_seconds = time.perf_counter() - start

    print(f"\nload time {load_seconds:.2f}s, total {total_seconds:.2f}s -> {DUCKDB_PATH}")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
