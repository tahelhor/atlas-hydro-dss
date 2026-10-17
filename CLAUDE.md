# CLAUDE.md - Atlas Hydro-Climate DSS (Oum Er-Rbia)

Prescriptive decision-support system: live GloFAS v4 / ECMWF data → Pydantic QA gates →
DuckDB → PuLP 30-day multi-reservoir allocation LP → Streamlit "What-If" dashboard.
Original build brief: `docs/PROJECT_SPEC.md`.

## Commands

```bash
uv sync                                                # Python 3.12 venv + deps (uv required)
uv run python -m src.ingestion.fetch_hydro_climate     # live ingestion -> data/hydro_warehouse.duckdb
uv run pytest                                          # full suite (unit + warehouse + dashboard)
uv run pytest -m "not warehouse"                       # offline unit tests only (no DB needed)
uv run streamlit run src/app/dashboard.py              # dashboard on http://localhost:8501
```

## Layout

```
src/config.py                         nodes, official capacities, API contracts, demand & weight assumptions
src/ingestion/validator.py            pydantic payload contracts + HydroDailyRecord row gate + QAReport
src/ingestion/fetch_hydro_climate.py  async httpx fetch (retry/backoff) -> polars transforms -> DuckDB upsert
src/warehouse.py                      read-only DuckDB access layer (returns polars)
src/models/water_optimizer.py         ScenarioParams -> build_inputs -> solve (PuLP + HiGHS)
src/app/dashboard.py                  Streamlit UI (4 tabs), .streamlit/config.toml holds the dark theme
tests/                                conftest (synthetic payloads, httpx.MockTransport), pipeline QA,
                                      optimizer math, live warehouse checks, AppTest dashboard smoke tests
```

## Rules

- **polars + duckdb only**; no pandas. Plotly gets plain lists (`.to_list()`).
- Every external payload passes `GloFASPayload` / `WeatherPayload`; every row passes
  `HydroDailyRecord` before insert. Failing rows go to `qa_rejections`, never silently dropped.
- Assumptions (demands, weights, lake areas, Kc) live in `src/config.py` only - not in model code.
- Weight ladder must hold (tested in `test_weight_ladder_is_consistent`):
  `irrigation 5 < soft buffer 6.5 (+30×0.01 daily) < irrigation deep-cut 7.5 < ecological 8 < potable 10 < hard buffer 1000`.

## DuckDB schema (`data/hydro_warehouse.duckdb`)

| table | grain / notes |
|---|---|
| `dim_basin_nodes` | 1 row per node; official coords + snapped GloFAS cell, capacity, seed storage |
| `fact_hydro_daily` | PK (node_id, date); 92 history + 30 forecast days; idempotent upsert keeps older history |
| `etl_run_log` | 1 row per ingestion run: counts, duration, status, first forecast date |
| `qa_rejections` | quarantined rows with pydantic error reasons |

## Domain decisions & gotchas

- **GloFAS cell snapping.** GloFAS v4 is a ~0.05° grid; the official dam coordinates hit
  side-stream cells (0.0–0.1 m³/s). Discharge is queried at the max-mean-flow cell in a 7×7
  neighbourhood (`glofas_lat/lon` in config). Weather uses the official coordinates.
  `test_cascade_is_physically_plausible` guards Massira > upstream dams > Khénifra.
- **Coalesce rule.** History uses `river_discharge`; forecast days use `river_discharge_mean`
  (consistent with the p25/p75 fan); each falls back to the other. First forecast day =
  `daily.time[92]` (the API's own "today").
- **Weather gaps.** The forecast API's past window is only ~60 days, so the first ~32 history
  days have null weather (kept nullable, reported in the QA tab). Forecast days 17–30 are
  forward-filled and flagged `weather_is_filled`. Hourly soil moisture → daily mean.
- **Cascade.** Hansali + Bin El Ouidane → Al Massira. Massira's local inflow is the GloFAS residual
  `Q_massira − Q_hansali − Q_bin_el_ouidane` (clipped ≥ 0); upstream water reaches it only via
  optimised ecological flow + excess releases (same-day routing). Potable/irrigation are consumptive.
- **Evaporation** = 1.05 × ET0 × lake area, area = A_full × (S₀/C)^(2/3) frozen at S₀ (keeps LP linear).
- **Buffer**: soft = penalty on end-of-horizon shortfall (hedges irrigation only); hard = protects
  storage at all costs. Physical dead storage (5 % of capacity) is a hard bound.
- **Irrigation hedging**: shortfall beyond 50 % of demand costs 1.5× → solver rations, not zeroes.
- **PuLP 4.x** (Rust core): create variables with `prob.add_variable(...)`; `prob.solve()` returns
  `LpSolveStats` (`.status` is `LpSolveStatus`); CBC is no longer bundled → `pulp[highs]` (in-process).
  Requires Python ≥ 3.12.
- Windows console: set `PYTHONIOENCODING=utf-8` when printing polars tables.

## Dashboard performance & the 3D basin story

- **The simulator tab is an `@st.fragment`** (`simulator_fragment` in `dashboard.py`): solution sliders
  rerun only the simulator, never the other tabs. Keep new simulator widgets inside the fragment.
- **Solves are cached per scenario** (`simulator._solve`): the business-as-usual baseline depends only
  on year + dam levels; each active solution is also solved alone (its own effect for the story cards).
  A slider step ≈ 2 LP solves (~0.2 s) + ~5 charts (~0.25 s).
- **Plotly**: `ui.py` sets `pio.templates.default = "none"` and `base_layout` applies all chrome in ONE
  `update_layout` call - Streamlit's default template and per-call validation cost ~40 ms per chart.
- **3D story** = Streamlit components v2 (`simulator_map.py` + `views/basin_story/{html,css,js}`).
  It mounts once; on each rerun Python sends new `data` and `story.js` animates in place (no reload).
  `data.hash` lets the JS skip identical updates. Month timeline, before/after toggle and province /
  solution focus are client-side on purpose (no Python rerun) - don't move them back to st widgets.
  The component definition is cached by the assets' mtimes (`_asset_signature`), so edits to the
  JS/CSS/HTML apply on the next rerun. Three.js is pinned (`THREE_VERSION`) and loaded from jsDelivr:
  offline, the story shows an error box and the Plotly charts still carry the results.
- Chapter copy is built in Python in both languages (`build_payload`); the JS only animates.
  Tap-water colour encoding (story + calendar heatmap): diverging red → grey (20.5 h) → blue (24 h).
