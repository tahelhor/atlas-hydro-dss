"""Atlas Hydro-Climate DSS - bilingual executive dashboard (Streamlit).

Run:  uv run streamlit run src/app/dashboard.py

Tabs: 🚰 water crisis (problems → causes → solutions) · 🧪 solutions simulator (12-month LP)
· 🗺️ 30-day operations (reservoir LP) · 🌊 hydrograph & forecast · 🛡️ data QA & sources.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import polars as pl  # noqa: E402
import streamlit as st  # noqa: E402

from src import warehouse  # noqa: E402
from src.app import i18n  # noqa: E402
from src.app.i18n import t  # noqa: E402
from src.app.ui import GOOD, WARNING, inject_css, kpi  # noqa: E402
from src.app.views import crisis, hydrology, operations, qa, simulator  # noqa: E402
from src.config import DB_PATH, RESERVOIR_IDS, RESERVOIRS  # noqa: E402
from src.models.regional_planner import available_years  # noqa: E402
from src.models.water_optimizer import OptimizationResult, ScenarioParams, optimize  # noqa: E402
from src.region.diagnostics import (  # noqa: E402
    hydro_year_table, load_climate_monthly, load_discharge_monthly,
)
from src.region.knowledge import KnowledgeBase, knowledge_base  # noqa: E402

st.set_page_config(page_title="Atlas Hydro-DSS · Béni Mellal–Khénifra", page_icon="💧", layout="wide")
inject_css()


# =========================================================================== data
@st.cache_data(ttl=600, show_spinner=False)
def load_data(db_mtime: float) -> dict:
    tables = warehouse.existing_tables()
    out = {
        "hydro": warehouse.load_hydro(),
        "runs": warehouse.load_run_log(),
        "counts": warehouse.table_row_counts(),
        "completeness": warehouse.completeness_by_node(),
        "rejections": warehouse.load_rejections(),
        "history_log": warehouse.load_history_log(),
        "climate": None, "discharge": None,
    }
    if {"fact_climate_monthly", "fact_discharge_monthly"} <= tables:
        out["climate"] = load_climate_monthly()
        out["discharge"] = load_discharge_monthly()
    return out


@st.cache_data(show_spinner=False, max_entries=256)
def run_ops(_hydro: pl.DataFrame, data_key: float, params: ScenarioParams) -> OptimizationResult:
    return optimize(_hydro, params)


@st.fragment
def simulator_fragment(discharge: pl.DataFrame, climate: pl.DataFrame, years: list[int],
                       data_key: float) -> None:
    """The solutions simulator reruns on its own: moving a solution slider no longer rebuilds
    the other four tabs (≈15 charts), only the simulator and its 3D story."""
    simulator.render(discharge, climate, years, data_key)


@st.cache_resource(show_spinner=False)
def load_kb() -> tuple[KnowledgeBase | None, str | None]:
    try:
        return knowledge_base(), None
    except Exception as exc:  # surfaced in the QA tab, never crashes the app
        return None, f"{type(exc).__name__}: {exc}"[:300]


# =========================================================================== sidebar
with st.sidebar:
    st.segmented_control("🌐 " + t("language"), list(i18n.LANGS), default="en", key="lang",
                         format_func=i18n.LANGS.get)
    if st.session_state.get("lang") is None:  # segmented control can be cleared
        st.session_state["lang"] = "en"

if not DB_PATH.exists():
    st.error(t("warehouse_missing") + "\n\n`uv run python -m src.ingestion.fetch_hydro_climate`\n\n"
             "`uv run python -m src.ingestion.fetch_climate_history`")
    st.stop()

data_key = DB_PATH.stat().st_mtime
data = load_data(data_key)
hydro: pl.DataFrame = data["hydro"]
runs: pl.DataFrame = data["runs"]
kb, kb_error = load_kb()

with st.sidebar:
    st.divider()
    st.markdown(f"### {t('sb_title')}")
    st.caption(t("sb_caption"))
    fc_keys = {"p25": t("fc_p25"), "mean": t("fc_mean"), "p75": t("fc_p75")}
    forecast = st.radio(t("sb_forecast"), list(fc_keys), index=1, format_func=fc_keys.get)
    shock = st.slider(t("sb_shock"), -50, 50, 0, 5, help=t("sb_shock_help"))
    irr_cap = st.slider(t("sb_irr"), 50, 120, 100, 5, help=t("sb_irr_help"))
    buffer_pct = st.slider(t("sb_buffer"), 10, 40, 20, 1)
    with st.expander(t("sb_advanced")):
        init_pct = st.slider(t("sb_init"), 25, 150, 100, 5, help=t("sb_init_help"))
        buffer_mode = st.radio(t("sb_buffer_mode"), ["soft", "hard"],
                               format_func=lambda m: t(f"buffer_{m}"))
    st.divider()
    last_run = runs.row(0, named=True) if runs.height else None
    if last_run:
        st.caption(t("sb_run", run=last_run["run_id"], status=last_run["status"]))
    if st.button(t("sb_refresh"), width="stretch"):
        from src.ingestion.fetch_hydro_climate import run_pipeline

        with st.spinner(t("sb_refreshing")):
            _, rep = run_pipeline()
        st.cache_data.clear()
        st.toast(t("sb_refreshed", ok=rep.rows_passed, n=rep.rows_received), icon="✅")
        st.rerun()

params = ScenarioParams(
    inflow_forecast=forecast,  # type: ignore[arg-type]
    inflow_shock_pct=float(shock),
    irrigation_cap_pct=float(irr_cap),
    safety_buffer_pct=float(buffer_pct),
    initial_storage_pct=float(init_pct),
    buffer_mode=buffer_mode,  # type: ignore[arg-type]
)
result = run_ops(hydro, data_key, params)

# =========================================================================== header + live KPIs
fc_dates = hydro.filter(pl.col("is_forecast"))["date"]
st.markdown(f'<p class="hero-title">💧 {t("app_title")}</p>', unsafe_allow_html=True)
st.markdown(f'<p class="hero-sub">{t("app_sub", date=f"{fc_dates.min():%d/%m/%Y}")}</p>',
            unsafe_allow_html=True)

if not result.is_optimal:
    st.error(t("infeasible", s=result.solver_status))
    st.stop()

s = result.summary
total_cap = sum(n.capacity_mm3 for n in RESERVOIRS)
mean_et0 = hydro.filter(pl.col("is_forecast") & pl.col("node_id").is_in(RESERVOIR_IDS))["et0_fao_mm"].mean()
k = st.columns(5)
kpi(k[0], t("kpi_storage"), f"{s['initial_storage']:,.0f} Mm³",
    t("kpi_storage_sub", pct=100 * s["initial_storage"] / total_cap, cap=total_cap))
delta = s["final_storage"] - s["initial_storage"]
kpi(k[1], t("kpi_day30"), f"{s['final_storage']:,.0f} Mm³",
    f"{'▲' if delta >= 0 else '▼'} {abs(delta):,.1f} Mm³ · {100 * s['final_storage'] / total_cap:.1f}%")
kpi(k[2], t("kpi_inflow"), f"{s['local_inflow']:,.1f} Mm³",
    t("kpi_inflow_sub", fc=params.inflow_forecast, shock=params.inflow_shock_pct))
kpi(k[3], t("kpi_et0"), f"{mean_et0:.2f} mm/j" if i18n.lang() == "fr" else f"{mean_et0:.2f} mm/day",
    t("kpi_et0_sub", evap=s["evaporation"]))
ok = result.status == "Optimal"
icon, color = ("✔", GOOD) if ok else ("⚠", WARNING)
kpi(k[4], t("kpi_status"),
    f'<span class="badge"><span class="dot" style="background:{color}"></span>{icon} {t("status_" + result.status)}</span>',
    t("kpi_status_sub", unmet=s["unmet"], share=s["unmet_share_pct"], ms=1000 * result.solve_seconds))

st.write("")
tab_crisis, tab_sim, tab_ops, tab_hydro, tab_qa = st.tabs(
    [t("tab_crisis"), t("tab_sim"), t("tab_ops"), t("tab_hydro"), t("tab_qa")])

has_history = data["climate"] is not None and data["discharge"] is not None
history_msg = ("Run `uv run python -m src.ingestion.fetch_climate_history` to load the 1991-today "
               "climate & river archive.")

with tab_crisis:
    if kb is None:
        st.error(f"Knowledge base invalid: {kb_error}")
    elif not has_history:
        st.info(history_msg)
    else:
        crisis.render(kb, hydro_year_table(data["climate"], data["discharge"]))

with tab_sim:
    if not has_history:
        st.info(history_msg)
    else:
        years = available_years(data["discharge"], data["climate"])
        simulator_fragment(data["discharge"], data["climate"], years, data_key)

with tab_ops:
    operations.render(result, params, hydro)

with tab_hydro:
    hydrology.render(hydro)

with tab_qa:
    qa.render(data, kb, kb_error)
