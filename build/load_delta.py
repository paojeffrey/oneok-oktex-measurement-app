"""Create and load the OkTex Delta tables in Unity Catalog, then verify.

Writes real query outputs to stdout so they can be captured as execution
evidence and embedded into the committed notebook.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_data import build_meters, build_segments, build_measurements  # noqa: E402
from dbx_sql import run_sql, fmt_table, get_token, CATALOG, SCHEMA  # noqa: E402

FQ = f"{CATALOG}.{SCHEMA}"


def sql_str(v):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def insert_rows(table, cols, rows, token, batch=200):
    total = 0
    for i in range(0, len(rows), batch):
        chunk = rows[i:i + batch]
        values = ",\n".join(
            "(" + ",".join(sql_str(r[c]) for c in cols) + ")" for r in chunk
        )
        run_sql(f"INSERT INTO {FQ}.{table} ({','.join(cols)}) VALUES {values}", token)
        total += len(chunk)
    return total


def main():
    token = get_token()
    print(f"# OkTex data build -> {FQ}\n")

    # ---- dim_meters ----
    print("## Step 1: dim_meters")
    run_sql(f"""CREATE OR REPLACE TABLE {FQ}.dim_meters (
        meter_id STRING, meter_name STRING, meter_type STRING,
        latitude DOUBLE, longitude DOUBLE, county STRING, state STRING,
        segment STRING, station_group STRING, pipe_diameter_in INT,
        capacity_dth BIGINT, operator STRING, status STRING
    ) USING DELTA COMMENT 'OkTex pipeline meter stations (real names/locations from public OKT system map; synthetic quantities)'""", token)
    meters = build_meters()
    mcols = list(meters[0].keys())
    n = insert_rows("dim_meters", mcols, meters, token)
    print(f"inserted {n} meter rows")
    rows, cols = run_sql(
        f"SELECT meter_type, COUNT(*) AS meters, SUM(capacity_dth) AS total_capacity_dth "
        f"FROM {FQ}.dim_meters GROUP BY meter_type ORDER BY meter_type", token)
    print(fmt_table(rows, cols) + "\n")

    # ---- pipeline_segments ----
    print("## Step 2: pipeline_segments (route polyline)")
    run_sql(f"""CREATE OR REPLACE TABLE {FQ}.pipeline_segments (
        seq INT, latitude DOUBLE, longitude DOUBLE, segment_name STRING
    ) USING DELTA COMMENT 'Ordered OkTex mainline vertices for map polyline'""", token)
    segments = build_segments()
    scols = list(segments[0].keys())
    n = insert_rows("pipeline_segments", scols, segments, token)
    print(f"inserted {n} route vertices")
    rows, cols = run_sql(
        f"SELECT seq, latitude, longitude, segment_name FROM {FQ}.pipeline_segments "
        f"ORDER BY seq LIMIT 5", token)
    print(fmt_table(rows, cols) + "\n")

    # ---- fact_daily_measurements ----
    print("## Step 3: fact_daily_measurements")
    run_sql(f"""CREATE OR REPLACE TABLE {FQ}.fact_daily_measurements (
        gas_day DATE, meter_id STRING, scheduled_dth BIGINT, actual_dth BIGINT,
        pressure_psig DOUBLE, temperature_f DOUBLE, variance_pct DOUBLE
    ) USING DELTA COMMENT 'Daily scheduled/measured gas quantities per meter (synthetic)'""", token)
    measurements = build_measurements(meters)
    fcols = list(measurements[0].keys())
    n = insert_rows("fact_daily_measurements", fcols, measurements, token)
    print(f"inserted {n} daily measurement rows")

    # ---- Verification ----
    print("## Step 4: verification")
    for label, q in [
        ("row counts", f"""SELECT 'dim_meters' AS table, COUNT(*) AS rows FROM {FQ}.dim_meters
            UNION ALL SELECT 'pipeline_segments', COUNT(*) FROM {FQ}.pipeline_segments
            UNION ALL SELECT 'fact_daily_measurements', COUNT(*) FROM {FQ}.fact_daily_measurements
            ORDER BY table"""),
        ("date range", f"""SELECT MIN(gas_day) AS first_day, MAX(gas_day) AS last_day,
            COUNT(DISTINCT gas_day) AS days FROM {FQ}.fact_daily_measurements"""),
    ]:
        rows, cols = run_sql(q, token)
        print(f"### {label}")
        print(fmt_table(rows, cols) + "\n")

    print("### daily receipt vs delivery balance (last 7 days)")
    rows, cols = run_sql(f"""
        SELECT m.gas_day,
               ROUND(SUM(CASE WHEN d.meter_type='RECEIPT' THEN m.actual_dth END)/1000,1) AS receipts_mdth,
               ROUND(SUM(CASE WHEN d.meter_type IN ('DELIVERY','BIDIRECTIONAL') THEN m.actual_dth END)/1000,1) AS deliveries_mdth
        FROM {FQ}.fact_daily_measurements m JOIN {FQ}.dim_meters d USING (meter_id)
        WHERE m.gas_day >= (SELECT MAX(gas_day) FROM {FQ}.fact_daily_measurements) - INTERVAL 6 DAYS
        GROUP BY m.gas_day ORDER BY m.gas_day""", token)
    print(fmt_table(rows, cols) + "\n")

    print("### today's top meters by measured quantity")
    rows, cols = run_sql(f"""
        SELECT d.meter_id, d.meter_name, d.meter_type, m.actual_dth, m.pressure_psig, m.variance_pct
        FROM {FQ}.fact_daily_measurements m JOIN {FQ}.dim_meters d USING (meter_id)
        WHERE m.gas_day = (SELECT MAX(gas_day) FROM {FQ}.fact_daily_measurements)
        ORDER BY m.actual_dth DESC LIMIT 10""", token)
    print(fmt_table(rows, cols) + "\n")
    print("BUILD OK")


if __name__ == "__main__":
    main()
