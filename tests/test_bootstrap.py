"""Self-provisioning of the warehouse on a fresh host (Streamlit Community Cloud ships no DB)."""

from __future__ import annotations

import httpx
import pytest

from src import bootstrap
from src.ingestion import fetch_climate_history, fetch_hydro_climate


def test_status_of_missing_warehouse(tmp_path):
    st = bootstrap.warehouse_status(tmp_path / "none.duckdb")
    assert st == {"exists": False, "live_age_h": None, "history_age_days": None}


def test_builds_then_skips_when_fresh(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(fetch_hydro_climate, "run_pipeline", lambda db: calls.append("live") or _touch_live(db))
    monkeypatch.setattr(fetch_climate_history, "run_history_pipeline", lambda db: calls.append("history") or _touch_history(db))
    db = tmp_path / "wh.duckdb"
    assert bootstrap.ensure_warehouse(db) == ["live", "history"]
    st = bootstrap.warehouse_status(db)
    assert st["live_age_h"] < 0.1 and st["history_age_days"] < 0.01
    assert bootstrap.ensure_warehouse(db) == []  # fresh: nothing to do
    assert calls == ["live", "history"]


def test_failed_refresh_keeps_existing_data(tmp_path, monkeypatch):
    db = tmp_path / "wh.duckdb"
    _touch_live(db, hours_ago=48)
    _touch_history(db)

    def offline(_db):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(fetch_hydro_climate, "run_pipeline", offline)
    assert bootstrap.ensure_warehouse(db) == []  # stale but usable: logged, not raised


def test_failure_without_any_data_is_raised(tmp_path, monkeypatch):
    def offline(_db):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(fetch_hydro_climate, "run_pipeline", offline)
    with pytest.raises(httpx.ConnectError):
        bootstrap.ensure_warehouse(tmp_path / "wh.duckdb")


# ----------------------------------------------------------------------------- helpers
def _touch_live(db, hours_ago: float = 0.0):
    import duckdb

    with duckdb.connect(str(db)) as con:
        con.execute("CREATE TABLE IF NOT EXISTS etl_run_log (run_id VARCHAR, finished_at TIMESTAMP)")
        con.execute("INSERT INTO etl_run_log VALUES ('r', now()::TIMESTAMP - to_hours(CAST(? AS BIGINT)))",
                    [int(hours_ago)])


def _touch_history(db):
    import duckdb

    with duckdb.connect(str(db)) as con:
        for t in ("fact_climate_monthly", "fact_discharge_monthly"):
            con.execute(f"CREATE TABLE IF NOT EXISTS {t} (x INTEGER)")
        con.execute("CREATE TABLE IF NOT EXISTS etl_history_log (run_id VARCHAR, finished_at TIMESTAMP)")
        con.execute("INSERT INTO etl_history_log VALUES ('h', now()::TIMESTAMP)")
