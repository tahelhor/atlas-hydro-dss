"""30-day multi-reservoir release optimisation (PuLP / CBC linear program).

Topology (cascade)::

    Khénifra gauge ──► Ahmed El Hansali ──┐
                                          ├──► Al Massira ──► Atlantic
                       Bin El Ouidane  ───┘

Decision variables per reservoir r and day t (all Mm3, continuous, >= 0):
    potable[r,t], irrigation[r,t], ecological[r,t]  deliveries (<= demand)
    excess[r,t]     extra river release (spill / transfer to the downstream reservoir)
    storage[r,t]    end-of-day storage, bounded by [dead storage, capacity]
    shortfall[r,t]  storage below the safety buffer (soft-constraint slack)

Mass balance (day t, S_0 = initial storage)::

    S[r,t] = S[r,t-1] + local_inflow[r,t] + Σ_u∈up(r) (eco[u,t] + excess[u,t])
             - evap[r,t] - potable[r,t] - irrigation[r,t] - eco[r,t] - excess[r,t]

Potable and irrigation are consumptive withdrawals (canals / pipelines); ecological flow
and excess releases stay in the river and become inflow to Al Massira the same day.

Objective (minimise)::

    Σ_r,t  w_use · (demand - delivered)            weighted unmet demand
         + 0.5·w_irr · deep_cut[r,t]                irrigation cut below the 50% hedge share
         + w_buf · shortfall[r,T]                   end-of-horizon buffer breach
         + w_day · Σ_t shortfall[r,t]               discourage mid-horizon dips
         + ε · excess[r,t]                          no voluntary spill
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

import polars as pl
import pulp

from src.config import (
    AL_MASSIRA,
    BIN_EL_OUIDANE,
    DEFAULT_SCENARIO,
    DEMANDS,
    HANSALI,
    HORIZON_DAYS,
    NODES_BY_ID,
    OPERATING_ASSUMPTIONS,
    PRIORITY_WEIGHTS,
    RESERVOIR_IDS,
    UPSTREAM_OF,
)

USES = ("potable", "ecological", "irrigation")
InflowForecast = Literal["mean", "p25", "p75"]
BufferMode = Literal["soft", "hard"]


# =========================================================================== inputs
@dataclass(frozen=True)
class ScenarioParams:
    inflow_forecast: InflowForecast = DEFAULT_SCENARIO["inflow_forecast"]
    inflow_shock_pct: float = DEFAULT_SCENARIO["inflow_shock_pct"]
    irrigation_cap_pct: float = DEFAULT_SCENARIO["irrigation_cap_pct"]
    safety_buffer_pct: float = DEFAULT_SCENARIO["safety_buffer_pct"]
    initial_storage_pct: float = DEFAULT_SCENARIO["initial_storage_pct"]
    buffer_mode: BufferMode = DEFAULT_SCENARIO["buffer_mode"]

    def __post_init__(self) -> None:
        if self.inflow_forecast not in ("mean", "p25", "p75"):
            raise ValueError(f"inflow_forecast must be mean|p25|p75, got {self.inflow_forecast}")
        if not -50 <= self.inflow_shock_pct <= 50:
            raise ValueError("inflow_shock_pct must be within [-50, 50]")
        if not 50 <= self.irrigation_cap_pct <= 120:
            raise ValueError("irrigation_cap_pct must be within [50, 120]")
        if not 10 <= self.safety_buffer_pct <= 40:
            raise ValueError("safety_buffer_pct must be within [10, 40]")
        if not 25 <= self.initial_storage_pct <= 150:
            raise ValueError("initial_storage_pct must be within [25, 150]")
        if self.buffer_mode not in ("soft", "hard"):
            raise ValueError("buffer_mode must be soft|hard")


@dataclass
class ReservoirSeries:
    node_id: str
    capacity: float
    initial_storage: float
    local_inflow: list[float]
    evaporation: list[float]
    potable_demand: list[float]
    irrigation_demand: list[float]
    ecological_demand: list[float]
    et0: list[float]


@dataclass
class OptimizationInputs:
    dates: list[date]
    reservoirs: dict[str, ReservoirSeries]
    params: ScenarioParams

    @property
    def horizon(self) -> int:
        return len(self.dates)


def _scenario_inflow_col(forecast: InflowForecast) -> pl.Expr:
    if forecast == "p25":
        return pl.coalesce("inflow_p25_mm3", "inflow_mm3")
    if forecast == "p75":
        return pl.coalesce("inflow_p75_mm3", "inflow_mm3")
    return pl.col("inflow_mm3")


def build_inputs(
    hydro: pl.DataFrame,
    params: ScenarioParams = ScenarioParams(),
    horizon_days: int = HORIZON_DAYS,
) -> OptimizationInputs:
    """Turn forecast rows of ``fact_hydro_daily`` into LP input series.

    Al Massira's GloFAS discharge already contains the upstream rivers, so its *local*
    inflow is the residual ``Q_massira - Q_hansali - Q_bin_el_ouidane`` (clipped at 0);
    upstream water only reaches it through the optimised river releases.
    """
    fc = (
        hydro.filter(pl.col("is_forecast") & pl.col("node_id").is_in(RESERVOIR_IDS))
        .with_columns(_scenario_inflow_col(params.inflow_forecast).alias("q"))
        .sort("date")
    )
    dates = sorted(fc["date"].unique().to_list())[:horizon_days]
    if not dates:
        raise ValueError("no forecast rows for reservoirs - run the ingestion first")
    wide = (
        fc.filter(pl.col("date").is_in(dates))
        .pivot(on="node_id", index="date", values=["q", "et0_fao_mm"])
        .sort("date")
    )
    for col in wide.columns:
        if col != "date":
            # Gaps from quarantined rows: carry neighbours, never invent water from nothing.
            wide = wide.with_columns(pl.col(col).forward_fill().backward_fill().fill_null(0.0))

    shock = 1.0 + params.inflow_shock_pct / 100.0
    q = {r: [v * shock for v in wide[f"q_{r}"].to_list()] for r in RESERVOIR_IDS}
    local = dict(q)
    local[AL_MASSIRA] = [
        max(m - h - b, 0.0) for m, h, b in zip(q[AL_MASSIRA], q[HANSALI], q[BIN_EL_OUIDANE])
    ]

    kc = OPERATING_ASSUMPTIONS["open_water_kc"]
    et0_ref = OPERATING_ASSUMPTIONS["et0_reference_mm"]
    reservoirs: dict[str, ReservoirSeries] = {}
    for r in RESERVOIR_IDS:
        node = NODES_BY_ID[r]
        demand = DEMANDS[r]
        s0 = min(node.baseline_storage_mm3 * params.initial_storage_pct / 100.0, node.capacity_mm3)
        # Lake area scales ~ (S/C)^(2/3) for a cone-shaped basin; frozen at S0 to stay linear.
        area_km2 = node.surface_area_full_km2 * (s0 / node.capacity_mm3) ** (2 / 3)
        et0 = wide[f"et0_fao_mm_{r}"].to_list()
        reservoirs[r] = ReservoirSeries(
            node_id=r,
            capacity=node.capacity_mm3,
            initial_storage=s0,
            local_inflow=local[r],
            # mm * km2 = 1e-3 m * 1e6 m2 = 1e3 m3 = 1e-3 Mm3
            evaporation=[kc * e * area_km2 / 1000.0 for e in et0],
            potable_demand=[demand.potable_mm3] * len(dates),
            irrigation_demand=[
                demand.irrigation_base_mm3 * (e / et0_ref) * params.irrigation_cap_pct / 100.0
                for e in et0
            ],
            ecological_demand=[demand.ecological_mm3] * len(dates),
            et0=et0,
        )
    return OptimizationInputs(dates=dates, reservoirs=reservoirs, params=params)


# =========================================================================== solver
def _solver() -> pulp.LpSolver:
    """HiGHS in-process (``pulp[highs]``); fall back to any CBC binary on PATH."""
    for candidate in (pulp.HiGHS(msg=False), pulp.COIN_CMD(msg=False)):
        if candidate.available():
            return candidate
    raise RuntimeError("no LP solver available - install with `uv add 'pulp[highs]'`")


@dataclass
class OptimizationResult:
    status: str  # Optimal | Deficit Warning | Infeasible
    solver_status: str
    objective: float
    solve_seconds: float
    daily: pl.DataFrame
    summary: dict[str, float] = field(default_factory=dict)

    @property
    def is_optimal(self) -> bool:
        return self.solver_status == "Optimal"


def solve(inputs: OptimizationInputs) -> OptimizationResult:
    p = inputs.params
    T = range(inputs.horizon)
    R = list(inputs.reservoirs)
    res = inputs.reservoirs
    buf_weight = OPERATING_ASSUMPTIONS[f"buffer_penalty_{p.buffer_mode}"]
    day_weight = OPERATING_ASSUMPTIONS["buffer_daily_penalty"]
    eps = OPERATING_ASSUMPTIONS["excess_release_penalty"]
    floor_pct = OPERATING_ASSUMPTIONS["min_storage_pct"] / 100.0

    prob = pulp.LpProblem("oum_er_rbia_allocation", pulp.LpMinimize)
    demand = {
        (r, u): getattr(res[r], f"{u}_demand") for r in R for u in USES
    }
    # PuLP >= 4 (Rust core) creates variables through the problem instance.
    var = prob.add_variable
    x = {
        (r, u, t): var(f"{u}_{r}_{t}", lowBound=0, upBound=demand[r, u][t])
        for r in R for u in USES for t in T
    }
    excess = {(r, t): var(f"excess_{r}_{t}", lowBound=0) for r in R for t in T}
    storage = {
        (r, t): var(f"storage_{r}_{t}", lowBound=floor_pct * res[r].capacity,
                    upBound=res[r].capacity)
        for r in R for t in T
    }
    shortfall = {(r, t): var(f"shortfall_{r}_{t}", lowBound=0) for r in R for t in T}
    # Irrigation shortfall beyond the hedge share (piecewise-linear convex penalty).
    deep_cut = {(r, t): var(f"irr_deep_cut_{r}_{t}", lowBound=0) for r in R for t in T}
    buffer = {r: p.safety_buffer_pct / 100.0 * res[r].capacity for r in R}
    hedge = OPERATING_ASSUMPTIONS["irrigation_hedge_share"]
    deep_extra = PRIORITY_WEIGHTS["irrigation"] * (
        OPERATING_ASSUMPTIONS["irrigation_deep_cut_multiplier"] - 1
    )

    last = inputs.horizon - 1
    prob += (
        pulp.lpSum(
            PRIORITY_WEIGHTS[u] * (demand[r, u][t] - x[r, u, t]) for r in R for u in USES for t in T
        )
        + pulp.lpSum(deep_extra * deep_cut[r, t] for r in R for t in T)
        + pulp.lpSum(buf_weight * shortfall[r, last] for r in R)
        + pulp.lpSum(day_weight * shortfall[r, t] for r in R for t in T)
        + pulp.lpSum(eps * excess[r, t] for r in R for t in T)
    )

    for r in R:
        for t in T:
            prev = res[r].initial_storage if t == 0 else storage[r, t - 1]
            upstream = pulp.lpSum(x[u, "ecological", t] + excess[u, t] for u in UPSTREAM_OF[r])
            prob += (
                storage[r, t]
                == prev + res[r].local_inflow[t] + upstream - res[r].evaporation[t]
                - pulp.lpSum(x[r, u, t] for u in USES) - excess[r, t],
                f"mass_balance_{r}_{t}",
            )
            prob += storage[r, t] + shortfall[r, t] >= buffer[r], f"buffer_{r}_{t}"
            prob += (
                deep_cut[r, t] >= (1 - hedge) * demand[r, "irrigation"][t] - x[r, "irrigation", t],
                f"irrigation_hedge_{r}_{t}",
            )

    t0 = time.perf_counter()
    stats = prob.solve(_solver())  # PuLP 4 returns an LpSolveStats record
    elapsed = time.perf_counter() - t0
    solver_status = stats.status.name

    if stats.status != pulp.LpSolveStatus.Optimal or not stats.has_solution:
        return OptimizationResult("Infeasible", solver_status, float("nan"), elapsed,
                                  pl.DataFrame(), {})

    def v(var: pulp.LpVariable) -> float:
        return max(float(var.value() or 0.0), 0.0)

    rows = []
    for r in R:
        for t in T:
            upstream_in = sum(v(x[u, "ecological", t]) + v(excess[u, t]) for u in UPSTREAM_OF[r])
            row = {
                "node_id": r,
                "name": NODES_BY_ID[r].name,
                "day": t + 1,
                "date": inputs.dates[t],
                "local_inflow_mm3": res[r].local_inflow[t],
                "upstream_release_in_mm3": upstream_in,
                "evaporation_mm3": res[r].evaporation[t],
                "excess_release_mm3": v(excess[r, t]),
                "storage_start_mm3": res[r].initial_storage if t == 0 else v(storage[r, t - 1]),
                "storage_mm3": v(storage[r, t]),
                "capacity_mm3": res[r].capacity,
                "buffer_mm3": buffer[r],
                "buffer_shortfall_mm3": v(shortfall[r, t]),
            }
            for u in USES:
                row[f"{u}_demand_mm3"] = demand[r, u][t]
                row[f"{u}_delivered_mm3"] = v(x[r, u, t])
                row[f"{u}_deficit_mm3"] = max(demand[r, u][t] - v(x[r, u, t]), 0.0)
            rows.append(row)
    daily = pl.DataFrame(rows).with_columns(
        (pl.col("storage_mm3") / pl.col("capacity_mm3") * 100).alias("storage_pct"),
        pl.sum_horizontal(f"{u}_deficit_mm3" for u in USES).alias("unmet_deficit_mm3"),
    )

    summary = summarise(daily, inputs)
    tol = OPERATING_ASSUMPTIONS["deficit_tolerance_pct"]
    warn = summary["unmet_share_pct"] > tol or summary["terminal_buffer_breach_mm3"] > 1e-6
    return OptimizationResult(
        status="Deficit Warning" if warn else "Optimal",
        solver_status=solver_status,
        objective=float(pulp.value(prob.objective)),
        solve_seconds=elapsed,
        daily=daily,
        summary=summary,
    )


def summarise(daily: pl.DataFrame, inputs: OptimizationInputs) -> dict[str, float]:
    tot = daily.select(
        *[pl.col(f"{u}_demand_mm3").sum().alias(f"{u}_demand") for u in USES],
        *[pl.col(f"{u}_delivered_mm3").sum().alias(f"{u}_delivered") for u in USES],
        pl.col("unmet_deficit_mm3").sum().alias("unmet"),
        pl.col("evaporation_mm3").sum().alias("evaporation"),
        pl.col("local_inflow_mm3").sum().alias("local_inflow"),
        (pl.col("buffer_shortfall_mm3") > 1e-6).sum().alias("buffer_breach_node_days"),
    ).row(0, named=True)
    last_day = daily.filter(pl.col("day") == daily["day"].max())
    total_demand = sum(tot[f"{u}_demand"] for u in USES)
    out = {
        **{k: float(v) for k, v in tot.items()},
        "total_demand": total_demand,
        "unmet_share_pct": 100 * tot["unmet"] / total_demand if total_demand else 0.0,
        "initial_storage": sum(r.initial_storage for r in inputs.reservoirs.values()),
        "final_storage": float(last_day["storage_mm3"].sum()),
        "terminal_buffer_breach_mm3": float(last_day["buffer_shortfall_mm3"].sum()),
    }
    for u in USES:
        d = tot[f"{u}_demand"]
        out[f"{u}_reliability_pct"] = 100 * tot[f"{u}_delivered"] / d if d else 100.0
    return out


def optimize(hydro: pl.DataFrame, params: ScenarioParams = ScenarioParams()) -> OptimizationResult:
    return solve(build_inputs(hydro, params))
