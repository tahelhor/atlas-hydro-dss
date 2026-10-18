"""Contract tests for the animated 3D basin story: payload shape, value ranges, change detection,
per-solution effects and the HTML/JS assets the component depends on."""

from __future__ import annotations

import json
import re
import time

import pytest

from src.config import DB_PATH
from src.region.planner_config import LEVERS

pytestmark = [
    pytest.mark.warehouse,
    pytest.mark.skipif(not DB_PATH.exists(), reason="warehouse not built - run the ingestion"),
]

FULL = dict(leak_reduction_pts=12, storage_autonomy_h=24, backup_source_pct=60, rural_connection_pct=50,
            interconnection_mm3=12, demand_saving_pct=8, drip_conversion_pct=60, reuse_mm3=16,
            groundwater_cap_pct=50, desal_mm3=150)
FILLS = (79.7, 82.9, 40.2)


@pytest.fixture(scope="module")
def world():
    from src.models.regional_planner import PlannerScenario, SolutionLevers, build_year_inputs, solve
    from src.region.diagnostics import load_climate_monthly, load_discharge_monthly

    inp = build_year_inputs(2022, load_discharge_monthly(), load_climate_monthly())
    base = solve(PlannerScenario(2022, FILLS), inp)
    levers = SolutionLevers(**{k: float(v) for k, v in FULL.items()})
    sol = solve(PlannerScenario(2022, FILLS, levers), inp)
    singles = {k: solve(PlannerScenario(2022, FILLS, SolutionLevers(**{k: float(v)})), inp) for k, v in FULL.items()}
    return inp, base, sol, levers, singles


@pytest.fixture(scope="module")
def payload(world):
    from src.app.views.simulator_map import build_payload

    inp, base, sol, levers, singles = world
    return build_payload(base, sol, levers, inp, singles)


def test_payload_is_json_and_compact(payload):
    text = json.dumps(payload)
    assert len(text) < 120_000  # sent on every slider move


def test_seven_chapters_in_story_order(payload):
    assert [c["id"] for c in payload["chapters"]] == ["basin", "drought", "who", "flows", "plan", "change", "explore"]
    for c in payload["chapters"]:
        assert c["title"] and c["text"]


def test_province_series_are_physical(payload):
    assert len(payload["provinces"]) == 5
    for p in payload["provinces"]:
        for view in ("before", "after"):
            block = p[view]
            assert len(block["monthly"]) == 12
            assert all(0 <= h <= 24 for h in block["monthly"])
            assert 0 <= block["annual"] <= 24 and block["breakdown"] >= 0 and block["noTap"] >= 0
        assert 0 <= p["localShare"] <= 100
        assert p["geometry"]["type"] in ("Polygon", "MultiPolygon")


def test_reservoirs_and_flows(payload):
    assert {r["id"] for r in payload["reservoirs"]} == {"HANSALI", "BIN_EL_OUIDANE", "AL_MASSIRA"}
    for r in payload["reservoirs"]:
        assert all(0 <= v <= 100 for v in r["before"] + r["after"]) and len(r["before"]) == 12
    assert not next(r for r in payload["reservoirs"] if r["id"] == "AL_MASSIRA")["inRegion"]
    assert payload["flows"]
    for f in payload["flows"]:
        assert f["kind"] in ("potable", "irrigation", "export")
        assert all(v >= 0 for v in f["before"] + f["after"])


def test_worst_province_is_the_lowest_baseline(payload):
    worst = min(payload["provinces"], key=lambda p: p["before"]["annual"])
    assert payload["worst"] == worst["id"]


def test_every_active_solution_has_a_build_card(payload):
    assert {lv["key"] for lv in payload["levers"]} == set(FULL)
    for lv in payload["levers"]:
        for field in ("component", "location", "build", "metric", "before", "own", "package", "anchor"):
            assert lv[field], (lv["key"], field)


def test_desalination_card_shows_water_kept_upstream(world, payload):
    inp, base, sol, levers, singles = world
    card = next(lv for lv in payload["levers"] if lv["key"] == "desal_mm3")
    assert singles["desal_mm3"].summary["upstream_to_massira"] <= base.summary["upstream_to_massira"]
    assert card["metric"]  # "Upstream water released downstream"


def test_hash_changes_only_when_data_changes(world):
    from src.app.views.simulator_map import build_payload
    from src.models.regional_planner import SolutionLevers

    inp, base, sol, levers, singles = world
    a = build_payload(base, sol, levers, inp, singles)["hash"]
    b = build_payload(base, sol, levers, inp, singles)["hash"]
    c = build_payload(base, base, SolutionLevers(), inp, {})["hash"]
    assert a == b != c


def test_no_solutions_invites_instead_of_fake_change(world):
    from src.app.views.simulator_map import build_payload
    from src.models.regional_planner import SolutionLevers

    inp, base, *_ = world
    p = build_payload(base, base, SolutionLevers(), inp, {})
    change = next(c for c in p["chapters"] if c["id"] == "change")
    assert change["stats"] == [] and p["levers"] == []


def _chapters(payload: dict) -> dict:
    return {c["id"]: c for c in payload["chapters"]}


def test_drought_copy_follows_the_numbers(payload):
    ch = _chapters(payload)
    assert ch["drought"]["title"].startswith("2021-22") and "drought" in ch["drought"]["title"]
    assert "58% to 33%" in ch["drought"]["text"]  # dam trajectory over the replayed year
    assert "14.5 h in July" in ch["who"]["text"]  # worst month named, not rounded to 14
    assert payload["replayYear"] == 2022  # month badge: Sep 2021 ... Aug 2022
    assert all(s["tone"] == "good" for s in ch["change"]["stats"])


def test_wet_year_is_not_told_as_a_drought(world):
    from src.app.views.simulator_map import build_payload
    from src.models.regional_planner import PlannerScenario, SolutionLevers, build_year_inputs, solve
    from src.region.diagnostics import load_climate_monthly, load_discharge_monthly

    wet = build_year_inputs(2010, load_discharge_monthly(), load_climate_monthly())
    base = solve(PlannerScenario(2010, FILLS), wet)
    ch = _chapters(build_payload(base, base, SolutionLevers(), wet, {}))
    assert "wet" in ch["drought"]["title"] and "only" not in ch["drought"]["text"]
    assert "refill" in ch["drought"]["text"]
    assert "run dry" not in ch["who"]["title"] and "fragile" in ch["who"]["title"]
    assert "beyond its recharge" not in ch["flows"]["text"]


@pytest.mark.parametrize("lever, tone, phrase", [
    ("desal_mm3", "", "doesn't change"),  # water kept upstream never reaches the towns that run short
    ("rural_connection_pct", "warn", "Trade-off"),  # new taps share the same springs and wells
])
def test_unchanged_or_worse_is_not_shown_as_a_gain(world, lever, tone, phrase):
    from src.app.views.simulator_map import build_payload
    from src.models.regional_planner import PlannerScenario, SolutionLevers, solve

    inp, base, *_ = world
    lv = SolutionLevers(**{lever: float(FULL[lever])})
    sol = solve(PlannerScenario(2022, FILLS, lv), inp)
    change = _chapters(build_payload(base, sol, lv, inp, {lever: sol}))["change"]
    assert change["stats"][0]["tone"] == tone
    assert phrase in change["text"]


def test_second_source_card_counts_residents_taken_off_a_single_pipe(payload):
    card = next(lv for lv in payload["levers"] if lv["key"] == "backup_source_pct")
    assert card["improves"]


def test_payload_and_step_are_fast(world):
    from src.app.views.simulator_map import build_payload
    from src.models.regional_planner import PlannerScenario, SolutionLevers, solve

    inp, base, sol, levers, singles = world
    t = time.perf_counter()
    build_payload(base, sol, levers, inp, singles)
    assert time.perf_counter() - t < 0.5
    t = time.perf_counter()  # one slider step = package solve + that lever alone
    solve(PlannerScenario(2022, FILLS, SolutionLevers(**{**FULL, "leak_reduction_pts": 13.0})), inp)
    solve(PlannerScenario(2022, FILLS, SolutionLevers(leak_reduction_pts=13.0)), inp)
    assert time.perf_counter() - t < 3.0


def test_assets_wire_up():
    from src.app.views.simulator_map import ASSET_DIR, _COPY

    html = (ASSET_DIR / "story.html").read_text(encoding="utf-8")
    js = (ASSET_DIR / "story.js").read_text(encoding="utf-8")
    assert "export default function" in js
    for cls in re.findall(r"\$\('\.([a-z-]+)'\)", js):  # every element the script queries exists
        assert f'class="{cls}' in html or f" {cls}" in html or f'"{cls}"' in html, cls
    for key in re.findall(r"copy\.([a-z_]+)", js):  # every copy key the script reads is provided
        assert key in _COPY, key
    assert re.search(r"THREE_VERSION = '\d+\.\d+\.\d+'", js)  # pinned Three.js version, no floating tag
    anchors = set(re.findall(r"l\.anchor === '([a-z_]+)'", js))
    from src.app.views.simulator_map import _PROJECT_VISUALS
    assert {v["anchor"] for v in _PROJECT_VISUALS.values()} <= anchors  # every solution has 3D assets
    assert set(_PROJECT_VISUALS) == set(LEVERS)
