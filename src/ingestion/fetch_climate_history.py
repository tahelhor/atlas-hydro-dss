"""Long-term climate & river-flow history -> monthly DuckDB tables.

Run:  uv run python -m src.ingestion.fetch_climate_history

* ERA5 reanalysis (Open-Meteo archive API, keyless), 1991 → today-7d, sampled at the 5
  provincial capitals: precipitation, snowfall, mean/max temperature, FAO-56 ET0.
* GloFAS v4 reanalysis (Open-Meteo flood API), 1997 → today, at the 4 basin river cells.

Daily payloads are validated (pydantic), aggregated to calendar months with polars and
upserted into ``fact_climate_monthly`` / ``fact_discharge_monthly``. These feed the
drought diagnostics and the 12-month drought stress-test planner.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import duckdb
import httpx
import polars as pl
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from src.config import DB_PATH, GLOFAS_URL, HTTP_TIMEOUT_S, M3S_TO_MM3_PER_DAY, NODES, TIMEZONE
from src.ingestion.fetch_hydro_climate import fetch_json
from src.ingestion.validator import _DailyBlock
from src.region.provinces import PROVINCES

log = logging.getLogger("atlas.history")

ERA5_URL = "https://archive-api.open-meteo.com/v1/archive"
ERA5_START = date(1991, 1, 1)
GLOFAS_HISTORY_START = date(1997, 1, 1)  # earlier GloFAS reanalysis days are null on this API
ERA5_LAG_DAYS = 7
ERA5_DAILY = {
    "precipitation_sum": "precip_mm",
    "snowfall_sum": "snow_cm",
    "temperature_2m_mean": "tmean_c",
    "temperature_2m_max": "tmax_c",
    "et0_fao_evapotranspiration": "et0_mm",
}


# =========================================================================== contracts
class ERA5Payload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    daily: _DailyBlock

    @model_validator(mode="after")
    def _vars(self) -> ERA5Payload:
        missing = set(ERA5_DAILY) - set(self.daily.model_extra or {})
        if missing:
            raise ValueError(f"ERA5 payload missing variables: {sorted(missing)}")
        return self


class GloFASHistoryPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    latitude: float
    longitude: float
    daily: _DailyBlock

    @model_validator(mode="after")
    def _vars(self) -> GloFASHistoryPayload:
        if "river_discharge" not in (self.daily.model_extra or {}):
            raise ValueError("GloFAS history payload missing river_discharge")
        return self


class ClimateMonthlyRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    province_id: str
    month: date
    n_days: int = Field(ge=1, le=31)
    precip_mm: float = Field(ge=0, le=2_000)
    snow_cm: float = Field(ge=0, le=1_000)
    tmean_c: float = Field(ge=-25, le=45)
    tmax_c: float = Field(ge=-20, le=55)
    et0_mm: float = Field(ge=0, le=400)

    @model_validator(mode="after")
    def _first_of_month(self) -> ClimateMonthlyRecord:
        if self.month.day != 1:
            raise ValueError("month must be the first day of the month")
        return self


class DischargeMonthlyRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_id: str
    month: date
    n_days: int = Field(ge=1, le=31)
    discharge_m3s_mean: float = Field(ge=0, le=20_000)
    volume_mm3: float = Field(ge=0)


# =========================================================================== transforms
def era5_monthly(payload: ERA5Payload, province_id: str) -> pl.DataFrame:
    d = payload.daily.model_extra or {}
    daily = pl.DataFrame(
        {"date": payload.daily.time, **{new: d[old] for old, new in ERA5_DAILY.items()}},
        schema_overrides={c: pl.Float64 for c in ERA5_DAILY.values()},
    ).drop_nulls()
    return (
        daily.with_columns(pl.col("date").dt.truncate("1mo").alias("month"))
        .group_by("month")
        .agg(
            pl.len().cast(pl.Int64).alias("n_days"),
            pl.col("precip_mm").sum(),
            pl.col("snow_cm").sum(),
            pl.col("tmean_c").mean(),
            pl.col("tmax_c").mean(),
            pl.col("et0_mm").sum(),
        )
        .with_columns(pl.lit(province_id).alias("province_id"))
        .sort("month")
    )


def glofas_monthly(payload: GloFASHistoryPayload, node_id: str) -> pl.DataFrame:
    d = payload.daily.model_extra or {}
    daily = pl.DataFrame(
        {"date": payload.daily.time, "q": d["river_discharge"]},
        schema_overrides={"q": pl.Float64},
    ).drop_nulls()
    return (
        daily.with_columns(pl.col("date").dt.truncate("1mo").alias("month"))
        .group_by("month")
        .agg(
            pl.len().cast(pl.Int64).alias("n_days"),
            pl.col("q").mean().alias("discharge_m3s_mean"),
            (pl.col("q") * M3S_TO_MM3_PER_DAY).sum().alias("volume_mm3"),
        )
        .with_columns(pl.lit(node_id).alias("node_id"))
        .sort("month")
    )


def validate_monthly(df: pl.DataFrame, model: type[BaseModel]) -> tuple[pl.DataFrame, list[str]]:
    clean, errors = [], []
    for row in df.to_dicts():
        try:
            clean.append(model.model_validate(row).model_dump())
        except ValidationError as exc:
            errors.append(f"{row}: {exc.errors()[0]['msg']}")
    return pl.DataFrame(clean, schema=df.schema).select(list(model.model_fields)), errors


# =========================================================================== fetch
async def _fetch_all(transport: httpx.AsyncBaseTransport | None, end: date) -> tuple[dict, dict]:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_S * 3, transport=transport) as client:
        era5_tasks = [
            fetch_json(client, ERA5_URL, {
                "latitude": p.lat, "longitude": p.lon,
                "start_date": ERA5_START.isoformat(), "end_date": (end - timedelta(days=ERA5_LAG_DAYS)).isoformat(),
                "daily": ",".join(ERA5_DAILY), "timezone": TIMEZONE,
            })
            for p in PROVINCES
        ]
        glofas_tasks = [
            fetch_json(client, GLOFAS_URL, {
                "latitude": n.glofas_lat, "longitude": n.glofas_lon,
                "start_date": GLOFAS_HISTORY_START.isoformat(), "end_date": end.isoformat(),
                "daily": "river_discharge",
            })
            for n in NODES
        ]
        # sequential groups keep the archive API within its fair-use rate limits
        era5 = await asyncio.gather(*era5_tasks)
        glofas = await asyncio.gather(*glofas_tasks)
    return (
        {p.province_id: ERA5Payload.model_validate(r) for p, r in zip(PROVINCES, era5)},
        {n.node_id: GloFASHistoryPayload.model_validate(r) for n, r in zip(NODES, glofas)},
    )


DDL = """
CREATE TABLE IF NOT EXISTS fact_climate_monthly (
    province_id VARCHAR NOT NULL, month DATE NOT NULL, n_days INTEGER NOT NULL,
    precip_mm DOUBLE NOT NULL CHECK (precip_mm >= 0), snow_cm DOUBLE NOT NULL,
    tmean_c DOUBLE NOT NULL, tmax_c DOUBLE NOT NULL, et0_mm DOUBLE NOT NULL CHECK (et0_mm >= 0),
    PRIMARY KEY (province_id, month)
);
CREATE TABLE IF NOT EXISTS fact_discharge_monthly (
    node_id VARCHAR NOT NULL, month DATE NOT NULL, n_days INTEGER NOT NULL,
    discharge_m3s_mean DOUBLE NOT NULL CHECK (discharge_m3s_mean >= 0),
    volume_mm3 DOUBLE NOT NULL CHECK (volume_mm3 >= 0),
    PRIMARY KEY (node_id, month)
);
CREATE TABLE IF NOT EXISTS etl_history_log (
    run_id VARCHAR PRIMARY KEY, finished_at TIMESTAMP, climate_rows INTEGER,
    discharge_rows INTEGER, rejected_rows INTEGER, last_climate_month DATE, last_discharge_month DATE
);
"""


def persist(db_path: Path, climate: pl.DataFrame, discharge: pl.DataFrame, rejected: int) -> str:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(db_path)) as con:
        con.execute("BEGIN")
        con.execute(DDL)
        for table, df, key in (("fact_climate_monthly", climate, "province_id"),
                               ("fact_discharge_monthly", discharge, "node_id")):
            con.register("stg", df)
            con.execute(f"DELETE FROM {table} t USING stg s WHERE t.{key} = s.{key} AND t.month = s.month")
            cols = ", ".join(df.columns)
            con.execute(f"INSERT INTO {table} ({cols}) SELECT {cols} FROM stg")
            con.unregister("stg")
        con.execute(
            "INSERT INTO etl_history_log VALUES (?, ?, ?, ?, ?, ?, ?)",
            [run_id, datetime.now(timezone.utc).replace(tzinfo=None), climate.height,
             discharge.height, rejected, climate["month"].max(), discharge["month"].max()],
        )
        con.execute("COMMIT")
    return run_id


def run_history_pipeline(
    db_path: Path = DB_PATH,
    transport: httpx.AsyncBaseTransport | None = None,
    end: date | None = None,
) -> tuple[pl.DataFrame, pl.DataFrame, list[str]]:
    end = end or date.today()
    era5, glofas = asyncio.run(_fetch_all(transport, end))
    climate_raw = pl.concat([era5_monthly(p, pid) for pid, p in era5.items()])
    discharge_raw = pl.concat([glofas_monthly(p, nid) for nid, p in glofas.items()])
    climate, e1 = validate_monthly(climate_raw, ClimateMonthlyRecord)
    discharge, e2 = validate_monthly(discharge_raw, DischargeMonthlyRecord)
    run_id = persist(db_path, climate, discharge, len(e1) + len(e2))
    log.info("history run %s: %s climate-months, %s discharge-months, %s rejected",
             run_id, climate.height, discharge.height, len(e1) + len(e2))
    for e in (e1 + e2)[:20]:
        log.warning("rejected: %s", e)
    return climate, discharge, e1 + e2


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=DB_PATH)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    run_history_pipeline(args.db)


if __name__ == "__main__":
    main()


__all__: list[Any] = ["run_history_pipeline", "era5_monthly", "glofas_monthly",
                      "ClimateMonthlyRecord", "DischargeMonthlyRecord"]
