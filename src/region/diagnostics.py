"""Data-driven drought diagnostics from the long-term warehouse tables.

All anomalies are relative to the 1998–2018 reference period (21 hydrological years common
to ERA5 and GloFAS, before the 2019+ drought sequence).
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from src.config import DB_PATH
from src.warehouse import _query

REF_START, REF_END = 1998, 2018


def _hy(col: str = "month") -> pl.Expr:
    return (pl.when(pl.col(col).dt.month() >= 9).then(pl.col(col).dt.year() + 1)
            .otherwise(pl.col(col).dt.year()).alias("hy"))


def load_climate_monthly(db_path: Path = DB_PATH) -> pl.DataFrame:
    return _query("SELECT * FROM fact_climate_monthly ORDER BY province_id, month", db_path)


def load_discharge_monthly(db_path: Path = DB_PATH) -> pl.DataFrame:
    return _query("SELECT * FROM fact_discharge_monthly ORDER BY node_id, month", db_path)


def hydro_year_table(climate: pl.DataFrame, discharge: pl.DataFrame) -> pl.DataFrame:
    """One row per complete hydrological year: regional climate means + Al Massira inflow,
    with anomalies vs. the reference period."""
    clim = (
        climate.with_columns(_hy())
        .group_by("hy", "province_id")
        .agg(pl.col("precip_mm").sum(), pl.col("snow_cm").sum(), pl.col("tmean_c").mean(),
             pl.col("et0_mm").sum(), pl.len().alias("n"))
        .filter(pl.col("n") == 12)
        .group_by("hy")
        .agg(pl.col("precip_mm").mean(), pl.col("snow_cm").mean(), pl.col("tmean_c").mean(),
             pl.col("et0_mm").mean(), pl.len().alias("provinces"))
    )
    flow = (
        discharge.filter(pl.col("node_id") == "DAM_AL_MASSIRA")
        .with_columns(_hy())
        .group_by("hy").agg(pl.col("volume_mm3").sum().alias("inflow_mm3"), pl.len().alias("n"))
        .filter(pl.col("n") == 12).drop("n")
    )
    df = clim.join(flow, on="hy", how="left").sort("hy")
    ref = df.filter(pl.col("hy").is_between(REF_START, REF_END))
    means = {c: ref[c].mean() for c in ("precip_mm", "snow_cm", "tmean_c", "et0_mm", "inflow_mm3")}
    return df.with_columns(
        ((pl.col("precip_mm") / means["precip_mm"] - 1) * 100).alias("precip_anom_pct"),
        ((pl.col("inflow_mm3") / means["inflow_mm3"] - 1) * 100).alias("inflow_anom_pct"),
        (pl.col("tmean_c") - means["tmean_c"]).alias("temp_anom_c"),
        ((pl.col("et0_mm") / means["et0_mm"] - 1) * 100).alias("et0_anom_pct"),
        ((pl.col("snow_cm") / means["snow_cm"] - 1) * 100).alias("snow_anom_pct"),
    )


def drought_streak(table: pl.DataFrame, threshold_pct: float = -20.0) -> tuple[int, int, int]:
    """Longest run of consecutive years with inflow anomaly below ``threshold_pct``:
    returns (length, first_year, last_year)."""
    best = (0, 0, 0)
    run_start, run_len = None, 0
    for hy, a in table.select("hy", "inflow_anom_pct").drop_nulls().iter_rows():
        if a < threshold_pct:
            run_start = hy if run_len == 0 else run_start
            run_len += 1
            if run_len > best[0]:
                best = (run_len, run_start, hy)
        else:
            run_len = 0
    return best


def amplification(table: pl.DataFrame, years: tuple[int, int]) -> dict[str, float]:
    """Mean anomalies over a period: shows rain deficits turning into larger flow deficits."""
    sub = table.filter(pl.col("hy").is_between(*years))
    return {
        "precip_anom_pct": float(sub["precip_anom_pct"].mean()),
        "inflow_anom_pct": float(sub["inflow_anom_pct"].mean()),
        "temp_anom_c": float(sub["temp_anom_c"].mean()),
        "et0_anom_pct": float(sub["et0_anom_pct"].mean()),
        "snow_anom_pct": float(sub["snow_anom_pct"].mean()),
    }
