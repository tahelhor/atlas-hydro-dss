"""Async ingestion: Copernicus GloFAS v4 discharge + Open-Meteo hydrometeorology -> DuckDB.

Run:  uv run python -m src.ingestion.fetch_hydro_climate

Pipeline per node (all 4 nodes x 2 APIs fetched concurrently):
    raw JSON -> pydantic payload contract -> polars transform -> join on date
    -> pydantic row gate -> DuckDB (fact_hydro_daily, dim_basin_nodes, etl_run_log, qa_rejections)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time
import uuid
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import httpx
import polars as pl

from src.config import (
    DB_PATH,
    GLOFAS_DAILY_VARS,
    GLOFAS_FORECAST_DAYS,
    GLOFAS_URL,
    HISTORY_DAYS,
    HTTP_MAX_RETRIES,
    HTTP_TIMEOUT_S,
    M3S_TO_MM3_PER_DAY,
    NODES,
    TIMEZONE,
    WEATHER_DAILY_VARS,
    WEATHER_FORECAST_DAYS,
    WEATHER_HOURLY_VARS,
    WEATHER_URL,
    BasinNode,
)
from src.ingestion.validator import GloFASPayload, QAReport, WeatherPayload, validate_rows

log = logging.getLogger("atlas.ingestion")

WEATHER_COLUMNS = {
    "precipitation_sum": "precipitation_mm",
    "snowfall_sum": "snowfall_cm",
    "temperature_2m_max": "temperature_max_c",
    "et0_fao_evapotranspiration": "et0_fao_mm",
}
FILLABLE_WEATHER = [*WEATHER_COLUMNS.values(), "soil_moisture_deep_m3m3"]

FACT_SCHEMA: dict[str, pl.DataType] = {
    "node_id": pl.Utf8,
    "date": pl.Date,
    "is_forecast": pl.Boolean,
    "river_discharge_m3s": pl.Float64,
    "discharge_p25_m3s": pl.Float64,
    "discharge_p75_m3s": pl.Float64,
    "inflow_mm3": pl.Float64,
    "inflow_p25_mm3": pl.Float64,
    "inflow_p75_mm3": pl.Float64,
    "precipitation_mm": pl.Float64,
    "snowfall_cm": pl.Float64,
    "temperature_max_c": pl.Float64,
    "et0_fao_mm": pl.Float64,
    "soil_moisture_deep_m3m3": pl.Float64,
    "weather_is_filled": pl.Boolean,
}


# =========================================================================== HTTP
def glofas_params(node: BasinNode) -> dict[str, Any]:
    return {
        "latitude": node.glofas_lat,
        "longitude": node.glofas_lon,
        "daily": ",".join(GLOFAS_DAILY_VARS),
        "past_days": HISTORY_DAYS,
        "forecast_days": GLOFAS_FORECAST_DAYS,
    }


def weather_params(node: BasinNode) -> dict[str, Any]:
    return {
        "latitude": node.lat,
        "longitude": node.lon,
        "daily": ",".join(WEATHER_DAILY_VARS),
        "hourly": ",".join(WEATHER_HOURLY_VARS),
        "past_days": HISTORY_DAYS,
        "forecast_days": WEATHER_FORECAST_DAYS,
        "timezone": TIMEZONE,
    }


async def fetch_json(client: httpx.AsyncClient, url: str, params: dict[str, Any]) -> dict[str, Any]:
    """GET with exponential backoff on transport errors, 429 and 5xx."""
    for attempt in range(1, HTTP_MAX_RETRIES + 1):
        try:
            resp = await client.get(url, params=params)
            if resp.status_code == 429 or resp.status_code >= 500:
                raise httpx.HTTPStatusError(f"retryable {resp.status_code}", request=resp.request,
                                            response=resp)
            resp.raise_for_status()
            return resp.json()
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            retryable = isinstance(exc, httpx.TransportError) or (
                exc.response.status_code == 429 or exc.response.status_code >= 500
            )
            if not retryable or attempt == HTTP_MAX_RETRIES:
                raise
            delay = 0.5 * 2 ** (attempt - 1)
            log.warning("retry %s/%s for %s in %.1fs (%s)", attempt, HTTP_MAX_RETRIES, url, delay, exc)
            await asyncio.sleep(delay)
    raise RuntimeError("unreachable")


async def fetch_node(client: httpx.AsyncClient, node: BasinNode) -> tuple[GloFASPayload, WeatherPayload]:
    glofas_raw, weather_raw = await asyncio.gather(
        fetch_json(client, GLOFAS_URL, glofas_params(node)),
        fetch_json(client, WEATHER_URL, weather_params(node)),
    )
    return GloFASPayload.model_validate(glofas_raw), WeatherPayload.model_validate(weather_raw)


async def fetch_all(
    nodes: tuple[BasinNode, ...] = NODES, transport: httpx.AsyncBaseTransport | None = None
) -> dict[str, tuple[GloFASPayload, WeatherPayload]]:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_S, transport=transport) as client:
        results = await asyncio.gather(*(fetch_node(client, n) for n in nodes))
    return {n.node_id: r for n, r in zip(nodes, results)}


# =========================================================================== transforms
def transform_glofas(payload: GloFASPayload, node_id: str) -> pl.DataFrame:
    """Daily discharge with the historical/forecast coalesce rule and Mm3/day conversion.

    The first forecast day is ``time[HISTORY_DAYS]`` (the API's own "today"). History uses
    ``river_discharge``; forecast days use the ensemble ``river_discharge_mean`` so the
    central line is consistent with the p25/p75 fan. Each side falls back to the other.
    """
    d = payload.daily.model_extra or {}
    first_forecast = payload.daily.time[min(HISTORY_DAYS, len(payload.daily.time) - 1)]
    df = pl.DataFrame(
        {
            "date": payload.daily.time,
            "q_hist": d["river_discharge"],
            "q_mean": d["river_discharge_mean"],
            "discharge_p25_m3s": d["river_discharge_p25"],
            "discharge_p75_m3s": d["river_discharge_p75"],
        },
        schema_overrides={c: pl.Float64 for c in ("q_hist", "q_mean", "discharge_p25_m3s",
                                                  "discharge_p75_m3s")},
    )
    is_fc = pl.col("date") >= pl.lit(first_forecast)
    return (
        df.with_columns(
            pl.lit(node_id).alias("node_id"),
            is_fc.alias("is_forecast"),
            pl.when(is_fc)
            .then(pl.coalesce("q_mean", "q_hist"))
            .otherwise(pl.coalesce("q_hist", "q_mean"))
            .alias("river_discharge_m3s"),
        )
        .with_columns(
            (pl.col("river_discharge_m3s") * M3S_TO_MM3_PER_DAY).alias("inflow_mm3"),
            (pl.col("discharge_p25_m3s") * M3S_TO_MM3_PER_DAY).alias("inflow_p25_mm3"),
            (pl.col("discharge_p75_m3s") * M3S_TO_MM3_PER_DAY).alias("inflow_p75_mm3"),
        )
        .drop("q_hist", "q_mean")
    )


def transform_weather(payload: WeatherPayload) -> pl.DataFrame:
    """Daily weather metrics joined with the daily mean of hourly deep soil moisture."""
    d = payload.daily.model_extra or {}
    daily = pl.DataFrame(
        {"date": payload.daily.time, **{new: d[old] for old, new in WEATHER_COLUMNS.items()}},
        schema_overrides={c: pl.Float64 for c in WEATHER_COLUMNS.values()},
    )
    h = payload.hourly.model_extra or {}
    soil = (
        pl.DataFrame(
            {"ts": payload.hourly.time, "sm": h["soil_moisture_28_to_100cm"]},
            schema_overrides={"sm": pl.Float64},
        )
        .with_columns(pl.col("ts").dt.date().alias("date"))
        .group_by("date")
        .agg(pl.col("sm").mean().alias("soil_moisture_deep_m3m3"))
    )
    return daily.join(soil, on="date", how="left").sort("date")


def join_node(glofas_df: pl.DataFrame, weather_df: pl.DataFrame) -> pl.DataFrame:
    """Left-join weather onto the 122-day GloFAS axis; forward-fill weather into forecast
    days beyond the 16-day weather horizon (days 17-30) and flag those rows."""
    joined = glofas_df.join(weather_df, on="date", how="left").sort("date")
    missing_on_forecast = pl.col("is_forecast") & pl.col("et0_fao_mm").is_null()
    joined = joined.with_columns(missing_on_forecast.alias("weather_is_filled"))
    filled = [
        pl.when(pl.col("is_forecast")).then(pl.col(c).forward_fill()).otherwise(pl.col(c)).alias(c)
        for c in FILLABLE_WEATHER
    ]
    return joined.with_columns(filled).select(list(FACT_SCHEMA))


def build_fact_frame(payloads: dict[str, tuple[GloFASPayload, WeatherPayload]]) -> pl.DataFrame:
    frames = [
        join_node(transform_glofas(g, node_id), transform_weather(w))
        for node_id, (g, w) in payloads.items()
    ]
    return pl.concat(frames).sort("node_id", "date")


# =========================================================================== DuckDB
DDL = """
CREATE OR REPLACE TABLE dim_basin_nodes (
    node_id VARCHAR PRIMARY KEY,
    name VARCHAR NOT NULL,
    node_type VARCHAR NOT NULL,
    river VARCHAR,
    lat DOUBLE, lon DOUBLE,
    glofas_lat DOUBLE, glofas_lon DOUBLE,
    capacity_mm3 DOUBLE,
    baseline_storage_mm3 DOUBLE,
    downstream_node_id VARCHAR,
    surface_area_full_km2 DOUBLE
);
CREATE TABLE IF NOT EXISTS fact_hydro_daily (
    node_id VARCHAR NOT NULL,
    date DATE NOT NULL,
    is_forecast BOOLEAN NOT NULL,
    river_discharge_m3s DOUBLE NOT NULL CHECK (river_discharge_m3s >= 0),
    discharge_p25_m3s DOUBLE,
    discharge_p75_m3s DOUBLE,
    inflow_mm3 DOUBLE NOT NULL CHECK (inflow_mm3 >= 0),
    inflow_p25_mm3 DOUBLE,
    inflow_p75_mm3 DOUBLE,
    precipitation_mm DOUBLE CHECK (precipitation_mm >= 0),
    snowfall_cm DOUBLE,
    temperature_max_c DOUBLE,
    et0_fao_mm DOUBLE CHECK (et0_fao_mm >= 0),
    soil_moisture_deep_m3m3 DOUBLE,
    weather_is_filled BOOLEAN NOT NULL,
    run_id VARCHAR NOT NULL,
    ingested_at TIMESTAMP NOT NULL,
    PRIMARY KEY (node_id, date)
);
CREATE TABLE IF NOT EXISTS etl_run_log (
    run_id VARCHAR PRIMARY KEY,
    started_at TIMESTAMP, finished_at TIMESTAMP, duration_s DOUBLE,
    first_forecast_date DATE,
    rows_received INTEGER, rows_passed INTEGER, rows_rejected INTEGER,
    anomaly_warnings INTEGER, status VARCHAR
);
CREATE TABLE IF NOT EXISTS qa_rejections (
    run_id VARCHAR, node_id VARCHAR, date VARCHAR, reason VARCHAR
);
"""


def persist(
    db_path: Path,
    fact: pl.DataFrame,
    report: QAReport,
    run_id: str,
    started_at: datetime,
    first_forecast_date: date | None,
) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
    nodes = pl.DataFrame([{k: v for k, v in asdict(n).items()} for n in NODES])
    staged = fact.with_columns(
        pl.lit(run_id).alias("run_id"), pl.lit(finished_at).alias("ingested_at")
    )
    rejections = pl.DataFrame(
        report.rejections or None,
        schema={"node_id": pl.Utf8, "date": pl.Utf8, "reason": pl.Utf8},
    ).with_columns(pl.lit(run_id).alias("run_id"))
    status = "SUCCESS" if report.rows_rejected == 0 else "SUCCESS_WITH_REJECTIONS"

    with duckdb.connect(str(db_path)) as con:
        con.execute("BEGIN")
        con.execute(DDL)
        con.register("stg_nodes", nodes)
        con.execute(
            "INSERT INTO dim_basin_nodes SELECT node_id, name, node_type, river, lat, lon, "
            "glofas_lat, glofas_lon, capacity_mm3, baseline_storage_mm3, downstream_node_id, "
            "surface_area_full_km2 FROM stg_nodes"
        )
        con.register("stg_fact", staged)
        # Idempotent upsert: newer runs supersede overlapping node-days, older history is kept.
        con.execute(
            "DELETE FROM fact_hydro_daily f USING stg_fact s "
            "WHERE f.node_id = s.node_id AND f.date = s.date"
        )
        cols = ", ".join([*FACT_SCHEMA, "run_id", "ingested_at"])
        con.execute(f"INSERT INTO fact_hydro_daily ({cols}) SELECT {cols} FROM stg_fact")
        con.register("stg_rej", rejections)
        con.execute("INSERT INTO qa_rejections SELECT run_id, node_id, date, reason FROM stg_rej")
        con.execute(
            "INSERT INTO etl_run_log VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                run_id, started_at, finished_at,
                (finished_at - started_at).total_seconds(), first_forecast_date,
                report.rows_received, report.rows_passed, report.rows_rejected,
                len(report.warnings), status,
            ],
        )
        con.execute("COMMIT")


# =========================================================================== orchestration
def run_pipeline(
    db_path: Path = DB_PATH, transport: httpx.AsyncBaseTransport | None = None
) -> tuple[pl.DataFrame, QAReport]:
    started_at = datetime.now(timezone.utc).replace(tzinfo=None)
    run_id = started_at.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    t0 = time.perf_counter()

    payloads = asyncio.run(fetch_all(transport=transport))
    raw = build_fact_frame(payloads)
    clean_rows, report = validate_rows(raw.to_dicts())
    fact = pl.DataFrame(clean_rows, schema=FACT_SCHEMA)
    forecast_dates = fact.filter(pl.col("is_forecast"))["date"]
    first_forecast = forecast_dates.min() if forecast_dates.len() else None

    persist(db_path, fact, report, run_id, started_at, first_forecast)
    log.info(
        "run %s: %s rows received, %s passed, %s rejected, %s anomaly warnings in %.1fs",
        run_id, report.rows_received, report.rows_passed, report.rows_rejected,
        len(report.warnings), time.perf_counter() - t0,
    )
    for w in report.warnings:
        log.warning("anomaly: %s", w)
    for r in report.rejections[:20]:
        log.warning("rejected %s %s: %s", r["node_id"], r["date"], r["reason"])
    return fact, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=DB_PATH, help="DuckDB file to write")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run_pipeline(args.db)


if __name__ == "__main__":
    main()
