"""Central configuration: basin topology, official ABHOER capacities, API contracts and
operating assumptions for the Oum Er-Rbia decision support system.

Everything that is an *assumption* (not an official figure) is grouped in
``OPERATING_ASSUMPTIONS`` / ``DEMANDS`` and documented so it can be swapped for
real ABHOER / ONEE / ORMVA figures without touching model code.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# --------------------------------------------------------------------------- paths
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "hydro_warehouse.duckdb"

# --------------------------------------------------------------------------- basin nodes
NodeType = Literal["river_gauge", "reservoir"]


@dataclass(frozen=True)
class BasinNode:
    node_id: str
    name: str
    node_type: NodeType
    river: str
    lat: float
    lon: float
    # GloFAS v4 runs on a ~0.05° grid. The official dam coordinates fall on small
    # side-stream cells (0.0-0.1 m3/s), so discharge is queried at the nearest
    # main-stem cell, found by a 7x7 neighbourhood search maximising mean flow
    # (see docs/PROJECT_SPEC.md and CLAUDE.md "GloFAS cell snapping").
    glofas_lat: float
    glofas_lon: float
    capacity_mm3: float | None = None
    baseline_storage_mm3: float | None = None
    downstream_node_id: str | None = None
    # Approximate lake surface at normal capacity, used for open-water evaporation.
    surface_area_full_km2: float | None = None

    @property
    def is_reservoir(self) -> bool:
        return self.node_type == "reservoir"


KHENIFRA = "KHENIFRA_HEADWATERS"
HANSALI = "DAM_AHMED_EL_HANSALI"
BIN_EL_OUIDANE = "DAM_BIN_EL_OUIDANE"
AL_MASSIRA = "DAM_AL_MASSIRA"

# Capacities & seed storage: Ministry of Equipment & Water figures of 1 Sept 2026 (Le360,
# 2026-09-02 - knowledge-base source S2). The original brief's 2019-era references are kept
# in comments; the ministry revised its reference capacities in 2026.
NODES: tuple[BasinNode, ...] = (
    BasinNode(
        node_id=KHENIFRA,
        name="Oum Er-Rbia Headwaters - Khénifra",
        node_type="river_gauge",
        river="Oum Er-Rbia",
        lat=32.9394,
        lon=-5.6686,
        glofas_lat=32.9394,
        glofas_lon=-5.7186,
        downstream_node_id=HANSALI,
    ),
    BasinNode(
        node_id=HANSALI,
        name="Barrage Ahmed El Hansali",
        node_type="reservoir",
        river="Oum Er-Rbia",
        lat=32.5150,
        lon=-5.9220,
        glofas_lat=32.3650,
        glofas_lon=-5.9220,
        capacity_mm3=697.18,  # brief: 668.0
        baseline_storage_mm3=555.63,  # 1 Sept 2026 (79.7%); brief seed: 385.0
        downstream_node_id=AL_MASSIRA,
        surface_area_full_km2=27.0,
    ),
    BasinNode(
        node_id=BIN_EL_OUIDANE,
        name="Barrage Bin El Ouidane",
        node_type="reservoir",
        river="Oued El Abid",
        lat=32.1060,
        lon=-6.4640,
        glofas_lat=32.1060,
        glofas_lon=-6.5140,
        capacity_mm3=1273.40,  # brief: 1215.0
        baseline_storage_mm3=1055.36,  # 1 Sept 2026 (82.9%); brief seed: 640.0
        downstream_node_id=AL_MASSIRA,
        surface_area_full_km2=38.0,
    ),
    BasinNode(
        node_id=AL_MASSIRA,
        name="Barrage Al Massira",
        node_type="reservoir",
        river="Oum Er-Rbia",
        lat=32.4730,
        lon=-7.6380,
        glofas_lat=32.4730,
        glofas_lon=-7.6880,
        capacity_mm3=2649.54,  # brief: 2656.0
        baseline_storage_mm3=1065.48,  # 1 Sept 2026 (40.2%); brief seed: 1120.0
        downstream_node_id=None,
        surface_area_full_km2=120.0,
    ),
)

NODES_BY_ID: dict[str, BasinNode] = {n.node_id: n for n in NODES}
NODE_IDS: tuple[str, ...] = tuple(NODES_BY_ID)
RESERVOIRS: tuple[BasinNode, ...] = tuple(n for n in NODES if n.is_reservoir)
RESERVOIR_IDS: tuple[str, ...] = tuple(n.node_id for n in RESERVOIRS)
# Reservoirs whose controlled river releases (ecological flow + spill) feed Al Massira.
UPSTREAM_OF: dict[str, tuple[str, ...]] = {
    AL_MASSIRA: (HANSALI, BIN_EL_OUIDANE),
    HANSALI: (),
    BIN_EL_OUIDANE: (),
}

# --------------------------------------------------------------------------- APIs
TIMEZONE = "Africa/Casablanca"
HISTORY_DAYS = 92
GLOFAS_FORECAST_DAYS = 30
WEATHER_FORECAST_DAYS = 16
HORIZON_DAYS = 30

GLOFAS_URL = "https://flood-api.open-meteo.com/v1/flood"
GLOFAS_DAILY_VARS = (
    "river_discharge",
    "river_discharge_mean",
    "river_discharge_p25",
    "river_discharge_p75",
)

WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
WEATHER_DAILY_VARS = (
    "precipitation_sum",
    "snowfall_sum",
    "temperature_2m_max",
    "et0_fao_evapotranspiration",
)
WEATHER_HOURLY_VARS = ("soil_moisture_28_to_100cm",)

HTTP_TIMEOUT_S = 45.0
HTTP_MAX_RETRIES = 4

# m3/s sustained for one day -> million m3
SECONDS_PER_DAY = 86_400
M3S_TO_MM3_PER_DAY = SECONDS_PER_DAY / 1_000_000

# --------------------------------------------------------------------------- optimisation
PRIORITY_WEIGHTS: dict[str, float] = {
    "potable": 10.0,  # ONEE urban drinking water
    "ecological": 8.0,  # minimum environmental river flow
    "irrigation": 5.0,  # Tadla (Beni Amir / Beni Moussa) & Doukkala perimeters
}


@dataclass(frozen=True)
class ReservoirDemand:
    """Daily demand assumptions in Mm3/day (illustrative, order-of-magnitude figures)."""

    potable_mm3: float
    irrigation_base_mm3: float  # at the reference ET0, before the user cap
    ecological_mm3: float
    irrigation_perimeter: str


DEMANDS: dict[str, ReservoirDemand] = {
    # Khouribga / Kasba Tadla supply + Beni Amir perimeter (Tadla rive droite)
    HANSALI: ReservoirDemand(0.06, 0.90, 0.15, "Tadla – Beni Amir"),
    # Beni Mellal / Azilal supply + Beni Moussa perimeter (Tadla rive gauche)
    BIN_EL_OUIDANE: ReservoirDemand(0.08, 1.60, 0.10, "Tadla – Beni Moussa"),
    # Casablanca–El Jadida–Safi–Marrakech transfers + Doukkala perimeter
    AL_MASSIRA: ReservoirDemand(0.55, 1.80, 0.30, "Doukkala"),
}

OPERATING_ASSUMPTIONS = {
    "et0_reference_mm": 5.0,  # irrigation demand = base * ET0_t / reference
    "open_water_kc": 1.05,  # open-water evaporation = Kc * ET0 * lake area
    # Penalty per Mm3 of end-of-horizon storage below the safety buffer.
    # Soft: between irrigation (5) and ecological (8) -> irrigation is hedged to protect
    # the buffer, potable & ecological flow are not. Hard: dominates every demand weight.
    "buffer_penalty_soft": 6.5,
    "buffer_penalty_hard": 1_000.0,
    # Small daily penalty on storage below the buffer: discourages mid-horizon dips.
    # It accumulates over the horizon (a release on day 1 lowers all 30 later days), so
    # buffer_penalty_soft + 30 * daily must stay below the irrigation deep-cut weight 7.5.
    "buffer_daily_penalty": 0.01,
    "excess_release_penalty": 0.01,  # tie-breaker: no voluntary spill / transfer
    # Irrigation hedging rule: shortfall beyond this share of demand costs more, so the
    # solver rations irrigation (e.g. to 50%) before cutting it entirely. The deep-cut
    # weight (5 * 1.5 = 7.5) stays below ecological (8) to keep strict priority order.
    "irrigation_hedge_share": 0.5,
    "irrigation_deep_cut_multiplier": 1.5,
    "min_storage_pct": 5.0,  # physical dead storage (hard floor, % of capacity)
    "deficit_tolerance_pct": 0.5,  # unmet share of demand tolerated before a warning
}

DEFAULT_SCENARIO = {
    "inflow_forecast": "mean",  # mean | p25 | p75
    "inflow_shock_pct": 0.0,  # -50 .. +50
    "irrigation_cap_pct": 100.0,  # 50 .. 120
    "safety_buffer_pct": 20.0,  # 10 .. 40
    "initial_storage_pct": 100.0,  # % of baseline seed storage
    "buffer_mode": "soft",  # soft | hard
}
