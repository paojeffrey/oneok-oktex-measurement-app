"""
Synthetic OkTex (OKT) pipeline data generator.

DATA POLICY: This module produces 100% SYNTHETIC data. Meter names, flows,
pressures and temperatures are fabricated. Geographic coordinates are placed
along the publicly documented OKT system-map bounding box
(lat 33.36->36.95, lon -102.33->-97.50 : West Texas Panhandle -> north-central
Oklahoma) purely so the demo map looks realistic. No ONEOK/customer data is used.

Pure Python standard library only (no third-party deps) so it runs anywhere.
"""
from __future__ import annotations
import csv
import json
import math
import random
from datetime import date, timedelta
from pathlib import Path

SEED = 20260828
random.seed(SEED)

# "Today" for the demo (Central Time context from CLAUDE.md).
TODAY = date(2026, 8, 28)
N_DAYS = 60

# ---------------------------------------------------------------------------
# Meter stations along a plausible OKT mainline: West Texas Panhandle -> OK.
# (meter_id, name, type, lat, lon, county, state, region, diameter_in, cap_dth)
# ---------------------------------------------------------------------------
METERS = [
    ("OKT-001", "Levelland Receipt",      "RECEIPT",      33.590, -102.300, "Hockley",   "TX", "West Texas",     24, 120000),
    ("OKT-002", "Lubbock Lateral",        "DELIVERY",     33.580, -101.855, "Lubbock",   "TX", "West Texas",     16,  55000),
    ("OKT-003", "Plainview Interconnect", "INTERCONNECT", 34.184, -101.708, "Hale",      "TX", "West Texas",     20,  70000),
    ("OKT-004", "Tulia Receipt",          "RECEIPT",      34.535, -101.760, "Swisher",   "TX", "West Texas",     20,  85000),
    ("OKT-005", "Canyon Delivery",        "DELIVERY",     34.980, -101.920, "Randall",   "TX", "Panhandle",      16,  42000),
    ("OKT-006", "Amarillo South",         "DELIVERY",     35.150, -101.850, "Potter",    "TX", "Panhandle",      16,  60000),
    ("OKT-007", "Amarillo Hub",           "INTERCONNECT", 35.222, -101.831, "Potter",    "TX", "Panhandle",      30, 140000),
    ("OKT-008", "Carson Receipt",         "RECEIPT",      35.350, -101.380, "Carson",    "TX", "Panhandle",      24, 110000),
    ("OKT-009", "Pampa Delivery",         "DELIVERY",     35.540, -100.960, "Gray",      "TX", "Panhandle",      16,  48000),
    ("OKT-010", "Perryton Receipt",       "RECEIPT",      36.400, -100.800, "Ochiltree", "TX", "Panhandle",      24, 130000),
    ("OKT-011", "Guymon Interconnect",    "INTERCONNECT", 36.680, -101.480, "Texas",     "OK", "OK Panhandle",   20,  75000),
    ("OKT-012", "Beaver Receipt",         "RECEIPT",      36.815, -100.520, "Beaver",    "OK", "OK Panhandle",   24, 100000),
    ("OKT-013", "Woodward Hub",           "INTERCONNECT", 36.433, -99.390,  "Woodward",  "OK", "Western OK",     30, 150000),
    ("OKT-014", "Mooreland Delivery",     "DELIVERY",     36.440, -99.200,  "Woodward",  "OK", "Western OK",     16,  45000),
    ("OKT-015", "Fairview Receipt",       "RECEIPT",      36.270, -98.480,  "Major",     "OK", "Western OK",     20,  80000),
    ("OKT-016", "Enid Delivery",          "DELIVERY",     36.400, -97.880,  "Garfield",  "OK", "North Central",  20,  90000),
    ("OKT-017", "Enid Terminal",          "DELIVERY",     36.420, -97.830,  "Garfield",  "OK", "North Central",  16,  52000),
    ("OKT-018", "Medford Interconnect",   "INTERCONNECT", 36.800, -97.730,  "Grant",     "OK", "North Central",  24,  95000),
    ("OKT-019", "Pond Creek Receipt",     "RECEIPT",      36.670, -97.800,  "Grant",     "OK", "North Central",  20,  70000),
    ("OKT-020", "Kremlin Delivery",       "DELIVERY",     36.550, -97.820,  "Garfield",  "OK", "North Central",  16,  40000),
]

# Ordered mainline vertices (SW -> NE) for drawing the pipeline polyline.
MAINLINE = [
    (33.590, -102.300, "West Texas"),
    (33.580, -101.855, "West Texas"),
    (34.184, -101.708, "West Texas"),
    (34.535, -101.760, "West Texas"),
    (34.980, -101.920, "Panhandle"),
    (35.222, -101.831, "Panhandle"),
    (35.350, -101.380, "Panhandle"),
    (35.540, -100.960, "Panhandle"),
    (36.400, -100.800, "Panhandle"),
    (36.815, -100.520, "OK Panhandle"),
    (36.433, -99.390,  "Western OK"),
    (36.270, -98.480,  "Western OK"),
    (36.400, -97.880,  "North Central"),
    (36.800, -97.730,  "North Central"),
]

OPERATOR = "OkTex Pipeline Company, L.L.C. (TSP 80-002-2246)"


def build_meters():
    random.seed(SEED)
    rows = []
    for (mid, name, mtype, lat, lon, county, state, region, dia, cap) in METERS:
        rows.append({
            "meter_id": mid,
            "meter_name": name,
            "meter_type": mtype,
            "latitude": lat,
            "longitude": lon,
            "county": county,
            "state": state,
            "segment": region,
            "pipe_diameter_in": dia,
            "capacity_dth": cap,
            "operator": OPERATOR,
            "status": "ACTIVE",
            "commissioned_year": random.choice([1998, 2001, 2004, 2007, 2011, 2014]),
        })
    return rows


def build_segments():
    return [
        {"seq": i, "latitude": lat, "longitude": lon, "segment_name": seg}
        for i, (lat, lon, seg) in enumerate(MAINLINE, start=1)
    ]


def _season_factor(d: date) -> float:
    """Gas demand seasonality: higher in winter, plus a weekly weekday bump."""
    doy = d.timetuple().tm_yday
    seasonal = 1.0 + 0.18 * math.cos((doy - 15) / 365.0 * 2 * math.pi)  # peak mid-Jan
    weekday = 1.03 if d.weekday() < 5 else 0.95
    return seasonal * weekday


def build_measurements(meters):
    """Daily scheduled/actual quantities per meter for the last N_DAYS.

    Receipts (supply) are balanced against deliveries+interconnects (demand)
    each day so the pipeline roughly balances, with realistic line-pack noise.
    """
    # Reseed with a distinct stream so measurements are fully reproducible
    # regardless of call order or process.
    random.seed(SEED + 1)
    rows = []
    # Per-meter base as a fraction of capacity (stable utilization profile).
    base_frac = {m["meter_id"]: random.uniform(0.55, 0.82) for m in meters}
    recv = [m for m in meters if m["meter_type"] == "RECEIPT"]
    demand = [m for m in meters if m["meter_type"] in ("DELIVERY", "INTERCONNECT")]

    for i in range(N_DAYS):
        d = TODAY - timedelta(days=N_DAYS - 1 - i)
        sf = _season_factor(d)
        day_jitter = random.uniform(0.97, 1.03)

        def sched(m):
            return m["capacity_dth"] * base_frac[m["meter_id"]] * sf * day_jitter

        recv_sched = {m["meter_id"]: sched(m) for m in recv}
        dem_sched = {m["meter_id"]: sched(m) for m in demand}
        total_recv = sum(recv_sched.values())
        total_dem = sum(dem_sched.values())
        # Scale demand so system balances within ~1.5% line pack.
        balance = (total_recv / total_dem) * random.uniform(0.985, 1.015) if total_dem else 1.0
        for mid in dem_sched:
            dem_sched[mid] *= balance

        for m in meters:
            mid = m["meter_id"]
            scheduled = recv_sched.get(mid, dem_sched.get(mid, 0.0))
            actual = scheduled * random.uniform(0.94, 1.06)  # nomination vs measured
            variance = (actual - scheduled) / scheduled * 100 if scheduled else 0.0
            pressure = round(random.uniform(650, 900) * (0.9 + 0.2 * base_frac[mid]), 1)
            temp = round(50 + 45 * _season_factor(d) / 1.2 + random.uniform(-6, 6), 1)
            rows.append({
                "flow_date": d.isoformat(),
                "meter_id": mid,
                "scheduled_dth": int(round(scheduled)),
                "actual_dth": int(round(actual)),
                "pressure_psig": pressure,
                "temperature_f": temp,
                "variance_pct": round(variance, 2),
            })
    return rows


def write_csvs(outdir: Path):
    outdir.mkdir(parents=True, exist_ok=True)
    meters = build_meters()
    segments = build_segments()
    measurements = build_measurements(meters)

    def dump(name, rows, fields):
        with open(outdir / name, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)

    dump("dim_meters.csv", meters, list(meters[0].keys()))
    dump("pipeline_segments.csv", segments, list(segments[0].keys()))
    dump("fact_daily_measurements.csv", measurements, list(measurements[0].keys()))
    return meters, segments, measurements


if __name__ == "__main__":
    here = Path(__file__).resolve().parent.parent / "data"
    meters, segments, measurements = write_csvs(here)
    print(f"meters={len(meters)} segments={len(segments)} measurements={len(measurements)}")
    print(f"wrote CSVs to {here}")
