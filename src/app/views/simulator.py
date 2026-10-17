"""Solutions simulator: replay a real drought year, pull solution levers, compare to business as usual."""

from __future__ import annotations

import plotly.graph_objects as go
import polars as pl
import streamlit as st

from src.app.i18n import lang
from src.app.ui import (
    AQUA, BLUE, CRITICAL, GOOD, GRID, MUTED, ORANGE, SERIOUS, SURFACE, TEXT, TEXT_2,
    base_layout, callout, esc, kpi, section, show,
)
from src.models.regional_planner import (
    PlannerResult, PlannerScenario, SolutionLevers, YearInputs, build_year_inputs, solve,
)
from src.app.views.simulator_map import render as render_basin_story
from src.region.planner_config import (
    DEMANDS, INFLOW_NORMAL_MM3, LEVER_GROUPS, LEVERS, MONTH_LABELS, PRESETS, RESERVOIRS,
)
from src.region.provinces import PROVINCES_BY_ID

L = {
    "kicker": ("Drought stress-test & solutions", "Test de sécheresse & solutions"),
    "title": ("What if a drought year came back - and what would each solution change?",
              "Et si une année de sécheresse revenait - que changerait chaque solution ?"),
    "lead": ("Pick a real past year (its actual rain, heat and river flows from the archive) and the "
             "dams' level on 1 September. The model plans 12 months of water for 2.5 M people, the "
             "Tadla farms and downstream exports - first with today's system (<b>business as "
             "usual</b>), then with the solutions you switch on.",
             "Choisissez une année réelle (sa pluie, sa chaleur et ses débits issus des archives) et "
             "le niveau des barrages au 1er septembre. Le modèle planifie 12 mois d'eau pour 2,5 M "
             "d'habitants, les fermes du Tadla et les transferts vers l'aval - d'abord avec le "
             "système actuel (<b>statu quo</b>), puis avec les solutions activées."),
    "year": ("Climate year to replay (hydrological year ending in August)",
             "Année climatique rejouée (année hydrologique finissant en août)"),
    "fill": ("Dam levels on 1 September (% of capacity)", "Remplissage des barrages au 1er septembre (%)"),
    "levers": ("🛠️ Your solutions", "🛠️ Vos solutions"),
    "reset": ("↺ Reset all solutions", "↺ Réinitialiser les solutions"),
    "package": ("✨ Try a full package", "✨ Essayer un plan complet"),
    "bau": ("business as usual", "statu quo"),
    "with": ("with your solutions", "avec vos solutions"),
    "k_hours": ("Running water · avg hours/day", "Eau au robinet · h/jour en moyenne"),
    "k_severe": ("Residents with severe rationing", "Habitants en rationnement sévère"),
    "k_severe_sub": ("a month below 18 h/day", "un mois sous 18 h/jour"),
    "k_break": ("Breakdown cuts · days/yr", "Coupures de panne · jours/an"),
    "k_break_sub": ("for {n:,.0f} k residents on a single pipe/plant", "pour {n:,.0f} k habitants sur une seule conduite/station"),
    "k_notap": ("Residents without a tap", "Habitants sans robinet"),
    "k_irr": ("Tadla irrigation served", "Irrigation du Tadla servie"),
    "k_aq": ("Aquifer over-pumping", "Surexploitation de la nappe"),
    "hours_chart": ("Hours of running water per day, by province (annual average)",
                    "Heures d'eau courante par jour, par province (moyenne annuelle)"),
    "break_chart": ("Breakdown cuts: days without water per year (residents on a single pipe/plant)",
                    "Coupures de panne : jours sans eau par an (habitants sur une seule conduite/station)"),
    "calendar": ("Month-by-month water service, hours/day ({w})", "Service mois par mois, h/jour ({w})"),
    "flows": ("Where the water comes from and where it goes ({w}, Mm³/yr)",
              "D'où vient l'eau et où elle va ({w}, Mm³/an)"),
    "storage": ("Dam storage through the year (% of capacity) - solid: {w} · dotted: {b}",
                "Remplissage des barrages (%) - plein : {w} · pointillé : {b}"),
    "year_facts": ("Year {y}: rain {r:.0f} mm ({ra:+.0f}% vs normal) · river inflow {q:,.0f} Mm³ · {note}",
                   "Année {y} : pluie {r:.0f} mm ({ra:+.0f} % vs normale) · apports {q:,.0f} Mm³ · {note}"),
    "how": ("ℹ️ How the model works & its assumptions", "ℹ️ Fonctionnement du modèle & hypothèses"),
    "no_change": ("👈 Switch on solutions to compare with business as usual - or try the full package.",
                  "👈 Activez des solutions pour comparer au statu quo - ou essayez le plan complet."),
    "story_title": ("From drought pressure to household impact", "Du stress hydrique à l'impact sur les ménages"),
    "story_pressure": ("01 · THE SITUATION", "01 · LA SITUATION"),
    "story_response": ("02 · YOUR RESPONSE", "02 · VOTRE RÉPONSE"),
    "story_impact": ("03 · WHAT CHANGES", "03 · CE QUI CHANGE"),
    "story_rain": ("Rainfall vs normal", "Pluie vs normale"),
    "story_inflow": ("River inflow vs normal", "Apports vs normale"),
    "story_storage": ("Dams at year start", "Barrages au début de l'année"),
    "story_normal": ("of normal", "de la normale"),
    "story_no_levers": ("No solutions switched on yet.", "Aucune solution activée pour l'instant."),
    "story_service": ("Average tap supply", "Eau au robinet en moyenne"),
    "story_hours_suffix": ("h/day", "h/jour"),
    "story_severe": ("Residents facing severe rationing", "Habitants en rationnement sévère"),
    "story_bau_label": ("Without solutions", "Sans solutions"),
    "story_solution_label": ("With your solutions", "Avec vos solutions"),
    "map_title": ("🎬 The basin story · 3D", "🎬 L'histoire du bassin · 3D"),
    "map_intro": ("A guided story in 7 chapters - press ▶ or use ‹ › and the dots. Move any slider above: the scene "
                  "animates to the new plan without reloading. Drag to orbit, click a province for its numbers.",
                  "Une histoire guidée en 7 chapitres - appuyez sur ▶ ou utilisez ‹ › et les points. Bougez un curseur "
                  "ci-dessus : la scène s'anime vers le nouveau plan sans rechargement. Glissez pour tourner, cliquez "
                  "une province pour ses chiffres."),
    "map_note": ("Dams and capitals use mapped coordinates. Colour and height show annual tap service; flow paths and intervention footprints are schematic.",
                 "Barrages et chefs-lieux aux coordonnées cartographiées. Couleur et relief montrent le service annuel ; trajets et emprises sont schématiques."),
    "unmet": ("⚠ Unmet", "⚠ Non couvert"),
}
SOURCE_NAMES = {
    "HANSALI": ("Ahmed El Hansali dam", "Barrage Ahmed El Hansali"),
    "BIN_EL_OUIDANE": ("Bin El Ouidane dam", "Barrage Bin El Ouidane"),
    "AL_MASSIRA": ("Al Massira dam", "Barrage Al Massira"),
    "AQUIFER_TADLA": ("Tadla aquifer (wells)", "Nappe du Tadla (puits)"),
    "REUSE": ("Treated wastewater", "Eaux usées traitées"),
    "RIVER_KHENIFRA": ("Oum Er-Rbia at Khénifra", "Oum Er-Rbia à Khénifra"),
    "LOCAL_HASSAN_I": ("Hassan Iᵉʳ dam (Azilal)", "Barrage Hassan Iᵉʳ (Azilal)"),
}
SPRINGS_NAME = ("Springs & local wells", "Sources & puits locaux")
USE_GROUPS = {
    "potable": ("Drinking water · region", "Eau potable · région"),
    "irrigation": ("Tadla irrigation", "Irrigation du Tadla"),
    "export_potable": ("Cities downstream (export)", "Villes de l'aval (transfert)"),
    "export_irrigation": ("Doukkala irrigation (export)", "Irrigation des Doukkala (transfert)"),
}
FULL_PACKAGE = dict(leak_reduction_pts=12, storage_autonomy_h=24, backup_source_pct=60,
                    rural_connection_pct=50, interconnection_mm3=12, demand_saving_pct=8,
                    drip_conversion_pct=60, reuse_mm3=16, groundwater_cap_pct=50, desal_mm3=150)


def _l(key: str, **fmt) -> str:
    en, fr = L[key]
    s = fr if lang() == "fr" else en
    return s.format(**fmt) if fmt else s


def _bi(pair: tuple[str, str]) -> str:
    return pair[1] if lang() == "fr" else pair[0]


@st.cache_data(show_spinner=False, max_entries=64)
def _inputs(year: int, data_key: float, _discharge: pl.DataFrame, _climate: pl.DataFrame) -> YearInputs:
    return build_year_inputs(year, _discharge, _climate)


@st.cache_data(show_spinner=False, max_entries=512)
def _solve(scn: PlannerScenario, data_key: float, _inp: YearInputs) -> PlannerResult:
    """One LP solve, cached per scenario. The business-as-usual baseline only depends on the
    year and dam levels, so it is solved once and reused while solution sliders move."""
    return solve(scn, _inp)


def _results_for(year: int, fills: tuple[float, float, float], levers: SolutionLevers, data_key: float,
                 inp: YearInputs) -> tuple[PlannerResult, PlannerResult, dict[str, PlannerResult]]:
    base = _solve(PlannerScenario(year, fills, SolutionLevers()), data_key, inp)
    sol = base if levers.is_baseline else _solve(PlannerScenario(year, fills, levers), data_key, inp)
    # each active solution on its own (cached): its isolated effect for the 3D story cards
    singles = {}
    for key, spec in LEVERS.items():
        value = getattr(levers, key)
        if value != spec["default"]:
            singles[key] = _solve(PlannerScenario(year, fills, SolutionLevers(**{key: value})), data_key, inp)
    return base, sol, singles


def _apply_preset(name: str) -> None:
    p = PRESETS[name]
    st.session_state["sim_year"] = p["year"]
    for r, v in zip(RESERVOIRS, p["fill"]):
        st.session_state[f"sim_fill_{r.res_id}"] = int(round(v))
    st.session_state["sim_note"] = name


def _set_levers(values: dict) -> None:
    for k, spec in LEVERS.items():
        st.session_state[f"lv_{k}"] = values.get(k, spec["default"])


def render(discharge: pl.DataFrame, climate: pl.DataFrame, years_available: list[int],
           data_key: float) -> None:
    section(_l("kicker"), _l("title"), _l("lead"))

    # ------------------------------------------------------------------ scenario
    default = "today_drought"
    if "sim_year" not in st.session_state:
        _apply_preset(default)
    pc = st.columns(len(PRESETS))
    for col, (name, p) in zip(pc, PRESETS.items()):
        col.button(_bi(p["label"]), key=f"preset_{name}", on_click=_apply_preset, args=(name,),
                   width="stretch", disabled=p["year"] not in years_available,
                   type="primary" if st.session_state.get("sim_note") == name else "secondary")
    c1, c2 = st.columns([2, 3], gap="large")
    with c1:
        year = st.select_slider(_l("year"), options=years_available, key="sim_year")
    with c2:
        st.markdown(f'<p style="font-size:0.88rem;margin-bottom:0">{_l("fill")}</p>', unsafe_allow_html=True)
        fc = st.columns(3)
        # low levels are allowed (Al Massira hit 0.4% in 2024); the model floors at dead storage
        fills = tuple(float(fc[i].slider(r.name, 1, 100, step=1, key=f"sim_fill_{r.res_id}"))
                      for i, r in enumerate(RESERVOIRS))

    # ------------------------------------------------------------------ levers
    st.markdown(f"#### {_l('levers')}")
    b1, b2 = st.columns(2)
    b1.button(_l("package"), on_click=_set_levers, args=(FULL_PACKAGE,), width="stretch")
    b2.button(_l("reset"), on_click=_set_levers, args=({},), width="stretch")
    lever_columns = st.columns(len(LEVER_GROUPS), gap="large")
    values = {}
    for column, (gkey, gtitle) in zip(lever_columns, LEVER_GROUPS.items()):
        with column:
            st.markdown(f"**{_bi(gtitle)}**")
            for name, spec in LEVERS.items():
                if spec["group"] != gkey:
                    continue
                st.session_state.setdefault(f"lv_{name}", spec["default"])
                values[name] = st.slider(
                    f"{spec['icon']} {_bi(spec['title'])}", spec["min"], spec["max"],
                    step=spec["step"], key=f"lv_{name}", help=_bi(spec["help"]),
                )
    levers = SolutionLevers(**{k: float(v) for k, v in values.items()})
    inp = _inputs(int(year), data_key, discharge, climate)
    base, sol, singles = _results_for(int(year), fills, levers, data_key, inp)
    _results(inp, base, sol, levers, singles)


def _delta(a: float, b: float, fmt: str, better_if_higher: bool = True, suffix: str = "") -> str:
    d = b - a
    if abs(d) < 1e-6:
        return f'<span class="note">= {_l("bau")}</span>'
    good = (d > 0) == better_if_higher
    cls = "delta-good" if good else "delta-bad"
    arrow = "▲" if d > 0 else "▼"
    return f'<span class="{cls}">{arrow} {format(abs(d), fmt)}{suffix}</span> vs {_l("bau")}'


def _results(inp: YearInputs, base: PlannerResult, sol: PlannerResult, levers: SolutionLevers,
             singles: dict[str, PlannerResult]) -> None:
    b, s = base.summary, sol.summary
    note = st.session_state.get("sim_note")
    note_txt = _bi(PRESETS[note]["note"]) if note in PRESETS and PRESETS[note]["year"] == inp.year else ""
    st.markdown(f'<p class="note">{_l("year_facts", y=inp.year, r=inp.annual_rain_mm, ra=s["rain_anomaly_pct"], q=s["inflow_total"], note=note_txt)}</p>',
                unsafe_allow_html=True)
    _story(base, sol, levers)
    k = st.columns(3)
    kpi(k[0], _l("k_hours"), f"{s['avg_hours_per_day']:.1f} h",
        _delta(b["avg_hours_per_day"], s["avg_hours_per_day"], ".1f", True, " h"))
    kpi(k[1], _l("k_severe"), f"{s['people_severe'] / 1e3:,.0f} k",
        _l("k_severe_sub") + " · " + _delta(b["people_severe"] / 1e3, s["people_severe"] / 1e3, ",.0f", False, " k"))
    kpi(k[2], _l("k_break"), f"{s['breakdown_days_exposed']:.1f} d",
        _l("k_break_sub", n=s["people_exposed"] / 1e3) + "<br>"
        + _delta(b["breakdown_days_exposed"], s["breakdown_days_exposed"], ".1f", False, " d"))
    st.write("")
    k = st.columns(3)
    kpi(k[0], _l("k_notap"), f"{s['people_no_tap'] / 1e3:,.0f} k",
        _delta(b["people_no_tap"] / 1e3, s["people_no_tap"] / 1e3, ",.0f", False, " k"))
    kpi(k[1], _l("k_irr"), f"{s['irrigation_pct']:.0f}%",
        _delta(b["irrigation_pct"], s["irrigation_pct"], ".0f", True, " pts"))
    kpi(k[2], _l("k_aq"), f"{s['aquifer_overdraft']:,.0f} Mm³",
        _delta(b["aquifer_overdraft"], s["aquifer_overdraft"], ",.0f", False, " Mm³"))
    st.write("")
    if levers.is_baseline:
        callout(_l("no_change"), accent=MUTED)
    else:
        callout(_narrative(base, sol), accent=GOOD if s["avg_hours_per_day"] >= b["avg_hours_per_day"] else SERIOUS)

    st.markdown(f"#### {_l('map_title')}")
    st.caption(_l("map_intro"))
    render_basin_story(base, sol, levers, inp, singles)
    st.caption(_l("map_note"))

    _hours_dumbbell(base, sol)
    _breakdowns(base, sol)
    _calendar(sol, levers)
    _sankey(sol, levers)
    _storage(base, sol)
    with st.expander(_l("how")):
        from src.region.planner_config import ASSUMPTIONS_MD
        st.markdown(_bi(ASSUMPTIONS_MD))


def _story(base: PlannerResult, sol: PlannerResult, levers: SolutionLevers) -> None:
    """Show the replayed drought, selected interventions, and their human impact in sequence."""
    summary = sol.summary
    start_fill = 100 * summary["start_storage"] / sum(r.capacity_mm3 for r in RESERVOIRS)
    pressure = (
        (_l("story_rain"), max(0.0, 100 + summary["rain_anomaly_pct"]), ORANGE),
        (_l("story_inflow"), 100 * summary["inflow_total"] / INFLOW_NORMAL_MM3, BLUE),
        (_l("story_storage"), start_fill, AQUA),
    )

    def meter(label: str, value: float, color: str, display_value: str | None = None) -> str:
        width = min(max(value, 0.0), 100.0)
        return (
            f'<div style="margin:10px 0 12px">'
            f'<div style="display:flex;justify-content:space-between;gap:8px;color:{TEXT_2};font-size:0.78rem">'
            f'<span>{esc(label)}</span><b style="color:{TEXT}">{display_value or f"{value:.0f}%"}</b></div>'
            f'<div role="meter" aria-valuemin="0" aria-valuemax="100" aria-valuenow="{width:.0f}" '
            f'style="height:7px;background:{GRID};border-radius:4px;overflow:hidden;margin-top:5px">'
            f'<div style="height:100%;width:{width:.1f}%;background:{color};border-radius:4px"></div></div>'
            f'</div>'
        )

    active = []
    for name, spec in LEVERS.items():
        value = getattr(levers, name)
        if value != spec["default"]:
            active.append(
                f'<div style="display:flex;justify-content:space-between;gap:8px;padding:6px 0;'
                f'border-bottom:1px solid {GRID};font-size:0.78rem">'
                f'<span style="color:{TEXT_2}">{spec["icon"]} {esc(_bi(spec["title"]))}</span>'
                f'<b style="color:{TEXT};white-space:nowrap">{spec["fmt"] % value}</b></div>'
            )

    pressure_html = "".join(meter(label, value, color) for label, value, color in pressure)
    response_html = "".join(active) or f'<p class="note">{_l("story_no_levers")}</p>'
    hours_base = base.summary["avg_hours_per_day"]
    hours_sol = sol.summary["avg_hours_per_day"]
    people_base = base.summary["people_severe"] / 1000
    people_sol = sol.summary["people_severe"] / 1000
    impact_html = (
        f'<div style="margin:10px 0 5px;color:{TEXT_2};font-size:0.78rem">{_l("story_service")}</div>'
        f'{meter(_l("story_bau_label"), 100 * hours_base / 24, SERIOUS, f"{hours_base:.1f} {_l('story_hours_suffix')}")}'
        f'{meter(_l("story_solution_label"), 100 * hours_sol / 24, AQUA, f"{hours_sol:.1f} {_l('story_hours_suffix')}")}'
        f'<div style="margin-top:12px;color:{TEXT_2};font-size:0.78rem">{_l("story_severe")}</div>'
        f'<div style="margin-top:3px;color:{TEXT};font-size:1.05rem;font-weight:700">'
        f'{people_base:,.0f}k <span style="color:{MUTED};font-size:0.85rem">→</span> {people_sol:,.0f}k</div>'
    )
    st.markdown(f'<h3 style="font-size:1.05rem;margin:0 0 10px;color:{TEXT}">{_l("story_title")}</h3>',
                unsafe_allow_html=True)
    columns = st.columns([1, 1, 1.1], gap="large")
    stages = (
        (columns[0], "story_pressure", ORANGE, pressure_html),
        (columns[1], "story_response", BLUE, response_html),
        (columns[2], "story_impact", AQUA, impact_html),
    )
    for column, label, color, body in stages:
        column.markdown(
            f'<div style="border-top:2px solid {color};padding-top:9px">'
            f'<div style="font-size:0.72rem;font-weight:700;color:{TEXT_2};margin-bottom:8px">{_l(label)}</div>'
            f'{body}</div>',
            unsafe_allow_html=True,
        )
    st.write("")


def _narrative(base: PlannerResult, sol: PlannerResult) -> str:
    bp = {r["demand_id"]: r for r in base.province.iter_rows(named=True)}
    gains = sorted(((r["hours_per_day"] - bp[r["demand_id"]]["hours_per_day"], r)
                    for r in sol.province.iter_rows(named=True)), key=lambda x: -x[0])
    top = [g for g in gains if g[0] > 0.05][:2]
    b, s = base.summary, sol.summary
    fr = lang() == "fr"
    name = (lambda pid: PROVINCES_BY_ID[pid].name_fr) if fr else (lambda pid: PROVINCES_BY_ID[pid].name_en)
    tops = (" et " if fr else " and ").join(
        f"<b>{name(r['province_id'])}</b> ({bp[r['demand_id']]['hours_per_day']:.1f} → {r['hours_per_day']:.1f} h)"
        for _, r in top)
    if fr:
        txt = (f"Avec vos solutions, l'eau coule en moyenne <b>{s['avg_hours_per_day']:.1f} h/jour</b> au lieu de "
               f"{b['avg_hours_per_day']:.1f} h" + (f", surtout à {tops}" if top else "") + ". "
               f"Coupures de panne : {b['breakdown_days_exposed']:.1f} → <b>{s['breakdown_days_exposed']:.1f} jours/an</b> "
               f"pour les habitants sur une seule conduite. Irrigation du Tadla : {b['irrigation_pct']:.0f} % → "
               f"<b>{s['irrigation_pct']:.0f} %</b> ; surexploitation de la nappe : {b['aquifer_overdraft']:,.0f} → "
               f"<b>{s['aquifer_overdraft']:,.0f} Mm³</b>.")
    else:
        txt = (f"With your solutions, taps run <b>{s['avg_hours_per_day']:.1f} h/day</b> on average instead of "
               f"{b['avg_hours_per_day']:.1f} h" + (f", especially in {tops}" if top else "") + ". "
               f"Breakdown cuts: {b['breakdown_days_exposed']:.1f} → <b>{s['breakdown_days_exposed']:.1f} days/yr</b> "
               f"for residents on a single pipe. Tadla irrigation: {b['irrigation_pct']:.0f}% → "
               f"<b>{s['irrigation_pct']:.0f}%</b>; aquifer over-pumping: {b['aquifer_overdraft']:,.0f} → "
               f"<b>{s['aquifer_overdraft']:,.0f} Mm³</b>.")
    return txt


def _province_names(rows) -> list[str]:
    return [PROVINCES_BY_ID[r["province_id"]].name_fr for r in rows]


def _hours_dumbbell(base: PlannerResult, sol: PlannerResult) -> None:
    bp = {r["demand_id"]: r for r in base.province.iter_rows(named=True)}
    rows = sorted(sol.province.iter_rows(named=True), key=lambda r: -bp[r["demand_id"]]["hours_per_day"])
    names = _province_names(rows)
    fig = go.Figure()
    for i, r in enumerate(rows):
        fig.add_trace(go.Scatter(x=[bp[r["demand_id"]]["hours_per_day"], r["hours_per_day"]], y=[names[i]] * 2,
                                 mode="lines", line=dict(color=GRID, width=6), hoverinfo="skip", showlegend=False))
    m = "mois" if lang() == "fr" else "months"
    fig.add_trace(go.Scatter(
        x=[bp[r["demand_id"]]["hours_per_day"] for r in rows], y=names, mode="markers", name=_l("bau"),
        marker=dict(size=14, color=SERIOUS, line=dict(color=SURFACE, width=2)),
        customdata=[[bp[r["demand_id"]]["worst_month_hours"], bp[r["demand_id"]]["months_rationed"]] for r in rows],
        hovertemplate="%{y}: %{x:.1f} h<br>min %{customdata[0]:.1f} h · %{customdata[1]} " + m + "<extra></extra>"))
    fig.add_trace(go.Scatter(
        x=[r["hours_per_day"] for r in rows], y=names, mode="markers+text", name=_l("with"),
        marker=dict(size=16, color=AQUA, symbol="diamond", line=dict(color=SURFACE, width=2)),
        text=[f"{r['hours_per_day']:.1f} h" for r in rows], textposition="middle right",
        textfont=dict(color=TEXT, size=12),
        customdata=[[r["worst_month_hours"], r["months_rationed"], r["population"]] for r in rows],
        hovertemplate="%{y}: %{x:.1f} h<br>min %{customdata[0]:.1f} h · %{customdata[1]} " + m
                      + "<br>%{customdata[2]:,}<extra></extra>"))
    lo = min(min(bp[r["demand_id"]]["hours_per_day"] for r in rows), min(r["hours_per_day"] for r in rows))
    base_layout(fig, 300, title=_l("hours_chart"), legend_traceorder="normal")
    fig.update_xaxes(range=[max(0, lo - 2), 25.8], ticksuffix=" h", showgrid=True, gridcolor=GRID)
    show(fig)


def _breakdowns(base: PlannerResult, sol: PlannerResult) -> None:
    bp = {r["demand_id"]: r for r in base.province.iter_rows(named=True)}
    rows = list(sol.province.iter_rows(named=True))
    names = _province_names(rows)
    fig = go.Figure()
    fig.add_trace(go.Bar(x=names, y=[bp[r["demand_id"]]["breakdown_days_exposed"] for r in rows], name=_l("bau"),
                         marker=dict(color=SERIOUS, cornerradius=3), hovertemplate="%{x}: %{y:.1f} d<extra></extra>"))
    fig.add_trace(go.Bar(x=names, y=[r["breakdown_days_exposed"] for r in rows], name=_l("with"),
                         marker=dict(color=AQUA, cornerradius=3),
                         text=[f"{r['breakdown_days_exposed']:.1f}" for r in rows], textposition="outside",
                         textfont=dict(color=TEXT_2), hovertemplate="%{x}: %{y:.1f} d<extra></extra>"))
    base_layout(fig, 280, title=_l("break_chart"), barmode="group", bargap=0.35, bargroupgap=0.08,
                legend_traceorder="normal")
    show(fig)


def _calendar(sol: PlannerResult, levers: SolutionLevers) -> None:
    pot = sol.monthly.filter(pl.col("kind") == "potable")
    order = [d.demand_id for d in DEMANDS]
    names = {d.demand_id: PROVINCES_BY_ID[d.province_id].name_fr for d in DEMANDS}
    z = [[24 * v for v in pot.filter(pl.col("demand_id") == d).sort("m")["service_ratio"].to_list()] for d in order]
    fig = go.Figure(go.Heatmap(
        x=[_bi(m) for m in MONTH_LABELS], y=[names[d] for d in order], z=z, zmin=12, zmax=24, xgap=2, ygap=2,
        # same diverging encoding as the 3D story: red (few hours) -> grey (20.5 h) -> blue (24 h)
        colorscale=[[0, CRITICAL], [0.417, "#e66767"], [0.708, "#8d8a84"], [0.875, "#6da7ec"], [1, "#2a78d6"]],
        colorbar=dict(title=dict(text="h", font=dict(color=TEXT_2)), tickfont=dict(color=TEXT_2), thickness=10),
        hovertemplate="%{y} · %{x}: %{z:.1f} h<extra></extra>",
        text=[[f"{v:.0f}" for v in row] for row in z], texttemplate="%{text}", textfont=dict(color=TEXT, size=11),
    ))
    base_layout(fig, 270, title=_l("calendar", w=_l("bau") if levers.is_baseline else _l("with")))
    show(fig)


def _sankey(res: PlannerResult, levers: SolutionLevers) -> None:
    m = res.monthly
    src_cols = [c for c in m.columns if c.startswith("from_")]
    flows: dict[tuple[str, str], float] = {}
    for (kind,), group in m.group_by("kind"):
        use = _bi(USE_GROUPS[kind])
        for c in src_cols:
            val = float(group[c].sum())
            if val < 0.5:
                continue
            sid = c[5:]
            name = _bi(SOURCE_NAMES[sid]) if sid in SOURCE_NAMES else _bi(SPRINGS_NAME)
            flows[(name, use)] = flows.get((name, use), 0) + val
        short = float(group["shortfall_mm3"].sum())
        if short > 0.5:
            flows[(_l("unmet"), use)] = short
    sources = list(dict.fromkeys(a for a, _ in flows))
    uses = list(dict.fromkeys(b for _, b in flows))
    nodes = sources + uses

    def color(n: str) -> str:
        if n == _l("unmet"):
            return CRITICAL
        if n in uses:
            return "#6c6b65"
        low = n.lower()
        if "aquifer" in low or "nappe" in low:
            return AQUA
        if "dam" in low or "barrage" in low:
            return BLUE
        return ORANGE

    fig = go.Figure(go.Sankey(
        arrangement="snap",
        node=dict(label=nodes, pad=16, thickness=16, line=dict(color=SURFACE, width=1),
                  color=[color(n) for n in nodes],
                  hovertemplate="%{label}: %{value:,.0f} Mm³<extra></extra>"),
        link=dict(source=[nodes.index(a) for a, _ in flows], target=[nodes.index(b) for _, b in flows],
                  value=list(flows.values()),
                  color=["rgba(208,59,59,0.35)" if a == _l("unmet") else "rgba(160,160,150,0.22)" for a, _ in flows],
                  hovertemplate="%{source.label} → %{target.label}: %{value:,.0f} Mm³<extra></extra>"),
        textfont=dict(color=TEXT, size=12),
    ))
    base_layout(fig, 420, title=_l("flows", w=_l("bau") if levers.is_baseline else _l("with")))
    show(fig)


def _storage(base: PlannerResult, sol: PlannerResult) -> None:
    fig = go.Figure()
    colors = {"HANSALI": BLUE, "BIN_EL_OUIDANE": ORANGE, "AL_MASSIRA": AQUA}
    labels = [_bi(m) for m in MONTH_LABELS]
    for r in RESERVOIRS:
        sb = base.storage.filter(pl.col("res_id") == r.res_id).sort("m")
        ss = sol.storage.filter(pl.col("res_id") == r.res_id).sort("m")
        fig.add_trace(go.Scatter(x=labels, y=sb["fill_pct"].to_list(), mode="lines", showlegend=False,
                                 line=dict(color=colors[r.res_id], width=1.5, dash="dot"),
                                 hovertemplate=f"{r.name} ({_l('bau')}): %{{y:.0f}}%<extra></extra>"))
        fig.add_trace(go.Scatter(x=labels, y=ss["fill_pct"].to_list(), mode="lines+markers", name=r.name,
                                 line=dict(color=colors[r.res_id], width=2.5), marker=dict(size=7),
                                 hovertemplate=f"{r.name}: %{{y:.0f}}%<extra></extra>"))
    base_layout(fig, 320, title=_l("storage", w=_l("with"), b=_l("bau")), hovermode="x unified")
    fig.update_yaxes(ticksuffix="%", rangemode="tozero")
    show(fig)
