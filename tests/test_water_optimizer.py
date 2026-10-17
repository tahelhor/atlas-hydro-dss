"""Mathematical verification of the PuLP allocation engine."""

from __future__ import annotations

import polars as pl
import pytest

from src.config import (
    AL_MASSIRA,
    BIN_EL_OUIDANE,
    DEMANDS,
    HANSALI,
    HORIZON_DAYS,
    M3S_TO_MM3_PER_DAY,
    NODES_BY_ID,
    OPERATING_ASSUMPTIONS,
    PRIORITY_WEIGHTS,
    RESERVOIR_IDS,
)
from src.models.water_optimizer import (
    USES,
    ScenarioParams,
    build_inputs,
    optimize,
    solve,
)
from tests.conftest import make_hydro_frame

TOL = 1e-6


@pytest.fixture
def baseline(hydro_frame):
    return optimize(hydro_frame, ScenarioParams())


def drought(hydro_frame, **kw):
    params = dict(inflow_forecast="p25", inflow_shock_pct=-50, initial_storage_pct=25,
                  safety_buffer_pct=40, irrigation_cap_pct=120)
    params.update(kw)
    return optimize(hydro_frame, ScenarioParams(**params))


# =========================================================================== inputs
class TestInputs:
    def test_horizon_is_30_days(self, hydro_frame):
        inp = build_inputs(hydro_frame)
        assert inp.horizon == 30
        assert set(inp.reservoirs) == set(RESERVOIR_IDS)

    def test_cascade_local_inflow_removes_upstream(self, hydro_frame):
        inp = build_inputs(hydro_frame)
        expected = (14.0 - 2.0 - 5.0) * M3S_TO_MM3_PER_DAY
        assert inp.reservoirs[AL_MASSIRA].local_inflow[0] == pytest.approx(expected)
        assert inp.reservoirs[HANSALI].local_inflow[0] == pytest.approx(2.0 * M3S_TO_MM3_PER_DAY)

    def test_local_inflow_never_negative(self):
        frame = make_hydro_frame({HANSALI: 10.0, BIN_EL_OUIDANE: 10.0, AL_MASSIRA: 5.0})
        inp = build_inputs(frame)
        assert min(inp.reservoirs[AL_MASSIRA].local_inflow) == 0.0

    @pytest.mark.parametrize("shock", [-50, -20, 0, 25, 50])
    def test_inflow_shock_scales_linearly(self, hydro_frame, shock):
        base = build_inputs(hydro_frame).reservoirs[HANSALI].local_inflow[0]
        shocked = build_inputs(hydro_frame, ScenarioParams(inflow_shock_pct=shock))
        assert shocked.reservoirs[HANSALI].local_inflow[0] == pytest.approx(base * (1 + shock / 100))

    def test_ensemble_scenarios_ordered(self, hydro_frame):
        tot = {
            f: sum(sum(r.local_inflow) for r in build_inputs(
                hydro_frame, ScenarioParams(inflow_forecast=f)).reservoirs.values())
            for f in ("p25", "mean", "p75")
        }
        assert tot["p25"] < tot["mean"] < tot["p75"]

    def test_irrigation_scales_with_et0_and_cap(self):
        frame = make_hydro_frame(et0=7.5)
        inp = build_inputs(frame, ScenarioParams(irrigation_cap_pct=80))
        base = DEMANDS[BIN_EL_OUIDANE].irrigation_base_mm3
        ref = OPERATING_ASSUMPTIONS["et0_reference_mm"]
        assert inp.reservoirs[BIN_EL_OUIDANE].irrigation_demand[0] == pytest.approx(
            base * 7.5 / ref * 0.8)

    def test_evaporation_units(self, hydro_frame):
        """ET0 5 mm over A km2 = 5e-3 m * A e6 m2 = 5e3*A m3 = 0.005*A Mm3 (times Kc)."""
        inp = build_inputs(hydro_frame)
        node = NODES_BY_ID[AL_MASSIRA]
        r = inp.reservoirs[AL_MASSIRA]
        area = node.surface_area_full_km2 * (r.initial_storage / node.capacity_mm3) ** (2 / 3)
        expected = OPERATING_ASSUMPTIONS["open_water_kc"] * 5.0 * area / 1000
        assert r.evaporation[0] == pytest.approx(expected)
        assert 0.05 < r.evaporation[0] < 1.0  # sanity: tenths of Mm3/day for a 120 km2 lake

    @pytest.mark.parametrize("kw", [
        {"inflow_shock_pct": -60}, {"inflow_shock_pct": 51}, {"irrigation_cap_pct": 40},
        {"irrigation_cap_pct": 130}, {"safety_buffer_pct": 5}, {"safety_buffer_pct": 45},
        {"inflow_forecast": "p90"}, {"buffer_mode": "medium"},
    ])
    def test_scenario_param_bounds(self, kw):
        with pytest.raises(ValueError):
            ScenarioParams(**kw)

    def test_empty_forecast_raises(self, hydro_frame):
        with pytest.raises(ValueError, match="no forecast rows"):
            build_inputs(hydro_frame.with_columns(pl.lit(False).alias("is_forecast")))


# =========================================================================== constraints
class TestConstraints:
    def test_baseline_is_optimal(self, baseline):
        assert baseline.solver_status == "Optimal"
        assert baseline.status == "Optimal"
        assert baseline.daily.height == 3 * 30

    @pytest.mark.parametrize("scenario", ["baseline", "drought", "flood"])
    def test_mass_balance_every_day(self, hydro_frame, scenario):
        if scenario == "baseline":
            res = optimize(hydro_frame)
        elif scenario == "drought":
            res = drought(hydro_frame)
        else:
            res = optimize(make_hydro_frame({HANSALI: 900, BIN_EL_OUIDANE: 1200, AL_MASSIRA: 4000}),
                           ScenarioParams(initial_storage_pct=150, inflow_shock_pct=50))
        assert res.is_optimal
        for r in RESERVOIR_IDS:
            rows = res.daily.filter(pl.col("node_id") == r).sort("day").to_dicts()
            for i, row in enumerate(rows):
                if i > 0:  # storage chains day to day
                    assert row["storage_start_mm3"] == pytest.approx(rows[i - 1]["storage_mm3"])
                outflow = sum(row[f"{u}_delivered_mm3"] for u in USES) + row["excess_release_mm3"]
                expected = (row["storage_start_mm3"] + row["local_inflow_mm3"]
                            + row["upstream_release_in_mm3"] - row["evaporation_mm3"] - outflow)
                assert row["storage_mm3"] == pytest.approx(expected, abs=1e-5), (r, row["day"])

    def test_initial_storage_seed(self, baseline):
        day1 = baseline.daily.filter(pl.col("day") == 1)
        for row in day1.to_dicts():
            assert row["storage_start_mm3"] == NODES_BY_ID[row["node_id"]].baseline_storage_mm3

    def test_cascade_routing(self, baseline):
        """Al Massira's upstream inflow equals Hansali + Bin El Ouidane river releases."""
        d = baseline.daily
        up = (d.filter(pl.col("node_id").is_in([HANSALI, BIN_EL_OUIDANE]))
              .group_by("day")
              .agg((pl.col("ecological_delivered_mm3") + pl.col("excess_release_mm3")).sum()
                   .alias("released")))
        m = d.filter(pl.col("node_id") == AL_MASSIRA).join(up, on="day")
        assert (m["upstream_release_in_mm3"] - m["released"]).abs().max() < TOL
        assert d.filter(pl.col("node_id") != AL_MASSIRA)["upstream_release_in_mm3"].max() == 0

    @pytest.mark.parametrize("mode", ["soft", "hard"])
    def test_storage_within_physical_bounds(self, hydro_frame, mode):
        res = drought(hydro_frame, buffer_mode=mode)
        floor = OPERATING_ASSUMPTIONS["min_storage_pct"] / 100
        d = res.daily
        assert (d["storage_mm3"] <= d["capacity_mm3"] + TOL).all()
        assert (d["storage_mm3"] >= floor * d["capacity_mm3"] - TOL).all()

    def test_deliveries_bounded_by_demand(self, hydro_frame):
        d = drought(hydro_frame).daily
        for u in USES:
            assert (d[f"{u}_delivered_mm3"] >= -TOL).all()
            assert (d[f"{u}_delivered_mm3"] <= d[f"{u}_demand_mm3"] + TOL).all()
            assert (d[f"{u}_deficit_mm3"] >= -TOL).all()

    def test_spill_when_full(self):
        frame = make_hydro_frame({HANSALI: 2000.0, BIN_EL_OUIDANE: 10.0, AL_MASSIRA: 2020.0})
        res = optimize(frame, ScenarioParams(initial_storage_pct=150))
        h = res.daily.filter(pl.col("node_id") == HANSALI)
        assert h["excess_release_mm3"].sum() > 0  # 172 Mm3/day cannot all be stored
        assert h["storage_mm3"].max() <= NODES_BY_ID[HANSALI].capacity_mm3 + TOL

    def test_no_voluntary_spill_when_not_needed(self, baseline):
        m = baseline.daily.filter(pl.col("node_id") == AL_MASSIRA)
        assert m["excess_release_mm3"].sum() == pytest.approx(0, abs=TOL)


# =========================================================================== economics / priorities
class TestPriorities:
    def test_weight_ladder_is_consistent(self):
        """irrigation < soft buffer (+ worst-case daily accumulation) < irrigation deep cut
        < ecological < potable < hard buffer. Breaking this ladder silently changes policy."""
        a, w = OPERATING_ASSUMPTIONS, PRIORITY_WEIGHTS
        soft_max = a["buffer_penalty_soft"] + HORIZON_DAYS * a["buffer_daily_penalty"]
        deep = w["irrigation"] * a["irrigation_deep_cut_multiplier"]
        assert w["irrigation"] < a["buffer_penalty_soft"] and soft_max < deep
        assert deep < w["ecological"] < w["potable"] < a["buffer_penalty_hard"]

    def test_full_service_under_normal_conditions(self, baseline):
        for u in USES:
            assert baseline.summary[f"{u}_reliability_pct"] == pytest.approx(100.0, abs=1e-4)

    def test_soft_buffer_hedges_irrigation_first(self, hydro_frame):
        res = drought(hydro_frame, buffer_mode="soft")
        s = res.summary
        assert res.status == "Deficit Warning"
        assert s["potable_reliability_pct"] == pytest.approx(100, abs=1e-4)
        assert s["ecological_reliability_pct"] == pytest.approx(100, abs=1e-4)
        assert s["irrigation_reliability_pct"] < 100

    def test_soft_buffer_rations_rather_than_cuts_irrigation(self, hydro_frame):
        """Hedging rule: with weight 5 < buffer 6.5 < deep-cut 7.5, irrigation is rationed
        to the hedge share instead of zeroed when the buffer is breached."""
        d = drought(hydro_frame, buffer_mode="soft").daily
        hedge = OPERATING_ASSUMPTIONS["irrigation_hedge_share"]
        ratio = d["irrigation_delivered_mm3"].sum() / d["irrigation_demand_mm3"].sum()
        assert ratio == pytest.approx(1 - hedge, abs=1e-4)
        hard = drought(hydro_frame, buffer_mode="hard").summary
        assert hard["irrigation_reliability_pct"] < 100 * (1 - hedge)

    def test_hard_buffer_cuts_irrigation_before_potable(self, hydro_frame):
        s = drought(hydro_frame, buffer_mode="hard").summary
        assert s["potable_reliability_pct"] >= s["irrigation_reliability_pct"] - 1e-6

    def test_hard_buffer_keeps_upstream_eco_flow(self, hydro_frame):
        """Upstream ecological releases are not lost to the basin: they refill Al Massira,
        so even 'protect storage at all costs' still delivers them."""
        d = drought(hydro_frame, buffer_mode="hard").daily
        up = d.filter(pl.col("node_id").is_in([HANSALI, BIN_EL_OUIDANE]))
        assert up["ecological_deficit_mm3"].sum() == pytest.approx(0, abs=1e-6)

    def test_priority_ordering_near_dead_storage(self):
        """Physical scarcity (not the buffer) binds: water goes potable > eco > irrigation."""
        inp = build_inputs(make_hydro_frame({HANSALI: 0.0, BIN_EL_OUIDANE: 0.0, AL_MASSIRA: 0.0}),
                           ScenarioParams(safety_buffer_pct=10))
        floor = OPERATING_ASSUMPTIONS["min_storage_pct"] / 100
        for r in inp.reservoirs.values():
            r.initial_storage = floor * r.capacity + 25.0  # 25 Mm3 usable for 30 days
            r.evaporation = [0.0] * inp.horizon
        res = solve(inp)
        assert res.is_optimal
        for r in RESERVOIR_IDS:
            d = res.daily.filter(pl.col("node_id") == r)
            rel = {u: d[f"{u}_delivered_mm3"].sum() / d[f"{u}_demand_mm3"].sum() for u in USES}
            assert rel["potable"] >= rel["ecological"] - 1e-6 >= rel["irrigation"] - 2e-6, (r, rel)
        assert res.summary["potable_reliability_pct"] == pytest.approx(100, abs=1e-4)
        assert res.summary["irrigation_reliability_pct"] < 100

    def test_hard_buffer_protects_storage_more(self, hydro_frame):
        soft = drought(hydro_frame, buffer_mode="soft").summary
        hard = drought(hydro_frame, buffer_mode="hard").summary
        assert hard["terminal_buffer_breach_mm3"] <= soft["terminal_buffer_breach_mm3"] + TOL
        assert hard["final_storage"] >= soft["final_storage"] - TOL

    def test_drier_never_reduces_deficit(self, hydro_frame):
        prev = -1.0
        for shock in (50, 0, -25, -50):
            res = optimize(hydro_frame, ScenarioParams(inflow_shock_pct=shock, initial_storage_pct=25,
                                                       safety_buffer_pct=30))
            assert res.summary["unmet"] >= prev - TOL
            prev = res.summary["unmet"]

    def test_higher_buffer_never_increases_storage_drawdown(self, hydro_frame):
        finals = [
            optimize(hydro_frame, ScenarioParams(safety_buffer_pct=b, initial_storage_pct=40))
            .summary["final_storage"]
            for b in (10, 20, 30, 40)
        ]
        assert finals == sorted(finals)

    def test_objective_matches_weighted_deficit(self, baseline):
        assert baseline.objective == pytest.approx(0.0, abs=1e-3)

    def test_solver_is_fast(self, baseline):
        assert baseline.solve_seconds < 5.0


def test_solve_accepts_prebuilt_inputs(hydro_frame):
    res = solve(build_inputs(hydro_frame, ScenarioParams(inflow_forecast="p75")))
    assert res.is_optimal
