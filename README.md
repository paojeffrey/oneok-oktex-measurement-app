# OkTex Pipeline — Daily Measurement App

An end-to-end Databricks build for **ONEOK** that visualizes the **OkTex (OKT)
natural-gas pipeline**: meter stations along the mainline and their **daily
measured quantities**, shown on an interactive map with hover tooltips, KPIs,
trend charts, a detail table, and an AI operations summary.

> ### ⚠️ Data policy — synthetic data only
> **No ONEOK or customer data is used anywhere in this repo.** Every measurement
> quantity (scheduled/actual Dth, pressure, temperature, variance) is
> **synthetically generated** with a seeded random generator
> ([`build/generate_data.py`](build/generate_data.py)). Meter names, IDs, and
> coordinates are fabricated and placed within the **publicly documented** OKT
> system-map bounding box (lat 33.36→36.95, lon −102.33→−97.50: West Texas
> Panhandle → north-central Oklahoma) purely so the demo map looks realistic.
> The operator label references the public FERC TSP number (80-002-2246). This
> is a solution-architecture demo artifact, not a source of real pipeline data.

---

## What this demonstrates (Databricks platform)

| Component | Technology | Where |
|-----------|-----------|-------|
| **Lakehouse tables** | Unity Catalog + Delta | `stable_classic_wg38i9_catalog.oneok_okt` |
| **Lakebase** | Managed Postgres (Autoscaling), Delta→Postgres sync | project `oktex`, database `oktex` |
| **App** | Databricks Apps (FastAPI + React/Leaflet), reads **live from Lakebase** | `app/` |
| **AI** | Foundation Model (Claude Sonnet 5) via Databricks Model Serving | `app/server/llm.py` |
| **Dashboard** | Lakeview (AI/BI) over the Delta tables | `dashboard/` |

**Live app:** `https://oneok-oktex-pipeline-7474649345910036.aws.databricksapps.com`
**Dashboard:** `https://fevm-stable-classic-wg38i9.cloud.databricks.com/dashboardsv3/01f1a32e13fa1331a64126e1b1b25f76/published`
*(Both require Databricks workspace login — this is a private FE-VM workspace.)*

---

## Architecture / data flow

```
build/generate_data.py         (synthetic meters, route, 60 days of measurements)
        │
        ├─► build/load_delta.py ─────►  Unity Catalog Delta
        │                               stable_classic_wg38i9_catalog.oneok_okt
        │                                 · dim_meters (20)
        │                                 · pipeline_segments (14)
        │                                 · fact_daily_measurements (1,200)
        │                                       │
        │                                       └─►  Lakeview dashboard (dashboard/)
        │
        └─► build/sync_lakebase.py ──►  Lakebase Postgres (db: oktex)
                                          · dim_meters / pipeline_segments
                                          · fact_daily_measurements
                                          · v_latest_measurements (view)
                                                │
                                                ▼
                              Databricks App  (app/, FastAPI + React/Leaflet)
                                 GET  /api/meters        (route + stations)
                                 GET  /api/measurements  (daily Dth per meter)  ◄─ hover tooltips
                                 GET  /api/trend         (receipts vs deliveries)
                                 POST /api/insights      ──► Claude (Model Serving)
```

## Data model (`stable_classic_wg38i9_catalog.oneok_okt`)

- **`dim_meters`** — 20 meter stations: id, name, type (RECEIPT / DELIVERY /
  INTERCONNECT), lat/lon, county, state, segment, pipe diameter, capacity.
- **`pipeline_segments`** — 14 ordered mainline vertices for the map polyline.
- **`fact_daily_measurements`** — 1,200 rows (20 meters × 60 days): scheduled &
  actual Dth, pressure, temperature, scheduled-vs-actual variance.

---

## ✅ Execution evidence (readable as text)

Everything below is **real captured output from actual runs** against the live
Databricks warehouse and Lakebase instance — committed as text, not screenshots.

| File | What it proves |
|------|----------------|
| [`notebooks/01_generate_and_load_delta.ipynb`](notebooks/01_generate_and_load_delta.ipynb) | Data generation + Delta load, **cell outputs visible** (row counts, samples, balance) |
| [`notebooks/02_sync_to_lakebase.ipynb`](notebooks/02_sync_to_lakebase.ipynb) | Delta→Lakebase sync + live `psql` verification, **outputs visible** |
| [`notebooks/03_measurement_analytics.ipynb`](notebooks/03_measurement_analytics.ipynb) | Analytics queries with **live result tables** |
| [`evidence/01_build_delta_run.log`](evidence/01_build_delta_run.log) | Raw stdout of the Delta build (counts, date range, top meters) |
| [`evidence/02_lakebase_sync.txt`](evidence/02_lakebase_sync.txt) | Lakebase sync + row-count/verification queries run over `psql` |
| [`evidence/03_app_deploy.log`](evidence/03_app_deploy.log) | App deployment SUCCEEDED + uvicorn startup logs |
| [`evidence/04_app_api_responses.txt`](evidence/04_app_api_responses.txt) | **Live JSON** from the deployed app (Lakebase-backed) + Claude AI summary |
| [`evidence/05_dashboard.txt`](evidence/05_dashboard.txt) | Lakeview dashboard id / path / published URL |

The notebooks are re-runnable and deterministic (seeded generator), so the
numbers in the notebooks, the Delta tables, Lakebase, the app API, and the
dashboard all agree.

---

## Repository layout

```
build/         Pipeline code (stdlib-only Databricks SQL client, data gen, loaders, dashboard/notebook builders)
notebooks/     Executed .ipynb notebooks WITH committed outputs (build evidence)
evidence/      Plain-text run logs, query results, live API responses
app/           Databricks App — FastAPI backend (server/) + React/Leaflet frontend (static/)
dashboard/     Lakeview dashboard definition (oktex_measurements.lvdash.json)
data/          Generated synthetic CSVs (mirror of the Delta/Lakebase contents)
```

## Reproduce

Prereqs: Databricks CLI authenticated to the FE-VM workspace (profile
`fe-vm-stable-classic-wg38i9`), `psql` (PostgreSQL 16 client), Python 3.

```bash
# 1. Generate + load Delta, sync Lakebase, (re)build notebooks with real outputs
python3 build/generate_data.py
python3 build/load_delta.py         # -> Unity Catalog Delta
python3 build/sync_lakebase.py      # -> Lakebase Postgres (db: oktex)
python3 build/make_notebooks.py     # -> notebooks/*.ipynb (executed, with outputs)
python3 build/make_dashboard.py     # -> Lakeview dashboard + dashboard/*.lvdash.json

# 2. Deploy the app
cd app
databricks sync . "/Users/<you>/oneok-oktex-pipeline" -p fe-vm-stable-classic-wg38i9 \
  --exclude __pycache__ --exclude .venv
databricks apps deploy oneok-oktex-pipeline \
  --source-code-path "/Workspace/Users/<you>/oneok-oktex-pipeline" -p fe-vm-stable-classic-wg38i9
```

The app's service principal is granted a Lakebase Postgres role (`oktex-app`,
`SELECT` on the tables) and `CAN_QUERY` on the Claude serving endpoint; it mints
a fresh Lakebase OAuth credential per connection (see
[`app/server/db.py`](app/server/db.py)).

## App API

| Endpoint | Returns |
|----------|---------|
| `GET /api/meters` | Meter dimension (id, type, lat/lon, county, capacity) |
| `GET /api/route` | Ordered pipeline polyline vertices |
| `GET /api/measurements?flow_date=YYYY-MM-DD` | Per-meter daily quantities + system KPIs (defaults to latest day) |
| `GET /api/trend` | Daily system receipts vs deliveries (full history) |
| `POST /api/insights` | Claude-generated operations summary for a day (graceful computed fallback if the model is unavailable) |

---

*Built by Jeffrey Pao (Solution Architect, Databricks) as a customer demo for ONEOK.
Platform: Unity Catalog · Lakebase · Databricks Apps · Foundation Models · Lakeview.*
