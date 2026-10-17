"""12-month drought stress-test & solutions planner for Béni Mellal–Khénifra (PuLP / HiGHS LP).

Replays a real hydrological year (Sept → Aug) from the warehouse - GloFAS monthly river flows
and ERA5 rain / ET0 - against today's demands, then re-solves with the user's solution levers
to show what each intervention changes for citizens (hours of running water per day), farmers
(irrigation served) and the aquifer (over-pumping).

Supply network (monthly, Mm³)::

    Khénifra karst river intake, springs, wells, Hassan Iᵉʳ (drought-sensitive) ─┐
    treatment / pipeline capacity fixed in l/s - binds in the summer peak  ──────┤
    Tadla aquifer (recharge ∝ year rainfall, over-pumping penalised) ───┼─► province drinking water
    Ahmed El Hansali ─┐                                                 │
    Bin El Ouidane  ──┼─ eco flow + releases ─► Al Massira ─► Marrakech, Casablanca, Doukkala
                      └─► Tadla irrigation (Béni Amir / Béni Moussa) ◄──┘
    treated wastewater (reuse lever) ─► irrigation

Two causes of cuts are modelled and reported separately:
* **drought rationing** - the LP cannot deliver the demand (resource shortage);
* **breakdown cuts** - towns on a single plant / long pipeline lose water for days when it
  fails; storage autonomy and backup sources shrink them (post-LP expected-value model).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from datetime import date

import polars as pl
import pulp

from src.models.water_optimizer import _solver
from src.region.planner_config import (
    AQUIFER,
    DEMANDS,
    DESAL_IRRIGATION_CAP_MM3,
    EXPORTS,
    INFLOW_NORMAL_MM3,
    INFLOW_REF_YEARS,
    IRRIGATION,
    LEVERS,
    MONTH_DAYS,
    MONTH_LABELS,
    NETWORK_EFFICIENCY,
    POTABLE_MONTHLY_FACTOR,
    RESERVOIRS,
    SPRINGS,
    WEIGHTS,
    Link,
    PotableDemand,
    production_need,
)

MONTHS = range(12)
RATIONED = 0.95  # a month counts as rationed below 95% of demand served (> ~1.2 h/day cut)
SEVERE = 0.75  # severe rationing: a month below 18 h/day of service
RES_TO_NODE = {"HANSALI": "DAM_AHMED_EL_HANSALI", "BIN_EL_OUIDANE": "DAM_BIN_EL_OUIDANE",
               "AL_MASSIRA": "DAM_AL_MASSIRA"}


# =========================================================================== levers
@dataclass(frozen=True)
class SolutionLevers:
    """User-controlled interventions. Defaults = business as usual."""

    leak_reduction_pts: float = 0.0
    storage_autonomy_h: float = 0.0
    backup_source_pct: float = 0.0
    rural_connection_pct: float = 0.0
    interconnection_mm3: float = 0.0
    demand_saving_pct: float = 0.0
    drip_conversion_pct: float = 0.0
    reuse_mm3: float = 0.0
    groundwater_cap_pct: float = 100.0
    desal_mm3: float = 0.0

    def __post_init__(self) -> None:
        for name, spec in LEVERS.items():
            v = getattr(self, name)
            if not spec["min"] <= v <= spec["max"]:
                raise ValueError(f"{name}={v} outside [{spec['min']}, {spec['max']}]")

    @property
    def is_baseline(self) -> bool:
        return self == SolutionLevers()


@dataclass(frozen=True)
class PlannerScenario:
    replay_year: int  # hydrological year ending in August of this year
    # storage on 1 September, % of capacity, in RESERVOIRS order (Hansali, Bin El Ouidane, Massira)
    start_fill_pct: tuple[float, float, float] = (35.0, 35.0, 35.0)
    levers: SolutionLevers = field(default_factory=SolutionLevers)


# =========================================================================== inputs
@dataclass
class YearInputs:
    year: int
    months: list[date]
    inflow: dict[str, list[float]]  # local inflow per reservoir, Mm³/month (calibrated)
    river_khenifra: list[float]  # Oum Er-Rbia at Khénifra, Mm³/month (calibrated)
    rain_factor: dict[str, float]  # province -> this year's rain / reference mean
    rain_factor_prev: dict[str, float]
    et0: dict[str, list[float]]  # province -> mm/month
    precip: dict[str, list[float]]
    annual_rain_mm: float  # regional mean
    normal_rain_mm: float
    calibration: float  # GloFAS → reported inflow factor


def hydrological_months(year: int) -> list[date]:
    """Sept (year-1) … Aug (year): Morocco's hydrological year."""
    return [date(year - 1 if m < 4 else year, (m + 8) % 12 + 1, 1) for m in MONTHS]


def _with_hy(df: pl.DataFrame) -> pl.DataFrame:
    return df.with_columns(
        pl.when(pl.col("month").dt.month() >= 9).then(pl.col("month").dt.year() + 1)
        .otherwise(pl.col("month").dt.year()).alias("hy"))


def available_years(discharge: pl.DataFrame, climate: pl.DataFrame) -> list[int]:
    """Hydrological years with 12 complete months for every node and province."""
    def complete(df: pl.DataFrame, key: str) -> set[int]:
        counts = _with_hy(df).group_by("hy", key).agg(pl.len().alias("n")).filter(pl.col("n") == 12)
        per = counts.group_by("hy").agg(pl.len().alias("k"))
        return set(per.filter(pl.col("k") == df[key].n_unique())["hy"].to_list())
    return sorted(complete(discharge, "node_id") & complete(climate, "province_id"))


def inflow_calibration(discharge: pl.DataFrame) -> float:
    """Factor bringing the GloFAS 3-dam system mean (reference years) to the reported normal."""
    q = _with_hy(discharge.filter(pl.col("node_id") == "DAM_AL_MASSIRA"))
    ann = q.group_by("hy").agg(pl.col("volume_mm3").sum(), pl.len().alias("n")).filter(pl.col("n") == 12)
    ref = ann.filter(pl.col("hy").is_between(*INFLOW_REF_YEARS))["volume_mm3"].mean()
    return INFLOW_NORMAL_MM3 / ref if ref else 1.0


def build_year_inputs(year: int, discharge: pl.DataFrame, climate: pl.DataFrame) -> YearInputs:
    months = hydrological_months(year)
    cal = inflow_calibration(discharge)
    q = discharge.filter(pl.col("month").is_in(months)).sort("month")
    vol = {n: [v * cal for v in q.filter(pl.col("node_id") == n)["volume_mm3"].to_list()]
           for n in q["node_id"].unique().to_list()}
    if len(vol) < 4 or any(len(v) != 12 for v in vol.values()):
        raise ValueError(f"incomplete discharge data for hydrological year {year}")
    h, b, m = vol["DAM_AHMED_EL_HANSALI"], vol["DAM_BIN_EL_OUIDANE"], vol["DAM_AL_MASSIRA"]
    inflow = {
        "HANSALI": h,
        "BIN_EL_OUIDANE": b,
        # GloFAS at Al Massira already includes the upstream rivers: keep the residual only
        "AL_MASSIRA": [max(mm - hh - bb, 0.0) for mm, hh, bb in zip(m, h, b)],
    }
    clim = _with_hy(climate)
    annual = (clim.group_by("province_id", "hy").agg(pl.col("precip_mm").sum(), pl.len().alias("n"))
              .filter(pl.col("n") == 12))
    normal = dict(annual.filter(pl.col("hy").is_between(*INFLOW_REF_YEARS)).group_by("province_id")
                  .agg(pl.col("precip_mm").mean()).iter_rows())

    def factor(y: int) -> dict[str, float]:
        cur = dict(annual.filter(pl.col("hy") == y).select("province_id", "precip_mm").iter_rows())
        return {p: (cur[p] / normal[p]) if p in cur else 1.0 for p in normal}

    yr = clim.filter(pl.col("month").is_in(months)).sort("month")
    et0 = {p: yr.filter(pl.col("province_id") == p)["et0_mm"].to_list() for p in normal}
    precip = {p: yr.filter(pl.col("province_id") == p)["precip_mm"].to_list() for p in normal}
    return YearInputs(
        year=year, months=months, inflow=inflow, river_khenifra=vol["KHENIFRA_HEADWATERS"],
        rain_factor=factor(year), rain_factor_prev=factor(year - 1), et0=et0, precip=precip,
        annual_rain_mm=sum(sum(v) for v in precip.values()) / max(len(precip), 1),
        normal_rain_mm=sum(normal.values()) / max(len(normal), 1), calibration=cal,
    )


# =========================================================================== demand model
def rural_tap_share(d: PotableDemand, lv: SolutionLevers) -> float:
    return d.rural_tap_pct + (1 - d.rural_tap_pct) * lv.rural_connection_pct / 100.0


def potable_demand(lv: SolutionLevers) -> dict[str, list[float]]:
    """Production needed at source (Mm³/month) = consumption / network efficiency."""
    out = {}
    eff = min(NETWORK_EFFICIENCY + lv.leak_reduction_pts / 100.0, 0.95)
    for d in DEMANDS:
        annual = production_need(d.urban_pop, d.rural_pop, rural_tap_share(d, lv), eff)
        annual *= 1 - lv.demand_saving_pct / 100.0
        out[d.demand_id] = [annual * POTABLE_MONTHLY_FACTOR[m] * MONTH_DAYS[m] / 365 for m in MONTHS]
    return out


def irrigation_demand(inp: YearInputs, lv: SolutionLevers) -> dict[str, list[float]]:
    """Gross need (Mm³/month) from FAO-56: area × max(Kc·ET0 − 0.75·P, 0) / efficiency.
    Drip conversion raises the efficiency of the converted share of flood-irrigated land."""
    out = {}
    share = lv.drip_conversion_pct / 100.0
    for perim in IRRIGATION:
        eff = perim.efficiency_surface + share * max(perim.efficiency_drip - perim.efficiency_surface, 0)
        et0, p = inp.et0[perim.climate_province], inp.precip[perim.climate_province]
        need_mm = [max(perim.kc[m] * et0[m] - 0.75 * p[m], 0.0) for m in MONTHS]
        out[perim.demand_id] = [perim.area_ha * n * 1e-5 / eff for n in need_mm]  # ha·mm = 10 m³
    return out


def spring_yield(inp: YearInputs) -> dict[str, list[float]]:
    """Springs & shallow wells respond to rainfall with a one-year memory (karst storage)."""
    out = {}
    for s in SPRINGS:
        f = 0.5 * inp.rain_factor.get(s.province_id, 1) + 0.5 * inp.rain_factor_prev.get(s.province_id, 1)
        f = min(max(f, 0.15), 1.4) ** s.elasticity
        out[s.source_id] = [s.normal_mm3_yr * f * MONTH_DAYS[m] / 365 for m in MONTHS]
    return out


def export_demand(lv: SolutionLevers) -> dict[str, list[float]]:
    """Desalination first replaces Casablanca's drinking water, then Doukkala irrigation."""
    left = lv.desal_mm3
    out = {}
    for e in EXPORTS:
        annual = e.annual_mm3
        if e.desal_substitutable:
            cap = annual if e.demand_id.startswith("EXP_POT") else min(annual, DESAL_IRRIGATION_CAP_MM3)
            cut = min(left, cap)
            annual -= cut
            left -= cut
        out[e.demand_id] = [annual * e.monthly_profile[m] for m in MONTHS]
    return out


def breakdown_days(d: PotableDemand, lv: SolutionLevers) -> float:
    """Expected days/yr without water for the average resident, from plant / pipeline failures."""
    autonomy = d.autonomy_hours + lv.storage_autonomy_h
    exposed = d.exposed_share * (1 - lv.backup_source_pct / 100.0)
    return exposed * d.outage_events_yr * max(d.outage_hours - autonomy, 0.0) / 24.0


# =========================================================================== solve
@dataclass
class PlannerResult:
    status: str
    solve_seconds: float
    monthly: pl.DataFrame  # one row per demand × month
    storage: pl.DataFrame  # one row per reservoir × month
    summary: dict[str, float]
    province: pl.DataFrame  # one row per province: hours/day, people under cuts…


def _kind(demand_id: str) -> str:
    if demand_id.startswith("POT_"):
        return "potable"
    if demand_id.startswith("IRR_"):
        return "irrigation"
    if demand_id.startswith("EXP_POT"):
        return "export_potable"
    return "export_irrigation"


def solve(scn: PlannerScenario, inp: YearInputs) -> PlannerResult:
    lv = scn.levers
    T = MONTHS
    prob = pulp.LpProblem("bmk_regional_plan", pulp.LpMinimize)
    var = prob.add_variable

    demand: dict[str, list[float]] = {**potable_demand(lv), **irrigation_demand(inp, lv),
                                      **export_demand(lv)}
    springs = spring_yield(inp)
    links: list[Link] = [*(lk for d in DEMANDS for lk in d.links),
                         *(lk for p in IRRIGATION for lk in p.links),
                         *(lk for e in EXPORTS for lk in e.links)]

    # ----- flows on capacitated links (keyed by link index: a demand may have two links,
    # e.g. an existing pipe and a new interconnection, from the same source)
    flow: dict[tuple[str, str, int, int], pulp.LpVariable] = {}
    for i, lk in enumerate(links):
        for t in T:
            frac = MONTH_DAYS[t] / 365
            if lk.interconnect:
                cap = lv.interconnection_mm3 * lk.share * frac
            elif lk.cap_mm3_yr is None:
                cap = None
            else:
                # plant / pipe capacity is fixed (l/s): it binds in the summer demand peak
                cap = lk.cap_mm3_yr * frac
            flow[lk.demand_id, lk.source_id, t, i] = var(
                f"f{i}_{lk.demand_id}_{lk.source_id}_{t}", lowBound=0, upBound=cap)

    def inflows_from(source: str, t: int):
        return pulp.lpSum(v for (_, s, tt, _), v in flow.items() if s == source and tt == t)

    delivered = {(d, t): pulp.lpSum(v for (dd, _, tt, _), v in flow.items() if dd == d and tt == t)
                 for d in demand for t in T}
    short = {(d, t): var(f"short_{d}_{t}", lowBound=0) for d in demand for t in T}
    deep = {(d, t): var(f"deep_{d}_{t}", lowBound=0) for d in demand for t in T}
    for d in demand:
        k = _kind(d)
        for t in T:
            prob += delivered[d, t] + short[d, t] == demand[d][t], f"demand_{d}_{t}"
            prob += deep[d, t] >= short[d, t] - WEIGHTS.tranche_share[k] * demand[d][t], f"tranche_{d}_{t}"

    # ----- reservoirs (cascade)
    S, eco, rel, floor_slack = {}, {}, {}, {}
    for r in RESERVOIRS:
        for t in T:
            S[r.res_id, t] = var(f"S_{r.res_id}_{t}", lowBound=r.dead_mm3, upBound=r.capacity_mm3)
            eco[r.res_id, t] = var(f"eco_{r.res_id}_{t}", lowBound=0,
                                   upBound=r.eco_mm3_yr * MONTH_DAYS[t] / 365)
            rel[r.res_id, t] = var(f"rel_{r.res_id}_{t}", lowBound=0)
            # Dead storage is a physical floor: when a near-empty lake evaporates more than it
            # receives it simply cannot go lower. This slack keeps the LP feasible and is
            # heavily penalised, so it is only ever non-zero in that physical situation.
            floor_slack[r.res_id, t] = var(f"floor_slack_{r.res_id}_{t}", lowBound=0)
    s0 = {r.res_id: min(max(r.capacity_mm3 * pct / 100.0, r.dead_mm3), r.capacity_mm3)
          for r, pct in zip(RESERVOIRS, scn.start_fill_pct, strict=True)}
    for r in RESERVOIRS:
        area = r.area_full_km2 * (s0[r.res_id] / r.capacity_mm3) ** (2 / 3)
        et0 = inp.et0[r.climate_province]
        for t in T:
            prev = s0[r.res_id] if t == 0 else S[r.res_id, t - 1]
            up = pulp.lpSum(eco[u, t] + rel[u, t] for u in r.upstream)
            evap = 1.05 * et0[t] * area / 1000.0
            prob += (S[r.res_id, t] == prev + inp.inflow[r.res_id][t] + up - evap
                     - inflows_from(r.res_id, t) - eco[r.res_id, t] - rel[r.res_id, t]
                     + floor_slack[r.res_id, t]), f"balance_{r.res_id}_{t}"

    # ----- local sources (springs, karst river intake, small dams), aquifer, reuse
    for t in T:
        for s in SPRINGS:
            prob += inflows_from(s.source_id, t) <= springs[s.source_id][t], f"spring_{s.source_id}_{t}"
        prob += inflows_from("REUSE", t) <= lv.reuse_mm3 * MONTH_DAYS[t] / 365, f"reuse_{t}"
    recharge = AQUIFER.recharge_mm3_yr * min(max(inp.rain_factor.get(AQUIFER.climate_province, 1), 0.2), 1.6)
    pumping = pulp.lpSum(inflows_from(AQUIFER.source_id, t) for t in T)
    overdraft = var("aquifer_overdraft", lowBound=0,
                    upBound=AQUIFER.max_overdraft_mm3_yr * lv.groundwater_cap_pct / 100.0)
    prob += pumping <= recharge + overdraft, "aquifer_balance"
    prob += pumping <= AQUIFER.max_pumping_mm3_yr, "aquifer_well_capacity"

    # ----- objective
    end_short = {r.res_id: var(f"carryover_short_{r.res_id}", lowBound=0) for r in RESERVOIRS}
    for r in RESERVOIRS:
        prob += S[r.res_id, 11] + end_short[r.res_id] >= r.carryover_pct / 100 * r.capacity_mm3, \
            f"carryover_{r.res_id}"
    prob += (
        pulp.lpSum(WEIGHTS.use[_kind(d)] * short[d, t] + WEIGHTS.deep_extra[_kind(d)] * deep[d, t]
                   for d in demand for t in T)
        + pulp.lpSum(WEIGHTS.ecological * (r.eco_mm3_yr * MONTH_DAYS[t] / 365 - eco[r.res_id, t])
                     for r in RESERVOIRS for t in T)
        + WEIGHTS.overdraft * overdraft
        + pulp.lpSum(WEIGHTS.carryover * end_short[r] for r in end_short)
        + pulp.lpSum(WEIGHTS.release * rel[k] for k in rel)
        + 1_000.0 * pulp.lpSum(floor_slack.values())
    )

    t0 = time.perf_counter()
    stats = prob.solve(_solver())
    elapsed = time.perf_counter() - t0
    if stats.status != pulp.LpSolveStatus.Optimal or not stats.has_solution:
        raise RuntimeError(f"regional planner not optimal: {stats.status.name}")

    def v(x) -> float:
        return max(float(pulp.value(x) or 0.0), 0.0)

    rows = []
    for d in demand:
        for t in T:
            row = {"demand_id": d, "kind": _kind(d), "m": t, "month": inp.months[t],
                   "demand_mm3": demand[d][t], "delivered_mm3": v(delivered[d, t])}
            for i, lk in enumerate(links):
                if lk.demand_id == d:
                    key = f"from_{lk.source_id}"
                    row[key] = row.get(key, 0.0) + v(flow[d, lk.source_id, t, i])
            rows.append(row)
    monthly = pl.DataFrame(rows, infer_schema_length=None)
    # only the from_<source> flow columns may be missing (a demand has no link to that source)
    monthly = monthly.with_columns(pl.col("^from_.*$").fill_null(0.0), pl.col("m").cast(pl.Int64)).with_columns(
        (pl.col("demand_mm3") - pl.col("delivered_mm3")).clip(0).alias("shortfall_mm3"),
        pl.when(pl.col("demand_mm3") > 0).then(pl.col("delivered_mm3") / pl.col("demand_mm3"))
        .otherwise(1.0).clip(0, 1).alias("service_ratio"),
    )
    areas = {r.res_id: r.area_full_km2 * (s0[r.res_id] / r.capacity_mm3) ** (2 / 3) for r in RESERVOIRS}
    storage = pl.DataFrame([
        {"res_id": r.res_id, "name": r.name, "m": t, "month": inp.months[t],
         "storage_start_mm3": s0[r.res_id] if t == 0 else v(S[r.res_id, t - 1]),
         "storage_mm3": v(S[r.res_id, t]), "capacity_mm3": r.capacity_mm3,
         "fill_pct": 100 * v(S[r.res_id, t]) / r.capacity_mm3,
         "inflow_mm3": inp.inflow[r.res_id][t],
         "upstream_mm3": sum(v(eco[u, t]) + v(rel[u, t]) for u in r.upstream),
         "evaporation_mm3": 1.05 * inp.et0[r.climate_province][t] * areas[r.res_id] / 1000.0,
         "withdrawal_mm3": sum(v(x) for (_, src, tt, _), x in flow.items() if src == r.res_id and tt == t),
         "eco_mm3": v(eco[r.res_id, t]), "release_mm3": v(rel[r.res_id, t]),
         "floor_slack_mm3": v(floor_slack[r.res_id, t])}
        for r in RESERVOIRS for t in T
    ])
    province = province_table(monthly, lv)
    summary = _summary(monthly, storage, province, v(overdraft), v(pumping), recharge, inp, s0, lv)
    return PlannerResult("Optimal", elapsed, monthly, storage, summary, province)


def province_table(monthly: pl.DataFrame, lv: SolutionLevers) -> pl.DataFrame:
    pot = monthly.filter(pl.col("kind") == "potable")
    rows = []
    for d in DEMANDS:
        p = pot.filter(pl.col("demand_id") == d.demand_id).sort("m")
        ratios = p["service_ratio"].to_list()
        drought_hours = 24 * sum(ratios) / 12
        bdays = breakdown_days(d, lv)
        hours = max(drought_hours - 24 * bdays / 365, 0.0)
        rural_tap = rural_tap_share(d, lv)
        no_tap = d.rural_pop * (1 - rural_tap) + d.urban_pop * (1 - d.urban_tap_pct)
        exposed = d.exposed_share * (1 - lv.backup_source_pct / 100.0)
        rows.append({
            "demand_id": d.demand_id, "province_id": d.province_id, "population": d.population,
            "drought_hours": drought_hours,
            "hours_per_day": hours,
            "worst_month_hours": 24 * min(ratios),
            "months_rationed": sum(r < RATIONED for r in ratios),
            "breakdown_days": bdays,
            "people_exposed": d.population * exposed,
            # days without water per year for a resident on a single plant / pipeline
            "breakdown_days_exposed": bdays / exposed if exposed > 0 else 0.0,
            "people_rationed": d.population * (1.0 if any(r < RATIONED for r in ratios) else 0.0),
            "people_severe": d.population * (1.0 if any(r < SEVERE for r in ratios) else 0.0),
            "people_no_tap": no_tap,
            "service_pct": 100 * p["delivered_mm3"].sum() / max(p["demand_mm3"].sum(), 1e-9),
            "shortfall_mm3": p["shortfall_mm3"].sum(),
        })
    return pl.DataFrame(rows)


def _summary(monthly, storage, province, overdraft, pumping, recharge, inp, s0, lv) -> dict[str, float]:
    def kind(k: str, col: str) -> float:
        return float(monthly.filter(pl.col("kind") == k)[col].sum())

    pot_d, pot_s = kind("potable", "demand_mm3"), kind("potable", "delivered_mm3")
    irr_d, irr_s = kind("irrigation", "demand_mm3"), kind("irrigation", "delivered_mm3")
    exp_d = kind("export_potable", "demand_mm3") + kind("export_irrigation", "demand_mm3")
    exp_s = kind("export_potable", "delivered_mm3") + kind("export_irrigation", "delivered_mm3")
    end = storage.filter(pl.col("m") == 11)
    pop = float(province["population"].sum())
    w = province["population"]
    return {
        "potable_demand": pot_d, "potable_served": pot_s,
        "potable_pct": 100 * pot_s / pot_d if pot_d else 100.0,
        "irrigation_demand": irr_d, "irrigation_served": irr_s,
        "irrigation_pct": 100 * irr_s / irr_d if irr_d else 100.0,
        "exports_demand": exp_d, "exports_served": exp_s,
        # water the upstream dams (Hansali, Bin El Ouidane) release down to Al Massira
        "upstream_to_massira": float(storage.filter(pl.col("res_id") == "AL_MASSIRA")["upstream_mm3"].sum()),
        "aquifer_pumping": pumping, "aquifer_recharge": recharge, "aquifer_overdraft": overdraft,
        "start_storage": sum(s0.values()), "end_storage": float(end["storage_mm3"].sum()),
        "end_fill_pct": 100 * float(end["storage_mm3"].sum()) / float(end["capacity_mm3"].sum()),
        "inflow_total": sum(sum(v) for v in inp.inflow.values()),
        "rain_mm": inp.annual_rain_mm,
        "rain_anomaly_pct": 100 * (inp.annual_rain_mm / inp.normal_rain_mm - 1) if inp.normal_rain_mm else 0.0,
        "people_rationed": float(province["people_rationed"].sum()),
        "people_severe": float(province["people_severe"].sum()),
        "people_no_tap": float(province["people_no_tap"].sum()),
        "avg_hours_per_day": float((province["hours_per_day"] * w).sum() / pop),
        "avg_drought_hours": float((province["drought_hours"] * w).sum() / pop),
        "avg_breakdown_days": float((province["breakdown_days"] * w).sum() / pop),
        "people_exposed": float(province["people_exposed"].sum()),
        "breakdown_days_exposed": (float((province["breakdown_days"] * w).sum())
                                   / max(float(province["people_exposed"].sum()), 1.0)),
    }


def compare(scn: PlannerScenario, inp: YearInputs) -> tuple[PlannerResult, PlannerResult]:
    """Business-as-usual vs. the scenario's levers, same year and starting storage."""
    base = solve(replace(scn, levers=SolutionLevers()), inp)
    return base, (base if scn.levers.is_baseline else solve(scn, inp))
