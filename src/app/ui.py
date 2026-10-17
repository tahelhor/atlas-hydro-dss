"""Shared dark-mode design system: tokens, CSS, chart chrome and HTML card helpers."""

from __future__ import annotations

import html

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

# Streamlit registers a large default plotly template that every go.Figure() merges at
# construction (~40 ms per chart). All chrome is set explicitly in base_layout, so the empty
# template is visually identical here and makes each chart ~20x cheaper to build.
pio.templates.default = "none"

# --------------------------------------------------------------------------- tokens
# Dark-mode categorical slots 1-3 (validated all-pairs: CVD ΔE 9.4, normal ΔE 20.9).
BG = "#121211"
SURFACE = "#1a1a19"
SURFACE_2 = "#222220"
TEXT = "#f0efec"
TEXT_2 = "#c3c2b7"
MUTED = "#8a897f"
GRID = "#2c2c2a"
BLUE, ORANGE, AQUA = "#3987e5", "#d95926", "#199e70"
USE_COLORS = {"potable": BLUE, "irrigation": ORANGE, "ecological": AQUA}
# status palette - reserved, always paired with an icon + label
GOOD, WARNING, SERIOUS, CRITICAL = "#0ca30c", "#fab219", "#ec835a", "#d03b3b"
SEQ_BLUE = [[0, "#104281"], [0.35, "#2a78d6"], [0.7, "#6da7ec"], [1, "#cde2fb"]]
# sequential stress ramp (single hue, light -> dark red on the dark surface reads low -> high)
SEQ_STRESS = [[0, "#2f2826"], [0.5, "#8c3b2b"], [0.75, "#c9512f"], [1, "#f29a6c"]]
DIVERGING_RED, DIVERGING_BLUE, DIVERGING_MID = "#e66767", "#3987e5", "#383835"

CSS = f"""
<style>
.block-container {{padding-top: 3.2rem; padding-bottom: 2rem; max-width: 1500px;}}
h1, h2, h3 {{letter-spacing: -0.01em;}}
.hero-title {{font-size: 1.75rem; font-weight: 700; color: {TEXT}; margin: 0;}}
.hero-sub {{color: {TEXT_2}; font-size: 0.95rem; margin: 0.15rem 0 1.1rem 0;}}
.kpi-card {{background: {SURFACE}; border: 1px solid {GRID}; border-radius: 12px;
           padding: 14px 18px; height: 100%;}}
.kpi-label {{color: {TEXT_2}; font-size: 0.78rem; text-transform: uppercase;
            letter-spacing: 0.06em; margin-bottom: 4px;}}
.kpi-value {{color: {TEXT}; font-size: 1.65rem; font-weight: 700; line-height: 1.15;}}
.kpi-sub {{color: {MUTED}; font-size: 0.82rem; margin-top: 4px;}}
.badge {{display: inline-flex; align-items: center; gap: 6px; font-weight: 700;
        font-size: 1.25rem; color: {TEXT};}}
.dot {{width: 12px; height: 12px; border-radius: 50%; display: inline-block;}}
.note {{color: {MUTED}; font-size: 0.8rem;}}
.section-kicker {{color: {BLUE}; font-size: 0.78rem; font-weight: 700; text-transform: uppercase;
                 letter-spacing: 0.08em; margin: 1.2rem 0 0.1rem 0;}}
.section-title {{color: {TEXT}; font-size: 1.35rem; font-weight: 700; margin: 0 0 0.25rem 0;}}
.section-lead {{color: {TEXT_2}; font-size: 0.95rem; margin: 0 0 0.9rem 0; max-width: 980px;}}
.card {{background: {SURFACE}; border: 1px solid {GRID}; border-radius: 12px; padding: 14px 16px;
       height: 100%; margin-bottom: 12px;}}
.card-head {{display: flex; align-items: center; gap: 10px; margin-bottom: 6px;}}
.card-icon {{font-size: 1.45rem; line-height: 1;}}
.card-title {{color: {TEXT}; font-weight: 700; font-size: 0.98rem; line-height: 1.25;}}
.card-body {{color: {TEXT_2}; font-size: 0.86rem; line-height: 1.45;}}
.card-foot {{color: {MUTED}; font-size: 0.74rem; margin-top: 8px;}}
.card-foot a {{color: {MUTED}; text-decoration: underline dotted;}}
.chip {{display: inline-block; border: 1px solid {GRID}; border-radius: 999px; padding: 1px 9px;
       font-size: 0.72rem; color: {TEXT_2}; margin: 0 4px 4px 0; background: {SURFACE_2};}}
.sev {{display: inline-flex; align-items: center; gap: 5px; font-size: 0.74rem; font-weight: 700;
      color: {TEXT_2};}}
.big-number {{font-size: 2.1rem; font-weight: 800; color: {TEXT}; line-height: 1.1;}}
.delta-good {{color: {GOOD}; font-weight: 700;}}
.delta-bad {{color: {SERIOUS}; font-weight: 700;}}
.cause-col {{border-top: 3px solid var(--accent); }}
.callout {{background: {SURFACE}; border-left: 4px solid {BLUE}; border-radius: 8px;
          padding: 12px 16px; color: {TEXT_2}; font-size: 0.92rem; margin: 6px 0 14px 0;}}
.callout b {{color: {TEXT};}}
div[data-testid="stSidebar"] .stMarkdown p {{font-size: 0.86rem;}}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def esc(text: str) -> str:
    return html.escape(text, quote=False)


# --------------------------------------------------------------------------- charts
_XAXIS = dict(showgrid=False, linecolor=GRID, tickcolor=GRID, zeroline=False, automargin=True)
_YAXIS = dict(gridcolor=GRID, gridwidth=1, zeroline=False, linecolor=GRID, automargin=True)


def base_layout(fig: go.Figure, height: int = 380, title: str | None = None, **kw) -> go.Figure:
    """Shared chart chrome: title top-left, legend on its own row beneath it.

    Applied in ONE ``update_layout`` call (no update_xaxes/update_yaxes passes) because chart
    construction dominated each Streamlit rerun - charts are rebuilt on every slider move.
    """
    has_legend = kw.get("showlegend", True) and len(fig.data) > 1
    layout = dict(
        template="none",
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=TEXT_2, size=12),
        title=dict(text=title, x=0, xanchor="left", y=1, yanchor="top", yref="container",
                   pad=dict(t=6, l=4), font=dict(color=TEXT, size=14)) if title else None,
        margin=dict(l=8, r=12, t=(78 if has_legend else 44) if title else 24, b=8),
        hoverlabel=dict(bgcolor=SURFACE, bordercolor=GRID, font=dict(color=TEXT)),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, x=0, bgcolor="rgba(0,0,0,0)",
                    font=dict(color=TEXT_2)),
    )
    if not title:
        del layout["title"]
    layout["xaxis"], layout["yaxis"] = dict(_XAXIS), dict(_YAXIS)
    layout.update(kw)
    fig.update_layout(layout)
    return fig


def show(fig: go.Figure, container=st, **kw) -> None:
    container.plotly_chart(fig, width="stretch", theme=None,
                           config={"displayModeBar": False, **kw.pop("config", {})}, **kw)


# --------------------------------------------------------------------------- HTML blocks
def kpi(col, label: str, value: str, sub: str = "") -> None:
    col.markdown(
        f'<div class="kpi-card"><div class="kpi-label">{label}</div>'
        f'<div class="kpi-value">{value}</div><div class="kpi-sub">{sub}</div></div>',
        unsafe_allow_html=True,
    )


def section(kicker: str, title: str, lead: str = "") -> None:
    st.markdown(
        f'<div class="section-kicker">{esc(kicker)}</div>'
        f'<div class="section-title">{esc(title)}</div>'
        + (f'<div class="section-lead">{lead}</div>' if lead else ""),
        unsafe_allow_html=True,
    )


def card(container, icon: str, title: str, body: str, foot: str = "", accent: str | None = None,
         chips: list[str] | None = None) -> None:
    style = f' style="border-top: 3px solid {accent};"' if accent else ""
    chips_html = "".join(f'<span class="chip">{esc(c)}</span>' for c in (chips or []))
    container.markdown(
        f'<div class="card"{style}><div class="card-head"><span class="card-icon">{icon}</span>'
        f'<span class="card-title">{esc(title)}</span></div>'
        f'<div class="card-body">{body}</div>'
        + (f'<div style="margin-top:8px">{chips_html}</div>' if chips_html else "")
        + (f'<div class="card-foot">{foot}</div>' if foot else "")
        + "</div>",
        unsafe_allow_html=True,
    )


def severity_badge(level: int, labels: dict[int, str]) -> str:
    color = {1: WARNING, 2: SERIOUS, 3: CRITICAL}.get(level, MUTED)
    icon = {1: "●", 2: "▲", 3: "■"}.get(level, "●")
    return (f'<span class="sev"><span style="color:{color}">{icon}</span>'
            f'{esc(labels.get(level, ""))}</span>')


def callout(html_text: str, accent: str = BLUE) -> None:
    st.markdown(f'<div class="callout" style="border-left-color:{accent}">{html_text}</div>',
                unsafe_allow_html=True)
