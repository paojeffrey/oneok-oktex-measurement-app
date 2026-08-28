"""Sync OkTex measurement data from the local generator (mirrors the Delta
tables) into Lakebase Postgres, then verify with real row-count queries.

Uses psql over an OAuth token — no third-party Python driver needed, which
keeps this runnable in a locked-down environment. The app reads these same
tables live from Lakebase at request time.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_data import build_meters, build_segments, build_measurements  # noqa: E402

PROFILE = "fe-vm-stable-classic-wg38i9"
PROJECT = "oktex"
BRANCH = "production"
ENDPOINT = "primary"
ENDPOINT_PATH = f"projects/{PROJECT}/branches/{BRANCH}/endpoints/{ENDPOINT}"
BRANCH_PATH = f"projects/{PROJECT}/branches/{BRANCH}"
DB = "oktex"
PSQL = os.environ.get("PSQL_BIN", "/opt/homebrew/opt/postgresql@16/bin/psql")


def _cli(args: list[str]) -> str:
    return subprocess.check_output(["databricks", *args, "-p", PROFILE], text=True)


def conn_info():
    host = json.loads(_cli(["postgres", "list-endpoints", BRANCH_PATH, "-o", "json"]))[0][
        "status"]["hosts"]["host"]
    token = json.loads(_cli(["postgres", "generate-database-credential", ENDPOINT_PATH,
                             "-o", "json"]))["token"]
    email = json.loads(_cli(["current-user", "me", "-o", "json"]))["userName"]
    return host, token, email


def psql(host, token, email, dbname, sql=None, sql_file=None):
    conn = f"host={host} port=5432 dbname={dbname} user={email} sslmode=require"
    env = {**os.environ, "PGPASSWORD": token}
    cmd = [PSQL, conn, "-v", "ON_ERROR_STOP=1"]
    if sql_file:
        cmd += ["-f", sql_file]
    else:
        cmd += ["-c", sql]
    return subprocess.run(cmd, env=env, text=True, capture_output=True)


def sql_str(v):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def main():
    host, token, email = conn_info()
    print(f"# Lakebase sync -> {host}  db={DB}\n")

    # 1. Create database (idempotent).
    print("## Step 1: create database")
    r = psql(host, token, email, "postgres",
             f"SELECT 1 FROM pg_database WHERE datname='{DB}'")
    if "1 row" not in r.stdout:
        r = psql(host, token, email, "postgres", f"CREATE DATABASE {DB}")
        print(r.stdout.strip() or r.stderr.strip())
    print(f"database '{DB}' ready\n")

    meters = build_meters()
    segments = build_segments()
    measurements = build_measurements(meters)

    # 2. Schema + data via a single SQL script (fast, transactional).
    print("## Step 2: create tables and load rows")
    parts = ["""
DROP VIEW IF EXISTS v_latest_measurements;
DROP TABLE IF EXISTS fact_daily_measurements CASCADE;
DROP TABLE IF EXISTS pipeline_segments CASCADE;
DROP TABLE IF EXISTS dim_meters CASCADE;

CREATE TABLE dim_meters (
    meter_id TEXT PRIMARY KEY,
    meter_name TEXT, meter_type TEXT,
    latitude DOUBLE PRECISION, longitude DOUBLE PRECISION,
    county TEXT, state TEXT, segment TEXT,
    pipe_diameter_in INT, capacity_dth BIGINT,
    operator TEXT, status TEXT, commissioned_year INT
);
CREATE TABLE pipeline_segments (
    seq INT PRIMARY KEY, latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION, segment_name TEXT
);
CREATE TABLE fact_daily_measurements (
    flow_date DATE, meter_id TEXT REFERENCES dim_meters(meter_id),
    scheduled_dth BIGINT, actual_dth BIGINT,
    pressure_psig DOUBLE PRECISION, temperature_f DOUBLE PRECISION,
    variance_pct DOUBLE PRECISION,
    PRIMARY KEY (flow_date, meter_id)
);
"""]

    def insert(table, cols, rows):
        vals = ",\n".join("(" + ",".join(sql_str(r[c]) for c in cols) + ")" for r in rows)
        return f"INSERT INTO {table} ({','.join(cols)}) VALUES {vals};\n"

    parts.append(insert("dim_meters", list(meters[0].keys()), meters))
    parts.append(insert("pipeline_segments", list(segments[0].keys()), segments))
    # batch measurements to keep statements a reasonable size
    fcols = list(measurements[0].keys())
    for i in range(0, len(measurements), 300):
        parts.append(insert("fact_daily_measurements", fcols, measurements[i:i + 300]))

    parts.append("""
CREATE INDEX IF NOT EXISTS idx_meas_date ON fact_daily_measurements(flow_date);
CREATE OR REPLACE VIEW v_latest_measurements AS
  SELECT m.*, d.meter_name, d.meter_type, d.latitude, d.longitude, d.county, d.state, d.segment
  FROM fact_daily_measurements m JOIN dim_meters d USING (meter_id)
  WHERE m.flow_date = (SELECT MAX(flow_date) FROM fact_daily_measurements);
GRANT SELECT ON ALL TABLES IN SCHEMA public TO PUBLIC;
""")

    with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False) as f:
        f.write("\n".join(parts))
        script = f.name
    r = psql(host, token, email, DB, sql_file=script)
    os.unlink(script)
    if r.returncode != 0:
        print("STDERR:", r.stderr[-2000:])
        raise SystemExit("load failed")
    print("tables created and loaded\n")

    # 3. Verify with real queries.
    print("## Step 3: verification (live psql against Lakebase)")
    checks = [
        ("row counts", """SELECT 'dim_meters' AS table_name, COUNT(*) AS rows FROM dim_meters
            UNION ALL SELECT 'pipeline_segments', COUNT(*) FROM pipeline_segments
            UNION ALL SELECT 'fact_daily_measurements', COUNT(*) FROM fact_daily_measurements
            ORDER BY table_name;"""),
        ("date coverage", """SELECT MIN(flow_date) first_day, MAX(flow_date) last_day,
            COUNT(DISTINCT flow_date) days FROM fact_daily_measurements;"""),
        ("today's flow by meter type", """SELECT meter_type, COUNT(*) meters,
            SUM(actual_dth) total_actual_dth
            FROM v_latest_measurements GROUP BY meter_type ORDER BY meter_type;"""),
        ("sample: today's top 8 meters", """SELECT meter_id, meter_name, meter_type,
            actual_dth, pressure_psig, variance_pct
            FROM v_latest_measurements ORDER BY actual_dth DESC LIMIT 8;"""),
    ]
    for label, q in checks:
        print(f"### {label}")
        r = psql(host, token, email, DB, q)
        print(r.stdout.strip() + "\n")
    print("LAKEBASE SYNC OK")


if __name__ == "__main__":
    main()
