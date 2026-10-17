"""30-day operations tab: basin map, reservoir status, optimal allocation, storage trajectories."""

from __future__ import annotations

import plotly.graph_objects as go
import polars as pl
import polars.selectors as cs
import streamlit as st

from src.app.i18n import t
from src.app.ui import (
    CRITICAL, GRID, MUTED, SEQ_BLUE, SURFACE, TEXT, TEXT_2, USE_COLORS, base_layout, show,
)
from src.config import (
    DEMANDS, NODES_BY_ID, OPERATING_ASSUMPTIONS, PRIORITY_WEIGHTS, RESERVOIR_IDS, RESERVOIRS,
)
from src.models.water_optimizer import USES, OptimizationResult, ScenarioParams

SHORT_NAME = {
    "KHENIFRA_HEADWATERS": "Khénifra",
    "DAM_AHMED_EL_HANSALI": "Ahmed El Hansali",
    "DAM_BIN_EL_OUIDANE": "Bin El Ouidane",
    "DAM_AL_MASSIRA": "Al Massira",
}


def render(result: OptimizationResult, params: ScenarioParams, hydro: pl.DataFrame) -> None:
    daily, s = result.daily, result.summary
    fc_dates = hydro.filter(pl.col("is_forecast"))["date"]
    first_day = daily.filter(pl.col("day") == 1)
    last_day = daily.filter(pl.col("day") == daily["day"].max())
    start_pct = {r["node_id"]: 100 * r["storage_start_mm3"] / r["capacity_mm3"]
                 for r in first_day.iter_rows(named=True)}
    end_pct = dict(last_day.select("node_id", "storage_pct").iter_rows())
    q_today = dict(hydro.filter(pl.col("date") == fc_dates.min())
                   .select("node_id", "river_discharge_m3s").iter_rows())
    res_nodes = list(RESERVOIRS)

    c_map, c_side = st.columns([1, 1], gap="large")
    with c_map:
        fig = go.Figure()
        for a, b in [("KHENIFRA_HEADWATERS", "DAM_AHMED_EL_HANSALI"),
                     ("DAM_AHMED_EL_HANSALI", "DAM_AL_MASSIRA"),
                     ("DAM_BIN_EL_OUIDANE", "DAM_AL_MASSIRA")]:
            na, nb = NODES_BY_ID[a], NODES_BY_ID[b]
            fig.add_trace(go.Scattermap(lat=[na.lat, nb.lat], lon=[na.lon, nb.lon], mode="lines",
                                        line=dict(width=2, color="#4b5a6b"), hoverinfo="skip",
                                        showlegend=False))
        gauge = NODES_BY_ID["KHENIFRA_HEADWATERS"]
        fig.add_trace(go.Scattermap(
            lat=[gauge.lat], lon=[gauge.lon], mode="markers+text",
            marker=dict(size=13, color=MUTED), text=["Khénifra"], textposition="top right",
            textfont=dict(color=TEXT_2), showlegend=False,
            hovertemplate=f"<b>{gauge.name}</b><br>Q: {q_today.get(gauge.node_id, 0):.2f} m³/s"
                          "<extra></extra>",
        ))
        fig.add_trace(go.Scattermap(
            lat=[n.lat for n in res_nodes], lon=[n.lon for n in res_nodes], mode="markers+text",
            text=[SHORT_NAME[n.node_id] for n in res_nodes], textposition="bottom center",
            textfont=dict(color=TEXT, size=12),
            marker=dict(
                size=[14 + 0.012 * n.capacity_mm3 for n in res_nodes],
                color=[start_pct[n.node_id] for n in res_nodes],
                colorscale=SEQ_BLUE, cmin=0, cmax=100,
                colorbar=dict(title=dict(text=t("storage_pct"), font=dict(color=TEXT_2)),
                              tickfont=dict(color=TEXT_2), thickness=10, len=0.6, x=1.0),
            ),
            customdata=[[n.name, n.capacity_mm3, start_pct[n.node_id], end_pct[n.node_id],
                         q_today.get(n.node_id, 0)] for n in res_nodes],
            hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]:,.0f} Mm³"
                          "<br>%{customdata[2]:.1f}% → J+30 %{customdata[3]:.1f}%"
                          "<br>Q %{customdata[4]:.2f} m³/s<extra></extra>",
            showlegend=False,
        ))
        fig.update_layout(
            map=dict(style="carto-darkmatter", center=dict(lat=32.5, lon=-6.65), zoom=7.0),
            height=520, margin=dict(l=0, r=0, t=0, b=0), paper_bgcolor="rgba(0,0,0,0)",
            hoverlabel=dict(bgcolor=SURFACE, bordercolor=GRID, font=dict(color=TEXT)),
        )
        show(fig)
        st.caption(t("ops_map_caption"))

    with c_side:
        st.markdown(f"##### {t('ops_status')}")
        rows = []
        for n in res_nodes:
            d = daily.filter(pl.col("node_id") == n.node_id)
            dem = sum(d[f"{u}_demand_mm3"].sum() for u in USES)
            rows.append({
                t("col_reservoir"): SHORT_NAME[n.node_id],
                t("col_now"): round(start_pct[n.node_id], 1),
                t("col_day30"): round(end_pct[n.node_id], 1),
                t("col_reliability"): round(100 * (1 - d["unmet_deficit_mm3"].sum() / dem), 1),
            })
        pct = dict(min_value=0, max_value=100, format="%.1f%%")
        st.dataframe(pl.DataFrame(rows), hide_index=True, width="stretch", column_config={
            t("col_now"): st.column_config.ProgressColumn(**pct),
            t("col_day30"): st.column_config.ProgressColumn(**pct),
        })
        st.markdown(f"##### {t('ops_reliability')}")
        for col, u in zip(st.columns(3), ("potable", "ecological", "irrigation")):
            col.metric(t(u), f"{s[f'{u}_reliability_pct']:.1f}%",
                       help=f"{t('use_' + u)} · w = {PRIORITY_WEIGHTS[u]:g}")
        st.markdown(
            '<p class="note">' + t(
                "ops_weights", p=PRIORITY_WEIGHTS["potable"], e=PRIORITY_WEIGHTS["ecological"],
                i=PRIORITY_WEIGHTS["irrigation"], mode=params.buffer_mode,
                b=OPERATING_ASSUMPTIONS["buffer_penalty_" + params.buffer_mode]) + "</p>",
            unsafe_allow_html=True,
        )

    st.divider()
    scope = st.segmented_control(
        t("ops_scope"), ["BASIN", *RESERVOIR_IDS], default="BASIN",
        format_func=lambda n: t("basin_total") if n == "BASIN" else SHORT_NAME[n],
    ) or "BASIN"
    view = daily if scope == "BASIN" else daily.filter(pl.col("node_id") == scope)
    agg = view.group_by("date").agg(
        *[pl.col(f"{u}_delivered_mm3").sum() for u in USES],
        pl.col("unmet_deficit_mm3").sum(),
        *[pl.col(f"{u}_demand_mm3").sum() for u in USES],
    ).sort("date")
    dates = agg["date"].to_list()
    fig = go.Figure()
    for u in ("potable", "ecological", "irrigation"):
        label = t("use_" + u)
        fig.add_trace(go.Bar(
            x=dates, y=agg[f"{u}_delivered_mm3"].to_list(), name=label,
            marker=dict(color=USE_COLORS[u], line=dict(color=SURFACE, width=1)),
            customdata=agg[f"{u}_demand_mm3"].to_list(),
            hovertemplate="%{y:.3f} " + t("hover_of") + " %{customdata:.3f} Mm³<extra>"
                          + label + "</extra>",
        ))
    fig.add_trace(go.Bar(
        x=dates, y=agg["unmet_deficit_mm3"].to_list(), name=t("use_deficit"),
        marker=dict(color="rgba(208,59,59,0.25)", line=dict(color=CRITICAL, width=1),
                    pattern=dict(shape="/", fgcolor=CRITICAL, size=6, solidity=0.35)),
        hovertemplate="%{y:.3f} Mm³<extra>⚠ " + t("use_deficit") + "</extra>",
    ))
    base_layout(fig, 400, title=t("ops_alloc_title"), barmode="stack", bargap=0.18,
                hovermode="x unified", legend_traceorder="normal")
    show(fig)

    st.markdown(f"##### {t('ops_traj')}")
    for col, r in zip(st.columns(3, gap="medium"), RESERVOIR_IDS):
        d = daily.filter(pl.col("node_id") == r).sort("date")
        node = NODES_BY_ID[r]
        x = [fc_dates.min() - (d["date"][1] - d["date"][0])] + d["date"].to_list()
        y = [d["storage_start_mm3"][0]] + d["storage_mm3"].to_list()
        buf = d["buffer_mm3"][0]
        tr = go.Figure()
        tr.add_hrect(y0=0, y1=buf, fillcolor="rgba(208,59,59,0.10)", line_width=0)
        tr.add_hline(y=buf, line=dict(color=CRITICAL, width=1),
                     annotation_text=f"{t('buffer')} {params.safety_buffer_pct:.0f}%",
                     annotation_font=dict(color=TEXT_2, size=10),
                     annotation_position="bottom right")
        tr.add_trace(go.Scatter(x=x, y=y, mode="lines", line=dict(width=2, color=TEXT),
                                fill="tozeroy", fillcolor="rgba(57,135,229,0.15)",
                                hovertemplate="%{y:,.1f} Mm³<extra></extra>", showlegend=False))
        base_layout(tr, 260, title=f"{SHORT_NAME[r]} · {node.capacity_mm3:,.0f} Mm³ {t('cap')}",
                    hovermode="x unified")
        tr.update_yaxes(range=[0, max(max(y), buf) * 1.15], title=dict(text="Mm³", font=dict(size=11)))
        show(tr, col)

    with st.expander(t("ops_table")):
        tbl = view.select(
            "date", "name", "local_inflow_mm3", "upstream_release_in_mm3", "evaporation_mm3",
            *[f"{u}_delivered_mm3" for u in USES], "unmet_deficit_mm3", "excess_release_mm3",
            "storage_mm3", "storage_pct",
        ).with_columns(cs.float().round(3))
        st.dataframe(tbl, hide_index=True, width="stretch", height=320)
        st.markdown(
            "\n".join(
                f"- **{SHORT_NAME[r]}** · potable {d.potable_mm3} · irrigation "
                f"{d.irrigation_base_mm3} ({d.irrigation_perimeter}) · eco {d.ecological_mm3} Mm³/d"
                for r, d in DEMANDS.items()
            )
            + f"\n- Irrigation × ET0 / {OPERATING_ASSUMPTIONS['et0_reference_mm']} mm × cap · "
            f"evaporation = {OPERATING_ASSUMPTIONS['open_water_kc']} × ET0 × A(S₀)"
        )
