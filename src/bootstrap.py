"""Self-provisioning of the DuckDB warehouse for hosted runs (e.g. Streamlit Community Cloud).

The repository does not ship the database. On a fresh machine the dashboard calls
:func:`ensure_warehouse`, which builds what is missing and refreshes what is stale:

* live 122-day window (GloFAS + ECMWF)  - if absent or older than ``max_live_age_h``
* 1991→today climate & river archive    - if absent or older than ``max_history_age_days``

A process-wide lock makes concurrent sessions wait for one ingestion instead of racing.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from src.config import DB_PATH

log = logging.getLogger("atlas.bootstrap")
_LOCK = threading.Lock()


def warehouse_status(db_path: Path = DB_PATH) -> dict:
    """What the warehouse contains and how old each part is (hours / days, None if absent)."""
    status = {"exists": db_path.exists(), "live_age_h": None, "history_age_days": None}
    if not status["exists"]:
        return status
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with duckdb.connect(str(db_path)) as con:
        tables = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
        if "etl_run_log" in tables:
            last = con.execute("SELECT max(finished_at) FROM etl_run_log").fetchone()[0]
            if last is not None:
                status["live_age_h"] = (now - last).total_seconds() / 3600
        if {"etl_history_log", "fact_climate_monthly", "fact_discharge_monthly"} <= tables:
            last = con.execute("SELECT max(finished_at) FROM etl_history_log").fetchone()[0]
            if last is not None:
                status["history_age_days"] = (now - last).total_seconds() / 86400
    return status


def ensure_warehouse(db_path: Path = DB_PATH, max_live_age_h: float = 12.0,
                     max_history_age_days: float = 30.0) -> list[str]:
    """Build / refresh the warehouse as needed. Returns the actions taken (empty if fresh).

    Network failures are re-raised only when no usable data exists yet; otherwise the app keeps
    serving the previous data and the failure is logged.
    """
    from src.ingestion.fetch_climate_history import run_history_pipeline
    from src.ingestion.fetch_hydro_climate import run_pipeline

    with _LOCK:
        actions: list[str] = []
        st = warehouse_status(db_path)
        live_missing = st["live_age_h"] is None
        if live_missing or st["live_age_h"] > max_live_age_h:
            try:
                run_pipeline(db_path)
                actions.append("live")
            except Exception:
                if live_missing:
                    raise
                log.exception("live refresh failed - keeping previous data")
        history_missing = st["history_age_days"] is None
        if history_missing or st["history_age_days"] > max_history_age_days:
            try:
                run_history_pipeline(db_path)
                actions.append("history")
            except Exception:
                if history_missing:
                    raise
                log.exception("history refresh failed - keeping previous data")
        return actions
