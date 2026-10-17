# Water stress in Béni Mellal–Khénifra: diagnosis and solution assessment

*Atlas Hydro-DSS analytical report · Taha EL HOR · data as of 17 October 2026*

---

## Executive summary

- **The 2018–2025 drought was amplified by heat.** Over the six consecutive drought years 2020–2025, regional rainfall was **22%** below the 1998–2018 reference. River inflow to Al Massira was **63%** below it, almost three times larger. Temperatures were **+2.0 °C** and Atlas snowfall **−70%**. In 2023-24 the basin's dams fell to **4.4%** of capacity and Al Massira to **0.4%**, its lowest level since 1979.
- **The burden falls on the mountain provinces and on rural households.** Replaying a 2021-22-type year, Azilal averages **18.1 h/day** of running water (**14.5 h** in July) and Khénifra **21.5 h** (**17.6 h**). The Tadla plain stays near 23–24 h. In the 2024 census, only **18.4%** of rural households in Khénifra and **13.6%** in Khouribga had running water.
- **Full dams do not protect everyone.** With today's dam levels (≈58%) instead of 2021's (≈20%), a 2022-type drought leaves drinking water in the mountain provinces **unchanged**: their towns rely on springs, wells and local intakes, not the large dams. Separately, residents served by a single plant or long pipeline lose **2.5 days a year** to breakdowns (Khénifra: **5.5**), which is why multi-day cuts continued in summer 2026 despite the wet winter.
- **The most effective drinking-water measure is structural.** Piping **12 Mm³/yr** of dam water to spring-dependent towns removes severe rationing for **~941,000 residents** on its own. Leak reduction (+12 points of network efficiency) and household savings (−8%) add about **+1.2** and **+0.7 h/day** of tap service respectively.
- **A combined package of 10 measures** restores **24 h/day** in every province even in a 2021-22-type year. It also gives **205,000** more residents a tap at home and cuts breakdown days by **32%** and aquifer over-pumping by **21%**.
- **Desalination on the coast does not, by itself, help the region in a drought year.** Upstream releases are already at the ecological minimum, so the freed water stays downstream unless allocation rules change.

## 1. Context

The Béni Mellal–Khénifra region (5 provinces, **2.51 M** inhabitants, RGPH 2024) is the source region of the **Oum Er-Rbia**. Its three large dams are Ahmed El Hansali (697 Mm³), Bin El Ouidane (1,273 Mm³) and Al Massira (2,650 Mm³), which lies downstream and outside the region.

The basin supplies drinking water to about 10 million people, including Casablanca, Marrakech and the coastal cities, and irrigates more than 335,000 ha. That includes the **Tadla** perimeter (Béni Amir 27,300 ha and Béni Moussa 69,600 ha). Average renewable resources (≈3.3 bn m³/yr) are below total use (≥3.66 bn m³), and the basin's aquifers are over-drawn by ≈300 Mm³/yr [S12].

The 2025-26 winter brought **+42%** inflows over normal and ended the drought (the basin was at **58.3%** on 12 Oct 2026). Al Massira, however, stalled near **40%** [S1][S2][S22].

## 2. Method

| Component | Data & approach |
|---|---|
| Climate diagnosis | ERA5 reanalysis (1991–2026) at the 5 provincial capitals; GloFAS v4 river discharge (1997–2026); anomalies by hydrological year (Sept–Aug) vs. 1998–2018 |
| Live situation | GloFAS v4 ensemble forecast (30 days, p25–p75) + ECMWF / FAO-56 ET0, refreshed on demand; Pydantic-validated, stored in DuckDB |
| Evidence base | 114 dated sources (HCP, ministry, ONEE, ABHOER, DGM, World Bank, academic papers, national and local press), compiled into a schema-validated, bilingual knowledge base |
| Solution assessment | 12-month linear program (PuLP + HiGHS) allocating water monthly across dams, the Tadla aquifer, springs, the Khénifra intake and reused wastewater. It covers 5 provincial drinking-water demands, Tadla irrigation (FAO-56 crop demand) and downstream exports, with priorities drinking water > ecological flow > irrigation. Solved once without and once with 10 solution levers. Breakdown cuts are modelled separately from drought rationing |

GloFAS inflows are rescaled so that the 1998–2018 mean matches the basin's reported normal inflow of 3,054 Mm³/yr [S8]. Parameters that are assumptions are tagged `[assume]` in `src/region/planner_config.py`.

## 3. Findings

### 3.1 A heat-amplified drought

| Hydrological year | Rainfall | River inflow (Al Massira) | Mean temperature | Atlas snowfall |
|---|---|---|---|---|
| 2020–2025 average | **−22%** | **−63%** | **+2.0 °C** | **−70%** |
| 2021-22 | −29% | −78% | +2.0 °C | −79% |
| 2023-24 | −44% | −75% | +2.3 °C | −99% |
| 2025-26 (recovery) | +39% | +149% | +1.5 °C | +79% |

*Anomalies vs. the 1998–2018 mean (ERA5, GloFAS v4).*

Warmer air raises evaporative demand (ET0 **+11%**), the snowpack that normally releases water in spring disappears, and dry soils absorb rain before it reaches rivers. This matches the official figures for 2023-24: rainfall −44.6% gave dam inflows −76% [S10][S11]. Climate projections point the same way: Oum Er-Rbia flows fall 16–44% by 2100, and snow water in the High Atlas falls 60–85% [S18][S19].

### 3.2 Who is affected, and how

**Drinking water.** Documented events include:
- night-time rationing in Béni Mellal (June 2022) [S30];
- a 50–65% supply loss for ≈4 days when storm mud stopped the Afourar plant (Sept 2024) [S32][S34];
- up to **6 days** without water in Moulay Bouazza in summer 2026 [S44];
- repeated cuts in Khouribga and Oued Zem (2020, 2023, 2025) [S51][S52][S53];
- recurring cuts in Demnate [S42].

In mountain douars, villagers walk up to **8 km** to a single private well [S37], and 2025–2026 saw thirst marches and sit-ins [S38][S40][S41].

**Agriculture.**
- **Irrigation cut:** Béni Amir irrigation was halted from October 2021, and Tadla received only **56 Mm³** from the dams in 2023-24 against a design allocation of ≈1,130 Mm³ [S76][S77].
- **Harvests:** olive output fell from ≈120,000 t to 44,000 t, citrus area shrank 15%, and sugar beet fell to 7,204 ha [S78][S84][S82].
- **Groundwater:** about 8,300 wells now supply over half of Tadla's irrigation, and water tables are falling [S72][S79].

**Modelled drinking-water service, 2021-22-type year, no new measures:**

| Province | Population | Avg tap service | Worst month | Breakdown days/yr* | Local-source share |
|---|---|---|---|---|---|
| Azilal | 572,867 | **18.1 h/day** | **14.5 h** | 2.8 | 100% |
| Khénifra | 367,963 | **21.5 h/day** | **17.6 h** | **5.5** | 100% |
| Béni Mellal | 576,266 | 23.3 h/day | 21.0 h | 1.8 | 55% |
| Khouribga | 518,610 | 23.5 h/day | 21.9 h | 2.2 | 35% |
| Fquih Ben Salah | 475,093 | 23.7 h/day | 22.4 h | 2.6 | 60% |

*\*For residents served by a single plant or long pipeline.*

### 3.3 Root causes

1. **Climate:** less rain, more evaporation, disappearing snow (§3.1).
2. **Over-use:** demand exceeds renewable resources, and aquifers are mined. Drip-irrigation savings have often been re-spent on denser or thirstier crops, a rebound effect documented in Tadla [S87][S88].
3. **Fragile infrastructure.** Single sources serve whole towns: Afourar supplies ≈⅔ of Béni Mellal, and Khouribga and Moulay Bouazza hang on 80–85 km pipelines [S32][S45][S51]. Town storage covers less than a day, 30–40% of drinking water is lost in networks [S89], and rural networks were never built.
4. **Allocation & governance.** In droughts, upstream dams release water to Al Massira for the coastal cities: 100 Mm³ in 2022 and 323 Mm³ in 2026 from Ahmed El Hansali [S76][S80]. Water is priced far below its delivery cost (≈15 DH/m³ vs 2.5–3 DH/m³ billed) [S98], and a regional operator (SRM) has been in transition since 2025 [S56].

### 3.4 Scenario results: without measures vs. full package

The full package is: leak reduction +12 pts, +24 h of town storage, a backup source for 60% of single-source residents, 50% of unserved rural homes connected, 12 Mm³ of dam interconnection, 8% household savings, 60% drip conversion, 16 Mm³ of wastewater reuse, a 50% cap on aquifer over-pumping, and 150 Mm³ of coastal desalination.

| Scenario (climate year · dam levels on 1 Sept) | Avg tap h/day | Residents under severe rationing¹ | Breakdown days² | Residents without a tap | Tadla irrigation served | Aquifer over-pumping |
|---|---|---|---|---|---|---|
| 2021-22 climate · **today's dams** (80/83/40%) | 22.0 → **24.0** | 941k → **0** | 2.5 → **1.7** | 454k → **249k** | 76% → **86%** | 126 → **100 Mm³** |
| 2021-22 climate · 2021 dams (26/32/12%) | 22.0 → **24.0** | 941k → **0** | 2.5 → **1.7** | 454k → **249k** | 58% → **67%** | 126 → **100 Mm³** |
| 2023-24 climate · 2023 dams (16/11/3%) | 21.2 → **23.9** | 941k → **0** | 2.5 → **1.7** | 454k → **249k** | 39% → **40%** | 200 → **100 Mm³** |
| 2025-26 climate (recovery) | 23.5 → **24.0** | 0 → 0 | 2.5 → **1.7** | 454k → **249k** | 75% → **88%** | 0 → 0 |

¹ At least one month below 18 h/day. ² Per resident on a single plant or pipeline.

**Reading:** dam levels decide how much water Tadla's farms get, but **not** whether mountain towns have water. Both 2021-22 rows show identical drinking-water results despite very different reservoir levels.

### 3.5 What each measure achieves on its own

*Measured in a 2021-22-type year starting from today's dam levels, one measure at a time.*

| Measure | Own effect | Cost · time |
|---|---|---|
| 🚰 Dam water for spring-dependent towns (12 Mm³/yr) | **+1.6 h/day** average; severe rationing **−941k** residents | high · structural |
| 🔧 Leak repair & pressure management (+12 pts efficiency) | **+1.2 h/day**; severe rationing −368k (Khénifra) | medium · 1–3 yrs |
| 🚿 Household savings & tariffs (−8%) | +0.7 h/day; severe rationing −368k | low · quick |
| 🛢️ Town storage (+24 h autonomy) | Breakdown days −0.9 per exposed resident (−34%) | medium · quick |
| 🔀 Second source for single-pipeline towns (60%) | ≈770,000 fewer residents exposed to single-point failures | high · 1–3 yrs |
| 🏘️ Connect unserved rural homes (50%) | **−205,000** residents without a tap; −0.35 h/day average, because more demand goes onto the same sources | high · structural |
| 💧 Drip conversion of remaining flood irrigation (60%) | Tadla irrigation served **+9.9 pts** (efficiency capped at 75% for rebound) | medium · 1–3 yrs |
| ♻️ Treated wastewater to farms (16 Mm³) | Irrigation +0.7 pts | high · quick |
| 📜 Aquifer contract (over-pumping capped at 50%) | Over-pumping **−26 Mm³/yr**, at −1.6 pts of irrigation | low · 1–3 yrs |
| 🌊 Coastal desalination replacing Al Massira water (150 Mm³) | **No regional effect in a drought year**; small reduction in upstream releases in wet years | high · structural |

## 4. Recommendations

1. **Connect spring-dependent towns to dam water first**, Khénifra and Azilal above all. In the model it is the only single measure that removes severe rationing. Double the new mains, or pair them with storage, so they don't become new single points of failure.
2. **Run leak reduction, 24-hour storage and backup sources together.** They are cheaper and faster, and they target the breakdown cuts that persist even in wet years.
3. **Connect rural homes, and secure the supply behind them.** Each new tap adds demand onto the same springs and wells, so connections must come with new supply.
4. **In agriculture, pair drip conversion with an aquifer contract.** Drip without pumping limits re-spends the savings, and limits without drip cut harvests.
5. **Write the upstream share of freed water into allocation rules.** Coastal desalination (Casablanca, Feb 2027) and the planned Sebou→Al Massira link (≈800 Mm³/yr) only help the region if the rules governing upstream releases change.
6. **Publish operational data:** network efficiency, outage logs and well registers. Several key parameters in this study had to be assumed because they are not public.

## 5. Limitations

- **This is decision support, not an operational forecast.** Supply shares, outage rates, aquifer recharge and some export volumes are documented assumptions.
- **GloFAS is a modelled product.** It needed grid-cell snapping and a rescaling to reported inflows, and it cannot resolve the karst springs at Khénifra.
- **"Hours of water per day"** is an equivalent of the share of demand served, not a measured schedule. Breakdown cuts are an expected-value model calibrated on documented events (2020–2026).
- **Same-month routing** between reservoirs, and perfect foresight of the replayed year.
- **Stress scores and problem severities** are an editorial synthesis of cited evidence.

## Key references

The full list of 114 sources is in `data/reference/bmk_knowledge_base.json` and on the dashboard's *Data QA & sources* tab.

- [S1] Le Matin, *Barrages au Maroc : les dernières pluies reboostent les réserves*, 12 Oct 2026 · [S2] Le360, *Summer chips away at dam recovery*, 2 Sept 2026
- [S10] DGM, *État du climat au Maroc 2024* · [S11] Hespress, *Déficit de précipitations de 44,6% dans le bassin de l'Oum Er-Rbia*, Feb 2025
- [S12] Le360, *Oum Er-Rbia : voyage au cœur d'un fleuve clé*, Apr 2026 · [S18] Tuel et al., HESS preprint, 2020
- [S27] [S29] HCP, RGPH 2024 provincial indicators · [S32] Aujourd'hui le Maroc, interview with RADEET's director general, Sept 2024
- [S44] Hespress, *Six days without water in Moulay Bouazza*, Aug 2026 · [S51] Hespress, *Khouribga et Oued Zem : coupures d'eau*, Aug 2025
- [S72] Hammani et al., *Cahiers Agricultures* (Tadla wells) · [S76] Médias24, emergency drinking-water plan, Mar 2022 · [S77] Médias24, agricultural water in Béni Mellal-Khénifra, Dec 2023
- [S87] Boularbah et al., *Irrigation & Drainage*, 2019 · [S88] Molle & Tanouti, *Agricultural Water Management*, 2017 · [S89] TelQuel, minister Baraka on network losses, Jun 2026

---

*© 2026 Taha EL HOR. This report is licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).*
