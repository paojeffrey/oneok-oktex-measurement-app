"""Build executed Jupyter notebooks (.ipynb) with REAL outputs embedded.

Each code cell is executed here and its genuine stdout is captured and written
into the notebook as a stream output. The result is a committed notebook whose
cell outputs are readable as text and reflect a real run against the live
Databricks warehouse and Lakebase Postgres instance.
"""
from __future__ import annotations
import contextlib
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NB_DIR = ROOT / "notebooks"
NB_DIR.mkdir(exist_ok=True)


def code_cell(source: str, shared: dict) -> dict:
    """Execute source in a shared namespace, capture stdout, embed as output."""
    buf = io.StringIO()
    err_text = None
    with contextlib.redirect_stdout(buf):
        try:
            exec(compile(source, "<cell>", "exec"), shared)
        except Exception as exc:  # capture the traceback text into the cell
            import traceback
            err_text = traceback.format_exc()
    out = buf.getvalue()
    outputs = []
    if out:
        outputs.append({
            "output_type": "stream", "name": "stdout",
            "text": out.splitlines(keepends=True),
        })
    if err_text:
        outputs.append({
            "output_type": "stream", "name": "stderr",
            "text": err_text.splitlines(keepends=True),
        })
        print(f"  ! cell raised:\n{err_text}", file=sys.stderr)
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": outputs,
        "source": source.splitlines(keepends=True),
    }


def md_cell(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {},
            "source": text.splitlines(keepends=True)}


def write_nb(name: str, cells: list[dict]):
    nb = {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.13"},
        },
        "nbformat": 4, "nbformat_minor": 5,
    }
    (NB_DIR / name).write_text(json.dumps(nb, indent=1))
    n_out = sum(len(c.get("outputs", [])) for c in cells)
    print(f"wrote {name}: {len(cells)} cells, {n_out} outputs")


# Shared setup prelude executed (not shown as a cell) so cells can import build modules.
PRELUDE = f"""
import sys
sys.path.insert(0, {str(ROOT / 'build')!r})
"""

# =====================================================================
# Notebook 01 — Generate synthetic data and load to Unity Catalog Delta
# =====================================================================
def build_nb01():
    ns = {}
    exec(PRELUDE, ns)
    cells = [
        md_cell(
            "# 01 · Generate OkTex Pipeline Data → Unity Catalog Delta\n\n"
            "**Target:** `stable_classic_wg38i9_catalog.oneok_okt`  \n"
            "**Warehouse:** Serverless Starter Warehouse JPao\n\n"
            "> **Data policy:** Meter names, types, and locations are the **real** OkTex "
            "stations from the *public* OKT System Overview Map (georeferenced Esri PDF). "
            "All measurement **quantities** are **synthetic**. No ONEOK or customer "
            "operational data is used.**\n\n"
            "This notebook generates three tables — `dim_meters`, `pipeline_segments`, "
            "`fact_daily_measurements` — and loads them into Delta, then verifies."
        ),
        md_cell("### 1. Generate the synthetic dataset (pure Python, seeded)"),
        code_cell(
            "from generate_data import build_meters, build_segments, build_measurements\n\n"
            "meters = build_meters()\n"
            "segments = build_segments()\n"
            "measurements = build_measurements(meters)\n"
            "print(f'meters={len(meters)}  route_vertices={len(segments)}  daily_measurements={len(measurements)}')\n"
            "print('meter types:', sorted({m[\"meter_type\"] for m in meters}))",
            ns),
        md_cell("### 2. Inspect a few generated rows"),
        code_cell(
            "import json\n"
            "print('--- dim_meters[0] ---')\n"
            "print(json.dumps(meters[0], indent=2))\n"
            "print('--- fact_daily_measurements[0] ---')\n"
            "print(json.dumps(measurements[0], indent=2))",
            ns),
        md_cell("### 3. Create & load the Delta tables (idempotent `CREATE OR REPLACE` + insert)\n"
                "Executed against the Databricks SQL warehouse via the Statement Execution API."),
        code_cell(
            "import load_delta\n"
            "load_delta.main()",
            ns),
    ]
    write_nb("01_generate_and_load_delta.ipynb", cells)


# =====================================================================
# Notebook 02 — Sync measurement data to Lakebase Postgres
# =====================================================================
def build_nb02():
    ns = {}
    exec(PRELUDE, ns)
    cells = [
        md_cell(
            "# 02 · Sync Measurements to Lakebase (Postgres)\n\n"
            "**Lakebase project:** `projects/oktex/branches/production/endpoints/primary` "
            "(Autoscaling tier)  \n**Database:** `oktex`\n\n"
            "The OkTex measurement tables are synced from the local generator (which "
            "mirrors the Delta tables built in notebook 01) into Lakebase Postgres. The "
            "Databricks App reads these tables **live** at request time. Verification "
            "queries below run over `psql` against the live endpoint using a short-lived "
            "OAuth credential."
        ),
        md_cell("### 1. Run the Delta → Lakebase sync and verify (live)"),
        code_cell(
            "import sync_lakebase\n"
            "sync_lakebase.main()",
            ns),
        md_cell("### 2. Confirm the app's read view exists and returns today's rows"),
        code_cell(
            "host, token, email = sync_lakebase.conn_info()\n"
            "r = sync_lakebase.psql(host, token, email, 'oktex',\n"
            "    \"SELECT meter_id, meter_name, meter_type, actual_dth, pressure_psig \"\n"
            "    \"FROM v_latest_measurements ORDER BY actual_dth DESC LIMIT 5;\")\n"
            "print(r.stdout)",
            ns),
    ]
    write_nb("02_sync_to_lakebase.ipynb", cells)


# =====================================================================
# Notebook 03 — Analytics / measurement checks over Delta
# =====================================================================
def build_nb03():
    ns = {}
    exec(PRELUDE, ns)
    cells = [
        md_cell(
            "# 03 · OkTex Measurement Analytics (Delta)\n\n"
            "Analytical queries over `stable_classic_wg38i9_catalog.oneok_okt` powering "
            "the dashboard and app — daily system balance, throughput by segment, and "
            "meters with the largest scheduled-vs-actual variance. Outputs are live "
            "query results."
        ),
        code_cell(
            "from dbx_sql import run_sql, fmt_table, get_token, CATALOG, SCHEMA\n"
            "FQ = f'{CATALOG}.{SCHEMA}'\n"
            "tok = get_token()\n"
            "print('querying', FQ)",
            ns),
        md_cell("### 1. Daily system balance — receipts vs deliveries (last 10 days)"),
        code_cell(
            "rows, cols = run_sql(f'''\n"
            "  SELECT m.gas_day,\n"
            "         ROUND(SUM(CASE WHEN d.meter_type='RECEIPT' THEN m.actual_dth END)/1000,1) AS receipts_mdth,\n"
            "         ROUND(SUM(CASE WHEN d.meter_type IN ('DELIVERY','BIDIRECTIONAL') THEN m.actual_dth END)/1000,1) AS deliv_mdth,\n"
            "         ROUND((SUM(CASE WHEN d.meter_type='RECEIPT' THEN m.actual_dth END)\n"
            "               -SUM(CASE WHEN d.meter_type IN ('DELIVERY','BIDIRECTIONAL') THEN m.actual_dth END))/1000,1) AS imbalance_mdth\n"
            "  FROM {FQ}.fact_daily_measurements m JOIN {FQ}.dim_meters d USING (meter_id)\n"
            "  WHERE m.gas_day >= (SELECT MAX(gas_day) FROM {FQ}.fact_daily_measurements) - INTERVAL 9 DAYS\n"
            "  GROUP BY m.gas_day ORDER BY m.gas_day''', tok)\n"
            "print(fmt_table(rows, cols))",
            ns),
        md_cell("### 2. Throughput by pipeline segment (today)"),
        code_cell(
            "rows, cols = run_sql(f'''\n"
            "  SELECT d.segment, COUNT(*) AS meters, ROUND(SUM(m.actual_dth)/1000,1) AS total_mdth\n"
            "  FROM {FQ}.fact_daily_measurements m JOIN {FQ}.dim_meters d USING (meter_id)\n"
            "  WHERE m.gas_day = (SELECT MAX(gas_day) FROM {FQ}.fact_daily_measurements)\n"
            "  GROUP BY d.segment ORDER BY total_mdth DESC''', tok)\n"
            "print(fmt_table(rows, cols))",
            ns),
        md_cell("### 3. Meters with the largest measurement variance (today)"),
        code_cell(
            "rows, cols = run_sql(f'''\n"
            "  SELECT d.meter_id, d.meter_name, d.meter_type, m.scheduled_dth, m.actual_dth, m.variance_pct\n"
            "  FROM {FQ}.fact_daily_measurements m JOIN {FQ}.dim_meters d USING (meter_id)\n"
            "  WHERE m.gas_day = (SELECT MAX(gas_day) FROM {FQ}.fact_daily_measurements)\n"
            "  ORDER BY ABS(m.variance_pct) DESC LIMIT 10''', tok)\n"
            "print(fmt_table(rows, cols))",
            ns),
    ]
    write_nb("03_measurement_analytics.ipynb", cells)


if __name__ == "__main__":
    build_nb01()
    build_nb02()
    build_nb03()
    print("all notebooks built")
