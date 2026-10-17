"""Animated 3D "basin story" for the solutions simulator (Three.js, Streamlit components v2).

The component stays mounted: when a slider moves, Python sends new data and the scene
*animates* to it (province colours and heights, reservoir levels, flows, solution assets)
instead of reloading. It tells the scenario as a guided story in seven chapters:

    1 the basin · 2 the drought year, month by month · 3 who runs dry first ·
    4 where the water goes · 5 your plan (what gets built, where, and its own effect) ·
    6 what changes for people · 7 explore freely (orbit, hover, month timeline, before/after)

Every piece of text is prepared here in the active language; the JavaScript only animates.
Positions of dams and capitals are mapped; rivers, routes and asset footprints are schematic.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import streamlit as st

from src.app.i18n import lang
from src.config import NODES_BY_ID
from src.models.regional_planner import PlannerResult, SolutionLevers, YearInputs
from src.region.planner_config import (
    DEMANDS, INFLOW_NORMAL_MM3, LEVERS, MONTH_LABELS, RESERVOIRS as MODEL_RESERVOIRS,
)
from src.region.provinces import PROVINCES, PROVINCES_BY_ID, province_geojson

ASSET_DIR = Path(__file__).with_name("basin_story")
BIG_DAMS = {"HANSALI", "BIN_EL_OUIDANE", "AL_MASSIRA"}
_RESERVOIR_SITE_IDS = {
    "HANSALI": "DAM_AHMED_EL_HANSALI",
    "BIN_EL_OUIDANE": "DAM_BIN_EL_OUIDANE",
    "AL_MASSIRA": "DAM_AL_MASSIRA",
}
# schematic geography (lon, lat) - labelled as schematic in the UI
TADLA_CENTER = (-6.55, 32.42)
COAST = (-8.25, 32.62)
RIVERS = {
    "oum_er_rbia": [(-5.669, 32.94), (-5.78, 32.78), (-5.922, 32.515), (-6.10, 32.57), (-6.27, 32.60),
                    (-6.62, 32.63), (-6.98, 32.57), (-7.30, 32.50), (-7.638, 32.473)],
    "el_abid": [(-6.464, 32.106), (-6.58, 32.22), (-6.74, 32.36), (-6.88, 32.47), (-6.98, 32.57)],
}

# What each solution physically builds and where (schematic) - drawn as 3D assets.
_PROJECT_VISUALS = {
    "leak_reduction_pts": {
        "anchor": "cities",
        "component": ("Leak repair & district meters", "Réparation des fuites & compteurs de secteur"),
        "location": ("Five provincial distribution networks · schematic placement", "Réseaux des cinq provinces · implantation schématique"),
        "build": ("Find high-loss zones, isolate them with district meters, and replace or repair the leakiest mains.",
                  "Repérer les secteurs à fortes pertes, les isoler par comptage et réparer ou remplacer les conduites prioritaires."),
    },
    "storage_autonomy_h": {
        "anchor": "cities",
        "component": ("Municipal service reservoirs", "Réservoirs de service municipaux"),
        "location": ("Near provincial capitals · indicative sites", "Près des chefs-lieux · sites indicatifs"),
        "build": ("Add covered storage tanks so short plant or pipeline failures do not immediately interrupt taps.",
                  "Ajouter des réservoirs couverts afin que les pannes courtes ne coupent pas immédiatement les robinets."),
    },
    "backup_source_pct": {
        "anchor": "pipes_all",
        "component": ("Second-source connections", "Raccordements à une seconde ressource"),
        "location": ("Single-source service zones · schematic links", "Zones à source unique · liaisons schématiques"),
        "build": ("Connect exposed towns to a backup wellfield, treatment plant, or parallel main.",
                  "Raccorder les villes exposées à un champ de captage, une station ou une conduite de secours."),
    },
    "rural_connection_pct": {
        "anchor": "homes",
        "component": ("Rural water connections", "Branchements d'eau ruraux"),
        "location": ("Rural service areas · indicative homes", "Zones rurales · foyers indicatifs"),
        "build": ("Extend distribution branches and household connections to rural homes without running water.",
                  "Étendre les antennes de distribution et les branchements aux foyers ruraux sans eau courante."),
    },
    "interconnection_mm3": {
        "anchor": "pipes_mountain",
        "component": ("Reservoir-to-town transfer mains", "Conduites de transfert barrages-villes"),
        "location": ("Dam system to spring-dependent towns · schematic route", "Système des barrages vers les villes sur sources · tracé schématique"),
        "build": ("Build conveyance and treatment capacity to move a limited share of dam water to towns relying on local springs.",
                  "Créer des capacités de transfert et de traitement pour alimenter les villes dépendantes des sources locales."),
    },
    "demand_saving_pct": {
        "anchor": "drops",
        "component": ("Household efficiency kits", "Équipements économes des ménages"),
        "location": ("Connected homes across the region · indicative", "Logements raccordés dans la région · indicatif"),
        "build": ("Install efficient fixtures and pair them with leak reporting and conservation measures.",
                  "Installer des équipements économes, avec signalement des fuites et mesures de sobriété."),
    },
    "drip_conversion_pct": {
        "anchor": "tadla_drip",
        "component": ("Drip irrigation laterals", "Réseaux d'irrigation goutte-à-goutte"),
        "location": ("Tadla irrigation perimeter · indicative footprint", "Périmètre irrigué du Tadla · emprise indicative"),
        "build": ("Convert selected flood-irrigated plots to drip lines; the model caps effective efficiency to reflect rebound.",
                  "Convertir certaines parcelles gravitaires au goutte-à-goutte ; le modèle limite le gain effectif pour tenir compte de l'effet rebond."),
    },
    "reuse_mm3": {
        "anchor": "tadla_plant",
        "component": ("Wastewater treatment & reuse plant", "Station de traitement et de réutilisation"),
        "location": ("Tadla irrigation perimeter · indicative site", "Périmètre irrigué du Tadla · site indicatif"),
        "build": ("Add tertiary treatment and a reclaimed-water main supplying farms instead of freshwater.",
                  "Ajouter un traitement tertiaire et une conduite d'eau réutilisée pour les fermes, en substitution d'eau douce."),
    },
    "groundwater_cap_pct": {
        "anchor": "tadla_wells",
        "component": ("Monitored wells & pumping limits", "Forages suivis & plafonds de pompage"),
        "location": ("Tadla aquifer · indicative monitoring wells", "Nappe du Tadla · forages de suivi indicatifs"),
        "build": ("Meter abstraction, monitor groundwater levels, and enforce a seasonal pumping cap.",
                  "Mesurer les prélèvements, suivre les niveaux piézométriques et appliquer un plafond saisonnier."),
    },
    "desal_mm3": {
        "anchor": "coast",
        "component": ("Coastal desalination & export substitution", "Dessalement côtier & substitution des transferts"),
        "location": ("Atlantic coast, downstream of this map", "Littoral atlantique, en aval de cette carte"),
        "build": ("Supply coastal cities with desalinated water so upstream dams release less water downstream.",
                  "Alimenter les villes côtières en eau dessalée pour que les barrages amont lâchent moins d'eau vers l'aval."),
    },
}
# metric used to show each solution's OWN effect (solved with that lever alone):
# key, label, unit, decimals, True if higher is better
_PROJECT_METRICS = {
    "leak_reduction_pts": ("avg_hours_per_day", "metric_hours", "h", 1, True),
    "storage_autonomy_h": ("breakdown_days_exposed", "metric_breakdowns", "d", 1, False),
    "backup_source_pct": ("breakdown_days_exposed", "metric_breakdowns", "d", 1, False),
    "rural_connection_pct": ("people_no_tap", "metric_no_tap", "k", 0, False),
    "interconnection_mm3": ("avg_hours_per_day", "metric_hours", "h", 1, True),
    "demand_saving_pct": ("avg_hours_per_day", "metric_hours", "h", 1, True),
    "drip_conversion_pct": ("irrigation_pct", "metric_irrigation", "%", 0, True),
    "reuse_mm3": ("irrigation_pct", "metric_irrigation", "%", 0, True),
    "groundwater_cap_pct": ("aquifer_overdraft", "metric_overdraft", "Mm³", 0, False),
    "desal_mm3": ("upstream_to_massira", "metric_kept", "Mm³", 0, False),
}

_COPY = {
    "loading": ("Building the 3D basin…", "Construction du bassin en 3D…"),
    "error": ("3D view unavailable (it needs an internet connection to load Three.js). The charts below show the same results.",
              "Vue 3D indisponible (connexion internet nécessaire pour charger Three.js). Les graphiques ci-dessous montrent les mêmes résultats."),
    "play": ("Play story", "Lancer l'histoire"), "pause": ("Pause", "Pause"),
    "prev": ("Previous chapter", "Chapitre précédent"), "next": ("Next chapter", "Chapitre suivant"),
    "replay": ("Replay story", "Rejouer l'histoire"),
    "before": ("Without solutions", "Sans solutions"), "after": ("With your solutions", "Avec vos solutions"),
    "year": ("Year", "Année"), "chapter": ("Chapter {i} of {n}", "Chapitre {i} sur {n}"),
    "legend_service": ("Tap water, hours/day", "Eau au robinet, h/jour"),
    "legend_dam": ("Dam water level", "Niveau des barrages"),
    "legend_flow": ("Water deliveries", "Livraisons d'eau"),
    "legend_schematic": ("Rivers and routes are schematic", "Rivières et tracés schématiques"),
    "hours": ("h/day", "h/jour"), "worst": ("worst month", "pire mois"),
    "breakdowns": ("days/yr without water from breakdowns", "jours/an sans eau (pannes)"),
    "no_tap": ("residents without a tap", "habitants sans robinet"),
    "full": ("full", "plein"), "of_normal": ("of normal", "de la normale"),
    "own_effect": ("On its own", "Seule"), "package": ("In your package", "Dans votre plan"),
    "drag": ("Drag to orbit · scroll to zoom · click a province", "Glissez pour tourner · molette pour zoomer · cliquez une province"),
    "resume": ("Resume story", "Reprendre l'histoire"),
    "tadla": ("Tadla irrigated plain", "Plaine irriguée du Tadla"),
    "aquifer": ("Tadla aquifer (wells)", "Nappe du Tadla (puits)"),
    "residents": ("residents", "habitants"),
    "local_sources": ("of supply from local springs, wells & intakes", "de l'eau issue de sources, puits et prises locales"),
    "downstream": ("Downstream: Casablanca · Marrakech · Doukkala", "Aval : Casablanca · Marrakech · Doukkala"),
    "outside": ("outside the region", "hors région"),
    "metric_hours": ("Average tap service", "Service moyen au robinet"),
    "metric_breakdowns": ("Breakdown days (single-pipe residents)", "Jours de panne (habitants sur conduite unique)"),
    "metric_no_tap": ("Residents without a tap", "Habitants sans robinet"),
    "metric_irrigation": ("Tadla irrigation served", "Irrigation du Tadla servie"),
    "metric_overdraft": ("Aquifer over-pumping", "Surexploitation de la nappe"),
    "metric_kept": ("Upstream water released downstream", "Eau amont lâchée vers l'aval"),
    "no_levers_card": ("Switch on solutions with the sliders above - or press “Try a full package” - and the plan will be built here.",
                       "Activez des solutions avec les curseurs ci-dessus - ou « Essayer un plan complet » - et le plan sera construit ici."),
}


def _t(key: str, **fmt) -> str:
    s = _COPY[key][1 if lang() == "fr" else 0]
    return s.format(**fmt) if fmt else s


def _fmt_metric(value: float, unit: str, decimals: int) -> str:
    if unit == "k":
        return f"{value / 1000:,.0f}k"
    return f"{value:,.{decimals}f} {unit}".replace(" %", "%")


# =========================================================================== payload
def _province_block(res: PlannerResult) -> dict[str, dict]:
    out = {}
    pot = res.monthly.filter(res.monthly["kind"] == "potable")
    for row in res.province.iter_rows(named=True):
        months = pot.filter(pot["demand_id"] == row["demand_id"]).sort("m")["service_ratio"].to_list()
        out[row["province_id"]] = {
            "annual": round(row["hours_per_day"], 2),
            "monthly": [round(24 * r, 2) for r in months],
            "worst": round(row["worst_month_hours"], 1),
            "breakdown": round(row["breakdown_days_exposed"], 1),
            "noTap": round(row["people_no_tap"]),
            "severe": row["people_severe"] > 0,
        }
    return out


def _flows(res: PlannerResult) -> dict[tuple[str, str, str], list[float]]:
    """(source, destination, kind) -> 12 monthly Mm³ for dam and aquifer deliveries."""
    flows: dict[tuple[str, str, str], list[float]] = {}
    province_of = {d.demand_id: d.province_id for d in DEMANDS}
    for row in res.monthly.iter_rows(named=True):
        kind = row["kind"]
        dest = (province_of.get(row["demand_id"]) if kind == "potable"
                else "TADLA" if kind == "irrigation" else "COAST")
        for src in (*BIG_DAMS, "AQUIFER_TADLA"):
            v = float(row.get(f"from_{src}", 0.0) or 0.0)
            key = (src, dest, "potable" if kind == "potable" else "irrigation" if kind == "irrigation" else "export")
            flows.setdefault(key, [0.0] * 12)[int(row["m"])] += v
    return flows


def _local_share(pid: str) -> int:
    d = next(x for x in DEMANDS if x.province_id == pid)
    caps = [(lk.source_id, lk.cap_mm3_yr or 0.0) for lk in d.links if not lk.interconnect]
    total = sum(c for _, c in caps) or 1.0
    return round(100 * sum(c for s, c in caps if s not in BIG_DAMS) / total)


def build_payload(base: PlannerResult, sol: PlannerResult, levers: SolutionLevers, inp: YearInputs,
                  singles: dict[str, PlannerResult]) -> dict:
    fr = lang() == "fr"
    i = 1 if fr else 0
    b, s = base.summary, sol.summary
    pb, ps = _province_block(base), _province_block(sol)
    fb, fs = _flows(base), _flows(sol)
    cap_total = sum(r.capacity_mm3 for r in MODEL_RESERVOIRS)
    start_fill = 100 * b["start_storage"] / cap_total
    inflow_pct = 100 * b["inflow_total"] / INFLOW_NORMAL_MM3
    rain_pct = 100 + b["rain_anomaly_pct"]
    worst = min(pb, key=lambda p: pb[p]["annual"])
    wname = PROVINCES_BY_ID[worst].name_fr if fr else PROVINCES_BY_ID[worst].name_en
    pop = sum(d.population for d in DEMANDS)

    provinces = []
    for feature in province_geojson()["features"]:
        pid = feature["properties"]["province_id"]
        p = PROVINCES_BY_ID[pid]
        provinces.append({
            "id": pid, "name": p.name_fr if fr else p.name_en, "capital": p.capital,
            "lat": p.lat, "lon": p.lon, "geometry": feature["geometry"],
            "population": next(d.population for d in DEMANDS if d.province_id == pid),
            "localShare": _local_share(pid),
            "before": pb[pid], "after": ps[pid],
        })

    reservoirs = []
    for r in MODEL_RESERVOIRS:
        site = NODES_BY_ID[_RESERVOIR_SITE_IDS[r.res_id]]
        sb = base.storage.filter(base.storage["res_id"] == r.res_id).sort("m")
        ss = sol.storage.filter(sol.storage["res_id"] == r.res_id).sort("m")
        start = 100 * sb["storage_start_mm3"][0] / r.capacity_mm3
        reservoirs.append({
            "id": r.res_id, "name": r.name, "lat": site.lat, "lon": site.lon,
            "capacity": r.capacity_mm3, "inRegion": r.res_id != "AL_MASSIRA", "start": round(start, 1),
            "before": [round(v, 1) for v in sb["fill_pct"].to_list()],
            "after": [round(v, 1) for v in ss["fill_pct"].to_list()],
        })

    flows = []
    for key in sorted(set(fb) | set(fs)):
        before, after = fb.get(key, [0.0] * 12), fs.get(key, [0.0] * 12)
        if sum(before) + sum(after) < 1.0:
            continue
        flows.append({"source": key[0], "destination": key[1], "kind": key[2],
                      "before": [round(v, 2) for v in before], "after": [round(v, 2) for v in after]})

    active = []
    for key, spec in LEVERS.items():
        value = getattr(levers, key)
        if value == spec["default"]:
            continue
        vis = _PROJECT_VISUALS[key]
        mkey, mlabel, unit, dec, higher = _PROJECT_METRICS[key]
        single = singles.get(key)
        own = single.summary[mkey] if single else s[mkey]
        active.append({
            "key": key, "icon": spec["icon"], "anchor": vis["anchor"],
            "title": spec["title"][i], "valueLabel": spec["fmt"] % value,
            "component": vis["component"][i], "location": vis["location"][i], "build": vis["build"][i],
            "metric": _t(mlabel),
            "before": _fmt_metric(b[mkey], unit, dec), "own": _fmt_metric(own, unit, dec),
            "package": _fmt_metric(s[mkey], unit, dec),
            "improves": (own > b[mkey]) == higher and abs(own - b[mkey]) > 1e-6,
        })

    month_names = [m[i] for m in MONTH_LABELS]
    rain_monthly = [round(sum(v[m] for v in inp.precip.values()) / max(len(inp.precip), 1), 1) for m in range(12)]

    def stat(label: str, value: str, tone: str = "") -> dict:
        return {"label": label, "value": value, "tone": tone}

    if fr:
        chapters = [
            dict(id="basin", title="Le château d'eau du Maroc",
                 text=f"Cinq provinces, {pop / 1e6:.2f} M d'habitants et trois grands barrages. L'Oum Er-Rbia naît près de Khénifra, "
                      "traverse le Tadla et rejoint Al Massira - puis alimente Casablanca, Marrakech et les Doukkala.",
                 stats=[stat("Habitants", f"{pop / 1e6:.2f} M"), stat("Barrages au 1er sept.", f"{start_fill:.0f} %")]),
            dict(id="drought", title=f"{inp.year} : une année à {rain_pct:.0f} % de la pluie normale",
                 text=f"Les rivières n'ont apporté que {inflow_pct:.0f} % de leur débit normal. Suivez, mois par mois, "
                      "les barrages et l'eau au robinet sans nouvelles solutions.",
                 stats=[stat("Pluie", f"{rain_pct:.0f} %", "warn" if rain_pct < 85 else ""),
                        stat("Apports", f"{inflow_pct:.0f} %", "warn" if inflow_pct < 70 else ""),
                        stat("Barrages au départ", f"{start_fill:.0f} %")]),
            dict(id="who", title=f"{wname} : là où les robinets lâchent en premier",
                 text=f"{wname} ne reçoit que {pb[worst]['annual']:.1f} h d'eau par jour en moyenne, {pb[worst]['worst']:.0f} h au pire mois. "
                      f"{_local_share(worst)} % de son eau vient de sources, puits et prises locales - pas des grands barrages. "
                      f"Les habitants sur une conduite unique perdent en plus {pb[worst]['breakdown']:.1f} jours par an en pannes.",
                 stats=[stat("Eau au robinet", f"{pb[worst]['annual']:.1f} h/j", "warn"),
                        stat("Pire mois", f"{pb[worst]['worst']:.0f} h/j", "warn"),
                        stat("Ressources locales", f"{_local_share(worst)} %")]),
            dict(id="flows", title="Où va l'eau",
                 text=f"Les barrages nourrissent les villes, les fermes du Tadla et l'aval. Cette année, les barrages amont lâchent "
                      f"{b['upstream_to_massira']:,.0f} Mm³ vers Al Massira pour les villes côtières, tandis que la nappe du Tadla est "
                      f"surexploitée de {b['aquifer_overdraft']:,.0f} Mm³.",
                 stats=[stat("Lâchers vers l'aval", f"{b['upstream_to_massira']:,.0f} Mm³"),
                        stat("Irrigation servie", f"{b['irrigation_pct']:.0f} %"),
                        stat("Surexploitation", f"{b['aquifer_overdraft']:,.0f} Mm³", "warn" if b["aquifer_overdraft"] > 1 else "")]),
            dict(id="plan", title=f"Votre plan : {len(active)} solution(s)" if active else "Votre plan",
                 text=("Chaque solution est construite sur la carte : ce qui est bâti, où, et son effet propre." if active
                       else "Aucune solution activée pour l'instant."),
                 stats=[stat("Solutions", str(len(active)))]),
            dict(id="change", title="Ce qui change pour les habitants",
                 text=f"Eau au robinet : {b['avg_hours_per_day']:.1f} → {s['avg_hours_per_day']:.1f} h/jour. "
                      f"Rationnement sévère : {b['people_severe'] / 1e3:,.0f}k → {s['people_severe'] / 1e3:,.0f}k habitants. "
                      f"Pannes : {b['breakdown_days_exposed']:.1f} → {s['breakdown_days_exposed']:.1f} jours/an.",
                 stats=[stat("h/jour", f"{b['avg_hours_per_day']:.1f} → {s['avg_hours_per_day']:.1f}", "good"),
                        stat("Rationnement sévère", f"{b['people_severe'] / 1e3:,.0f}k → {s['people_severe'] / 1e3:,.0f}k", "good"),
                        stat("Sans robinet", f"{b['people_no_tap'] / 1e3:,.0f}k → {s['people_no_tap'] / 1e3:,.0f}k", "good")]),
            dict(id="explore", title="Explorez librement",
                 text="Comparez avant/après, parcourez les mois, survolez les barrages et cliquez une province pour ses chiffres.",
                 stats=[]),
        ]
    else:
        chapters = [
            dict(id="basin", title="Morocco's water tower",
                 text=f"Five provinces, {pop / 1e6:.2f} M people and three big dams. The Oum Er-Rbia rises near Khénifra, "
                      "crosses the Tadla plain and reaches Al Massira - then supplies Casablanca, Marrakech and the Doukkala.",
                 stats=[stat("People", f"{pop / 1e6:.2f} M"), stat("Dams on 1 Sept", f"{start_fill:.0f}%")]),
            dict(id="drought", title=f"{inp.year}: a year with {rain_pct:.0f}% of normal rain",
                 text=f"Rivers carried only {inflow_pct:.0f}% of their normal flow. Watch the dams and the taps month by month, "
                      "with no new solutions.",
                 stats=[stat("Rain", f"{rain_pct:.0f}%", "warn" if rain_pct < 85 else ""),
                        stat("River inflow", f"{inflow_pct:.0f}%", "warn" if inflow_pct < 70 else ""),
                        stat("Dams at start", f"{start_fill:.0f}%")]),
            dict(id="who", title=f"{wname}: where taps run dry first",
                 text=f"{wname} gets only {pb[worst]['annual']:.1f} h of water a day on average, {pb[worst]['worst']:.0f} h in the worst month. "
                      f"{_local_share(worst)}% of its water comes from springs, wells and local intakes - not the big dams. "
                      f"Residents on a single pipeline also lose {pb[worst]['breakdown']:.1f} days a year to breakdowns.",
                 stats=[stat("Tap water", f"{pb[worst]['annual']:.1f} h/day", "warn"),
                        stat("Worst month", f"{pb[worst]['worst']:.0f} h/day", "warn"),
                        stat("Local sources", f"{_local_share(worst)}%")]),
            dict(id="flows", title="Where the water goes",
                 text=f"The dams feed towns, Tadla's farms and the cities downstream. This year upstream dams release "
                      f"{b['upstream_to_massira']:,.0f} Mm³ to Al Massira for the coastal cities, while the Tadla aquifer is "
                      f"over-pumped by {b['aquifer_overdraft']:,.0f} Mm³.",
                 stats=[stat("Released downstream", f"{b['upstream_to_massira']:,.0f} Mm³"),
                        stat("Irrigation served", f"{b['irrigation_pct']:.0f}%"),
                        stat("Over-pumping", f"{b['aquifer_overdraft']:,.0f} Mm³", "warn" if b["aquifer_overdraft"] > 1 else "")]),
            dict(id="plan", title=f"Your plan: {len(active)} solution(s)" if active else "Your plan",
                 text=("Each solution is built on the map: what gets built, where, and its own effect." if active
                       else "No solutions switched on yet."),
                 stats=[stat("Solutions", str(len(active)))]),
            dict(id="change", title="What changes for people",
                 text=f"Tap water: {b['avg_hours_per_day']:.1f} → {s['avg_hours_per_day']:.1f} h/day. "
                      f"Severe rationing: {b['people_severe'] / 1e3:,.0f}k → {s['people_severe'] / 1e3:,.0f}k residents. "
                      f"Breakdowns: {b['breakdown_days_exposed']:.1f} → {s['breakdown_days_exposed']:.1f} days/yr.",
                 stats=[stat("h/day", f"{b['avg_hours_per_day']:.1f} → {s['avg_hours_per_day']:.1f}", "good"),
                        stat("Severe rationing", f"{b['people_severe'] / 1e3:,.0f}k → {s['people_severe'] / 1e3:,.0f}k", "good"),
                        stat("Without a tap", f"{b['people_no_tap'] / 1e3:,.0f}k → {s['people_no_tap'] / 1e3:,.0f}k", "good")]),
            dict(id="explore", title="Explore freely",
                 text="Compare before and after, scrub through the months, hover the dams and click a province for its numbers.",
                 stats=[]),
        ]

    if not active:  # nothing to compare yet: invite the reader instead of showing "22 → 22"
        change = next(c for c in chapters if c["id"] == "change")
        change["text"] = _t("no_levers_card")
        change["stats"] = []

    payload = {
        "lang": lang(),
        "copy": {k: _t(k) for k in _COPY},
        "months": month_names,
        "rainMonthly": rain_monthly,
        "worst": worst,
        "tadla": {"lon": TADLA_CENTER[0], "lat": TADLA_CENTER[1]},
        "coast": {"lon": COAST[0], "lat": COAST[1]},
        "rivers": [[list(p) for p in pts] for pts in RIVERS.values()],
        "cities": [{"id": p.province_id, "lat": p.lat, "lon": p.lon} for p in PROVINCES],
        "provinces": provinces,
        "reservoirs": reservoirs,
        "flows": flows,
        "levers": active,
        "chapters": chapters,
    }
    payload["hash"] = hashlib.sha1(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
    return payload


# =========================================================================== component
def _asset_signature() -> str:
    return "|".join(f"{p.name}:{p.stat().st_mtime_ns}" for p in sorted(ASSET_DIR.iterdir()) if p.is_file())


@st.cache_resource(show_spinner=False)
def _component(signature: str):
    """Registered once per version of the html/css/js files (signature = their mtimes), so
    edits to the story assets are picked up without restarting the server."""
    return st.components.v2.component(
        "atlas_basin_story",
        html=(ASSET_DIR / "story.html").read_text(encoding="utf-8"),
        css=(ASSET_DIR / "story.css").read_text(encoding="utf-8"),
        js=(ASSET_DIR / "story.js").read_text(encoding="utf-8"),
    )


def render(base: PlannerResult, sol: PlannerResult, levers: SolutionLevers, inp: YearInputs,
           singles: dict[str, PlannerResult]) -> None:
    _component(_asset_signature())(data=build_payload(base, sol, levers, inp, singles),
                                   key="atlas_basin_story", height=700)
