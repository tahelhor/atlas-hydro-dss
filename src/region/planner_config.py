"""Parameters of the 12-month regional planner, with their provenance.

Tags in comments:
  [S<n>]   figure taken from knowledge-base source S<n> (data/reference/bmk_knowledge_base.json)
  [calc]   derived from sourced figures (formula given)
  [assume] modelling assumption - order of magnitude, editable here
"""

from __future__ import annotations

from dataclasses import dataclass, field

MONTH_DAYS = [30, 31, 30, 31, 31, 28, 31, 30, 31, 30, 31, 31]  # Sep … Aug
MONTH_LABELS = [("Sep", "sept"), ("Oct", "oct"), ("Nov", "nov"), ("Dec", "déc"), ("Jan", "janv"),
                ("Feb", "févr"), ("Mar", "mars"), ("Apr", "avr"), ("May", "mai"), ("Jun", "juin"),
                ("Jul", "juil"), ("Aug", "août")]
# summer peak of household demand [assume]: sums to 12
POTABLE_MONTHLY_FACTOR = [1.05, 0.95, 0.88, 0.85, 0.85, 0.87, 0.92, 0.98, 1.06, 1.18, 1.23, 1.18]


@dataclass(frozen=True)
class Link:
    demand_id: str
    source_id: str
    cap_mm3_yr: float | None = None  # production / conveyance capacity; None = unlimited
    interconnect: bool = False  # capacity added by the interconnection lever
    share: float = 0.0  # share of the interconnection lever allocated to this link


@dataclass(frozen=True)
class PotableDemand:
    demand_id: str
    province_id: str
    population: int  # RGPH 2024 municipal population
    urban_pop: int
    rural_pop: int
    urban_tap_pct: float  # households with running water (HCP "eau courante")
    rural_tap_pct: float
    lpcd: float  # litres / person / day delivered (blended urban + rural)
    network_efficiency: float  # billed / produced
    links: tuple[Link, ...]
    # infrastructure fragility (breakdowns, turbidity shutdowns) [assume, calibrated on documented events]
    exposed_share: float  # population depending on a single long pipeline / single plant
    outage_events_yr: float
    outage_hours: float  # mean duration of a major outage
    autonomy_hours: float  # current storage autonomy of town reservoirs


@dataclass(frozen=True)
class IrrigationPerimeter:
    demand_id: str
    name: str
    area_ha: float
    efficiency_surface: float
    efficiency_drip: float
    kc: tuple[float, ...]  # composite crop coefficient Sep … Aug
    climate_province: str
    links: tuple[Link, ...]


@dataclass(frozen=True)
class Export:
    demand_id: str
    name_en: str
    name_fr: str
    annual_mm3: float
    monthly_profile: tuple[float, ...]
    desal_substitutable: bool
    links: tuple[Link, ...]


@dataclass(frozen=True)
class Reservoir:
    res_id: str
    name: str
    capacity_mm3: float
    dead_mm3: float
    area_full_km2: float
    eco_mm3_yr: float
    carryover_pct: float
    upstream: tuple[str, ...]
    climate_province: str


@dataclass(frozen=True)
class Aquifer:
    source_id: str
    recharge_mm3_yr: float
    max_overdraft_mm3_yr: float
    max_pumping_mm3_yr: float  # installed well capacity
    climate_province: str


@dataclass(frozen=True)
class Spring:
    source_id: str
    province_id: str
    normal_mm3_yr: float
    elasticity: float


@dataclass(frozen=True)
class Weights:
    use: dict = field(default_factory=lambda: {
        "potable": 10.0, "export_potable": 10.0, "irrigation": 5.0, "export_irrigation": 5.0})
    # extra cost beyond the tranche share: spreads cuts instead of concentrating them
    deep_extra: dict = field(default_factory=lambda: {
        "potable": 4.0, "export_potable": 4.0, "irrigation": 2.5, "export_irrigation": 2.5})
    # share of demand that can be cut at the base weight before the deep-cut extra applies
    tranche_share: dict = field(default_factory=lambda: {
        "potable": 0.15, "export_potable": 0.15, "irrigation": 0.5, "export_irrigation": 0.5})
    ecological: float = 8.0
    overdraft: float = 3.0  # < irrigation: farmers over-pump when surface water fails (observed)
    carryover: float = 1.0  # end-of-year reserve target (hedging for next year)
    release: float = 0.001


WEIGHTS = Weights()


# =========================================================================== calibration
# GloFAS inflows are rescaled so that the 1998-2018 mean of the 3-dam system matches the
# basin's reported normal inflow of ~3,054 Mm³/yr [S8]. GloFAS under-estimates dry years
# (2022: 441 vs ~773 Mm³ reported [S8]); the rescaling brings drought years close to reports.
INFLOW_NORMAL_MM3 = 3054.0
INFLOW_REF_YEARS = (1998, 2018)
# ONEE sales ≈ 70-90 m³/yr per domestic subscriber ≈ 50-75 l/person/day [S105][calc]
URBAN_LPCD = 85.0
CONNECTED_RURAL_LPCD = 45.0  # [assume]
UNCONNECTED_LPCD = 20.0  # standpipes / wells / tankers [assume]
# billed / distributed 67-70% in 2020 (Khouribga, Azilal, Khénifra, RADEET) [S105][calc];
# RADEET 63% in 2009 [S90]; 30-40% of drinking water lost nationally [S89]
NETWORK_EFFICIENCY = 0.68


def production_need(urban: int, rural: int, rural_tap: float, efficiency: float = NETWORK_EFFICIENCY) -> float:
    """Mm³/yr at source for a province, from its population and tap access."""
    lpd = urban * URBAN_LPCD + rural * (rural_tap * CONNECTED_RURAL_LPCD + (1 - rural_tap) * UNCONNECTED_LPCD)
    return lpd * 365 / 1e9 / efficiency


def _province(pid: str, urban: int, rural: int, urban_tap: float, rural_tap: float,
              shares: dict[str, float], margin: float, interconnect_from: str,
              interconnect_share: float, exposed: float, events: float, hours: float,
              autonomy: float) -> PotableDemand:
    pop = urban + rural
    need = production_need(urban, rural, rural_tap)
    links = tuple(
        Link(f"POT_{pid}", src, cap_mm3_yr=round(need * margin * share, 2))
        for src, share in shares.items()
    ) + (Link(f"POT_{pid}", interconnect_from, cap_mm3_yr=0.0, interconnect=True,
              share=interconnect_share),)
    lpcd = need * NETWORK_EFFICIENCY * 1e9 / 365 / pop
    return PotableDemand(f"POT_{pid}", pid, pop, urban, rural, urban_tap, rural_tap, lpcd,
                         NETWORK_EFFICIENCY, links, exposed, events, hours, autonomy)


# =========================================================================== potable demand
# Population: RGPH 2024 municipal population & running-water shares [S25-S29].
# Source shares (rounded from ONEE 2020 production by source [S105] and system descriptions):
# Béni Mellal - Afourar/Bin El Ouidane ≈263 l/s, Aïn Asserdoun spring ≈126 l/s, Sidi Jaber
# boreholes [S104][S106][S32]; Fquih Ben Salah - Ouled Abdellah boreholes ≈300 l/s, Afourar
# for Souk Sebt / Oulad Ayad since 2023 [S48][S114]; Khouribga - Maroc-central plant at Aït
# Messaoud (Ahmed El Hansali) via an 80 km main + Fquih Ben Salah groundwater [S104][S51];
# Khénifra - ≈80% Oum Er-Rbia river via the Khénifra plant (420 l/s, reverse osmosis) [S108];
# Azilal - Hassan Iᵉʳ dam plant (Lakhdar basin) for Azilal & Demnate + springs/wells [S107].
# Outage parameters are [assume], calibrated on documented events 2020-2026 (S32, S34, S44,
# S45, S48, S51, S52, S61): exposed share = population on a single plant / long pipeline.
DEMANDS: tuple[PotableDemand, ...] = (
    _province("KHENIFRA", 242_376, 125_587, 0.982, 0.184,
              {"RIVER_KHENIFRA": 0.80, "SPRING_KHENIFRA": 0.20}, 1.08,
              "HANSALI", 0.40, exposed=0.35, events=1.5, hours=96, autonomy=8),
    _province("BENI_MELLAL", 349_406, 226_860, 0.971, 0.784,
              {"BIN_EL_OUIDANE": 0.45, "SPRING_BENI_MELLAL": 0.30, "AQUIFER_TADLA": 0.25}, 1.15,
              "BIN_EL_OUIDANE", 0.15, exposed=0.65, events=0.5, hours=96, autonomy=8),
    _province("AZILAL", 112_340, 460_527, 0.966, 0.833,
              {"LOCAL_HASSAN_I": 0.45, "SPRING_AZILAL": 0.55}, 1.08,
              "BIN_EL_OUIDANE", 0.35, exposed=0.30, events=1.0, hours=72, autonomy=6),
    _province("FQUIH_BEN_SALAH", 202_010, 273_083, 0.960, 0.813,
              {"AQUIFER_TADLA": 0.60, "BIN_EL_OUIDANE": 0.40}, 1.15,
              "BIN_EL_OUIDANE", 0.05, exposed=0.40, events=0.7, hours=96, autonomy=8),
    _province("KHOURIBGA", 368_429, 150_181, 0.951, 0.136,
              {"HANSALI": 0.65, "AQUIFER_TADLA": 0.35}, 1.12,
              "HANSALI", 0.05, exposed=0.80, events=1.0, hours=60, autonomy=8),
)

# Local sources: normal yield = the capacity their link was sized for. Drought response:
# karst springs & shallow wells dry up faster than rain falls (elasticity 1.6); the Hassan Iᵉʳ
# dam buffers part of it (0.8); the Oum Er-Rbia at Khénifra is fed by large karst springs
# (≈9 m³/s, S113) that GloFAS cannot resolve, so it is modelled as a well-buffered local
# source (0.5) [assume]. Elasticity applies to the 2-year rain factor.
LOCAL_ELASTICITY = {"LOCAL_HASSAN_I": 0.8, "RIVER_KHENIFRA": 0.5}
SPRINGS: tuple[Spring, ...] = tuple(
    Spring(lk.source_id, d.province_id, lk.cap_mm3_yr, LOCAL_ELASTICITY.get(lk.source_id, 1.6))
    for d in DEMANDS for lk in d.links if lk.source_id.startswith(("SPRING_", "LOCAL_", "RIVER_"))
)

# =========================================================================== irrigation
# Béni Amir 27,300 ha [S112] (design 420 Mm³/yr) and Béni Moussa 69,600 ha [S73][S112]
# (design 710-720 Mm³/yr) [S71]. Surface efficiency 50% → 90% target with modern systems [S73]; Tadla field
# evidence shows little net saving from drip (rebound) [S87][S88], so the effective drip
# efficiency used is 75% [assume]. Kc: composite cereals/beet/olive/citrus/alfalfa [assume].
_KC = (0.55, 0.45, 0.50, 0.55, 0.65, 0.80, 0.95, 1.00, 0.90, 0.75, 0.70, 0.60)
IRRIGATION: tuple[IrrigationPerimeter, ...] = (
    IrrigationPerimeter("IRR_BENI_AMIR", "Béni Amir", 27_300, 0.55, 0.75, _KC, "FQUIH_BEN_SALAH", (
        Link("IRR_BENI_AMIR", "HANSALI", cap_mm3_yr=420.0),
        Link("IRR_BENI_AMIR", "AQUIFER_TADLA"),
        Link("IRR_BENI_AMIR", "REUSE"),
    )),
    IrrigationPerimeter("IRR_BENI_MOUSSA", "Béni Moussa", 69_600, 0.62, 0.75, _KC, "BENI_MELLAL", (
        Link("IRR_BENI_MOUSSA", "BIN_EL_OUIDANE", cap_mm3_yr=720.0),
        Link("IRR_BENI_MOUSSA", "AQUIFER_TADLA"),
        Link("IRR_BENI_MOUSSA", "REUSE"),
    )),
)

# =========================================================================== exports (Al Massira)
# Marrakech pipeline 216,000 m³/day ≈ 79 Mm³/yr [S16][calc]; Casablanca drew 109 Mm³ from
# the Oum Er-Rbia in 2021 [S109] (Al Massira supplies ≈300 Mm³/yr to cities [S110]);
# Doukkala irrigation (~100 kha) ≈ 450 Mm³/yr in a normal year [assume; 277 Mm³ allotted for
# the rest of 2025-26, S21]. Desalination (Casablanca, 200 → 300 Mm³/yr incl. 50 Mm³ for
# agriculture [S13][S14]) can substitute Casablanca's drinking water and up to 50 Mm³ of
# irrigation. Not modelled: Bin El Ouidane water to the Tassaout (Haouz) via canal T2 [S113].
_FLAT = tuple(d / 365 for d in MONTH_DAYS)
_IRR_PROFILE = tuple(k / sum(_KC) for k in _KC)
EXPORTS: tuple[Export, ...] = (
    Export("EXP_POT_MARRAKECH", "Marrakech (pipeline)", "Marrakech (conduite)", 79.0, _FLAT, False,
           (Link("EXP_POT_MARRAKECH", "AL_MASSIRA"),)),
    Export("EXP_POT_CASABLANCA", "Casablanca-Settat-Berrechid", "Casablanca-Settat-Berrechid", 109.0,
           _FLAT, True, (Link("EXP_POT_CASABLANCA", "AL_MASSIRA"),)),
    Export("EXP_IRR_DOUKKALA", "Doukkala irrigation", "Irrigation des Doukkala", 450.0, _IRR_PROFILE,
           True, (Link("EXP_IRR_DOUKKALA", "AL_MASSIRA"),)),
)
DESAL_IRRIGATION_CAP_MM3 = 50.0  # agricultural share of the Casablanca plant [S13]

# =========================================================================== reservoirs & aquifer
# Capacities: Ministry figures of 1 Sept 2026 [S2]. Areas, ecological flows and carry-over
# targets [assume].
RESERVOIRS: tuple[Reservoir, ...] = (
    Reservoir("HANSALI", "Ahmed El Hansali", 697.18, 35.0, 27.0, 47.0, 30.0, (), "BENI_MELLAL"),
    Reservoir("BIN_EL_OUIDANE", "Bin El Ouidane", 1273.40, 64.0, 38.0, 32.0, 30.0, (), "AZILAL"),
    Reservoir("AL_MASSIRA", "Al Massira", 2649.54, 132.0, 120.0, 95.0, 20.0,
              ("HANSALI", "BIN_EL_OUIDANE"), "KHOURIBGA"),
)
# Tadla aquifer system: ~8,300 wells supplying ~300 Mm³/yr (>50% of irrigation) [S72];
# mobilisable groundwater 440 Mm³/yr (190 Béni Amir, 250 Béni Moussa) [S113]; falling water
# tables [S79][S86]; basin-wide overdraft ~300 Mm³/yr [S12]. Normal-year renewable recharge
# (between observed pumping-with-decline and "mobilisable") and the overdraft ceiling [assume].
AQUIFER = Aquifer("AQUIFER_TADLA", recharge_mm3_yr=330.0, max_overdraft_mm3_yr=200.0,
                  max_pumping_mm3_yr=380.0,
                  climate_province="FQUIH_BEN_SALAH")

# =========================================================================== levers
LEVER_GROUPS = {
    "potable": ("💧 Drinking water", "💧 Eau potable"),
    "agri": ("🌾 Agriculture & groundwater", "🌾 Agriculture & nappes"),
    "basin": ("🌊 Basin allocation", "🌊 Répartition du bassin"),
}
LEVERS: dict[str, dict] = {
    "leak_reduction_pts": dict(
        group="potable", icon="🔧", min=0, max=20, step=1, default=0, fmt="+%d pts",
        title=("Fix leaks (network efficiency)", "Réparer les fuites (rendement)"),
        help=("Raise network efficiency from ~68% today (30-40% of drinking water is lost). "
              "ONEE targeted 80%.",
              "Porter le rendement d'environ 68 % aujourd'hui (30-40 % de l'eau potable perdue). "
              "L'ONEE visait 80 %.")),
    "storage_autonomy_h": dict(
        group="potable", icon="🛢️", min=0, max=40, step=4, default=0, fmt="+%d h",
        title=("Town storage tanks (hours of autonomy)", "Réservoirs urbains (heures d'autonomie)"),
        help=("Extra hours of demand stored in town reservoirs - short breakdowns become "
              "invisible. RADEET targets 24 h per centre.",
              "Heures de demande stockées en plus - les pannes courtes deviennent invisibles. "
              "La RADEET vise 24 h d'autonomie par centre.")),
    "backup_source_pct": dict(
        group="potable", icon="🔀", min=0, max=100, step=10, default=0, fmt="%d%%",
        title=("Second source for single-pipeline towns", "Seconde source pour les villes à conduite unique"),
        help=("Share of people on a single plant / pipeline that get a backup "
              "(second main, borehole field, interconnection).",
              "Part des habitants dépendant d'une seule station / conduite qui obtiennent un "
              "secours (seconde conduite, forages, interconnexion).")),
    "rural_connection_pct": dict(
        group="potable", icon="🏘️", min=0, max=100, step=10, default=0, fmt="%d%%",
        title=("Connect unserved rural homes", "Raccorder les foyers ruraux non desservis"),
        help=("Share of rural households without running water that get a tap (PNAEPI / SRM). "
              "More taps also means more water to find.",
              "Part des ménages ruraux sans eau courante raccordés (PNAEPI / SRM). Plus de "
              "robinets, c'est aussi plus d'eau à trouver.")),
    "interconnection_mm3": dict(
        group="potable", icon="🚰", min=0, max=30, step=2, default=0, fmt="%d Mm³",
        title=("Dam water for spring-dependent towns", "Eau des barrages pour les villes sur sources"),
        help=("New pipelines from dam treatment plants to towns relying on springs, wells and "
              "the river (Khénifra, Azilal, Béni Mellal…), Mm³/yr.",
              "Nouvelles conduites des stations de barrage vers les villes dépendant de sources, "
              "puits et du fleuve (Khénifra, Azilal, Béni Mellal…), Mm³/an.")),
    "demand_saving_pct": dict(
        group="potable", icon="🚿", min=0, max=20, step=1, default=0, fmt="%d%%",
        title=("Household water saving", "Économies domestiques"),
        help=("Tariffs closer to cost (≈15 DH/m³ cost vs 2.5-3 DH billed), awareness, "
              "efficient fixtures.",
              "Tarifs plus proches du coût (≈15 DH/m³ contre 2,5-3 DH facturés), sensibilisation, "
              "équipements économes.")),
    "drip_conversion_pct": dict(
        group="agri", icon="💧", min=0, max=100, step=10, default=0, fmt="%d%%",
        title=("Convert remaining flood irrigation to drip", "Convertir l'irrigation gravitaire restante"),
        help=("Share of the still flood-irrigated Tadla area converted. Effective efficiency "
              "capped at 75% because savings are often re-spent (rebound effect).",
              "Part de la surface encore gravitaire convertie. Efficience effective plafonnée à "
              "75 % car les économies sont souvent réutilisées (effet rebond).")),
    "reuse_mm3": dict(
        group="agri", icon="♻️", min=0, max=40, step=2, default=0, fmt="%d Mm³",
        title=("Treated wastewater for farms", "Eaux usées traitées pour l'agriculture"),
        help=("Mm³/yr of treated wastewater for Tadla irrigation (regional plants produce "
              "~16.7 Mm³/yr, today sent to OCP).",
              "Mm³/an d'eaux usées traitées pour l'irrigation du Tadla (~16,7 Mm³/an produits, "
              "aujourd'hui destinés à l'OCP).")),
    "groundwater_cap_pct": dict(
        group="agri", icon="⛔", min=0, max=100, step=10, default=100, fmt="%d%%",
        title=("Allowed aquifer over-pumping (aquifer contract)", "Surexploitation tolérée (contrat de nappe)"),
        help=("100% = today's unregulated pumping. Lower values enforce an aquifer contract: "
              "less over-pumping, more irrigation cuts.",
              "100 % = pompage actuel non régulé. En dessous : contrat de nappe, moins de "
              "surexploitation mais plus de restrictions d'irrigation.")),
    "desal_mm3": dict(
        group="basin", icon="🌊", min=0, max=160, step=10, default=0, fmt="%d Mm³",
        title=("Casablanca desalination replaces Al Massira water",
               "Le dessalement de Casablanca remplace l'eau d'Al Massira"),
        help=("Mm³/yr of downstream demand (Casablanca drinking water, then up to 50 Mm³ of "
              "Doukkala irrigation) met by desalination, so less upstream water is released.",
              "Mm³/an de demande aval (eau potable de Casablanca, puis jusqu'à 50 Mm³ "
              "d'irrigation des Doukkala) couverts par le dessalement : moins de lâchers amont.")),
}

# =========================================================================== presets
# Starting dam levels (% of capacity: Hansali, Bin El Ouidane, Massira) on or near 1 Sept.
PRESETS: dict[str, dict] = {
    "today_drought": dict(
        year=2022, fill=(79.7, 82.9, 40.2),
        label=("🔮 Today's dams + a 2022-type drought", "🔮 Barrages actuels + sécheresse type 2022"),
        note=("Dam levels of 1 Sept 2026 [S2], climate of 2021-22", "Niveaux du 1er sept. 2026 [S2], climat de 2021-22")),
    "drought_2022": dict(
        year=2022, fill=(26.2, 31.6, 11.9),
        label=("🔥 Relive 2021-22", "🔥 Revivre 2021-22"),
        note=("Dam levels of late June 2021 [S69]", "Niveaux de fin juin 2021 [S69]")),
    "drought_2024": dict(
        year=2024, fill=(15.5, 11.2, 3.0),
        label=("🔥 Relive 2023-24", "🔥 Revivre 2023-24"),
        note=("Dam levels of Jan 2023 [S70] / Oct 2023 [S5]", "Niveaux de janv. 2023 [S70] / oct. 2023 [S5]")),
    "wet_2026": dict(
        year=2026, fill=(12.0, 10.0, 3.4),
        label=("🌧️ The 2025-26 recovery", "🌧️ La reprise de 2025-26"),
        note=("Approximate levels of summer 2025 [S3][S4]", "Niveaux approximatifs de l'été 2025 [S3][S4]")),
}

ASSUMPTIONS_MD = (
    "**What the model does.** A linear program (PuLP + HiGHS) allocates water month by month "
    "over one hydrological year (Sept → Aug) across the 3 dams, the Tadla aquifer, springs, the "
    "Khénifra river intake and treated wastewater. Priorities: drinking water (weight 10, cuts "
    "spread across provinces), ecological flow (8), irrigation (5, rationed before being cut); "
    "aquifer over-pumping is penalised (3). It is solved twice: business as usual and with your "
    "solutions.\n\n"
    "**Two causes of cuts.** *Drought rationing* comes from the optimisation: not enough water at "
    "the source. *Breakdown cuts* come from fragile infrastructure: towns on one plant or one long "
    "pipeline lose water for days when it fails (mud after storms, leaks, pumps). Storage tanks and "
    "second sources reduce them - which is why cuts happen even in a wet year, as in summer 2026.\n\n"
    "**Data.** Real monthly river flows (GloFAS v4, rescaled to the basin's reported normal inflow "
    "of 3,054 Mm³/yr), rain and evapotranspiration (ERA5) for the replayed year; population and tap "
    "access from the 2024 census; dam capacities from 2026 ministry figures.\n\n"
    "**Limits.** A decision-support sketch, not an operational model. Supply shares, outage rates, "
    "aquifer recharge and some export volumes are documented assumptions "
    "(`src/region/planner_config.py`). Same-month routing. 'Hours of water per day' is an "
    "equivalent of the share of demand served.",
    "**Ce que fait le modèle.** Un programme linéaire (PuLP + HiGHS) répartit l'eau mois par mois "
    "sur une année hydrologique (sept. → août) entre les 3 barrages, la nappe du Tadla, les "
    "sources, la prise d'eau de Khénifra et les eaux usées traitées. Priorités : eau potable "
    "(poids 10, coupures réparties entre provinces), débit écologique (8), irrigation (5, "
    "rationnée avant d'être coupée) ; la surexploitation de la nappe est pénalisée (3). Il est "
    "résolu deux fois : statu quo et avec vos solutions.\n\n"
    "**Deux causes de coupures.** Le *rationnement de sécheresse* vient de l'optimisation : pas "
    "assez d'eau à la source. Les *coupures de panne* viennent d'infrastructures fragiles : les "
    "villes dépendant d'une seule station ou conduite perdent l'eau pendant des jours en cas "
    "d'incident (boue après orage, fuite, pompe). Réservoirs et secondes sources les réduisent - "
    "d'où des coupures même en année humide, comme à l'été 2026.\n\n"
    "**Données.** Débits mensuels réels (GloFAS v4, recalés sur l'apport normal publié du bassin, "
    "3 054 Mm³/an), pluie et évapotranspiration (ERA5) de l'année rejouée ; population et accès au "
    "robinet du RGPH 2024 ; capacités des barrages : chiffres 2026 du ministère.\n\n"
    "**Limites.** Outil d'aide à la décision, pas un modèle opérationnel. Parts de sources, taux de "
    "panne, recharge de la nappe et certains transferts sont des hypothèses documentées "
    "(`src/region/planner_config.py`). Routage dans le mois. Les « heures d'eau par jour » "
    "équivalent à la part de la demande servie.",
)
