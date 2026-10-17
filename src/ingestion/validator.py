"""Pydantic v2 QA gates.

Two layers:
1. **Payload contracts** (``GloFASPayload``, ``WeatherPayload``) - reject malformed API
   responses before any transformation (missing variables, ragged arrays, bad dates).
2. **Row gate** (``HydroDailyRecord``) - every joined daily row must satisfy physical
   hydrological bounds before it may be written to DuckDB. Failing rows are quarantined
   with the reason, never silently dropped.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    ValidationError,
    field_validator,
    model_validator,
)

from src.config import (
    GLOFAS_DAILY_VARS,
    M3S_TO_MM3_PER_DAY,
    NODE_IDS,
    WEATHER_DAILY_VARS,
    WEATHER_HOURLY_VARS,
)

# Physical plausibility ceilings for the Oum Er-Rbia basin (well above observed records).
MAX_DISCHARGE_M3S = 20_000.0
MAX_DAILY_PRECIP_MM = 500.0
MAX_DAILY_SNOW_CM = 300.0
MAX_ET0_MM = 20.0
TEMP_RANGE_C = (-30.0, 60.0)
EARLIEST_DATE = date(1979, 1, 1)
MAX_FORECAST_LEAD_DAYS = 45
INFLOW_REL_TOL = 1e-6


def _is_finite(v: float | None) -> bool:
    return v is None or math.isfinite(v)


# =========================================================================== payloads
class _DailyBlock(BaseModel):
    model_config = ConfigDict(extra="allow")
    time: list[date] = Field(min_length=1)

    @model_validator(mode="after")
    def _arrays_aligned(self) -> _DailyBlock:
        n = len(self.time)
        for key, values in (self.model_extra or {}).items():
            if not isinstance(values, list) or len(values) != n:
                raise ValueError(f"array '{key}' length != len(time)={n}")
        if len(set(self.time)) != n:
            raise ValueError("duplicate dates in time axis")
        if self.time != sorted(self.time):
            raise ValueError("time axis is not sorted ascending")
        return self


class _HourlyBlock(BaseModel):
    model_config = ConfigDict(extra="allow")
    time: list[datetime] = Field(min_length=1)

    @model_validator(mode="after")
    def _arrays_aligned(self) -> _HourlyBlock:
        n = len(self.time)
        for key, values in (self.model_extra or {}).items():
            if not isinstance(values, list) or len(values) != n:
                raise ValueError(f"array '{key}' length != len(time)={n}")
        return self


class _PayloadBase(BaseModel):
    model_config = ConfigDict(extra="ignore")
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class GloFASPayload(_PayloadBase):
    daily: _DailyBlock

    @model_validator(mode="after")
    def _required_vars(self) -> GloFASPayload:
        missing = set(GLOFAS_DAILY_VARS) - set(self.daily.model_extra or {})
        if missing:
            raise ValueError(f"GloFAS payload missing daily variables: {sorted(missing)}")
        return self


class WeatherPayload(_PayloadBase):
    timezone: str
    daily: _DailyBlock
    hourly: _HourlyBlock

    @model_validator(mode="after")
    def _required_vars(self) -> WeatherPayload:
        missing = set(WEATHER_DAILY_VARS) - set(self.daily.model_extra or {})
        missing |= set(WEATHER_HOURLY_VARS) - set(self.hourly.model_extra or {})
        if missing:
            raise ValueError(f"weather payload missing variables: {sorted(missing)}")
        return self


# =========================================================================== row gate
class HydroDailyRecord(BaseModel):
    """One node-day in ``fact_hydro_daily``. Weather fields are nullable because the
    forecast API's past window is shorter than GloFAS's; discharge is mandatory."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    node_id: str
    date: date
    is_forecast: StrictBool

    river_discharge_m3s: float = Field(ge=0, le=MAX_DISCHARGE_M3S)
    discharge_p25_m3s: float | None = Field(default=None, ge=0, le=MAX_DISCHARGE_M3S)
    discharge_p75_m3s: float | None = Field(default=None, ge=0, le=MAX_DISCHARGE_M3S)
    inflow_mm3: float = Field(ge=0)
    inflow_p25_mm3: float | None = Field(default=None, ge=0)
    inflow_p75_mm3: float | None = Field(default=None, ge=0)

    precipitation_mm: float | None = Field(default=None, ge=0, le=MAX_DAILY_PRECIP_MM)
    snowfall_cm: float | None = Field(default=None, ge=0, le=MAX_DAILY_SNOW_CM)
    temperature_max_c: float | None = Field(default=None, ge=TEMP_RANGE_C[0], le=TEMP_RANGE_C[1])
    et0_fao_mm: float | None = Field(default=None, ge=0, le=MAX_ET0_MM)
    soil_moisture_deep_m3m3: float | None = Field(default=None, ge=0, le=1)
    weather_is_filled: StrictBool = False

    @field_validator("node_id")
    @classmethod
    def _known_node(cls, v: str) -> str:
        if v not in NODE_IDS:
            raise ValueError(f"unknown node_id '{v}'")
        return v

    @field_validator("date")
    @classmethod
    def _date_window(cls, v: date) -> date:
        if v < EARLIEST_DATE or v > date.today() + timedelta(days=MAX_FORECAST_LEAD_DAYS):
            raise ValueError(f"date {v} outside plausible window")
        return v

    @field_validator(
        "river_discharge_m3s",
        "discharge_p25_m3s",
        "discharge_p75_m3s",
        "inflow_mm3",
        "precipitation_mm",
        "et0_fao_mm",
        "soil_moisture_deep_m3m3",
    )
    @classmethod
    def _finite(cls, v: float | None) -> float | None:
        if not _is_finite(v):
            raise ValueError("non-finite value (NaN/inf)")
        return v

    @model_validator(mode="after")
    def _cross_field_rules(self) -> HydroDailyRecord:
        p25, p75 = self.discharge_p25_m3s, self.discharge_p75_m3s
        if p25 is not None and p75 is not None and p25 > p75 + 1e-9:
            raise ValueError(f"ensemble bounds inverted: p25={p25} > p75={p75}")
        expected = self.river_discharge_m3s * M3S_TO_MM3_PER_DAY
        if not math.isclose(self.inflow_mm3, expected, rel_tol=INFLOW_REL_TOL, abs_tol=1e-9):
            raise ValueError(f"inflow_mm3={self.inflow_mm3} != discharge*0.0864={expected}")
        if self.weather_is_filled and not self.is_forecast:
            raise ValueError("forward-filled weather is only allowed on forecast days")
        return self


# =========================================================================== reporting
@dataclass
class QAReport:
    rows_received: int = 0
    rows_passed: int = 0
    rejections: list[dict[str, Any]] = field(default_factory=list)
    rule_failures: Counter = field(default_factory=Counter)
    warnings: list[str] = field(default_factory=list)

    @property
    def rows_rejected(self) -> int:
        return len(self.rejections)

    @property
    def pass_rate(self) -> float:
        return self.rows_passed / self.rows_received if self.rows_received else 0.0


def validate_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], QAReport]:
    """Run every row through ``HydroDailyRecord``; return clean dicts + QA report."""
    report = QAReport(rows_received=len(rows))
    clean: list[dict[str, Any]] = []
    for row in rows:
        try:
            clean.append(HydroDailyRecord.model_validate(row).model_dump())
        except ValidationError as exc:
            reasons = []
            for err in exc.errors():
                loc = ".".join(str(p) for p in err["loc"]) or "row"
                reasons.append(f"{loc}: {err['msg']}")
                report.rule_failures[loc] += 1
            report.rejections.append(
                {
                    "node_id": str(row.get("node_id")),
                    "date": str(row.get("date")),
                    "reason": "; ".join(reasons),
                }
            )
    report.rows_passed = len(clean)
    report.warnings.extend(detect_anomalies(clean))
    return clean, report


def detect_anomalies(rows: list[dict[str, Any]], spike_ratio: float = 10.0,
                     spike_floor_m3s: float = 50.0) -> list[str]:
    """Soft anomaly gate: flag (but keep) day-over-day discharge spikes."""
    warnings: list[str] = []
    by_node: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_node.setdefault(r["node_id"], []).append(r)
    for node_id, series in by_node.items():
        series.sort(key=lambda r: r["date"])
        for prev, cur in zip(series, series[1:]):
            q0, q1 = prev["river_discharge_m3s"], cur["river_discharge_m3s"]
            if q1 > spike_floor_m3s and q1 > spike_ratio * max(q0, 0.01):
                warnings.append(f"{node_id} {cur['date']}: discharge spike {q0:.2f} -> {q1:.2f} m3/s")
    return warnings
