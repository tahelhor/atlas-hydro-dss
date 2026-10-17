"""QA suite for the ingestion pipeline: API contracts, physical bounds, transforms, persistence."""

from __future__ import annotations

import asyncio
import math
from datetime import date, timedelta

import duckdb
import httpx
import polars as pl
import pytest
from pydantic import ValidationError

from src.config import (
    GLOFAS_FORECAST_DAYS,
    HISTORY_DAYS,
    M3S_TO_MM3_PER_DAY,
    NODES,
    WEATHER_FORECAST_DAYS,
)
from src.ingestion import fetch_hydro_climate as ingest
from src.ingestion.validator import (
    GloFASPayload,
    HydroDailyRecord,
    WeatherPayload,
    detect_anomalies,
    validate_rows,
)
from tests.conftest import make_glofas_payload, make_weather_payload

TOTAL_DAYS = HISTORY_DAYS + GLOFAS_FORECAST_DAYS


def valid_row(**overrides) -> dict:
    q = overrides.pop("river_discharge_m3s", 12.5)
    row = {
        "node_id": "DAM_AL_MASSIRA",
        "date": date.today(),
        "is_forecast": True,
        "river_discharge_m3s": q,
        "discharge_p25_m3s": q * 0.8,
        "discharge_p75_m3s": q * 1.2,
        "inflow_mm3": q * M3S_TO_MM3_PER_DAY,
        "inflow_p25_mm3": q * 0.8 * M3S_TO_MM3_PER_DAY,
        "inflow_p75_mm3": q * 1.2 * M3S_TO_MM3_PER_DAY,
        "precipitation_mm": 3.1,
        "snowfall_cm": 0.0,
        "temperature_max_c": 22.0,
        "et0_fao_mm": 4.2,
        "soil_moisture_deep_m3m3": 0.21,
        "weather_is_filled": False,
    }
    row.update(overrides)
    return row


# =========================================================================== payload contracts
class TestPayloadContracts:
    def test_valid_glofas_payload(self, glofas_payload):
        p = GloFASPayload.model_validate(glofas_payload)
        assert len(p.daily.time) == TOTAL_DAYS
        assert isinstance(p.daily.time[0], date)

    def test_valid_weather_payload(self, weather_payload):
        p = WeatherPayload.model_validate(weather_payload)
        assert len(p.hourly.time) == 24 * len(p.daily.time)

    @pytest.mark.parametrize("var", ["river_discharge", "river_discharge_mean",
                                     "river_discharge_p25", "river_discharge_p75"])
    def test_glofas_missing_variable_rejected(self, glofas_payload, var):
        del glofas_payload["daily"][var]
        with pytest.raises(ValidationError, match="missing daily variables"):
            GloFASPayload.model_validate(glofas_payload)

    def test_weather_missing_hourly_soil_moisture_rejected(self, weather_payload):
        del weather_payload["hourly"]["soil_moisture_28_to_100cm"]
        with pytest.raises(ValidationError, match="missing variables"):
            WeatherPayload.model_validate(weather_payload)

    def test_ragged_arrays_rejected(self, glofas_payload):
        glofas_payload["daily"]["river_discharge_p75"].pop()
        with pytest.raises(ValidationError, match="length"):
            GloFASPayload.model_validate(glofas_payload)

    def test_duplicate_dates_rejected(self, glofas_payload):
        glofas_payload["daily"]["time"][1] = glofas_payload["daily"]["time"][0]
        with pytest.raises(ValidationError, match="duplicate"):
            GloFASPayload.model_validate(glofas_payload)

    def test_unsorted_dates_rejected(self, glofas_payload):
        t = glofas_payload["daily"]["time"]
        t[0], t[1] = t[1], t[0]
        with pytest.raises(ValidationError, match="sorted"):
            GloFASPayload.model_validate(glofas_payload)

    def test_malformed_date_rejected(self, glofas_payload):
        glofas_payload["daily"]["time"][5] = "2026-13-45"
        with pytest.raises(ValidationError):
            GloFASPayload.model_validate(glofas_payload)

    @pytest.mark.parametrize("lat", [-91, 91])
    def test_coordinates_bounded(self, glofas_payload, lat):
        glofas_payload["latitude"] = lat
        with pytest.raises(ValidationError):
            GloFASPayload.model_validate(glofas_payload)

    def test_api_error_payload_rejected(self):
        with pytest.raises(ValidationError):
            GloFASPayload.model_validate({"error": True, "reason": "Cannot initialize"})


# =========================================================================== physical bounds
class TestRowGate:
    def test_valid_row_passes(self):
        rec = HydroDailyRecord.model_validate(valid_row())
        assert rec.inflow_mm3 == pytest.approx(12.5 * 0.0864)

    def test_nullable_weather_on_history_allowed(self):
        row = valid_row(is_forecast=False, precipitation_mm=None, et0_fao_mm=None,
                        soil_moisture_deep_m3m3=None, date=date.today() - timedelta(days=80))
        HydroDailyRecord.model_validate(row)

    @pytest.mark.parametrize(
        "field,value",
        [
            ("precipitation_mm", -0.1),
            ("et0_fao_mm", -0.01),
            ("snowfall_cm", -1.0),
            ("discharge_p25_m3s", -2.0),
            ("soil_moisture_deep_m3m3", 1.2),
            ("soil_moisture_deep_m3m3", -0.05),
            ("temperature_max_c", 75.0),
            ("et0_fao_mm", 35.0),
            ("precipitation_mm", 900.0),
        ],
    )
    def test_physical_bounds(self, field, value):
        with pytest.raises(ValidationError):
            HydroDailyRecord.model_validate(valid_row(**{field: value}))

    def test_negative_discharge_rejected(self):
        row = valid_row(river_discharge_m3s=-1.0)
        with pytest.raises(ValidationError, match="greater than or equal to 0"):
            HydroDailyRecord.model_validate(row)

    def test_discharge_ceiling(self):
        with pytest.raises(ValidationError):
            HydroDailyRecord.model_validate(valid_row(river_discharge_m3s=50_000.0))

    @pytest.mark.parametrize("value", [float("nan"), float("inf")])
    def test_non_finite_rejected(self, value):
        with pytest.raises(ValidationError):
            HydroDailyRecord.model_validate(valid_row(et0_fao_mm=value))

    def test_inverted_ensemble_bounds_rejected(self):
        with pytest.raises(ValidationError, match="inverted"):
            HydroDailyRecord.model_validate(valid_row(discharge_p25_m3s=20, discharge_p75_m3s=10))

    def test_inflow_must_match_unit_conversion(self):
        with pytest.raises(ValidationError, match="inflow_mm3"):
            HydroDailyRecord.model_validate(valid_row(inflow_mm3=12.5))  # m3/s left unconverted

    @pytest.mark.parametrize("value", ["yes", 1, "true", None])
    def test_is_forecast_must_be_strict_bool(self, value):
        with pytest.raises(ValidationError):
            HydroDailyRecord.model_validate(valid_row(is_forecast=value))

    @pytest.mark.parametrize("d", [date(1900, 1, 1), date.today() + timedelta(days=120),
                                   "not-a-date"])
    def test_date_window(self, d):
        with pytest.raises(ValidationError):
            HydroDailyRecord.model_validate(valid_row(date=d))

    def test_unknown_node_rejected(self):
        with pytest.raises(ValidationError, match="unknown node_id"):
            HydroDailyRecord.model_validate(valid_row(node_id="DAM_ATLANTIS"))

    def test_extra_columns_forbidden(self):
        with pytest.raises(ValidationError):
            HydroDailyRecord.model_validate(valid_row(sneaky_column=1))

    def test_ffill_only_on_forecast(self):
        with pytest.raises(ValidationError, match="forward-filled"):
            HydroDailyRecord.model_validate(valid_row(is_forecast=False, weather_is_filled=True))

    def test_validate_rows_quarantines_and_reports(self):
        rows = [valid_row(), valid_row(precipitation_mm=-5.0), valid_row(et0_fao_mm=-1)]
        clean, report = validate_rows(rows)
        assert len(clean) == 1
        assert report.rows_received == 3
        assert report.rows_rejected == 2
        assert report.pass_rate == pytest.approx(1 / 3)
        assert report.rule_failures["precipitation_mm"] == 1
        assert all("reason" in r for r in report.rejections)

    def test_anomaly_detector_flags_spike_but_keeps_row(self):
        rows = [valid_row(date=date.today(), river_discharge_m3s=2.0),
                valid_row(date=date.today() + timedelta(days=1), river_discharge_m3s=400.0)]
        assert len(detect_anomalies(rows)) == 1
        clean, report = validate_rows(rows)
        assert len(clean) == 2 and len(report.warnings) == 1


# =========================================================================== transforms
class TestTransforms:
    def test_unit_conversion_constant(self):
        assert M3S_TO_MM3_PER_DAY == pytest.approx(0.0864)
        assert 100 * 86_400 / 1_000_000 == pytest.approx(8.64)

    def test_glofas_coalesce_and_conversion(self, glofas_payload):
        df = ingest.transform_glofas(GloFASPayload.model_validate(glofas_payload), "DAM_AL_MASSIRA")
        assert df.height == TOTAL_DAYS
        hist, fc = df.filter(~pl.col("is_forecast")), df.filter(pl.col("is_forecast"))
        assert hist.height == HISTORY_DAYS and fc.height == GLOFAS_FORECAST_DAYS
        # history uses river_discharge (q+1 = 11), forecast uses the ensemble mean (q = 10)
        assert hist["river_discharge_m3s"].unique().to_list() == [11.0]
        assert fc["river_discharge_m3s"].unique().to_list() == [10.0]
        assert fc["inflow_mm3"][0] == pytest.approx(10.0 * 0.0864)
        assert fc["inflow_p25_mm3"][0] == pytest.approx(6.0 * 0.0864)
        assert fc["inflow_p75_mm3"][0] == pytest.approx(15.0 * 0.0864)

    def test_glofas_coalesce_falls_back_when_null(self, glofas_payload):
        d = glofas_payload["daily"]
        d["river_discharge"][0] = None  # historical gap -> fall back to mean
        d["river_discharge_mean"][-1] = None  # forecast gap -> fall back to control run
        df = ingest.transform_glofas(GloFASPayload.model_validate(glofas_payload), "X")
        assert df["river_discharge_m3s"][0] == 10.0
        assert df["river_discharge_m3s"][-1] == 11.0
        assert df["river_discharge_m3s"].null_count() == 0

    def test_first_forecast_day_is_today(self, glofas_payload):
        df = ingest.transform_glofas(GloFASPayload.model_validate(glofas_payload), "X")
        assert df.filter(pl.col("is_forecast"))["date"].min() == date.today()

    def test_soil_moisture_daily_mean(self, weather_payload):
        df = ingest.transform_weather(WeatherPayload.model_validate(weather_payload))
        assert df["soil_moisture_deep_m3m3"].to_list() == pytest.approx([0.25] * df.height)

    def test_join_forward_fills_days_17_to_30(self, glofas_payload, weather_payload):
        weather_payload["daily"]["et0_fao_evapotranspiration"][-1] = 6.6
        g = ingest.transform_glofas(GloFASPayload.model_validate(glofas_payload), "X")
        w = ingest.transform_weather(WeatherPayload.model_validate(weather_payload))
        j = ingest.join_node(g, w)
        assert j.height == TOTAL_DAYS
        fc = j.filter(pl.col("is_forecast"))
        filled = fc.filter(pl.col("weather_is_filled"))
        assert filled.height == GLOFAS_FORECAST_DAYS - WEATHER_FORECAST_DAYS
        assert filled["et0_fao_mm"].unique().to_list() == [6.6]  # last observed value carried
        assert fc["et0_fao_mm"].null_count() == 0
        assert j.columns == list(ingest.FACT_SCHEMA)

    def test_join_does_not_backfill_history(self, glofas_payload):
        weather = make_weather_payload(null_head=30)
        g = ingest.transform_glofas(GloFASPayload.model_validate(glofas_payload), "X")
        w = ingest.transform_weather(WeatherPayload.model_validate(weather))
        j = ingest.join_node(g, w)
        hist = j.filter(~pl.col("is_forecast"))
        assert hist["et0_fao_mm"].null_count() == 30
        assert not hist["weather_is_filled"].any()

    def test_request_params_match_contract(self):
        node = NODES[1]
        gp, wp = ingest.glofas_params(node), ingest.weather_params(node)
        assert gp["past_days"] == 92 and gp["forecast_days"] == 30
        assert gp["daily"] == ("river_discharge,river_discharge_mean,"
                               "river_discharge_p25,river_discharge_p75")
        assert wp["forecast_days"] == 16 and wp["timezone"] == "Africa/Casablanca"
        assert wp["hourly"] == "soil_moisture_28_to_100cm"
        assert "et0_fao_evapotranspiration" in wp["daily"]


# =========================================================================== HTTP + persistence
class TestPipelineEndToEnd:
    def test_retry_on_transient_5xx(self, mock_transport_factory):
        transport = mock_transport_factory(fail_first=2, status=503)
        payloads = asyncio.run(ingest.fetch_all(nodes=NODES[:1], transport=transport))
        assert NODES[0].node_id in payloads
        assert transport.calls["n"] == 4  # 2 failures + 2 successful calls

    def test_client_error_is_not_retried(self, mock_transport_factory):
        transport = mock_transport_factory(fail_first=1, status=400)
        with pytest.raises(httpx.HTTPStatusError):
            asyncio.run(ingest.fetch_all(nodes=NODES[:1], transport=transport))

    def test_full_pipeline_writes_warehouse(self, tmp_path, mock_transport_factory):
        db = tmp_path / "wh.duckdb"
        fact, report = ingest.run_pipeline(db, transport=mock_transport_factory())
        assert report.rows_rejected == 0
        with duckdb.connect(str(db), read_only=True) as con:
            assert con.execute("SELECT count(*) FROM dim_basin_nodes").fetchone()[0] == 4
            n, nodes, fc = con.execute(
                "SELECT count(*), count(DISTINCT node_id), sum(is_forecast::INT) "
                "FROM fact_hydro_daily").fetchone()
            assert (n, nodes, fc) == (4 * TOTAL_DAYS, 4, 4 * GLOFAS_FORECAST_DAYS)
            bad = con.execute(
                "SELECT count(*) FROM fact_hydro_daily "
                "WHERE abs(inflow_mm3 - river_discharge_m3s * 0.0864) > 1e-9").fetchone()[0]
            assert bad == 0
            assert con.execute("SELECT status FROM etl_run_log").fetchone()[0] == "SUCCESS"

    def test_pipeline_is_idempotent(self, tmp_path, mock_transport_factory):
        db = tmp_path / "wh.duckdb"
        ingest.run_pipeline(db, transport=mock_transport_factory())
        ingest.run_pipeline(db, transport=mock_transport_factory())
        with duckdb.connect(str(db), read_only=True) as con:
            assert con.execute("SELECT count(*) FROM fact_hydro_daily").fetchone()[0] == 4 * TOTAL_DAYS
            assert con.execute("SELECT count(*) FROM etl_run_log").fetchone()[0] == 2
            dupes = con.execute("SELECT count(*) FROM (SELECT node_id, date FROM fact_hydro_daily "
                                "GROUP BY ALL HAVING count(*) > 1)").fetchone()[0]
            assert dupes == 0

    def test_bad_rows_are_quarantined_not_loaded(self, tmp_path, mock_transport_factory):
        def corrupt(payload: dict, lat: float) -> dict:
            if math.isclose(lat, NODES[0].glofas_lat):
                payload["daily"]["river_discharge"][3] = -7.0  # physically impossible
            return payload

        db = tmp_path / "wh.duckdb"
        _, report = ingest.run_pipeline(db, transport=mock_transport_factory(corrupt))
        assert report.rows_rejected == 1
        with duckdb.connect(str(db), read_only=True) as con:
            assert con.execute("SELECT count(*) FROM fact_hydro_daily").fetchone()[0] == 4 * TOTAL_DAYS - 1
            assert con.execute("SELECT min(river_discharge_m3s) FROM fact_hydro_daily").fetchone()[0] >= 0
            reason = con.execute("SELECT reason FROM qa_rejections").fetchone()[0]
            assert "river_discharge_m3s" in reason
            status = con.execute("SELECT status FROM etl_run_log").fetchone()[0]
            assert status == "SUCCESS_WITH_REJECTIONS"

    def test_malformed_payload_aborts_before_write(self, tmp_path, mock_transport_factory):
        def drop_var(payload: dict, lat: float) -> dict:
            del payload["daily"]["river_discharge_p25"]
            return payload

        db = tmp_path / "wh.duckdb"
        with pytest.raises(ValidationError):
            ingest.run_pipeline(db, transport=mock_transport_factory(drop_var))
        assert not db.exists()
