# 💧 Atlas Hydro-DSS: water stress in Béni Mellal–Khénifra, Morocco

**A decision-support system that explains why taps run dry in the Oum Er-Rbia basin, who is affected, and what each solution would change.**
It takes live satellite and reanalysis data, checks every record, and runs two optimisation models. Everything is shown in a bilingual (EN/FR) dashboard, including an animated 3D story of the basin.

![Python](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-1.66-FF4B4B?logo=streamlit&logoColor=white)
![PuLP / HiGHS](https://img.shields.io/badge/optimisation-PuLP%20%2B%20HiGHS-2a78d6)
![DuckDB](https://img.shields.io/badge/warehouse-DuckDB-FFF000?logo=duckdb&logoColor=black)
![Tests](https://img.shields.io/badge/tests-205%20passing-0ca30c)
![Data](https://img.shields.io/badge/data-Copernicus%20%C2%B7%20ECMWF%20%C2%B7%20HCP-6da7ec)
![License](https://img.shields.io/badge/license-MIT-8d8a84)

![The basin story: the 2022 drought replayed month by month](docs/screenshots/06_story_drought_year.png)

> 📄 **Full analysis:** [docs/REPORT.md](docs/REPORT.md). It covers the diagnosis, the scenario results, the effect of each solution, and recommendations.

---

## Why this project

From 2018 to 2025 Morocco went through seven dry years. The Oum Er-Rbia basin fell to **4.4%** of its dam capacity (Sept 2024), and Al Massira, the country's second-largest dam, to **0.4%**.

In the region that feeds this river, people faced:
- night-time rationing;
- six-day outages;
- villages supplied by tanker trucks;
- farmers whose wells went from 20 m to 40 m deep.

The rains of winter 2025-26 refilled the dams, **yet multi-day cuts still happened in summer 2026.** This project uses data to answer three questions:

1. **What are citizens and farmers actually facing?** 18 documented problems, 6 citizen testimonies and an impact map, all sourced.
2. **Why?** Reanalysis data shows that the 2020–2025 drought cut rainfall by **22%** but river inflow by **63%**. The cause is **+2.0 °C** of warming and **70%** less snow, made worse by over-pumped aquifers and towns that depend on a single plant or pipeline.
3. **What would each solution change?** A 12-month optimisation model replays a real drought year with and without 10 solution levers. It reports the result in **hours of running water per day** for each province.

## Key findings

| | |
|---|---|
| 🌡️ **A heat-amplified drought** | 2020–2025: rain −22%, river inflow −63% (×2.9), +2.0 °C, snow −70% (ERA5 + GloFAS, vs 1998–2018) |
| 🏔️ **The mountains are hit first** | In a 2022-type year, **Azilal gets 18 h/day** (14.5 h in July) and **Khénifra 21.5 h** (17.6 h). Both rely almost entirely on springs, wells and local intakes |
| 🔗 **Fragile infrastructure, not only drought** | Residents on single pipelines lose **2.5 days/yr** to breakdowns (Khénifra: 5.5). This is why cuts continue even with full dams |
| 🚰 **The most effective solution** | **12 Mm³/yr of dam water piped to spring-dependent towns** removes severe rationing for **941,000 people** on its own |
| 📦 **A full package** | 24 h/day of water in every province, 205,000 more residents with a tap at home, breakdown days −32%, aquifer over-pumping −21% |

## Screenshots

| | |
|---|---|
| ![Crisis overview](docs/screenshots/01_crisis_overview.png) **Water crisis:** live KPIs, provincial stress map, profiles | ![Citizen problems](docs/screenshots/02_citizen_problems.png) **What citizens face:** sourced problem cards |
| ![Root causes](docs/screenshots/03_root_causes_evidence.png) **Why:** rain vs river flow, warming stripes, snow, and causes | ![Solutions matrix](docs/screenshots/04_solutions_matrix.png) **What can be done:** impact × time-to-deliver |
| ![Simulator](docs/screenshots/05_simulator_controls.png) **Solutions simulator:** real drought years, dam levels, 10 levers | ![Who runs dry](docs/screenshots/07_story_who_runs_dry.png) **3D story · who runs dry first** |
| ![Where the water goes](docs/screenshots/08_story_where_water_goes.png) **3D story · where the water goes** | ![Your plan](docs/screenshots/09_story_your_plan.png) **3D story · your plan:** what gets built, where, and its own effect |
| ![What changes](docs/screenshots/10_story_what_changes.png) **3D story · what changes for people** | ![Results](docs/screenshots/11_simulator_results.png) **Results:** hours/day, breakdowns, monthly calendar, water balance |
| ![30-day operations](docs/screenshots/12_operations_30_day.png) **30-day operations:** live reservoir allocation LP | ![Hydrograph](docs/screenshots/13_hydrograph_forecast.png) **Hydrograph:** GloFAS 30-day ensemble forecast |
| ![Data quality](docs/screenshots/14_data_quality.png) **Data QA & sources:** validation, freshness, 114 sources | ![French](docs/screenshots/15_french_version.png) **Bilingual:** the full interface in French |

## What's inside

**Data pipeline**
- **Async ingestion** (`httpx`) of the Copernicus GloFAS v4 ensemble discharge forecast and ECMWF weather and FAO-56 evapotranspiration for 4 river nodes, plus 35 years of ERA5 climate and 30 years of GloFAS river-flow history.
- **QA gates:** every API payload and every row passes strict Pydantic v2 models covering physical bounds, unit conversions, ensemble ordering and date windows. Failing rows are quarantined with the reason and every run is logged.
- **DuckDB warehouse** with idempotent upserts. All processing is in **Polars**; there is no pandas.
- **Knowledge base** (`data/reference/bmk_knowledge_base.json`): 114 dated sources, and 18 problems, 15 root causes and 14 solutions, all bilingual. It is validated like API data: no statement may lack a source.

**Models**
- **30-day reservoir model** (PuLP + HiGHS): mass balance across the dam cascade, a priority-weighted allocation (drinking water > ecological flow > irrigation), and a safety buffer.
- **12-month regional planner** (PuLP + HiGHS). It replays a real hydrological year (rain, heat and river flows from the archive) across:
  - 3 dams, the Tadla aquifer, springs, the Khénifra river intake and treated wastewater;
  - 5 provincial drinking-water demands;
  - Tadla irrigation;
  - exports downstream to Casablanca, Marrakech and Doukkala.

  It reports two separate causes of cuts: **drought rationing** (from the optimisation) and **breakdown cuts** (single plants or pipelines, which storage and backup sources reduce). It then solves again with the user's 10 solution levers.

**Dashboard (Streamlit + Plotly + Three.js)**
- **Five tabs:** water crisis, solutions simulator, 30-day operations, hydrograph & forecast, data QA & sources.
- **Bilingual EN/FR**, dark mode, colour-blind-safe palettes, and a red → grey → blue diverging scale for tap hours.
- **A 7-chapter animated 3D story:** basin → drought month by month → who runs dry → where the water goes → your plan → what changes → explore. It is a Streamlit components v2 element that stays mounted and **animates to new results instead of reloading**.
- **Responsive:** the simulator is an `st.fragment` and LP solves are cached per scenario. A slider step is about 0.5 s server-side, and month and before/after changes are instant because they run in the browser.

## Architecture

```mermaid
flowchart LR
    A[Open-Meteo GloFAS v4<br/>flood API] -->|async httpx| C{Pydantic<br/>QA gates}
    B[Open-Meteo ECMWF<br/>& ERA5 archive] -->|async httpx| C
    K[Knowledge base<br/>114 sourced facts] -->|schema-validated| W
    C -->|clean rows| W[(DuckDB<br/>warehouse)]
    C -->|rejects| Q[(qa_rejections)]
    W --> O[30-day reservoir LP<br/>PuLP + HiGHS]
    W --> R[12-month regional planner<br/>PuLP + HiGHS]
    O --> D[Streamlit dashboard<br/>EN / FR]
    R --> D
    R --> S[3D basin story<br/>Three.js component]
    S --> D
```

## Quick start

Requires [uv](https://docs.astral.sh/uv/). Python 3.12 is installed automatically.

```bash
git clone https://github.com/tahelhor/atlas-hydro-dss.git
cd atlas-hydro-dss
uv sync
uv run python -m src.ingestion.fetch_hydro_climate      # live 122-day window   (~5 s)
uv run python -m src.ingestion.fetch_climate_history    # 1991 → today archive (~30 s)
uv run pytest                                           # 205 tests
uv run streamlit run src/app/dashboard.py               # http://localhost:8501
```

No API key is needed. The 3D story loads Three.js from jsDelivr, so it needs an internet connection; the charts work offline.

## Project structure

```
src/
├── config.py                       basin nodes, 2026 dam capacities, API contracts
├── warehouse.py                    read-only DuckDB access (polars)
├── ingestion/
│   ├── fetch_hydro_climate.py      GloFAS + ECMWF live window → fact_hydro_daily
│   ├── fetch_climate_history.py    ERA5 + GloFAS archive → monthly facts
│   └── validator.py                Pydantic payload contracts & row gate
├── models/
│   ├── water_optimizer.py          30-day reservoir allocation LP
│   └── regional_planner.py         12-month drought stress-test & solutions LP
├── region/
│   ├── provinces.py · knowledge.py · diagnostics.py
│   └── planner_config.py           every parameter with its provenance tag [S#] / [assume]
└── app/
    ├── dashboard.py · ui.py · i18n.py
    └── views/  crisis · simulator · simulator_map + basin_story/ (3D) · operations · hydrology · qa
data/reference/                     province boundaries (geoBoundaries) · knowledge base (JSON)
docs/                               REPORT.md · screenshots · original project brief
tests/                              205 tests (pipeline QA, both LPs, knowledge base, dashboard, 3D story)
```

## Testing

There are 205 tests (`uv run pytest`). They cover:
- **API contracts and physical bounds:** NaN, negative values, inverted ensembles, unit conversion.
- **Pipeline behaviour:** retries, idempotent upserts and quarantine.
- **Model correctness:** mass balance on every day and month, cascade routing, capacities, the aquifer budget and priority ordering.
- **Solution levers:** each lever must move its metric in the right direction.
- **Knowledge base:** source integrity and bilingual completeness.
- **Headless dashboard runs:** both languages, presets and the full package.
- **3D story:** the data it receives and a performance budget.

## Data sources & licences

| Source | Use | Licence |
|---|---|---|
| [Open-Meteo](https://open-meteo.com/) Flood API (Copernicus **GloFAS v4**), Forecast & Archive APIs (**ECMWF**, **ERA5**) | River discharge, weather, ET0, soil moisture, 1991→ climate | CC BY 4.0 (Open-Meteo) · Copernicus / ECMWF terms |
| [geoBoundaries](https://www.geoboundaries.org/) gbOpen MAR ADM2 | Province boundaries | ODbL 1.0 (OpenStreetMap, Wambacher) |
| HCP (RGPH 2024 census), Ministry of Equipment & Water, ONEE, ABHOER, DGM, World Bank, academic papers, Moroccan press | Populations, dam levels, supply systems, problems, causes, solutions | Cited per fact in the knowledge base and the report |

## Limitations

- **This is a decision-support sketch, not an operational model.** Supply shares, outage rates, aquifer recharge and some export volumes are documented assumptions, tagged `[assume]` in `planner_config.py`.
- **GloFAS is a modelled product.** Its ~5 km grid needed snapping to main-stem cells, it misses karst spring flow, and its inflows are rescaled to the basin's reported normal (3,054 Mm³/yr).
- **"Hours of water per day"** is an equivalent of the share of demand served. It is not a measured supply schedule.
- **Problem severity and stress scores** are an editorial synthesis of the cited evidence, not an official index.

## Licence

- **Code:** [MIT](LICENSE). Data licences are detailed in [NOTICE.md](NOTICE.md).
- **Knowledge base & report** (`data/reference/bmk_knowledge_base.json`, `docs/REPORT.md`): [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Each entry cites its original source.
- **Province boundaries** (`data/reference/bmk_provinces.geojson`): [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/), © OpenStreetMap contributors, via geoBoundaries.
- **Open-Meteo data** (GloFAS, ECMWF, ERA5) is fetched at run time under CC BY 4.0 and not redistributed here.

## Author

**Taha EL HOR** · [@tahelhor](https://github.com/tahelhor)

Built with Python, Polars, DuckDB, Pydantic, PuLP/HiGHS, Streamlit, Plotly and Three.js.
