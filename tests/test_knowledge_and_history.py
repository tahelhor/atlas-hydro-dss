"""QA for the sourced knowledge base, the long-term climate archive pipeline and diagnostics."""

from __future__ import annotations

import asyncio
import copy
import json
from datetime import date, timedelta

import duckdb
import httpx
import polars as pl
import pytest
from pydantic import ValidationError

from src.config import M3S_TO_MM3_PER_DAY, NODES
from src.ingestion import fetch_climate_history as hist
from src.region.diagnostics import amplification, drought_streak, hydro_year_table
from src.region.knowledge import KB_PATH, KnowledgeBase, load_knowledge_base
from src.region.planner_config import DEMANDS, LEVERS
from src.region.provinces import PROVINCE_IDS, PROVINCES, province_geojson


# =========================================================================== knowledge base
@pytest.fixture(scope="module")
def kb_raw() -> dict:
    return json.loads(KB_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def kb() -> KnowledgeBase:
    return load_knowledge_base()


class TestKnowledgeBase:
    def test_loads_and_validates(self, kb):
        assert len(kb.sources) >= 50
        assert len(kb.problems) >= 10 and len(kb.root_causes) >= 8 and len(kb.solutions) >= 8

    def test_every_statement_is_sourced(self, kb):
        for group in (kb.key_figures, kb.provinces, kb.towns, kb.problems, kb.root_causes,
                      kb.solutions, kb.stories):
            for entry in group:
                assert entry.source_ids, entry

    def test_sources_are_https_and_dated(self, kb):
        for s in kb.sources:
            assert str(s.url).startswith("https://"), s.id
            assert date(2000, 1, 1) <= s.published <= kb.compiled_on, s.id

    def test_problems_cover_daily_life_and_agriculture(self, kb):
        cats = {p.category for p in kb.problems}
        assert {"daily_life", "agriculture"} <= cats

    def test_root_causes_cover_all_groups(self, kb):
        assert {r.group for r in kb.root_causes} == {"climate", "overuse", "infrastructure", "governance"}

    def test_every_simulator_lever_has_a_solution_card(self, kb):
        assert set(LEVERS) <= {s.lever for s in kb.solutions if s.lever}

    def test_profiles_match_planner_populations(self, kb):
        planner = {d.province_id: d.population for d in DEMANDS}
        for p in kb.provinces:
            assert p.population_2024 == planner[p.province_id]

    def test_towns_fall_inside_their_province_bbox(self, kb):
        gj = province_geojson()
        bbox = {}
        for f in gj["features"]:
            ring = f["geometry"]["coordinates"][0]
            lons, lats = [c[0] for c in ring], [c[1] for c in ring]
            bbox[f["id"]] = (min(lons) - 0.05, max(lons) + 0.05, min(lats) - 0.05, max(lats) + 0.05)
        for t in kb.towns:
            x0, x1, y0, y1 = bbox[t.province_id]
            assert x0 <= t.lon <= x1 and y0 <= t.lat <= y1, t.name

    @pytest.mark.parametrize("mutation,match", [
        (lambda d: d["problems"][0].update(desc_fr=""), "bilingual"),
        (lambda d: d["problems"][0]["source_ids"].append("S999"), "unknown sources"),
        (lambda d: d["problems"][0].update(source_ids=[]), "at least 1"),
        (lambda d: d["towns"][0].update(province_id="ATLANTIS"), "unknown province"),
        (lambda d: d["towns"][0].update(lat=40.0), "less than or equal"),
        (lambda d: d["sources"].append(dict(d["sources"][0])), "duplicate source"),
        (lambda d: d["sources"][0].update(url="not a url"), "URL"),
        (lambda d: d["provinces"].pop(), "each of the 5 provinces"),
        (lambda d: d["problems"][0].update(severity=7), "less than or equal"),
    ])
    def test_schema_rejects_bad_content(self, kb_raw, mutation, match):
        bad = copy.deepcopy(kb_raw)
        mutation(bad)
        with pytest.raises(ValidationError, match=match):
            KnowledgeBase.model_validate(bad)


def test_province_geojson_has_the_five_provinces():
    gj = province_geojson()
    assert {f["id"] for f in gj["features"]} == set(PROVINCE_IDS)
    assert "ODbL" in gj["attribution"]
    assert len(PROVINCES) == 5


# =========================================================================== climate archive
def _era5_payload(start: date, days: int, precip: float = 2.0) -> dict:
    t = [(start + timedelta(days=i)).isoformat() for i in range(days)]
    return {"latitude": 32.3, "longitude": -6.3, "daily": {
        "time": t, "precipitation_sum": [precip] * days, "snowfall_sum": [0.0] * days,
        "temperature_2m_mean": [15.0] * days, "temperature_2m_max": [22.0] * days,
        "et0_fao_evapotranspiration": [3.0] * days}}


def _glofas_payload(start: date, days: int, q: float = 10.0) -> dict:
    t = [(start + timedelta(days=i)).isoformat() for i in range(days)]
    return {"latitude": 32.4, "longitude": -6.5, "daily": {"time": t, "river_discharge": [q] * days}}


class TestClimateHistory:
    def test_era5_monthly_aggregation(self):
        df = hist.era5_monthly(hist.ERA5Payload.model_validate(_era5_payload(date(2024, 1, 1), 60)), "AZILAL")
        jan = df.filter(pl.col("month") == date(2024, 1, 1)).row(0, named=True)
        assert jan["n_days"] == 31 and jan["precip_mm"] == pytest.approx(62.0)
        assert jan["tmean_c"] == pytest.approx(15.0) and jan["et0_mm"] == pytest.approx(93.0)

    def test_glofas_monthly_volume(self):
        df = hist.glofas_monthly(hist.GloFASHistoryPayload.model_validate(_glofas_payload(date(2024, 2, 1), 29)), "X")
        row = df.row(0, named=True)
        assert row["volume_mm3"] == pytest.approx(10.0 * M3S_TO_MM3_PER_DAY * 29)

    def test_payload_contract_rejects_missing_variable(self):
        p = _era5_payload(date(2024, 1, 1), 10)
        del p["daily"]["et0_fao_evapotranspiration"]
        with pytest.raises(ValidationError, match="missing"):
            hist.ERA5Payload.model_validate(p)

    def test_monthly_gate_rejects_impossible_values(self):
        df = pl.DataFrame([{"province_id": "AZILAL", "month": date(2024, 1, 1), "n_days": 31,
                            "precip_mm": -5.0, "snow_cm": 0.0, "tmean_c": 10.0, "tmax_c": 15.0,
                            "et0_mm": 50.0},
                           {"province_id": "AZILAL", "month": date(2024, 2, 1), "n_days": 29,
                            "precip_mm": 5.0, "snow_cm": 0.0, "tmean_c": 10.0, "tmax_c": 15.0,
                            "et0_mm": 50.0}])
        clean, errors = hist.validate_monthly(df, hist.ClimateMonthlyRecord)
        assert clean.height == 1 and len(errors) == 1

    def test_pipeline_writes_and_is_idempotent(self, tmp_path):
        def handler(request: httpx.Request) -> httpx.Response:
            start = date.fromisoformat(request.url.params["start_date"])
            end = date.fromisoformat(request.url.params["end_date"])
            days = (end - start).days + 1
            if request.url.host.startswith("archive-api"):
                return httpx.Response(200, json=_era5_payload(start, days))
            return httpx.Response(200, json=_glofas_payload(start, days))

        db = tmp_path / "wh.duckdb"
        end = date(1999, 12, 31)
        for _ in range(2):
            hist.run_history_pipeline(db, transport=httpx.MockTransport(handler), end=end)
        with duckdb.connect(str(db), read_only=True) as con:
            n_climate = con.execute("SELECT count(*) FROM fact_climate_monthly").fetchone()[0]
            n_q = con.execute("SELECT count(*) FROM fact_discharge_monthly").fetchone()[0]
            runs = con.execute("SELECT count(*) FROM etl_history_log").fetchone()[0]
        assert n_climate == 5 * 108  # 1991-01 … 1999-12, 5 provinces, no duplicates after 2 runs
        assert n_q == len(NODES) * 36  # 1997-01 … 1999-12
        assert runs == 2


# =========================================================================== diagnostics
def _synthetic_years() -> tuple[pl.DataFrame, pl.DataFrame]:
    clim, q = [], []
    for y in range(1997, 2026):
        for m in range(1, 13):
            hy = y + 1 if m >= 9 else y
            drought = 2020 <= hy <= 2025
            for p in PROVINCE_IDS:
                clim.append({"province_id": p, "month": date(y, m, 1), "precip_mm": 40.0 * (0.8 if drought else 1.0),
                             "snow_cm": 1.0 * (0.2 if drought else 1.0), "tmean_c": 17.0 + (2.0 if drought else 0.0),
                             "et0_mm": 120.0 * (1.1 if drought else 1.0)})
            q.append({"node_id": "DAM_AL_MASSIRA", "month": date(y, m, 1),
                      "volume_mm3": 150.0 * (0.4 if drought else 1.0)})
    return pl.DataFrame(clim), pl.DataFrame(q)


class TestDiagnostics:
    def test_anomalies_and_amplification(self):
        clim, q = _synthetic_years()
        table = hydro_year_table(clim, q)
        ref = table.filter(pl.col("hy").is_between(1998, 2018))
        assert ref["precip_anom_pct"].mean() == pytest.approx(0, abs=1e-6)
        amp = amplification(table, (2020, 2025))
        assert amp["precip_anom_pct"] == pytest.approx(-20, abs=1e-6)
        assert amp["inflow_anom_pct"] == pytest.approx(-60, abs=1e-6)
        assert amp["temp_anom_c"] == pytest.approx(2.0, abs=1e-6)

    def test_drought_streak(self):
        clim, q = _synthetic_years()
        assert drought_streak(hydro_year_table(clim, q)) == (6, 2020, 2025)
