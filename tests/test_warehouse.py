"""Integration checks against the live ``data/hydro_warehouse.duckdb`` built by the ingestion.

Skipped automatically when the warehouse has not been built yet.
"""

from __future__ import annotations

import duckdb
import polars as pl
import pytest

from src import warehouse
from src.config import DB_PATH, GLOFAS_FORECAST_DAYS, HORIZON_DAYS, NODES, NODES_BY_ID
from src.models.water_optimizer import ScenarioParams, optimize

pytestmark = [
    pytest.mark.warehouse,
    pytest.mark.skipif(not DB_PATH.exists(), reason="warehouse not built - run the ingestion"),
]


@pytest.fixture(scope="module")
def con():
    # same configuration as the app's readers/writers (DuckDB refuses mixed configs in one process)
    with duckdb.connect(str(DB_PATH)) as c:
        yield c


@pytest.fixture(scope="module")
def hydro() -> pl.DataFrame:
    return warehouse.load_hydro()


def scalar(con, sql: str):
    return con.execute(sql).fetchone()[0]


def test_dim_nodes_match_official_capacities(con):
    rows = con.execute("SELECT node_id, capacity_mm3, baseline_storage_mm3, lat, lon "
                       "FROM dim_basin_nodes").fetchall()
    assert len(rows) == 4
    for node_id, cap, seed, lat, lon in rows:
        node = NODES_BY_ID[node_id]
        assert (cap, seed, lat, lon) == (node.capacity_mm3, node.baseline_storage_mm3,
                                         node.lat, node.lon)


def test_every_node_has_full_window(hydro):
    counts = hydro.group_by("node_id").agg(pl.len(), pl.col("is_forecast").sum().alias("fc"))
    assert counts.height == len(NODES)
    assert (counts["fc"] == GLOFAS_FORECAST_DAYS).all()
    assert (counts["len"] >= 100).all()


def test_no_physical_violations_in_warehouse(con):
    assert scalar(con, """
        SELECT count(*) FROM fact_hydro_daily
        WHERE river_discharge_m3s < 0 OR inflow_mm3 < 0 OR precipitation_mm < 0
           OR et0_fao_mm < 0 OR snowfall_cm < 0
           OR soil_moisture_deep_m3m3 NOT BETWEEN 0 AND 1
           OR discharge_p25_m3s > discharge_p75_m3s + 1e-9
    """) == 0


def test_unit_conversion_in_warehouse(con):
    assert scalar(con, "SELECT max(abs(inflow_mm3 - river_discharge_m3s * 86400 / 1e6)) "
                       "FROM fact_hydro_daily") < 1e-9


def test_no_duplicate_node_days(con):
    assert scalar(con, "SELECT count(*) FROM (SELECT node_id, date FROM fact_hydro_daily "
                       "GROUP BY ALL HAVING count(*) > 1)") == 0


def test_forecast_days_have_weather(hydro):
    """Forecast days 1-16 come from the API, 17-30 are forward-filled - none may be null."""
    fc = hydro.filter(pl.col("is_forecast"))
    assert fc["et0_fao_mm"].null_count() == 0
    assert fc["weather_is_filled"].sum() > 0
    assert not hydro.filter(~pl.col("is_forecast"))["weather_is_filled"].any()


def test_cascade_is_physically_plausible(hydro):
    """Al Massira (downstream) should carry more mean flow than each upstream dam cell -
    guards against GloFAS snapping to a tributary cell."""
    mean_q = dict(hydro.group_by("node_id").agg(pl.col("river_discharge_m3s").mean()).iter_rows())
    assert mean_q["DAM_AL_MASSIRA"] > mean_q["DAM_AHMED_EL_HANSALI"]
    assert mean_q["DAM_AL_MASSIRA"] > mean_q["DAM_BIN_EL_OUIDANE"]
    assert mean_q["DAM_AHMED_EL_HANSALI"] > mean_q["KHENIFRA_HEADWATERS"]


def test_latest_run_logged(con):
    status, received, passed = con.execute(
        "SELECT status, rows_received, rows_passed FROM etl_run_log "
        "ORDER BY started_at DESC LIMIT 1").fetchone()
    assert status.startswith("SUCCESS") and passed <= received and passed > 0


@pytest.mark.parametrize("params", [
    ScenarioParams(),
    ScenarioParams(inflow_forecast="p25", inflow_shock_pct=-50, safety_buffer_pct=40),
    ScenarioParams(inflow_forecast="p75", inflow_shock_pct=50, irrigation_cap_pct=120),
    ScenarioParams(initial_storage_pct=25, buffer_mode="hard"),
])
def test_optimizer_solves_on_live_data(hydro, params):
    res = optimize(hydro, params)
    assert res.is_optimal and res.status in ("Optimal", "Deficit Warning")
    assert res.daily["day"].max() == HORIZON_DAYS
