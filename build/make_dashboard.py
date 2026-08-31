"""Build and deploy the OkTex Lakeview dashboard over the Delta tables.

Tests every dataset query against the warehouse first, then serializes the
dashboard, deploys via the Lakeview API, and writes the definition to
dashboard/oktex_measurements.lvdash.json.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dbx_sql import run_sql, get_token, HOST, WAREHOUSE_ID, CATALOG, SCHEMA, PROFILE  # noqa
import subprocess
import urllib.request

FQ = f"{CATALOG}.{SCHEMA}"
ROOT = Path(__file__).resolve().parent.parent

MAXDAY = f"(SELECT MAX(gas_day) FROM {FQ}.fact_daily_measurements)"

DATASETS = {
    "ds_kpi": (
        f"SELECT "
        f"CAST(ROUND(SUM(CASE WHEN d.meter_type='RECEIPT' THEN m.actual_dth END)) AS BIGINT) AS receipts_dth, "
        f"CAST(ROUND(SUM(CASE WHEN d.meter_type IN ('DELIVERY','BIDIRECTIONAL') THEN m.actual_dth END)) AS BIGINT) AS deliveries_dth, "
        f"CAST(ROUND(SUM(CASE WHEN d.meter_type='RECEIPT' THEN m.actual_dth END) "
        f"- SUM(CASE WHEN d.meter_type IN ('DELIVERY','BIDIRECTIONAL') THEN m.actual_dth END)) AS BIGINT) AS imbalance_dth, "
        f"COUNT(DISTINCT m.meter_id) AS active_meters "
        f"FROM {FQ}.fact_daily_measurements m JOIN {FQ}.dim_meters d USING (meter_id) "
        f"WHERE m.gas_day = {MAXDAY}"
    ),
    "ds_balance": (
        f"SELECT m.gas_day, "
        f"SUM(CASE WHEN d.meter_type='RECEIPT' THEN m.actual_dth ELSE 0 END) AS receipts_dth, "
        f"SUM(CASE WHEN d.meter_type IN ('DELIVERY','BIDIRECTIONAL') THEN m.actual_dth ELSE 0 END) AS deliveries_dth "
        f"FROM {FQ}.fact_daily_measurements m JOIN {FQ}.dim_meters d USING (meter_id) "
        f"GROUP BY m.gas_day ORDER BY m.gas_day"
    ),
    "ds_segment": (
        f"SELECT d.segment, SUM(m.actual_dth) AS total_dth "
        f"FROM {FQ}.fact_daily_measurements m JOIN {FQ}.dim_meters d USING (meter_id) "
        f"WHERE m.gas_day = {MAXDAY} GROUP BY d.segment"
    ),
    "ds_type": (
        f"SELECT d.meter_type, SUM(m.actual_dth) AS total_dth "
        f"FROM {FQ}.fact_daily_measurements m JOIN {FQ}.dim_meters d USING (meter_id) "
        f"WHERE m.gas_day = {MAXDAY} GROUP BY d.meter_type"
    ),
    "ds_meter": (
        f"SELECT d.meter_id, d.meter_name, d.meter_type, d.county, d.state, "
        f"m.scheduled_dth, m.actual_dth, m.variance_pct, m.pressure_psig "
        f"FROM {FQ}.fact_daily_measurements m JOIN {FQ}.dim_meters d USING (meter_id) "
        f"WHERE m.gas_day = {MAXDAY} ORDER BY m.actual_dth DESC"
    ),
}


def test_queries(tok):
    print("## Testing dataset queries")
    for name, q in DATASETS.items():
        rows, cols = run_sql(q, tok)
        print(f"  {name}: {len(rows)} rows, cols={cols}")


def text_widget(name, md, x, y, w, h):
    return {"widget": {"name": name, "multilineTextboxSpec": {"lines": [md]}},
            "position": {"x": x, "y": y, "width": w, "height": h}}


def counter(name, ds, field, title, x, y):
    return {"widget": {"name": name, "queries": [{"name": "main_query", "query": {
        "datasetName": ds, "fields": [{"name": field, "expression": f"`{field}`"}],
        "disaggregated": True}}],
        "spec": {"version": 2, "widgetType": "counter",
                 "encodings": {"value": {"fieldName": field, "displayName": title}},
                 "frame": {"showTitle": True, "title": title}}},
        "position": {"x": x, "y": y, "width": 3, "height": 3}}


def datasets_block():
    return [{"name": n, "displayName": n,
             "queryLines": [q]} for n, q in DATASETS.items()]


def build_serialized():
    layout = []
    layout.append(text_widget("title", "## OkTex Pipeline — Daily Measurement Overview", 0, 0, 6, 1))
    layout.append(text_widget("subtitle",
        "Synthetic demo data · West Texas Panhandle → North-Central Oklahoma · source: stable_classic_wg38i9_catalog.oneok_okt",
        0, 1, 6, 1))

    # KPI row
    layout.append(counter("kpi-receipts", "ds_kpi", "receipts_dth", "Total Receipts (Dth)", 0, 2))
    layout.append(counter("kpi-deliveries", "ds_kpi", "deliveries_dth", "Total Deliveries (Dth)", 3, 2))
    # imbalance + meters
    layout.append(counter("kpi-imbalance", "ds_kpi", "imbalance_dth", "System Imbalance (Dth)", 0, 5))
    layout.append(counter("kpi-meters", "ds_kpi", "active_meters", "Active Meters", 3, 5))

    # Balance trend (full width line, two Y)
    layout.append({"widget": {"name": "balance-trend", "queries": [{"name": "main_query", "query": {
        "datasetName": "ds_balance", "fields": [
            {"name": "gas_day", "expression": "`gas_day`"},
            {"name": "receipts_dth", "expression": "SUM(`receipts_dth`)"},
            {"name": "deliveries_dth", "expression": "SUM(`deliveries_dth`)"},
        ], "disaggregated": False}}],
        "spec": {"version": 3, "widgetType": "line",
                 "encodings": {
                     "x": {"fieldName": "gas_day", "scale": {"type": "temporal"}, "displayName": "Flow date"},
                     "y": {"scale": {"type": "quantitative"}, "fields": [
                         {"fieldName": "receipts_dth", "displayName": "Receipts (Dth)"},
                         {"fieldName": "deliveries_dth", "displayName": "Deliveries + Interconnect (Dth)"}]},
                 },
                 "frame": {"showTitle": True, "title": "System Throughput Trend (Receipts vs Deliveries)"},
                 "mark": {"colors": ["#00A972", "#2563eb"]}}},
        "position": {"x": 0, "y": 8, "width": 6, "height": 6}})

    # Segment bar + type pie
    layout.append({"widget": {"name": "by-segment", "queries": [{"name": "main_query", "query": {
        "datasetName": "ds_segment", "fields": [
            {"name": "segment", "expression": "`segment`"},
            {"name": "sum(total_dth)", "expression": "SUM(`total_dth`)"}], "disaggregated": False}}],
        "spec": {"version": 3, "widgetType": "bar",
                 "encodings": {"x": {"fieldName": "segment", "scale": {"type": "categorical", "sort": {"by": "y-reversed"}}, "displayName": "Segment"},
                               "y": {"fieldName": "sum(total_dth)", "scale": {"type": "quantitative"}, "displayName": "Measured Dth"},
                               "label": {"show": True}},
                 "frame": {"showTitle": True, "title": "Today's Throughput by Segment"},
                 "mark": {"colors": ["#FFAB00"]}}},
        "position": {"x": 0, "y": 14, "width": 3, "height": 6}})

    layout.append({"widget": {"name": "by-type", "queries": [{"name": "main_query", "query": {
        "datasetName": "ds_type", "fields": [
            {"name": "sum(total_dth)", "expression": "SUM(`total_dth`)"},
            {"name": "meter_type", "expression": "`meter_type`"}], "disaggregated": False}}],
        "spec": {"version": 3, "widgetType": "pie",
                 "encodings": {"angle": {"fieldName": "sum(total_dth)", "scale": {"type": "quantitative"}, "displayName": "Measured Dth"},
                               "color": {"fieldName": "meter_type", "scale": {"type": "categorical",
                                   "mappings": [{"value": "RECEIPT", "color": "#00A972"},
                                                {"value": "DELIVERY", "color": "#2563eb"},
                                                {"value": "BIDIRECTIONAL", "color": "#e08a1e"}]}, "displayName": "Meter type"}},
                 "frame": {"showTitle": True, "title": "Today's Flow by Meter Type"}}},
        "position": {"x": 3, "y": 14, "width": 3, "height": 6}})

    # Meter detail table
    cols = [("meter_id", "Meter"), ("meter_name", "Name"), ("meter_type", "Type"),
            ("county", "County"), ("state", "State"), ("scheduled_dth", "Scheduled Dth"),
            ("actual_dth", "Actual Dth"), ("variance_pct", "Var %"), ("pressure_psig", "Pressure psig")]
    layout.append({"widget": {"name": "meter-table", "queries": [{"name": "main_query", "query": {
        "datasetName": "ds_meter", "fields": [{"name": c, "expression": f"`{c}`"} for c, _ in cols],
        "disaggregated": True}}],
        "spec": {"version": 2, "widgetType": "table",
                 "encodings": {"columns": [{"fieldName": c, "displayName": d} for c, d in cols]},
                 "frame": {"showTitle": True, "title": "Meter Measurements — Latest Flow Date"}}},
        "position": {"x": 0, "y": 20, "width": 6, "height": 8}})

    return {"datasets": datasets_block(),
            "pages": [{"name": "overview", "displayName": "Overview",
                       "pageType": "PAGE_TYPE_CANVAS", "layout": layout}],
            "uiSettings": {"theme": {"widgetHeaderAlignment": "ALIGNMENT_UNSPECIFIED"}}}


# Existing dashboard to update in place (avoid creating duplicates).
DASHBOARD_ID = "01f1a32e13fa1331a64126e1b1b25f76"


def deploy(serialized, tok):
    from dbx_sql import _post, _get, HOST  # authed helpers with SSL ctx
    import urllib.request
    body = {
        "display_name": "OkTex Pipeline — Daily Measurements",
        "warehouse_id": WAREHOUSE_ID,
        "serialized_dashboard": json.dumps(serialized),
    }
    if DASHBOARD_ID:
        # PATCH existing dashboard
        req = urllib.request.Request(
            HOST + f"/api/2.0/lakeview/dashboards/{DASHBOARD_ID}",
            data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
            method="PATCH")
        from dbx_sql import _CTX
        with urllib.request.urlopen(req, timeout=120, context=_CTX) as r:
            resp = json.loads(r.read().decode())
        # publish the updated version
        _post(f"/api/2.0/lakeview/dashboards/{DASHBOARD_ID}/published",
              {"embed_credentials": True, "warehouse_id": WAREHOUSE_ID}, tok)
        return resp
    me = json.loads(subprocess.check_output(
        ["databricks", "current-user", "me", "--profile", PROFILE], text=True))["userName"]
    body["parent_path"] = f"/Users/{me}"
    return _post("/api/2.0/lakeview/dashboards", body, tok)


if __name__ == "__main__":
    tok = get_token()
    test_queries(tok)
    serialized = build_serialized()
    out = ROOT / "dashboard" / "oktex_measurements.lvdash.json"
    out.write_text(json.dumps(serialized, indent=2))
    print(f"wrote {out}")
    resp = deploy(serialized, tok)
    did = resp.get("dashboard_id")
    print("dashboard_id:", did)
    print("path:", resp.get("path"))
    (ROOT / "evidence" / "05_dashboard.txt").write_text(
        f"Dashboard created: {resp.get('display_name')}\n"
        f"dashboard_id: {did}\n"
        f"path: {resp.get('path')}\n"
        f"warehouse_id: {WAREHOUSE_ID}\n"
        f"datasets: {list(DATASETS.keys())}\n"
    )
    print("DASHBOARD OK")
