"""Shared fixtures: synthetic Open-Meteo payloads, a mock HTTP transport and LP inputs."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Callable

import httpx
import polars as pl
import pytest

from src.config import (
    AL_MASSIRA,
    BIN_EL_OUIDANE,
    GLOFAS_FORECAST_DAYS,
    HANSALI,
    HISTORY_DAYS,
    M3S_TO_MM3_PER_DAY,
    NODES,
    RESERVOIR_IDS,
    WEATHER_FORECAST_DAYS,
)


def _dates(n_past: int, n_future: int) -> list[str]:
    start = date.today() - timedelta(days=n_past)
    return [(start + timedelta(days=i)).isoformat() for i in range(n_past + n_future)]


def make_glofas_payload(q: float = 10.0, n_past: int = HISTORY_DAYS,
                        n_future: int = GLOFAS_FORECAST_DAYS) -> dict[str, Any]:
    days = _dates(n_past, n_future)
    n = len(days)
    return {
        "latitude": 32.5,
        "longitude": -6.0,
        "daily_units": {"river_discharge": "m³/s"},
        "daily": {
            "time": days,
            # control run slightly differs from the ensemble mean to test the coalesce rule
            "river_discharge": [q + 1.0] * n,
            "river_discharge_mean": [q] * n,
            "river_discharge_p25": [q * 0.6] * n,
            "river_discharge_p75": [q * 1.5] * n,
        },
    }


def make_weather_payload(n_past: int = HISTORY_DAYS, n_future: int = WEATHER_FORECAST_DAYS,
                         null_head: int = 0) -> dict[str, Any]:
    days = _dates(n_past, n_future)
    n = len(days)

    def col(value: float) -> list[float | None]:
        return [None] * null_head + [value] * (n - null_head)

    hours = [
        (datetime.fromisoformat(days[0]) + timedelta(hours=h)).isoformat(timespec="minutes")
        for h in range(24 * n)
    ]
    # soil moisture alternates 0.20 / 0.30 hourly -> daily mean 0.25
    sm = [0.20 if h % 2 == 0 else 0.30 for h in range(24 * n)]
    return {
        "latitude": 32.5,
        "longitude": -6.0,
        "timezone": "Africa/Casablanca",
        "daily": {
            "time": days,
            "precipitation_sum": col(1.2),
            "snowfall_sum": col(0.0),
            "temperature_2m_max": col(24.0),
            "et0_fao_evapotranspiration": col(4.0),
        },
        "hourly": {"time": hours, "soil_moisture_28_to_100cm": sm},
    }


@pytest.fixture
def glofas_payload() -> dict[str, Any]:
    return make_glofas_payload()


@pytest.fixture
def weather_payload() -> dict[str, Any]:
    return make_weather_payload()


@pytest.fixture
def mock_transport_factory() -> Callable[..., httpx.MockTransport]:
    """Build an httpx.MockTransport serving synthetic payloads for both APIs.

    ``glofas_override(payload, lat)`` lets a test corrupt a specific node's payload.
    """

    def factory(glofas_override: Callable[[dict, float], dict] | None = None,
                fail_first: int = 0, status: int = 503) -> httpx.MockTransport:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] <= fail_first:
                return httpx.Response(status, json={"error": True})
            lat = float(request.url.params["latitude"])
            if request.url.host.startswith("flood-api"):
                payload = make_glofas_payload(q=lat)  # distinct flow per node
                if glofas_override:
                    payload = glofas_override(payload, lat)
                return httpx.Response(200, json=payload)
            return httpx.Response(200, json=make_weather_payload())

        transport = httpx.MockTransport(handler)
        transport.calls = calls  # type: ignore[attr-defined]
        return transport

    return factory


def make_hydro_frame(
    q_m3s: dict[str, float] | None = None,
    et0: float = 5.0,
    days: int = 30,
) -> pl.DataFrame:
    """Forecast-only fact_hydro_daily-like frame for the 3 reservoirs."""
    q_m3s = q_m3s or {HANSALI: 2.0, BIN_EL_OUIDANE: 5.0, AL_MASSIRA: 14.0}
    start = date.today()
    rows = []
    for r in RESERVOIR_IDS:
        q = q_m3s[r]
        for i in range(days):
            rows.append(
                {
                    "node_id": r,
                    "date": start + timedelta(days=i),
                    "is_forecast": True,
                    "inflow_mm3": q * M3S_TO_MM3_PER_DAY,
                    "inflow_p25_mm3": 0.5 * q * M3S_TO_MM3_PER_DAY,
                    "inflow_p75_mm3": 1.5 * q * M3S_TO_MM3_PER_DAY,
                    "et0_fao_mm": et0,
                }
            )
    return pl.DataFrame(rows)


@pytest.fixture
def hydro_frame() -> pl.DataFrame:
    return make_hydro_frame()


@pytest.fixture
def all_node_ids() -> list[str]:
    return [n.node_id for n in NODES]
