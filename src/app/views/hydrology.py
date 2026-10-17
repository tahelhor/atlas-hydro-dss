"""Hydrograph tab: 92-day history + 30-day GloFAS ensemble forecast with uncertainty fan."""

from __future__ import annotations

import plotly.graph_objects as go
import polars as pl
import streamlit as st

from src.app.i18n import t
from src.app.ui import BLUE, MUTED, TEXT_2, USE_COLORS, base_layout, show
from src.config import NODES, NODES_BY_ID


def render(hydro: pl.DataFrame) -> None:
    node_id = st.selectbox(t("node"), [n.node_id for n in NODES], index=3,
                           format_func=lambda n: NODES_BY_ID[n].name)
    h = hydro.filter(pl.col("node_id") == node_id).sort("date")
    hist, fc = h.filter(~pl.col("is_forecast")), h.filter(pl.col("is_forecast"))
    fc_line = pl.concat([hist.tail(1), fc]) if hist.height else fc  # continuous line

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=fc["date"].to_list(), y=fc["discharge_p75_m3s"].to_list(),
                             mode="lines", line=dict(width=0), hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(x=fc["date"].to_list(), y=fc["discharge_p25_m3s"].to_list(),
                             mode="lines", line=dict(width=0), fill="tonexty",
                             fillcolor="rgba(57,135,229,0.22)", name=t("h_band"),
                             hovertemplate="p25 %{y:.2f} m³/s<extra></extra>"))
    fig.add_trace(go.Scatter(x=hist["date"].to_list(), y=hist["river_discharge_m3s"].to_list(),
                             mode="lines", line=dict(width=2, color=TEXT_2), name=t("h_hist"),
                             hovertemplate="%{y:.2f} m³/s<extra></extra>"))
    fig.add_trace(go.Scatter(x=fc_line["date"].to_list(), y=fc_line["river_discharge_m3s"].to_list(),
                             mode="lines", line=dict(width=2, color=BLUE, dash="dot"),
                             name=t("h_fc"), hovertemplate="%{y:.2f} m³/s<extra></extra>"))
    fig.add_trace(go.Scatter(x=fc["date"].to_list(), y=fc["discharge_p75_m3s"].to_list(),
                             mode="lines", line=dict(width=0), showlegend=False,
                             hovertemplate="p75 %{y:.2f} m³/s<extra></extra>"))
    today = fc["date"].min()
    fig.add_vline(x=today, line=dict(color=MUTED, width=1))
    fig.add_annotation(x=today, y=1, yref="paper", text=t("h_forecast"), showarrow=False,
                       xanchor="left", font=dict(color=MUTED, size=11))
    base_layout(fig, 420, title=t("h_title", name=NODES_BY_ID[node_id].name), hovermode="x unified")
    show(fig)

    c1, c2 = st.columns(2, gap="large")
    met = go.Figure()
    met.add_trace(go.Bar(x=h["date"].to_list(), y=h["precipitation_mm"].to_list(), name=t("precip"),
                         marker=dict(color=BLUE, cornerradius=2),
                         hovertemplate="%{y:.1f} mm<extra></extra>"))
    met.add_trace(go.Scatter(x=h["date"].to_list(), y=h["et0_fao_mm"].to_list(), name="FAO-56 ET0",
                             mode="lines", line=dict(width=2, color=USE_COLORS["irrigation"]),
                             hovertemplate="%{y:.2f} mm<extra></extra>"))
    met.add_vline(x=today, line=dict(color=MUTED, width=1))
    base_layout(met, 300, title=t("h_drivers"), hovermode="x unified", bargap=0.25)
    show(met, c1)

    sm = go.Figure()
    sm.add_trace(go.Scatter(x=h["date"].to_list(), y=h["soil_moisture_deep_m3m3"].to_list(),
                            mode="lines", line=dict(width=2, color=USE_COLORS["ecological"]),
                            name=t("h_soil_series"), hovertemplate="%{y:.3f} m³/m³<extra></extra>"))
    sm.add_vline(x=today, line=dict(color=MUTED, width=1))
    base_layout(sm, 300, title=t("h_soil"), hovermode="x unified", showlegend=False)
    show(sm, c2)
    st.caption(t("h_caption"))
