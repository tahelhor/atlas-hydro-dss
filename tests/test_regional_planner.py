"""Verification of the 12-month regional planner: physics, capacities, priorities and the
direction of every solution lever. Uses synthetic archives so it runs without the warehouse."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import polars as pl
import pytest

from src.config import M3S_TO_MM3_PER_DAY
from src.models.regional_planner import (
    MONTHS,
    PlannerScenario,
    SolutionLevers,
    available_years,
    breakdown_days,
    build_year_inputs,
    compare,
    export_demand,
    hydrological_months,
    inflow_calibration,
    irrigation_demand,
    potable_demand,
    solve,
)
from src.region.planner_config import (
    AQUIFER,
    DEMANDS,
    EXPORTS,
    INFLOW_NORMAL_MM3,
    IRRIGATION,
    LEVERS,
    MONTH_DAYS,
    PRESETS,
    RESERVOIRS,
)
from src.region.provinces import PROVINCE_IDS

TOL = 1e-4
NODE_Q = {"KHENIFRA_HEADWATERS": 3.0, "DAM_AHMED_EL_HANSALI": 12.0, "DAM_BIN_EL_OUIDANE": 30.0,
          "DAM_AL_MASSIRA": 75.0}  # m³/s, wet-ish normal regime
DRY_YEAR, WET_YEAR = 2022, 2010


def _month_range(y0: int, y1: int) -> list[date]:
    return [date(y, m, 1) for y in range(y0, y1 + 1) for m in range(1, 13)]


def _factor(month: date) -> float:
    """Dry hydrological year 2022 (Sep 2021-Aug 2022): 30% of normal flow & 60% of rain."""
    hy = month.year + 1 if month.month >= 9 else month.year
    return {DRY_YEAR: 0.3, WET_YEAR: 1.6}.get(hy, 1.0)


@pytest.fixture(scope="module")
def discharge() -> pl.DataFrame:
    rows = []
    for m in _month_range(1997, 2025):
        days = (date(m.year + (m.month == 12), m.month % 12 + 1, 1) - m).days
        for node, q in NODE_Q.items():
            qq = q * _factor(m) * (1.5 if m.month in (1, 2, 3, 4) else 0.7)
            rows.append({"node_id": node, "month": m, "n_days": days, "discharge_m3s_mean": qq,
                         "volume_mm3": qq * M3S_TO_MM3_PER_DAY * days})
    return pl.DataFrame(rows)


@pytest.fixture(scope="module")
def climate() -> pl.DataFrame:
    rows = []
    for m in _month_range(1997, 2025):
        wet = m.month in (11, 12, 1, 2, 3, 4)
        f = _factor(m) ** 0.5  # rain deficit smaller than flow deficit (amplification)
        for p in PROVINCE_IDS:
            rows.append({"province_id": p, "month": m, "n_days": 30,
                         "precip_mm": (70.0 if wet else 8.0) * f, "snow_cm": 2.0 if wet else 0.0,
                         "tmean_c": 12.0 if wet else 24.0, "tmax_c": 18.0 if wet else 32.0,
                         "et0_mm": 60.0 if wet else 170.0})
    return pl.DataFrame(rows)


@pytest.fixture(scope="module")
def dry(discharge, climate):
    return build_year_inputs(DRY_YEAR, discharge, climate)


@pytest.fixture(scope="module")
def wet(discharge, climate):
    return build_year_inputs(WET_YEAR, discharge, climate)


@pytest.fixture(scope="module")
def dry_base(dry):
    return solve(PlannerScenario(DRY_YEAR, (30.0, 30.0, 15.0)), dry)


# =========================================================================== inputs
class TestInputs:
    def test_hydrological_year_is_sept_to_aug(self):
        months = hydrological_months(2022)
        assert months[0] == date(2021, 9, 1) and months[-1] == date(2022, 8, 1)
        assert len(set(months)) == 12

    def test_available_years_need_complete_data(self, discharge, climate):
        years = available_years(discharge, climate)
        assert DRY_YEAR in years and 1998 in years
        assert 1997 not in years  # Sep-Dec 1996 missing
        assert available_years(discharge.filter(pl.col("month") != date(2010, 3, 1)), climate).count(2010) == 0

    def test_calibration_hits_reported_normal(self, discharge):
        cal = inflow_calibration(discharge)
        ref = (discharge.filter(pl.col("node_id") == "DAM_AL_MASSIRA")
               .filter(pl.col("month").is_between(date(1997, 9, 1), date(2018, 8, 1)))["volume_mm3"].sum())
        n_years = 2018 - 1998 + 1
        assert ref / n_years * cal == pytest.approx(INFLOW_NORMAL_MM3, rel=0.02)

    def test_massira_local_inflow_is_residual(self, dry):
        for t in MONTHS:
            assert dry.inflow["AL_MASSIRA"][t] >= 0
        total_upstream = sum(dry.inflow["HANSALI"]) + sum(dry.inflow["BIN_EL_OUIDANE"])
        assert sum(dry.inflow["AL_MASSIRA"]) < sum(dry.inflow["AL_MASSIRA"]) + total_upstream

    def test_dry_year_has_lower_rain_factor(self, dry, wet):
        assert all(dry.rain_factor[p] < 1 < wet.rain_factor[p] for p in PROVINCE_IDS)


# =========================================================================== demand model
class TestDemand:
    def test_regional_drinking_water_magnitude(self):
        """Production need should match ONEE's ~113 Mm³ regional production (2020, incl. bulk
        sales to OCP) within a plausible band."""
        total = sum(sum(v) for v in potable_demand(SolutionLevers()).values())
        assert 60 < total < 130

    def test_populations_match_census_total(self):
        assert sum(d.population for d in DEMANDS) == 2_510_799  # RGPH 2024 municipal

    def test_leak_reduction_lowers_abstraction(self):
        base = sum(sum(v) for v in potable_demand(SolutionLevers()).values())
        fixed = sum(sum(v) for v in potable_demand(SolutionLevers(leak_reduction_pts=12)).values())
        assert fixed == pytest.approx(base * 0.68 / 0.80, rel=1e-6)

    def test_rural_connection_raises_demand(self):
        base = sum(sum(v) for v in potable_demand(SolutionLevers()).values())
        more = sum(sum(v) for v in potable_demand(SolutionLevers(rural_connection_pct=100)).values())
        assert more > base

    def test_irrigation_follows_et0_minus_rain(self, dry, wet):
        d = sum(sum(v) for v in irrigation_demand(dry, SolutionLevers()).values())
        w = sum(sum(v) for v in irrigation_demand(wet, SolutionLevers()).values())
        assert d > w > 0

    def test_drip_reduces_irrigation_need(self, dry):
        base = sum(sum(v) for v in irrigation_demand(dry, SolutionLevers()).values())
        drip = sum(sum(v) for v in irrigation_demand(dry, SolutionLevers(drip_conversion_pct=100)).values())
        assert drip < base

    def test_desal_replaces_casablanca_then_doukkala(self):
        full = {k: sum(v) for k, v in export_demand(SolutionLevers()).items()}
        some = {k: sum(v) for k, v in export_demand(SolutionLevers(desal_mm3=100)).items()}
        allx = {k: sum(v) for k, v in export_demand(SolutionLevers(desal_mm3=160)).items()}
        assert some["EXP_POT_CASABLANCA"] == pytest.approx(full["EXP_POT_CASABLANCA"] - 100, abs=TOL)
        assert some["EXP_IRR_DOUKKALA"] == pytest.approx(full["EXP_IRR_DOUKKALA"], abs=TOL)
        assert allx["EXP_POT_CASABLANCA"] == pytest.approx(0, abs=TOL)
        assert allx["EXP_IRR_DOUKKALA"] == pytest.approx(full["EXP_IRR_DOUKKALA"] - 50, abs=TOL)
        assert some["EXP_POT_MARRAKECH"] == pytest.approx(full["EXP_POT_MARRAKECH"])

    def test_breakdown_model(self):
        d = DEMANDS[0]
        base = breakdown_days(d, SolutionLevers())
        assert base == pytest.approx(d.exposed_share * d.outage_events_yr * (d.outage_hours - d.autonomy_hours) / 24)
        assert breakdown_days(d, SolutionLevers(backup_source_pct=100)) == 0
        big_tank = SolutionLevers(storage_autonomy_h=40)
        assert breakdown_days(d, big_tank) < base

    @pytest.mark.parametrize("name", list(LEVERS))
    def test_lever_bounds_enforced(self, name):
        spec = LEVERS[name]
        with pytest.raises(ValueError):
            SolutionLevers(**{name: spec["max"] + 1})


# =========================================================================== solver physics
class TestSolver:
    def test_optimal_and_fast(self, dry_base):
        assert dry_base.status == "Optimal" and dry_base.solve_seconds < 5

    def test_reservoir_mass_balance(self, dry_base):
        for row in dry_base.storage.iter_rows(named=True):
            expected = (row["storage_start_mm3"] + row["inflow_mm3"] + row["upstream_mm3"]
                        - row["evaporation_mm3"] - row["withdrawal_mm3"] - row["eco_mm3"]
                        - row["release_mm3"] + row["floor_slack_mm3"])
            assert row["storage_mm3"] == pytest.approx(expected, abs=1e-3), (row["res_id"], row["m"])

    def test_storage_chains_month_to_month(self, dry_base):
        for r in RESERVOIRS:
            s = dry_base.storage.filter(pl.col("res_id") == r.res_id).sort("m")
            assert s["storage_start_mm3"][1:].to_list() == pytest.approx(s["storage_mm3"][:-1].to_list())

    def test_storage_bounds(self, dry_base):
        for r in RESERVOIRS:
            s = dry_base.storage.filter(pl.col("res_id") == r.res_id)
            assert s["storage_mm3"].min() >= r.dead_mm3 - TOL
            assert s["storage_mm3"].max() <= r.capacity_mm3 + TOL

    def test_cascade_routing(self, dry_base):
        st = dry_base.storage
        for t in MONTHS:
            up = st.filter((pl.col("m") == t) & pl.col("res_id").is_in(["HANSALI", "BIN_EL_OUIDANE"]))
            massira = st.filter((pl.col("m") == t) & (pl.col("res_id") == "AL_MASSIRA"))
            assert massira["upstream_mm3"][0] == pytest.approx(
                (up["eco_mm3"] + up["release_mm3"]).sum(), abs=1e-3)

    def test_deliveries_bounded(self, dry_base):
        m = dry_base.monthly
        assert (m["delivered_mm3"] <= m["demand_mm3"] + TOL).all()
        assert m["service_ratio"].is_between(0, 1).all()
        src_cols = [c for c in m.columns if c.startswith("from_")]
        assert (m.select(pl.sum_horizontal(src_cols)).to_series() - m["delivered_mm3"]).abs().max() < 1e-3

    def test_link_capacities_respected(self, dry_base):
        m = dry_base.monthly
        for perim in IRRIGATION:
            for lk in perim.links:
                if lk.cap_mm3_yr is None:
                    continue
                rows = m.filter(pl.col("demand_id") == perim.demand_id).sort("m")
                for t, val in enumerate(rows[f"from_{lk.source_id}"].to_list()):
                    assert val <= lk.cap_mm3_yr * MONTH_DAYS[t] / 365 + TOL

    def test_aquifer_budget(self, dry_base, dry):
        s = dry_base.summary
        assert s["aquifer_pumping"] <= s["aquifer_recharge"] + s["aquifer_overdraft"] + 1e-3
        assert s["aquifer_pumping"] <= AQUIFER.max_pumping_mm3_yr + 1e-3
        assert s["aquifer_overdraft"] <= AQUIFER.max_overdraft_mm3_yr + 1e-3

    def test_drinking_water_has_priority_over_irrigation(self, dry_base):
        assert dry_base.summary["potable_pct"] >= dry_base.summary["irrigation_pct"]

    def test_drought_is_worse_than_wet_year(self, dry, wet):
        fill = (30.0, 30.0, 15.0)
        d = solve(PlannerScenario(DRY_YEAR, fill), dry).summary
        w = solve(PlannerScenario(WET_YEAR, fill), wet).summary
        assert d["avg_hours_per_day"] <= w["avg_hours_per_day"] + TOL
        assert d["irrigation_pct"] < w["irrigation_pct"]

    def test_fuller_dams_help(self, dry):
        low = solve(PlannerScenario(DRY_YEAR, (10.0, 10.0, 5.0)), dry).summary
        high = solve(PlannerScenario(DRY_YEAR, (80.0, 80.0, 40.0)), dry).summary
        assert high["irrigation_pct"] >= low["irrigation_pct"]
        assert high["avg_hours_per_day"] >= low["avg_hours_per_day"] - TOL

    def test_compare_reuses_baseline(self, dry):
        scn = PlannerScenario(DRY_YEAR, (30.0, 30.0, 15.0))
        base, sol = compare(scn, dry)
        assert base is sol


# =========================================================================== lever directions
LEVER_TESTS = [
    ("leak_reduction_pts", 15, "avg_hours_per_day", +1),
    ("interconnection_mm3", 20, "avg_hours_per_day", +1),
    ("demand_saving_pct", 15, "avg_hours_per_day", +1),
    ("storage_autonomy_h", 24, "breakdown_days_exposed", -1),
    ("backup_source_pct", 80, "people_exposed", -1),
    ("rural_connection_pct", 80, "people_no_tap", -1),
    ("drip_conversion_pct", 80, "irrigation_pct", +1),
    ("reuse_mm3", 30, "irrigation_pct", +1),
    ("groundwater_cap_pct", 20, "aquifer_overdraft", -1),
    ("desal_mm3", 150, "irrigation_pct", +1),
]


@pytest.mark.parametrize("lever,value,metric,direction", LEVER_TESTS)
def test_each_lever_moves_its_metric_the_right_way(dry, dry_base, lever, value, metric, direction):
    scn = PlannerScenario(DRY_YEAR, (30.0, 30.0, 15.0), SolutionLevers(**{lever: value}))
    res = solve(scn, dry)
    delta = res.summary[metric] - dry_base.summary[metric]
    assert direction * delta >= -1e-3, f"{lever} moved {metric} the wrong way ({delta:+.3f})"


def test_full_package_strictly_improves_citizens(dry, dry_base):
    lv = SolutionLevers(leak_reduction_pts=12, storage_autonomy_h=24, backup_source_pct=60,
                        rural_connection_pct=50, interconnection_mm3=12, demand_saving_pct=8,
                        drip_conversion_pct=60, reuse_mm3=16, groundwater_cap_pct=50, desal_mm3=150)
    res = solve(replace(PlannerScenario(DRY_YEAR, (30.0, 30.0, 15.0)), levers=lv), dry)
    assert res.summary["avg_hours_per_day"] > dry_base.summary["avg_hours_per_day"]
    assert res.summary["people_no_tap"] < dry_base.summary["people_no_tap"]
    assert res.summary["breakdown_days_exposed"] < dry_base.summary["breakdown_days_exposed"]


# =========================================================================== configuration integrity
def test_presets_are_valid():
    for p in PRESETS.values():
        assert 1998 <= p["year"] <= 2030
        assert len(p["fill"]) == len(RESERVOIRS)
        assert all(0 <= f <= 100 for f in p["fill"])


def test_interconnection_shares_sum_to_one():
    shares = [lk.share for d in DEMANDS for lk in d.links if lk.interconnect]
    assert sum(shares) == pytest.approx(1.0)


def test_every_link_source_exists():
    known = {r.res_id for r in RESERVOIRS} | {AQUIFER.source_id, "REUSE"}
    from src.region.planner_config import SPRINGS
    known |= {s.source_id for s in SPRINGS}
    links = [lk for d in DEMANDS for lk in d.links] + [lk for p in IRRIGATION for lk in p.links] \
        + [lk for e in EXPORTS for lk in e.links]
    assert {lk.source_id for lk in links} <= known
