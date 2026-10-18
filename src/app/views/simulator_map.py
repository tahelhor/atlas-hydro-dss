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
    "backup_source_pct": ("people_exposed", "metric_exposed", "k", 0, False),
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
    "metric_exposed": ("Residents on a single plant or pipeline", "Habitants sur une seule station ou conduite"),
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

    chapters = _chapters(fr, inp, base, sol, pb, ps, active, singles, month_names)

    payload = {
        "lang": lang(),
        "copy": {k: _t(k) for k in _COPY},
        "months": month_names,
        "rainMonthly": rain_monthly,
        "worst": worst,
        "replayYear": inp.year,  # hydrological year ending in August
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


# =========================================================================== chapter copy
# Every sentence is chosen from the scenario's own numbers: a wet year is not told as a drought,
# an unchanged metric is not shown as a gain, and trade-offs are named.
_YEAR_CLASS = (  # (rain % of normal upper bound, EN, FR)
    (75, "a severe drought year", "une année de sécheresse sévère"),
    (90, "a dry year", "une année sèche"),
    (110, "a near-normal year", "une année proche de la normale"),
    (float("inf"), "a wet year", "une année humide"),
)
_MONTHS_FULL = (("September", "septembre"), ("October", "octobre"), ("November", "novembre"), ("December", "décembre"),
                ("January", "janvier"), ("February", "février"), ("March", "mars"), ("April", "avril"), ("May", "mai"),
                ("June", "juin"), ("July", "juillet"), ("August", "août"))  # hydrological year order
FRAGILE_H = 22.5  # no severe rationing and at least this many h/day = "fragile", not "running dry"
EPS_H = 0.05  # h/day: smaller differences are "no change"
EPS_PEOPLE = 500


def _k(people: float) -> str:
    return "0" if people < EPS_PEOPLE else f"{people / 1e3:,.0f}k"


def _arrow_tone(before: float, after: float, higher_is_better: bool, eps: float) -> str:
    if abs(after - before) <= eps:
        return ""
    return "good" if (after > before) == higher_is_better else "warn"


def _join(items: list[str], fr: bool) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + (" et " if fr else " and ") + items[-1]


def _chapters(fr: bool, inp: YearInputs, base: PlannerResult, sol: PlannerResult, pb: dict, ps: dict,
              active: list[dict], singles: dict[str, PlannerResult], month_names: list[str]) -> list[dict]:
    def t(en: str, fr_: str) -> str:
        return fr_ if fr else en

    def stat(label: str, value: str, tone: str = "") -> dict:
        return {"label": label, "value": value, "tone": tone}

    def pname(pid: str) -> str:
        return PROVINCES_BY_ID[pid].name_fr if fr else PROVINCES_BY_ID[pid].name_en

    b, s = base.summary, sol.summary
    pop = sum(d.population for d in DEMANDS)
    start_fill = 100 * b["start_storage"] / sum(r.capacity_mm3 for r in MODEL_RESERVOIRS)
    end_fill = b["end_fill_pct"]
    rain = 100 + b["rain_anomaly_pct"]
    inflow = 100 * b["inflow_total"] / INFLOW_NORMAL_MM3
    dry = rain < 90
    _, label_en, label_fr = next(c for c in _YEAR_CLASS if rain < c[0])
    year_label = f"{inp.year - 1}-{inp.year % 100:02d}"  # hydrological year Sept -> Aug

    # ------------------------------------------------------------ 1 the basin
    basin = dict(id="basin", title=t("Morocco's water tower", "Le château d'eau du Maroc"),
                 text=t(f"Five provinces, {pop / 1e6:.2f} M people and three big dams. The Oum Er-Rbia rises near Khénifra, "
                        "crosses the Tadla plain and reaches Al Massira, which also supplies Casablanca, Marrakech and the Doukkala.",
                        f"Cinq provinces, {pop / 1e6:.2f} M d'habitants et trois grands barrages. L'Oum Er-Rbia naît près de Khénifra, "
                        "traverse la plaine du Tadla et rejoint Al Massira, qui alimente aussi Casablanca, Marrakech et les Doukkala."),
                 stats=[stat(t("People", "Habitants"), f"{pop / 1e6:.2f} M"),
                        stat(t("Dams on 1 Sept", "Barrages au 1er sept."), f"{start_fill:.0f}%", "warn" if start_fill < 30 else "")])

    # ------------------------------------------------------------ 2 the replayed year
    if inflow < 100 and inflow < rain - 10:
        flow = t(f"Rain reached {rain:.0f}% of normal, but rivers carried only {inflow:.0f}%: heat, dry soils and missing "
                 f"snow turned a {100 - rain:.0f}% rain deficit into a {100 - inflow:.0f}% river deficit.",
                 f"La pluie a atteint {rain:.0f} % de la normale, mais les rivières seulement {inflow:.0f} % : chaleur, sols secs "
                 f"et neige absente ont transformé un déficit de pluie de {100 - rain:.0f} % en déficit d'écoulement de {100 - inflow:.0f} %.")
    elif inflow < 100:
        flow = t(f"Rain reached {rain:.0f}% of normal and rivers carried {inflow:.0f}% of their normal flow.",
                 f"La pluie a atteint {rain:.0f} % de la normale et les rivières {inflow:.0f} % de leur débit normal.")
    else:
        flow = t(f"Rain reached {rain:.0f}% of normal and rivers ran at {inflow:.0f}% of their normal flow.",
                 f"La pluie a atteint {rain:.0f} % de la normale et les rivières ont coulé à {inflow:.0f} % de leur débit normal.")
    if end_fill < start_fill - 3:
        dams = t(f"Without new solutions, the dams fall from {start_fill:.0f}% to {end_fill:.0f}% by the end of August",
                 f"Sans nouvelles solutions, les barrages passent de {start_fill:.0f} % à {end_fill:.0f} % fin août")
        dams += t(", close to empty." if end_fill < 15 else ".", ", presque vides." if end_fill < 15 else ".")
    elif end_fill > start_fill + 3:
        dams = t(f"The dams refill from {start_fill:.0f}% to {end_fill:.0f}% by the end of August.",
                 f"Les barrages remontent de {start_fill:.0f} % à {end_fill:.0f} % fin août.")
    else:
        dams = t(f"The dams hold at about {end_fill:.0f}% over the year.",
                 f"Les barrages se maintiennent autour de {end_fill:.0f} % sur l'année.")
    year = dict(id="drought", title=year_label + t(": ", " : ") + t(label_en, label_fr),
                text=f"{flow} {dams} " + t("Press play to follow it month by month.", "Lancez la lecture pour suivre l'année mois par mois."),
                stats=[stat(t("Rain", "Pluie"), f"{rain:.0f}%", "warn" if rain < 85 else ""),
                       stat(t("River inflow", "Apports"), f"{inflow:.0f}%", "warn" if inflow < 70 else ""),
                       stat(t("Dams, Sept → Aug", "Barrages, sept. → août"), f"{start_fill:.0f} → {end_fill:.0f}%",
                            _arrow_tone(start_fill, end_fill, True, 3))])

    # ------------------------------------------------------------ 3 who runs short first
    worst = min(pb, key=lambda p: pb[p]["annual"])
    w, wn = pb[worst], pname(worst)
    wm = min(range(12), key=lambda m: w["monthly"][m])
    month, month_short = _MONTHS_FULL[wm][1 if fr else 0], month_names[wm]
    share = _local_share(worst)
    if not w["severe"] and w["annual"] >= FRAGILE_H:
        who_title = t(f"{wn}: the most fragile", f"{wn} : la plus fragile")
        who = t(f"No province falls into severe rationing this year, but {wn} stays the most fragile: "
                f"{w['annual']:.1f} h of water a day on average, {w['worst']:.1f} h in {month}.",
                f"Aucune province ne tombe en rationnement sévère cette année, mais {wn} reste la plus fragile : "
                f"{w['annual']:.1f} h d'eau par jour en moyenne, {w['worst']:.1f} h en {month}.")
    else:
        who_title = t(f"{wn}: where taps run dry first", f"{wn} : là où les robinets lâchent en premier")
        who = t(f"{wn} gets {w['annual']:.1f} h of water a day on average, and only {w['worst']:.1f} h in {month}.",
                f"{wn} reçoit {w['annual']:.1f} h d'eau par jour en moyenne, et seulement {w['worst']:.1f} h en {month}.")
    if share >= 80:
        who += t(f" {share}% of its water comes from springs, wells and local intakes, not the big dams, so dam levels barely change its supply.",
                 f" {share} % de son eau vient de sources, puits et prises locales, pas des grands barrages : leur niveau change peu son approvisionnement.")
    elif share >= 50:
        who += t(f" {share}% of its water comes from local springs, wells and intakes; the rest comes from the dams.",
                 f" {share} % de son eau vient de sources, puits et prises locales ; le reste vient des barrages.")
    else:
        who += t(f" {100 - share}% of its water comes from the dams, so dam levels matter here.",
                 f" {100 - share} % de son eau vient des barrages : leur niveau compte ici.")
    if w["worst"] < 22.5 and not dry:
        who += t(f" Even in a {'wet' if rain > 110 else 'normal'} year, the {month} demand peak exceeds what its sources and plants can deliver.",
                 f" Même en année {'humide' if rain > 110 else 'normale'}, la pointe de {month} dépasse ce que ses ressources et stations peuvent fournir.")
    if w["breakdown"] >= 0.5:
        who += t(f" Residents on a single plant or pipeline also lose about {w['breakdown']:.1f} days a year to breakdowns.",
                 f" Les habitants dépendant d'une seule station ou conduite perdent aussi environ {w['breakdown']:.1f} jours par an en pannes.")
    who_ch = dict(id="who", title=who_title, text=who,
                  stats=[stat(t("Tap water", "Eau au robinet"), f"{w['annual']:.1f} " + t("h/day", "h/j"), "warn" if w["annual"] < 22 else ""),
                         stat(t(f"Worst month ({month_short})", f"Pire mois ({month_short})"), f"{w['worst']:.1f} " + t("h/day", "h/j"),
                              "warn" if w["worst"] < 20 else ""),
                         stat(t("Local sources", "Ressources locales"), f"{share}%")])

    # ------------------------------------------------------------ 4 where the water goes
    rel, irr, od = b["upstream_to_massira"], b["irrigation_pct"], b["aquifer_overdraft"]
    flows = t("The dams feed towns, Tadla's farms and the cities downstream.",
              "Les barrages alimentent les villes, les fermes du Tadla et l'aval.")
    if rel > 1:
        flows += (t(f" Even in {label_en}, the upstream dams release {rel:,.0f} Mm³ to Al Massira, which supplies the coastal cities.",
                    f" Même en {label_fr.removeprefix('une ')}, les barrages amont lâchent {rel:,.0f} Mm³ vers Al Massira, qui alimente les villes côtières.")
                  if dry else
                  t(f" The upstream dams pass {rel:,.0f} Mm³ down to Al Massira and the coastal cities.",
                    f" Les barrages amont lâchent {rel:,.0f} Mm³ vers Al Massira et les villes côtières."))
    if irr < 60:
        flows += t(f" Tadla's farms get only {irr:.0f}% of their irrigation water: agriculture is cut first to protect drinking water.",
                   f" Les fermes du Tadla ne reçoivent que {irr:.0f} % de leur eau d'irrigation : l'agriculture est coupée en premier pour protéger l'eau potable.")
    elif irr < 90:
        flows += t(f" Tadla's farms get {irr:.0f}% of their irrigation water.",
                   f" Les fermes du Tadla reçoivent {irr:.0f} % de leur eau d'irrigation.")
    else:
        flows += t(f" Tadla's farms get almost all their irrigation water ({irr:.0f}%).",
                   f" Les fermes du Tadla reçoivent presque toute leur eau d'irrigation ({irr:.0f} %).")
    flows += (t(f" The Tadla aquifer is pumped {od:,.0f} Mm³ beyond its recharge.",
                f" La nappe du Tadla est pompée {od:,.0f} Mm³ au-delà de sa recharge.") if od > 1 else
              t(" Pumping stays within the aquifer's recharge this year.",
                " Le pompage reste dans la limite de la recharge de la nappe cette année."))
    flows_ch = dict(id="flows", title=t("Where the water goes", "Où va l'eau"), text=flows,
                    stats=[stat(t("Released downstream", "Lâchers vers l'aval"), f"{rel:,.0f} Mm³"),
                           stat(t("Irrigation served", "Irrigation servie"), f"{irr:.0f}%", "warn" if irr < 70 else ""),
                           stat(t("Over-pumping", "Surexploitation"), f"{od:,.0f} Mm³", "warn" if od > 1 else "")])

    # ------------------------------------------------------------ 5 the plan
    n = len(active)
    if not n:
        plan_ch = dict(id="plan", title=t("Your plan", "Votre plan"),
                       text=t("No solutions switched on yet. Use the sliders above, or try a full package.",
                              "Aucune solution activée pour l'instant. Utilisez les curseurs ci-dessus ou essayez un plan complet."),
                       stats=[stat("Solutions", "0")])
    else:
        working = [a for a in active if a["improves"]]
        idle = [a["title"].split(" (")[0] for a in active if not a["improves"]]
        gains = {a["key"]: round(singles[a["key"]].summary["avg_hours_per_day"], 1) - round(b["avg_hours_per_day"], 1)
                 for a in active if a["key"] in singles}
        best = max(gains, key=gains.get) if gains else None
        plan = t("Each solution is built on the map, with its own effect when used alone.",
                 "Chaque solution est construite sur la carte, avec son effet propre lorsqu'elle est seule.")
        if best and gains[best] > EPS_H:
            title = next(a["title"] for a in active if a["key"] == best).split(" (")[0]
            plan += t(f" Biggest gain in tap water on its own: {title} (+{gains[best]:.1f} h/day).",
                      f" Plus grand gain d'eau au robinet à elle seule : {title} (+{gains[best]:.1f} h/jour).")
        elif gains:
            plan += (t(" It doesn't add tap-water hours on its own this year.",
                       " Elle n'ajoute pas d'heures d'eau au robinet cette année.") if n == 1 else
                     t(" None of them adds tap-water hours on its own this year.",
                       " Aucune n'ajoute à elle seule d'heures d'eau au robinet cette année."))
        if idle:
            if n > 1:
                plan += t(f" No measurable effect alone this year: {_join(idle, False)}.",
                          f" Sans effet mesurable seule cette année : {_join(idle, True)}.")
            else:
                plan += t(" On its own it has no measurable effect this year.",
                          " Seule, elle n'a pas d'effet mesurable cette année.")
        plural = "s" if n > 1 else ""
        plan_ch = dict(id="plan", title=t(f"Your plan: {n} solution{plural}", f"Votre plan : {n} solution{plural}"),
                       text=plan,
                       stats=[stat("Solutions", str(n)),
                              stat(t("Work on their own", "Efficaces seules"), f"{len(working)}/{n}",
                                   "good" if len(working) == n else "warn" if not working else "")])

    # ------------------------------------------------------------ 6 what changes for people
    if not n:
        change_ch = dict(id="change", title=t("What changes for people", "Ce qui change pour les habitants"),
                         text=_t("no_levers_card"), stats=[])
    else:
        hb, hs = round(b["avg_hours_per_day"], 1), round(s["avg_hours_per_day"], 1)  # compare what is displayed
        parts = []
        if all(ps[p]["annual"] >= 23.9 for p in ps):
            parts.append(t(f"Every province now gets close to 24 h of water a day (regional average {hb:.1f} → {hs:.1f} h).",
                           f"Toutes les provinces reçoivent désormais près de 24 h d'eau par jour (moyenne régionale {hb:.1f} → {hs:.1f} h)."))
        elif hs > hb + EPS_H:
            wa = min(ps, key=lambda p: ps[p]["annual"])
            parts.append(t(f"Tap water rises from {hb:.1f} to {hs:.1f} h/day on average; {pname(wa)} still has the least ({ps[wa]['annual']:.1f} h).",
                           f"L'eau au robinet passe de {hb:.1f} à {hs:.1f} h/jour en moyenne ; {pname(wa)} reste la moins servie ({ps[wa]['annual']:.1f} h)."))
        elif hs < hb - EPS_H:
            parts.append(t(f"Tap water falls from {hb:.1f} to {hs:.1f} h/day on average.",
                           f"L'eau au robinet baisse de {hb:.1f} à {hs:.1f} h/jour en moyenne."))
        else:
            parts.append(t(f"Tap water doesn't change ({hs:.1f} h/day on average).",
                           f"L'eau au robinet ne change pas ({hs:.1f} h/jour en moyenne)."))
        losers = [pname(p) for p in ps if round(ps[p]["annual"], 1) < round(pb[p]["annual"], 1)]
        if losers:
            if any(a["key"] == "rural_connection_pct" for a in active):
                parts.append(t(f"Trade-off: new rural connections draw on the same springs and wells, so hours fall in {_join(losers, False)}.",
                               f"Contrepartie : les nouveaux branchements ruraux puisent dans les mêmes sources et puits, et les heures baissent à {_join(losers, True)}."))
            else:
                parts.append(t(f"Hours fall in {_join(losers, False)}.", f"Les heures baissent à {_join(losers, True)}."))
        sev_b, sev_s = b["people_severe"], s["people_severe"]
        if sev_b < EPS_PEOPLE and sev_s < EPS_PEOPLE:
            parts.append(t("No one faces severe rationing, with or without the plan.",
                           "Personne ne subit de rationnement sévère, avec ou sans plan."))
        elif sev_s < sev_b - EPS_PEOPLE:
            parts.append(t(f"{_k(sev_b - sev_s)} fewer residents face severe rationing (a month below 18 h/day).",
                           f"{_k(sev_b - sev_s)} habitants de moins subissent un rationnement sévère (un mois sous 18 h/jour)."))
        elif sev_s > sev_b + EPS_PEOPLE:
            parts.append(t(f"{_k(sev_s - sev_b)} more residents face severe rationing.",
                           f"{_k(sev_s - sev_b)} habitants de plus subissent un rationnement sévère."))
        else:
            parts.append(t(f"{_k(sev_s)} residents still face severe rationing in at least one month.",
                           f"{_k(sev_s)} habitants subissent encore un rationnement sévère au moins un mois."))
        homes = []  # who gains a tap / a second source, in one sentence
        if s["people_no_tap"] < b["people_no_tap"] - EPS_PEOPLE:
            homes.append(t(f"{_k(b['people_no_tap'] - s['people_no_tap'])} more residents get a tap at home",
                           f"{_k(b['people_no_tap'] - s['people_no_tap'])} habitants de plus ont un robinet chez eux"))
        if s["people_exposed"] < b["people_exposed"] - EPS_PEOPLE:
            homes.append(t(f"{_k(b['people_exposed'] - s['people_exposed'])} fewer depend on a single plant or pipeline",
                           f"{_k(b['people_exposed'] - s['people_exposed'])} de moins dépendent d'une seule station ou conduite"))
        if homes:
            sentence = _join(homes, fr)
            parts.append(sentence[0].upper() + sentence[1:] + ".")
        also = []  # secondary effects, compressed into one line
        if s["breakdown_days_exposed"] < b["breakdown_days_exposed"] - 0.05:
            also.append(t(f"breakdown cuts {b['breakdown_days_exposed']:.1f} → {s['breakdown_days_exposed']:.1f} days/yr",
                          f"pannes {b['breakdown_days_exposed']:.1f} → {s['breakdown_days_exposed']:.1f} jours/an"))
        if abs(s["irrigation_pct"] - b["irrigation_pct"]) >= 1:
            also.append(t(f"Tadla irrigation {b['irrigation_pct']:.0f}% → {s['irrigation_pct']:.0f}%",
                          f"irrigation du Tadla {b['irrigation_pct']:.0f} % → {s['irrigation_pct']:.0f} %"))
        if abs(s["aquifer_overdraft"] - b["aquifer_overdraft"]) >= 1:
            also.append(t(f"aquifer over-pumping {b['aquifer_overdraft']:,.0f} → {s['aquifer_overdraft']:,.0f} Mm³",
                          f"surexploitation de la nappe {b['aquifer_overdraft']:,.0f} → {s['aquifer_overdraft']:,.0f} Mm³"))
        if also:
            parts.append(t("Also: ", "Aussi : ") + ", ".join(also) + ".")
        kept = b["upstream_to_massira"] - s["upstream_to_massira"]
        if kept >= 1 and abs(hs - hb) <= EPS_H:
            parts.append(t(f"The upstream dams keep {kept:,.0f} Mm³ instead of releasing it downstream, but the towns that run short "
                           "don't draw on those dams, so their taps don't change.",
                           f"Les barrages amont gardent {kept:,.0f} Mm³ au lieu de les lâcher vers l'aval, mais les villes en manque "
                           "ne puisent pas dans ces barrages : leurs robinets ne changent pas."))
        change_ch = dict(
            id="change", title=t("What changes for people", "Ce qui change pour les habitants"), text=" ".join(parts),
            stats=[stat(t("h/day", "h/jour"), f"{hb:.1f} → {hs:.1f}", _arrow_tone(hb, hs, True, EPS_H)),
                   stat(t("Severe rationing", "Rationnement sévère"), f"{_k(sev_b)} → {_k(sev_s)}",
                        _arrow_tone(sev_b, sev_s, False, EPS_PEOPLE)),
                   stat(t("Without a tap", "Sans robinet"), f"{_k(b['people_no_tap'])} → {_k(s['people_no_tap'])}",
                        _arrow_tone(b["people_no_tap"], s["people_no_tap"], False, EPS_PEOPLE))])

    explore = dict(id="explore", title=t("Explore freely", "Explorez librement"),
                   text=t("Compare before and after, scrub through the months, hover the dams and click a province for its numbers.",
                          "Comparez avant/après, parcourez les mois, survolez les barrages et cliquez une province pour ses chiffres."),
                   stats=[])
    return [basin, year, who_ch, flows_ch, plan_ch, change_ch, explore]


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
