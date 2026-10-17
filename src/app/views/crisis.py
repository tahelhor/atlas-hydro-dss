"""Water-crisis tab: what citizens face → why (data + sourced causes) → what can be done."""

from __future__ import annotations

import plotly.graph_objects as go
import polars as pl
import streamlit as st

from src.app.i18n import lang, pick
from src.app.ui import (
    AQUA, BLUE, CRITICAL, DIVERGING_BLUE, DIVERGING_RED, GRID, MUTED, ORANGE, SEQ_STRESS, SERIOUS,
    SURFACE, TEXT, TEXT_2, WARNING, base_layout, callout, card, esc, kpi, section, severity_badge,
    show,
)
from src.region.diagnostics import REF_END, REF_START, amplification, drought_streak
from src.region.knowledge import KnowledgeBase
from src.region.provinces import PROVINCES_BY_ID, province_geojson

L = {  # tab-local bilingual copy
    "kicker1": ("1 · What citizens face", "1 · Ce que vivent les citoyens"),
    "title1": ("Five provinces, one shrinking resource", "Cinq provinces, une ressource qui s'épuise"),
    "lead1": ("Béni Mellal–Khénifra is the source region of the Oum Er-Rbia, Morocco's second "
              "river - yet its towns and farms ran short of water during the 2019–2025 drought. "
              "Colour = synthesis stress score from the cited evidence; dots = towns with "
              "documented supply cuts.",
              "Béni Mellal–Khénifra est la région source de l'Oum Er-Rbia, deuxième fleuve du "
              "Maroc - et pourtant ses villes et ses fermes ont manqué d'eau pendant la sécheresse "
              "2019–2025. Couleur = score de stress issu des sources citées ; points = villes avec "
              "coupures documentées."),
    "daily": ("🏠 Daily life", "🏠 Vie quotidienne"),
    "agri": ("🌾 Agriculture & livelihoods", "🌾 Agriculture & revenus"),
    "env": ("🌍 Environment & economy", "🌍 Environnement & économie"),
    "stories": ("Voices from the region", "Témoignages de la région"),
    "kicker2": ("2 · Why it happens", "2 · Pourquoi"),
    "title2": ("A drought amplified by heat, over-pumping and fragile networks",
               "Une sécheresse amplifiée par la chaleur, le surpompage et des réseaux fragiles"),
    "kicker3": ("3 · What can be done", "3 · Que faire"),
    "title3": ("Solutions: quick wins and structural fixes", "Solutions : gains rapides et réformes de fond"),
    "lead3": ("Rows = how much water or reliability a solution secures; columns = how fast it can "
              "be delivered. Hover a solution for its potential; those marked 🧪 can be tested in "
              "the simulator tab.",
              "Lignes = eau ou fiabilité sécurisée ; colonnes = rapidité de mise en œuvre. Survolez "
              "une solution pour voir son potentiel ; celles marquées 🧪 sont testables dans le "
              "simulateur."),
    "sev": ({1: "Moderate", 2: "Severe", 3: "Critical"}, {1: "Modéré", 2: "Sévère", 3: "Critique"}),
    "pop": ("Population (2024 census)", "Population (RGPH 2024)"),
    "drought": ("Consecutive drought years", "Années de sécheresse consécutives"),
    "drought_sub": ("{a}–{b}: river inflow < −20% every year", "{a}–{b} : apports < −20 % chaque année"),
    "amp": ("Rain deficit → river deficit", "Déficit de pluie → déficit d'écoulement"),
    "amp_sub": ("{a}–{b} mean vs {r1}–{r2}: drought amplified ×{x:.1f}",
                "moyenne {a}–{b} vs {r1}–{r2} : sécheresse amplifiée ×{x:.1f}"),
    "warm": ("Warming", "Réchauffement"),
    "warm_sub": ("{a}–{b} vs {r1}–{r2} · ET0 {e:+.0f}% · snow {s:+.0f}%",
                 "{a}–{b} vs {r1}–{r2} · ET0 {e:+.0f} % · neige {s:+.0f} %"),
    "rain_vs_flow": ("Rainfall vs. river inflow to Al Massira - anomaly by hydrological year (%)",
                     "Pluie vs apports au barrage Al Massira - anomalie par année hydrologique (%)"),
    "rain": ("Rainfall (5-province mean, ERA5)", "Pluie (moyenne 5 provinces, ERA5)"),
    "flow": ("River inflow (GloFAS v4)", "Apports du fleuve (GloFAS v4)"),
    "stripes": ("Warming stripes - mean temperature anomaly (°C) vs {r1}–{r2}",
                "Bandes de réchauffement - anomalie de température (°C) vs {r1}–{r2}"),
    "snow_t": ("Atlas snowfall (cm/yr, 5 capitals)", "Neige sur l'Atlas (cm/an, 5 chefs-lieux)"),
    "evidence": ("📊 What the data shows", "📊 Ce que montrent les données"),
    "groups": {"climate": ("🌡️ Climate", "🌡️ Climat"), "overuse": ("⛏️ Over-use", "⛏️ Surexploitation"),
               "infrastructure": ("🚧 Infrastructure", "🚧 Infrastructures"),
               "governance": ("⚖️ Allocation & governance", "⚖️ Répartition & gouvernance")},
    "horizon": {"short": ("Quick win (< 1 yr)", "Rapide (< 1 an)"),
                "medium": ("1–3 years", "1–3 ans"), "long": ("Structural (3+ yrs)", "Structurel (3 ans +)")},
    "impact_axis": ("Water secured", "Eau sécurisée"),
    "time_axis": ("Time to deliver", "Délai de mise en œuvre"),
    "impact": {1: ("Low", "Faible"), 2: ("Medium", "Moyen"), 3: ("High", "Élevé")},
    "cost": {"low": ("Low cost", "Coût faible"), "medium": ("Medium cost", "Coût moyen"),
             "high": ("High cost", "Coût élevé")},
    "potential": ("Potential", "Potentiel"),
    "barriers": ("Barriers", "Freins"),
    "simulate": ("🧪 testable in simulator", "🧪 testable dans le simulateur"),
    "sources": ("📚 Sources ({n}) · compiled {d}", "📚 Sources ({n}) · compilées le {d}"),
    "stress": ("Stress score", "Score de stress"),
    "supply": ("Where the water comes from", "D'où vient l'eau"),
    "issue": ("Main issue", "Problème principal"),
    "pick_prov": ("Province profile", "Profil de province"),
    "affected_towns": ("Towns with documented cuts", "Villes avec coupures documentées"),
}


def _l(key: str, **fmt) -> str:
    en, fr = L[key]
    s = fr if lang() == "fr" else en
    return s.format(**fmt) if fmt else s


def _sources_foot(kb: KnowledgeBase, ids: list[str]) -> str:
    parts = []
    for sid in ids:
        s = kb.source(sid)
        parts.append(f'<a href="{s.url}" target="_blank" title="{esc(s.title)}">[{sid.lstrip("S")}]</a>')
    return " ".join(parts)


def render(kb: KnowledgeBase, years: pl.DataFrame) -> None:
    streak = drought_streak(years)
    amp = amplification(years, (streak[1], streak[2])) if streak[0] else amplification(years, (2020, 2025))
    x = amp["inflow_anom_pct"] / amp["precip_anom_pct"] if amp["precip_anom_pct"] else float("nan")
    pop_total = sum(p.population_2024 for p in kb.provinces)

    # ------------------------------------------------------------------ headline KPIs
    c = st.columns(4)
    kpi(c[0], _l("pop"), f"{pop_total / 1e6:.2f} M", "Khénifra · Béni Mellal · Azilal · Fquih Ben Salah · Khouribga")
    kpi(c[1], _l("drought"), f"{streak[0]}", _l("drought_sub", a=streak[1], b=streak[2]))
    kpi(c[2], _l("amp"), f"{amp['precip_anom_pct']:+.0f}% → {amp['inflow_anom_pct']:+.0f}%",
        _l("amp_sub", a=streak[1], b=streak[2], r1=REF_START, r2=REF_END, x=x))
    kpi(c[3], _l("warm"), f"{amp['temp_anom_c']:+.1f} °C",
        _l("warm_sub", a=streak[1], b=streak[2], r1=REF_START, r2=REF_END,
           e=amp["et0_anom_pct"], s=amp["snow_anom_pct"]))

    # ------------------------------------------------------------------ 1. citizens
    section(_l("kicker1"), _l("title1"), _l("lead1"))
    c_map, c_prof = st.columns([3, 2], gap="large")
    with c_map:
        _province_map(kb)
    with c_prof:
        pid = st.selectbox(_l("pick_prov"), [p.province_id for p in kb.provinces],
                           format_func=lambda p: f"{PROVINCES_BY_ID[p].name_fr} · {PROVINCES_BY_ID[p].name_ar}")
        prof = next(p for p in kb.provinces if p.province_id == pid)
        geo = PROVINCES_BY_ID[pid]
        stress_color = [MUTED, WARNING, WARNING, SERIOUS, CRITICAL, CRITICAL][prof.stress_score]
        towns = [t.name for t in kb.towns if t.province_id == pid]
        body = (
            f'<div class="big-number">{prof.population_2024:,}</div>'
            f'<div class="note">{_l("pop")}'
            + (f' · {prof.urban_share_pct:.0f}% urban' if prof.urban_share_pct and lang() == "en" else "")
            + (f' · {prof.urban_share_pct:.0f} % urbaine' if prof.urban_share_pct and lang() == "fr" else "")
            + f'</div><p style="margin:8px 0 4px 0">{esc(geo.landscape_fr if lang() == "fr" else geo.landscape_en)}</p>'
            f'<p><b style="color:{TEXT}">{_l("stress")}:</b> '
            f'<span style="color:{stress_color}">{"■" * prof.stress_score}{"□" * (5 - prof.stress_score)}</span></p>'
            f'<p><b style="color:{TEXT}">{_l("supply")}:</b> {esc(pick(prof, "supply"))}</p>'
            f'<p><b style="color:{TEXT}">{_l("issue")}:</b> {esc(pick(prof, "main_issue"))}</p>'
        )
        card(st, "📍", f"{geo.name_fr} · {geo.name_ar}", body,
             foot=_sources_foot(kb, prof.source_ids), accent=stress_color,
             chips=[f"🚱 {t}" for t in towns])

    cats = [("daily_life", _l("daily")), ("agriculture", _l("agri"))]
    if any(p.category in ("environment", "economy") for p in kb.problems):
        cats.append(("env", _l("env")))
    cols = st.columns(len(cats), gap="large")
    sev_labels = L["sev"][1] if lang() == "fr" else L["sev"][0]
    for col, (cat, title) in zip(cols, cats):
        col.markdown(f"##### {title}")
        items = [p for p in kb.problems
                 if (p.category == cat or (cat == "env" and p.category in ("environment", "economy")))]
        for p in sorted(items, key=lambda p: -p.severity):
            chips = [PROVINCES_BY_ID[x].name_fr if x in PROVINCES_BY_ID else "Région" for x in p.provinces]
            card(col, p.icon, pick(p, "title"),
                 f'{severity_badge(p.severity, sev_labels)}<br>{esc(pick(p, "desc"))}',
                 foot=_sources_foot(kb, p.source_ids), chips=chips)

    if kb.stories:
        st.markdown(f"##### 💬 {_l('stories')}")
        scol = st.columns(min(len(kb.stories), 3), gap="medium")
        for i, s in enumerate(kb.stories):
            card(scol[i % len(scol)], s.icon, PROVINCES_BY_ID[s.province_id].name_fr,
                 f'<i>“{esc(pick(s, "quote"))}”</i>', foot=_sources_foot(kb, s.source_ids))

    # ------------------------------------------------------------------ 2. causes
    section(_l("kicker2"), _l("title2"))
    callout(_cause_headline(amp, x, streak))
    st.markdown(f"##### {_l('evidence')}")
    _rain_vs_flow(years)
    c1, c2 = st.columns([3, 2], gap="large")
    with c1:
        _warming_stripes(years)
    with c2:
        _snow_chart(years)

    groups = ["climate", "overuse", "infrastructure", "governance"]
    accents = {"climate": ORANGE, "overuse": SERIOUS, "infrastructure": BLUE, "governance": AQUA}
    gcols = st.columns(4, gap="medium")
    for col, g in zip(gcols, groups):
        en, fr = L["groups"][g]
        col.markdown(f"##### {fr if lang() == 'fr' else en}")
        for rc in [r for r in kb.root_causes if r.group == g]:
            card(col, rc.icon, pick(rc, "title"),
                 f'{esc(pick(rc, "desc"))}<br><span style="color:{TEXT}">▸ {esc(pick(rc, "evidence"))}</span>',
                 foot=_sources_foot(kb, rc.source_ids), accent=accents[g])

    # ------------------------------------------------------------------ 3. solutions
    section(_l("kicker3"), _l("title3"), _l("lead3"))
    _solution_matrix(kb)
    scols = st.columns(3, gap="medium")
    for i, s in enumerate(sorted(kb.solutions, key=lambda s: (-s.impact, ["short", "medium", "long"].index(s.horizon)))):
        hz = L["horizon"][s.horizon][1 if lang() == "fr" else 0]
        cost = L["cost"][s.cost][1 if lang() == "fr" else 0]
        imp = L["impact"][s.impact][1 if lang() == "fr" else 0]
        chips = [f"⏱ {hz}", f"💰 {cost}", f"💧 {imp}"] + ([_l("simulate")] if s.lever else [])
        body = (f'{esc(pick(s, "desc"))}<br><b style="color:{TEXT}">{_l("potential")}:</b> '
                f'{esc(pick(s, "potential"))}<br><b style="color:{TEXT}">{_l("barriers")}:</b> '
                f'{esc(pick(s, "barriers"))}')
        card(scols[i % 3], s.icon, pick(s, "title"), body, foot=_sources_foot(kb, s.source_ids),
             chips=chips)

    with st.expander(_l("sources", n=len(kb.sources), d=kb.compiled_on.isoformat())):
        st.caption(pick(kb, "disclaimer"))
        st.markdown("\n".join(
            f"{s.id.lstrip('S')}. [{s.title}]({s.url}) - *{s.publisher}*, {s.published.isoformat()}"
            for s in sorted(kb.sources, key=lambda s: int(s.id[1:]))
        ))


# ---------------------------------------------------------------------- charts
def _cause_headline(amp: dict, x: float, streak: tuple[int, int, int]) -> str:
    if lang() == "fr":
        return (f"<b>Le cœur du problème :</b> pendant {streak[0]} années consécutives "
                f"({streak[1]}–{streak[2]}), la pluie n'a baissé que de "
                f"<b>{-amp['precip_anom_pct']:.0f} %</b>, mais les apports du fleuve ont chuté de "
                f"<b>{-amp['inflow_anom_pct']:.0f} %</b> (×{x:.1f}). Avec <b>+{amp['temp_anom_c']:.1f} °C</b>, "
                f"l'évaporation augmente, la neige de l'Atlas disparaît ({amp['snow_anom_pct']:+.0f} %) et des sols "
                "assoiffés absorbent la pluie avant qu'elle n'atteigne les rivières. Les nappes surexploitées "
                "ne compensent plus, et les villes dépendant de sources locales sont les premières touchées.")
    return (f"<b>The root problem:</b> for {streak[0]} consecutive years ({streak[1]}–{streak[2]}) "
            f"rainfall fell only <b>{-amp['precip_anom_pct']:.0f}%</b>, but river inflow collapsed by "
            f"<b>{-amp['inflow_anom_pct']:.0f}%</b> (×{x:.1f}). At <b>+{amp['temp_anom_c']:.1f} °C</b>, more "
            f"water evaporates, the Atlas snowpack vanishes ({amp['snow_anom_pct']:+.0f}%) and parched soils "
            "absorb rain before it reaches rivers. Over-pumped aquifers can no longer buffer the gap, and "
            "towns relying on local springs and wells are hit first.")


def _province_map(kb: KnowledgeBase) -> None:
    gj = province_geojson()
    prof = {p.province_id: p for p in kb.provinces}
    ids = [f["id"] for f in gj["features"]]
    fig = go.Figure()
    fig.add_trace(go.Choroplethmap(
        geojson=gj, locations=ids, featureidkey="id",
        z=[prof[i].stress_score for i in ids], zmin=1, zmax=5, colorscale=SEQ_STRESS,
        marker=dict(line=dict(color="#55534d", width=1), opacity=0.78),
        colorbar=dict(title=dict(text=_l("stress"), font=dict(color=TEXT_2)), tickvals=[1, 2, 3, 4, 5],
                      tickfont=dict(color=TEXT_2), thickness=10, len=0.55, x=1.0),
        customdata=[[PROVINCES_BY_ID[i].name_fr, prof[i].population_2024, pick(prof[i], "main_issue")]
                    for i in ids],
        hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]:,} hab.<br>%{customdata[2]}<extra></extra>",
    ))
    if kb.towns:
        fig.add_trace(go.Scattermap(
            lat=[t.lat for t in kb.towns], lon=[t.lon for t in kb.towns], mode="markers+text",
            marker=dict(size=11, color=CRITICAL), text=[t.name for t in kb.towns],
            textposition="top right", textfont=dict(color=TEXT, size=11),
            customdata=[[t.name, pick(t, "note")] for t in kb.towns],
            hovertemplate="<b>🚱 %{customdata[0]}</b><br>%{customdata[1]}<extra></extra>",
            name=_l("affected_towns"),
        ))
    fig.update_layout(
        map=dict(style="carto-darkmatter", center=dict(lat=32.45, lon=-6.25), zoom=6.9),
        height=500, margin=dict(l=0, r=0, t=0, b=0), paper_bgcolor="rgba(0,0,0,0)",
        legend=dict(x=0.01, y=0.99, bgcolor="rgba(26,26,25,0.85)", font=dict(color=TEXT_2)),
        hoverlabel=dict(bgcolor=SURFACE, bordercolor=GRID, font=dict(color=TEXT)),
    )
    show(fig)


def _rain_vs_flow(years: pl.DataFrame) -> None:
    y = years.drop_nulls("inflow_anom_pct")
    hy = y["hy"].to_list()
    fig = go.Figure()
    fig.add_trace(go.Bar(x=hy, y=y["precip_anom_pct"].to_list(), name=_l("rain"),
                         marker=dict(color=BLUE, cornerradius=3),
                         hovertemplate="%{x}: %{y:+.0f}%<extra></extra>"))
    fig.add_trace(go.Scatter(x=hy, y=y["inflow_anom_pct"].to_list(), name=_l("flow"),
                             mode="lines+markers", line=dict(color=ORANGE, width=2),
                             marker=dict(size=8, line=dict(color=SURFACE, width=2)),
                             hovertemplate="%{x}: %{y:+.0f}%<extra></extra>"))
    fig.add_hline(y=0, line=dict(color=MUTED, width=1))
    fig.add_vrect(x0=2019.5, x1=2025.5, fillcolor="rgba(208,59,59,0.08)", line_width=0,
                  annotation_text="2020–2025", annotation_position="top left",
                  annotation_font=dict(color=TEXT_2, size=11))
    base_layout(fig, 360, title=_l("rain_vs_flow"), hovermode="x unified", bargap=0.3)
    fig.update_yaxes(ticksuffix="%")
    show(fig)


def _warming_stripes(years: pl.DataFrame) -> None:
    hy = years["hy"].to_list()
    an = years["temp_anom_c"].to_list()
    lim = max(abs(min(an)), abs(max(an)))
    fig = go.Figure(go.Heatmap(
        x=hy, y=[""], z=[an], zmin=-lim, zmax=lim, xgap=1,
        colorscale=[[0, DIVERGING_BLUE], [0.5, "#383835"], [1, DIVERGING_RED]],
        colorbar=dict(title=dict(text="°C", font=dict(color=TEXT_2)), tickfont=dict(color=TEXT_2),
                      thickness=10),
        hovertemplate="%{x}: %{z:+.2f} °C<extra></extra>",
    ))
    base_layout(fig, 220, title=_l("stripes", r1=REF_START, r2=REF_END))
    fig.update_yaxes(showgrid=False, showticklabels=False)
    show(fig)


def _snow_chart(years: pl.DataFrame) -> None:
    fig = go.Figure(go.Bar(x=years["hy"].to_list(), y=years["snow_cm"].to_list(),
                           marker=dict(color="#cde2fb", cornerradius=2),
                           hovertemplate="%{x}: %{y:.1f} cm<extra></extra>"))
    base_layout(fig, 220, title=_l("snow_t"), bargap=0.25)
    show(fig)


def _solution_matrix(kb: KnowledgeBase) -> None:
    """Impact × time-to-deliver grid; each cell lists its solutions with a cost marker."""
    i = 1 if lang() == "fr" else 0
    horizons = ("short", "medium", "long")
    cost_mark = {"low": "€", "medium": "€€", "high": "€€€"}
    tint = {3: "rgba(25,158,112,0.16)", 2: "rgba(57,135,229,0.12)", 1: "rgba(138,137,127,0.10)"}
    head = "".join(f'<th style="padding:8px 10px;color:{TEXT_2};font-weight:600;text-align:left">'
                   f'⏱ {L["horizon"][h][i]}</th>' for h in horizons)
    rows = []
    for imp in (3, 2, 1):
        cells = []
        for h in horizons:
            items = [s for s in kb.solutions if s.impact == imp and s.horizon == h]
            chips = "".join(
                f'<div style="background:{SURFACE};border:1px solid {GRID};border-radius:8px;'
                f'padding:6px 9px;margin:0 0 6px 0;color:{TEXT};font-size:0.84rem" '
                f'title="{esc(pick(s, "potential"))}">{s.icon} {esc(pick(s, "title"))}'
                f'<span style="color:{MUTED};font-size:0.74rem"> · {cost_mark[s.cost]}'
                f'{" · 🧪" if s.lever else ""}</span></div>'
                for s in items)
            cells.append(f'<td style="vertical-align:top;padding:8px;background:{tint[imp]};'
                         f'border-radius:8px">{chips or "&nbsp;"}</td>')
        label = L["impact"][imp][i]
        rows.append(f'<tr><th style="padding:8px 10px;color:{TEXT_2};text-align:left;'
                    f'white-space:nowrap;vertical-align:top">💧 {label}</th>{"".join(cells)}</tr>')
    legend = ("€ coût faible · €€ moyen · €€€ élevé · 🧪 testable dans le simulateur" if lang() == "fr"
              else "€ low cost · €€ medium · €€€ high · 🧪 testable in the simulator")
    st.markdown(
        f'<table style="width:100%;border-collapse:separate;border-spacing:6px;margin-bottom:6px">'
        f'<tr><th style="padding:8px 10px;color:{MUTED};text-align:left;font-size:0.78rem">'
        f'{_l("impact_axis")} ↓ / {_l("time_axis")} →</th>{head}</tr>{"".join(rows)}</table>'
        f'<p class="note">{legend}</p>',
        unsafe_allow_html=True,
    )
