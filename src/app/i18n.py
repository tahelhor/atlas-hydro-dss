"""Bilingual (English / Français) UI strings.

Usage: ``t("key")`` or ``t("key", n=3)`` (str.format placeholders). The active language
lives in ``st.session_state["lang"]`` ("en" | "fr"). Content strings (problems, causes,
solutions) are bilingual in the knowledge base itself; this table only covers UI chrome.
"""

from __future__ import annotations

import streamlit as st

LANGS = {"en": "English", "fr": "Français"}

STRINGS: dict[str, tuple[str, str]] = {
    # ---- app chrome
    "app_title": ("Atlas Hydro-Climate DSS · Béni Mellal–Khénifra & Oum Er-Rbia",
                  "Atlas Hydro-Climat · Béni Mellal–Khénifra & Oum Er-Rbia"),
    "app_sub": ("From live satellite & reanalysis data to decisions: why taps run dry, who is "
                "affected, and which solutions work · data as of {date}",
                "Des données satellitaires et de réanalyse aux décisions : pourquoi les robinets "
                "se tarissent, qui est touché, quelles solutions fonctionnent · données au {date}"),
    "language": ("Language", "Langue"),
    "tab_crisis": ("🚰 Water crisis", "🚰 Crise de l'eau"),
    "tab_sim": ("🧪 Solutions simulator", "🧪 Simulateur de solutions"),
    "tab_ops": ("🗺️ 30-day operations", "🗺️ Opérations 30 jours"),
    "tab_hydro": ("🌊 Hydrograph & forecast", "🌊 Hydrogramme & prévision"),
    "tab_qa": ("🛡️ Data QA & sources", "🛡️ Qualité des données & sources"),
    "warehouse_missing": ("Warehouse not found. Build it first:", "Entrepôt introuvable. Construisez-le :"),
    # ---- live KPI ribbon
    "kpi_storage": ("Basin storage now", "Réserves du bassin"),
    "kpi_storage_sub": ("{pct:.1f}% of {cap:,.0f} Mm³ capacity", "{pct:.1f}% de {cap:,.0f} Mm³"),
    "kpi_day30": ("Projected storage · day 30", "Réserves prévues · J+30"),
    "kpi_inflow": ("30-day expected inflow", "Apports attendus 30 j"),
    "kpi_inflow_sub": ("{fc} forecast · shock {shock:+.0f}%", "prévision {fc} · choc {shock:+.0f}%"),
    "kpi_et0": ("Mean FAO ET0", "ET0 FAO moyenne"),
    "kpi_et0_sub": ("evaporation loss {evap:,.1f} Mm³ / 30 d", "pertes par évaporation {evap:,.1f} Mm³ / 30 j"),
    "kpi_status": ("Optimisation status", "Statut de l'optimisation"),
    "kpi_status_sub": ("unmet {unmet:,.1f} Mm³ ({share:.1f}%) · solved in {ms:.0f} ms",
                       "déficit {unmet:,.1f} Mm³ ({share:.1f}%) · résolu en {ms:.0f} ms"),
    "status_Optimal": ("Optimal", "Optimal"),
    "status_Deficit Warning": ("Deficit Warning", "Alerte déficit"),
    # ---- sidebar
    "sb_title": ("🎛️ 30-day operations levers", "🎛️ Leviers opérationnels 30 jours"),
    "sb_caption": ("Drive the 30-day reservoir model (KPI ribbon & Operations tab). Every change "
                   "re-solves the PuLP linear program.",
                   "Pilotent le modèle de barrages à 30 jours (bandeau & onglet Opérations). Chaque "
                   "changement relance le programme linéaire PuLP."),
    "sb_forecast": ("GloFAS ensemble forecast", "Prévision d'ensemble GloFAS"),
    "fc_p25": ("p25 · pessimistic", "p25 · pessimiste"),
    "fc_mean": ("mean · central", "moyenne · centrale"),
    "fc_p75": ("p75 · optimistic", "p75 · optimiste"),
    "sb_shock": ("Climate inflow shock (%)", "Choc climatique sur les apports (%)"),
    "sb_shock_help": ("-50% severe drought → +50% wet anomaly, on top of the selected forecast.",
                      "-50 % sécheresse sévère → +50 % anomalie humide, appliqué à la prévision."),
    "sb_irr": ("Agricultural irrigation demand cap (%)", "Plafond de la demande d'irrigation (%)"),
    "sb_irr_help": ("Scales Tadla & Doukkala demand (already scaled by FAO ET0).",
                    "Module la demande du Tadla et des Doukkala (déjà indexée sur l'ET0 FAO)."),
    "sb_buffer": ("Minimum reservoir safety buffer (% of capacity)",
                  "Réserve de sécurité minimale (% de la capacité)"),
    "sb_advanced": ("Advanced scenario levers", "Leviers avancés"),
    "sb_init": ("Starting storage (% of ABHOER seed)", "Stock initial (% de la référence ABHOER)"),
    "sb_init_help": ("Stress-test a dry or wet start of season.",
                     "Tester un début de saison sec ou humide."),
    "sb_buffer_mode": ("Buffer enforcement", "Application de la réserve"),
    "buffer_soft": ("Soft · hedge irrigation first", "Souple · rationner l'irrigation d'abord"),
    "buffer_hard": ("Hard · protect storage at all costs", "Stricte · protéger le stock à tout prix"),
    "sb_run": ("Data run `{run}` · {status}", "Exécution `{run}` · {status}"),
    "sb_refresh": ("🔄 Refresh live data (Open-Meteo)", "🔄 Actualiser les données (Open-Meteo)"),
    "sb_refreshing": ("Fetching GloFAS v4 + ECMWF data for 4 nodes…",
                      "Récupération GloFAS v4 + ECMWF pour 4 nœuds…"),
    "sb_refreshed": ("Ingested {ok}/{n} rows", "{ok}/{n} lignes intégrées"),
    "infeasible": ("Solver returned **{s}** - the scenario is infeasible. Relax the levers.",
                   "Le solveur renvoie **{s}** - scénario infaisable. Assouplissez les leviers."),
    # ---- uses
    "use_potable": ("Potable (ONEE)", "Eau potable (ONEE)"),
    "use_irrigation": ("Irrigation (Tadla/Doukkala)", "Irrigation (Tadla/Doukkala)"),
    "use_ecological": ("Ecological flow", "Débit écologique"),
    "use_deficit": ("Unmet deficit", "Déficit non couvert"),
    "potable": ("Potable", "Eau potable"),
    "irrigation": ("Irrigation", "Irrigation"),
    "ecological": ("Ecological", "Écologique"),
    # ---- operations tab
    "ops_map_caption": ("Marker size ∝ normal capacity · colour = storage % at start of horizon. "
                        "Lines are a schematic of the river cascade.",
                        "Taille ∝ capacité normale · couleur = taux de remplissage au départ. "
                        "Les lignes schématisent la cascade du fleuve."),
    "storage_pct": ("Storage %", "Remplissage %"),
    "ops_status": ("Reservoir status", "État des barrages"),
    "col_reservoir": ("Reservoir", "Barrage"),
    "col_now": ("Now (%)", "Actuel (%)"),
    "col_day30": ("Day 30 (%)", "J+30 (%)"),
    "col_reliability": ("Reliability (%)", "Fiabilité (%)"),
    "ops_reliability": ("Service reliability by use", "Fiabilité du service par usage"),
    "ops_weights": ("Priority weights: potable {p:g} · ecological {e:g} · irrigation {i:g}. "
                    "Buffer penalty ({mode}): {b:g}.",
                    "Poids de priorité : eau potable {p:g} · écologique {e:g} · irrigation {i:g}. "
                    "Pénalité de réserve ({mode}) : {b:g}."),
    "ops_scope": ("Scope", "Périmètre"),
    "basin_total": ("Basin total", "Total bassin"),
    "ops_alloc_title": ("Optimal daily water allocation (Mm³/day)",
                        "Allocation journalière optimale (Mm³/jour)"),
    "ops_traj": ("Projected storage trajectories vs. safety buffer",
                 "Trajectoires de stock prévues vs réserve de sécurité"),
    "buffer": ("buffer", "réserve"),
    "cap": ("cap.", "cap."),
    "ops_table": ("📋 Allocation table & model assumptions", "📋 Tableau d'allocation & hypothèses"),
    "hover_of": ("of", "sur"),
    # ---- hydro tab
    "node": ("Node", "Nœud"),
    "h_band": ("GloFAS p25–p75 ensemble", "Ensemble GloFAS p25–p75"),
    "h_hist": ("Observed / reanalysis (92 d)", "Observé / réanalyse (92 j)"),
    "h_fc": ("Forecast ensemble mean (30 d)", "Moyenne d'ensemble prévue (30 j)"),
    "h_forecast": ("forecast →", "prévision →"),
    "h_title": ("River discharge · {name} (m³/s)", "Débit du fleuve · {name} (m³/s)"),
    "h_drivers": ("Water balance drivers (mm/day)", "Moteurs du bilan hydrique (mm/jour)"),
    "precip": ("Precipitation", "Précipitations"),
    "h_soil": ("Deep root-zone soil moisture (m³/m³)", "Humidité du sol profonde (m³/m³)"),
    "h_soil_series": ("Soil moisture 28–100 cm", "Humidité du sol 28–100 cm"),
    "h_caption": ("Weather fields start ~60 days back (forecast-API archive limit); forecast days "
                  "17–30 carry the day-16 value forward (flagged `weather_is_filled`).",
                  "Les champs météo débutent ~60 jours en arrière (limite de l'API) ; les jours "
                  "17–30 reprennent la valeur du jour 16 (indicateur `weather_is_filled`)."),
    # ---- QA tab
    "qa_last": ("Last pipeline run", "Dernière exécution"),
    "qa_fresh": ("Data freshness", "Fraîcheur des données"),
    "qa_fresh_v": ("{h:.1f} h ago", "il y a {h:.1f} h"),
    "qa_fresh_ok": ("✔ fresh (< 24 h)", "✔ à jour (< 24 h)"),
    "qa_fresh_bad": ("⚠ stale - refresh from sidebar", "⚠ ancienne - actualiser via le menu"),
    "qa_pass": ("Pydantic pass rate", "Taux de validation Pydantic"),
    "qa_rows": ("{ok} / {n} rows", "{ok} / {n} lignes"),
    "qa_quarantine": ("Rows quarantined", "Lignes en quarantaine"),
    "qa_anomalies": ("{n} anomaly warnings", "{n} alertes d'anomalie"),
    "qa_fact_rows": ("{n:,} rows", "{n:,} lignes"),
    "qa_fact_sub": ("{nodes} nodes · {runs} runs logged", "{nodes} nœuds · {runs} exécutions"),
    "qa_completeness": ("Completeness by node (current 122-day window, % non-null)",
                        "Complétude par nœud (fenêtre de 122 jours, % non nul)"),
    "qa_history": ("Run history", "Historique des exécutions"),
    "qa_counts": ("DuckDB table row counts", "Nombre de lignes par table DuckDB"),
    "qa_gates": ("QA gates enforced", "Contrôles qualité appliqués"),
    "qa_gates_md": (
        "- **Payload contracts** - required variables present, arrays aligned, dates parseable, "
        "sorted & unique, coordinates valid\n"
        "- **Physical bounds** - discharge ∈ [0, 20 000] m³/s · precip ∈ [0, 500] mm · ET0 ∈ "
        "[0, 20] mm · soil moisture ∈ [0, 1] · T ∈ [-30, 60] °C\n"
        "- **Consistency** - p25 ≤ p75 · inflow = Q × 86400 / 10⁶ · strict boolean `is_forecast` "
        "· forward-fill only on forecast days · finite values only\n"
        "- **Knowledge base** - every fact, problem, cause and solution cites ≥ 1 dated source "
        "with a valid URL\n"
        "- **Anomaly gate (soft)** - > 10× day-over-day discharge spikes above 50 m³/s are "
        "flagged but kept",
        "- **Contrats d'API** - variables requises présentes, tableaux alignés, dates valides, "
        "triées et uniques, coordonnées valides\n"
        "- **Bornes physiques** - débit ∈ [0, 20 000] m³/s · pluie ∈ [0, 500] mm · ET0 ∈ "
        "[0, 20] mm · humidité du sol ∈ [0, 1] · T ∈ [-30, 60] °C\n"
        "- **Cohérence** - p25 ≤ p75 · apport = Q × 86400 / 10⁶ · booléen strict `is_forecast` "
        "· report uniquement sur les jours prévus · valeurs finies\n"
        "- **Base de connaissances** - chaque fait, problème, cause et solution cite ≥ 1 source "
        "datée avec une URL valide\n"
        "- **Détection d'anomalies** - pics de débit > 10× d'un jour à l'autre au-delà de "
        "50 m³/s signalés mais conservés"),
    "qa_quarantined": ("Quarantined rows ({n})", "Lignes en quarantaine ({n})"),
    "qa_none": ("No rows quarantined - every ingested record passed validation.",
                "Aucune ligne en quarantaine - tous les enregistrements ont été validés."),
}


def lang() -> str:
    return st.session_state.get("lang", "en")


def t(key: str, **fmt) -> str:
    en, fr = STRINGS[key]
    s = fr if lang() == "fr" else en
    return s.format(**fmt) if fmt else s


def pick(obj, field: str) -> str:
    """Pick ``<field>_en`` / ``<field>_fr`` from a bilingual object or dict."""
    suffix = "fr" if lang() == "fr" else "en"
    if isinstance(obj, dict):
        return obj.get(f"{field}_{suffix}") or obj.get(f"{field}_en", "")
    return getattr(obj, f"{field}_{suffix}", None) or getattr(obj, f"{field}_en", "")
