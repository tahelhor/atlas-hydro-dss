"""Read-only access layer over ``data/hydro_warehouse.duckdb`` (returns polars frames)."""

from __future__ import annotations

from pathlib import Path

import duckdb
import polars as pl

from src.config import DB_PATH

TABLES = ("dim_basin_nodes", "fact_hydro_daily", "etl_run_log", "qa_rejections",
          "fact_climate_monthly", "fact_discharge_monthly", "etl_history_log")


def _query(sql: str, db_path: Path = DB_PATH, params: list | None = None) -> pl.DataFrame:
    if not db_path.exists():
        raise FileNotFoundError(
            f"{db_path} not found - run `uv run python -m src.ingestion.fetch_hydro_climate` first"
        )
    # Same (read-write) configuration as the ingestion writers: inside one process DuckDB shares
    # a single database instance, whereas a read_only connection fails while a writer is open
    # ("different configuration") - e.g. a visitor refreshing data on Streamlit Cloud.
    with duckdb.connect(str(db_path)) as con:
        return con.execute(sql, params or []).pl()


def load_nodes(db_path: Path = DB_PATH) -> pl.DataFrame:
    return _query("SELECT * FROM dim_basin_nodes ORDER BY lon DESC", db_path)


def load_hydro(db_path: Path = DB_PATH) -> pl.DataFrame:
    """Latest 122-day window (92 history + 30 forecast) for every node."""
    return _query(
        """
        SELECT f.* FROM fact_hydro_daily f
        WHERE f.date >= (SELECT max(first_forecast_date) - INTERVAL 92 DAY FROM etl_run_log)
        ORDER BY node_id, date
        """,
        db_path,
    )


def load_run_log(db_path: Path = DB_PATH) -> pl.DataFrame:
    return _query("SELECT * FROM etl_run_log ORDER BY started_at DESC", db_path)


def load_rejections(db_path: Path = DB_PATH, limit: int = 200) -> pl.DataFrame:
    return _query(
        "SELECT * FROM qa_rejections ORDER BY run_id DESC, node_id, date LIMIT ?", db_path, [limit]
    )


def existing_tables(db_path: Path = DB_PATH) -> set[str]:
    df = _query("SELECT table_name FROM information_schema.tables", db_path)
    return set(df["table_name"].to_list())


def table_row_counts(db_path: Path = DB_PATH) -> dict[str, int]:
    present = [t for t in TABLES if t in existing_tables(db_path)]
    union = " UNION ALL ".join(f"SELECT '{t}' AS t, count(*) AS n FROM {t}" for t in present)
    df = _query(union, db_path)
    return dict(zip(df["t"].to_list(), df["n"].to_list()))


def load_history_log(db_path: Path = DB_PATH) -> pl.DataFrame:
    if "etl_history_log" not in existing_tables(db_path):
        return pl.DataFrame()
    return _query("SELECT * FROM etl_history_log ORDER BY finished_at DESC", db_path)


def completeness_by_node(db_path: Path = DB_PATH) -> pl.DataFrame:
    """Share of non-null values per metric and node in the current window."""
    hydro = load_hydro(db_path)
    metrics = ["river_discharge_m3s", "discharge_p25_m3s", "et0_fao_mm", "precipitation_mm",
               "soil_moisture_deep_m3m3"]
    return (
        hydro.group_by("node_id")
        .agg(
            pl.len().alias("rows"),
            pl.col("is_forecast").sum().alias("forecast_rows"),
            pl.col("weather_is_filled").sum().alias("weather_ffilled_rows"),
            *[(pl.col(m).is_not_null().mean() * 100).round(1).alias(f"{m}_pct") for m in metrics],
        )
        .sort("node_id")
    )
