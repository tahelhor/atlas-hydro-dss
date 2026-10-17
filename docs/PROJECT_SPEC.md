You are a Staff Data Scientist, Operations Research Engineer, and QA Architect. I want you to scaffold, build, test, and verify a complete, production-grade portfolio project from scratch: "Atlas Hydro-Climate Decision Support System (DSS) for the Oum Er-Rbia Basin".

### 1. PROJECT VISION & ARCHITECTURE

Build an end-to-end Prescriptive Decision Support System (DSS) that ingests real-time and historical satellite/hydro-meteorological data for the Oum Er-Rbia watershed in Morocco (from the Khénifra headwaters down to the major dams), validates the data through strict QA gates, stores it in DuckDB, runs a Linear Programming (Operations Research) solver to optimize water allocation under drought stress, and serves an executive dark-mode interactive simulator.

### 2. TECH STACK & STRICT RULES

- **Data Processing & Storage:** Use `polars` (strictly avoid pandas unless required by a plotting library) and `duckdb` (`data/hydro_warehouse.duckdb`).
- **Data QA & Test Automation:** Use `pydantic` v2 to validate all external API payloads before inserting into DuckDB, and write a comprehensive `pytest` suite verifying API schemas, physical hydrological bounds, and solver mathematical constraints.
- **Decision Support / Operations Research:** Use `pulp` (Linear Programming) to solve a 30-day rolling multi-reservoir water release optimization problem.
- **Frontend UI:** Use `streamlit` and `plotly` to build a polished, executive dark-mode dashboard with interactive "What-If" simulation sliders.
- **First Step:** Create a `CLAUDE.md` file documenting the architecture and commands, set up the dependency environment (`pyproject.toml` or `requirements.txt`), create the modular `src/` and `tests/` folder structure, and then execute each build step autonomously.

### 3. BASIN NODES & OFFICIAL REFERENCE CAPACITIES

Configure these exact 4 hydrological nodes in the Oum Er-Rbia basin (Morocco):

1. `KHENIFRA_HEADWATERS` ("Oum Er-Rbia Headwaters - Khénifra"): Upstream river gauge | `lat: 32.9394, lon: -5.6686` | No reservoir capacity.
2. `DAM_AHMED_EL_HANSALI` ("Barrage Ahmed El Hansali"): Reservoir | `lat: 32.5150, lon: -5.9220` | Normal Capacity: `668.0 Mm3` | Baseline Storage Seed: `385.0 Mm3`
3. `DAM_BIN_EL_OUIDANE` ("Barrage Bin El Ouidane"): Reservoir | `lat: 32.1060, lon: -6.4640` | Normal Capacity: `1215.0 Mm3` | Baseline Storage Seed: `640.0 Mm3`
4. `DAM_AL_MASSIRA` ("Barrage Al Massira"): Downstream Mega-Reservoir | `lat: 32.4730, lon: -7.6380` | Normal Capacity: `2656.0 Mm3` | Baseline Storage Seed: `1120.0 Mm3`

### 4. TRUSTED, KEYLESS APIs TO USE FOR DATA COLLECTION

Write an async Python ingestion pipeline (`httpx` + `asyncio`) that queries these exact two keyless APIs for all 4 nodes:

**API A: Copernicus GloFAS v4 River Discharge (Open-Meteo Flood API - No API Key Needed)**

- **Endpoint:** `https://flood-api.open-meteo.com/v1/flood`
- **Query Params:**
  - `latitude` & `longitude`: Node coordinates
  - `daily`: `river_discharge,river_discharge_mean,river_discharge_p25,river_discharge_p75`
  - `past_days`: `92`
  - `forecast_days`: `30`
- **Transformation Rule:** Coalesce `river_discharge` (historical) with `river_discharge_mean` (future forecast). Convert flow rate from cubic meters per second (`m3/s`) into daily inflow volume in Million Cubic Meters (`Mm3/day`) using the formula: `inflow_mm3 = (m3_per_sec * 86400) / 1_000_000`. Keep the `p25` and `p75` ensemble bounds for uncertainty fan charts.

**API B: ECMWF ERA5-Land Hydrometeorology & FAO Evapotranspiration (Open-Meteo Forecast API - No API Key Needed)**

- **Endpoint:** `https://api.open-meteo.com/v1/forecast`
- **Query Params:**
  - `latitude` & `longitude`: Node coordinates
  - `daily`: `precipitation_sum,snowfall_sum,temperature_2m_max,et0_fao_evapotranspiration`
  - `hourly`: `soil_moisture_28_to_100cm`
  - `past_days`: `92`
  - `forecast_days`: `16`
  - `timezone`: `Africa/Casablanca`
- **Transformation Rule:** Aggregate the hourly `soil_moisture_28_to_100cm` (deep root-zone moisture) into a daily mean per date, join it with the daily weather metrics, and join both with the 30-day GloFAS discharge data on date (forward-filling weather/ET0 metrics for forecast days 17 to 30).

### 5. PYDANTIC QA GATE & DUCKDB SCHEMA

- Pass every ingested row through a strict `pydantic` model checking physical bounds (`precip >= 0`, `et0_fao >= 0`, `river_discharge >= 0`, valid dates, boolean `is_forecast` flag).
- Persist clean tables in `data/hydro_warehouse.duckdb`: `dim_basin_nodes` and `fact_hydro_daily`.
- Run the ingestion script immediately and verify the DuckDB tables are populated with real data from the APIs.

### 6. PRESCRIPTIVE OPTIMIZATION ENGINE (`PuLP`)

Build a Linear Programming solver that optimizes daily water allocations over the next 30-day forecast horizon across the 3 reservoirs (`Ahmed El Hansali`, `Bin El Ouidane`, `Al Massira`):

- **Inputs:** Current reservoir storage (`Mm3`), 30-day forecasted daily inflows (`inflow_mm3`), evaporation loss factor derived from `et0_fao_evapotranspiration`, and user-adjustable scenario parameters.
- **Competing Demands & Priority Weights:**
  1. Potable Water Supply (ONEE Urban Priority - Weight: 10)
  2. Agricultural Irrigation Demand (Tadla & Doukkala perimeters, scaled by FAO ET0 - Weight: 5)
  3. Minimum Ecological River Flow (Weight: 8)
- **Constraints:** Water mass-balance conservation per day (`Storage_t = Storage_{t-1} + Inflow_t - Evap_t - Releases_t - Spill_t`), maximum storage capacity, and a soft/hard penalty if reservoir storage drops below a configurable Dead Storage Safety Buffer (default 20% of capacity).

### 7. EXECUTIVE STREAMLIT UI

Build a sleek, LinkedIn-ready Streamlit application featuring:

1. **Top KPI Ribbon:** Total Basin Storage (`Mm3` & `%`), 30-Day Expected Inflow (`Mm3`), Mean FAO Evapotranspiration (`mm/day`), and Optimization Status (`Optimal` / `Deficit Warning`).
2. **Interactive "What-If" Sidebar:** Sliders for:
   - Climate Inflow Shock (`-50%` severe drought to `+50%` wet anomaly, or toggle between GloFAS `p25` pessimistic, `mean`, and `p75` optimistic forecasts)
   - Agricultural Irrigation Demand Cap (`50%` to `120%`)
   - Minimum Reservoir Safety Buffer (`10%` to `40%`)
     *(Adjusting any slider must re-run the PuLP solver in real time and update all charts).*
3. **Visualizations (Plotly + Map):**
   - An interactive map of the 4 nodes in the Oum Er-Rbia basin sized/colored by storage level.
   - A hydrograph with a shaded uncertainty fan chart (`p25` to `p75`) showing past 90 days of discharge vs. 30-day forecast at Khénifra and the dams.
   - A stacked area/bar chart of optimal daily water allocations (Potable vs. Agriculture vs. Ecological vs. Unmet Deficit) alongside projected reservoir storage trajectories.
   - A "Data QA & Pipeline Health" tab displaying Pydantic validation metrics, DuckDB row counts, and data freshness.

### 8. EXECUTION INSTRUCTIONS

Do not ask me for confirmation at every step. Create the structure, install the required packages, run the live API ingestion to build the DuckDB database, run `pytest` to ensure all tests pass, and verify the Streamlit app runs without errors.
