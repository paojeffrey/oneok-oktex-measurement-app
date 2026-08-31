"""
OkTex (OKT) pipeline data generator — REAL meter stations and route.

Meter names, types, and locations are taken from ONEOK's **public** OKT System
Overview Map (https://www.oneok.com/okt, "OKT System Map" PDF), a georeferenced
Esri ArcGIS export. Coordinates were derived from the map's WGS-84
georeferencing (main viewport GPTS lat 33.35884→36.95256, lon −102.32771→
−97.49879, plus the per-detail-inset viewports for the El Paso and Red River
border areas). This is public infrastructure/regulatory data.

DATA POLICY: The pipeline geography and meter identities are public. All
**measurement quantities** (scheduled/actual Dth, pressure, temperature,
variance) are **synthetic**, generated with a seeded RNG. No ONEOK or customer
operational data is used.

Pure Python standard library only.
"""
from __future__ import annotations
import csv
import math
import random
from datetime import date, timedelta
from pathlib import Path

SEED = 20260828
TODAY = date(2026, 8, 28)
N_DAYS = 60
OPERATOR = "OkTex Pipeline Company, L.L.C. (TSP 80-002-2246)"

# ---------------------------------------------------------------------------
# Real OKT meter stations grouped by the map's station groups / regions.
# (meter_id, name, type, lat, lon, county, state, region, group)
#   type: RECEIPT (green) | DELIVERY (cyan) | BIDIRECTIONAL (bi-directional)
# Coordinates from the public OKT system map's georeferencing.
# ---------------------------------------------------------------------------
METERS = [
    # ---- West Texas: El Paso County (Area 2 inset, lon ~ -106.5) ----
    ("OKT-DN1-01", "Del Norte 1",            "RECEIPT",       31.752, -106.443, "El Paso", "TX", "West Texas — El Paso", "DEL NORTE #1"),
    ("OKT-DN1-02", "Juarez MGI",             "DELIVERY",      31.760, -106.452, "El Paso", "TX", "West Texas — El Paso", "DEL NORTE #1"),
    ("OKT-DN4-01", "7164 Gillette Rd",       "DELIVERY",      31.898, -106.618, "El Paso", "TX", "West Texas — El Paso", "DEL NORTE #4"),
    ("OKT-DN4-02", "7218 Gillette Rd",       "DELIVERY",      31.901, -106.620, "El Paso", "TX", "West Texas — El Paso", "DEL NORTE #4"),
    ("OKT-DN4-03", "Canutillo State Line B.S.", "BIDIRECTIONAL", 31.910, -106.606, "El Paso", "TX", "West Texas — El Paso", "DEL NORTE #4"),
    ("OKT-DN4-04", "El Paso Canutillo",      "DELIVERY",      31.912, -106.598, "El Paso", "TX", "West Texas — El Paso", "DEL NORTE #4"),
    ("OKT-DN4-05", "Gato Rd.",               "DELIVERY",      31.893, -106.620, "El Paso", "TX", "West Texas — El Paso", "DEL NORTE #4"),
    ("OKT-DN4-06", "PNM-Canutillo",          "DELIVERY",      31.919, -106.602, "El Paso", "TX", "West Texas — El Paso", "DEL NORTE #4"),
    ("OKT-DN4-07", "Strahan Rd",             "DELIVERY",      31.905, -106.604, "El Paso", "TX", "West Texas — El Paso", "DEL NORTE #4"),
    ("OKT-DN4-08", "TGS-Canutillo",          "DELIVERY",      31.921, -106.592, "El Paso", "TX", "West Texas — El Paso", "DEL NORTE #4"),
    ("OKT-DN4-09", "WGI Canutillo",          "DELIVERY",      31.914, -106.586, "El Paso", "TX", "West Texas — El Paso", "DEL NORTE #4"),
    ("OKT-DN5-01", "Anthony Farmer's Gin",   "RECEIPT",       32.003, -106.603, "El Paso", "TX", "West Texas — El Paso", "DEL NORTE #5"),
    ("OKT-DN5-02", "El Paso Anthony",        "DELIVERY",      32.001, -106.598, "El Paso", "TX", "West Texas — El Paso", "DEL NORTE #5"),
    ("OKT-DN5-03", "FM RD 1905",             "DELIVERY",      31.994, -106.610, "El Paso", "TX", "West Texas — El Paso", "DEL NORTE #5"),
    ("OKT-DN5-04", "Frank Lehman",           "BIDIRECTIONAL", 32.006, -106.612, "El Paso", "TX", "West Texas — El Paso", "DEL NORTE #5"),
    ("OKT-DN5-05", "PNM-Anthony",            "BIDIRECTIONAL", 32.012, -106.601, "El Paso", "TX", "West Texas — El Paso", "DEL NORTE #5"),
    ("OKT-DN5-06", "TGS-Anthony",            "BIDIRECTIONAL", 32.004, -106.591, "El Paso", "TX", "West Texas — El Paso", "DEL NORTE #5"),

    # ---- Red River border crossings (TX/OK, lat ~34) ----
    ("OKT-OK1-01", "Jackson T. Hardeman",    "RECEIPT",       34.302, -99.742, "Hardeman", "TX", "Red River Border", "OK #1"),
    ("OKT-OK1-02", "OK-1 Atmos FT624",       "DELIVERY",      34.308, -99.732, "Harmon",   "OK", "Red River Border", "OK #1"),
    ("OKT-OK1-03", "OK-1 Atmos FT688",       "DELIVERY",      34.311, -99.724, "Harmon",   "OK", "Red River Border", "OK #1"),
    ("OKT-OK1-04", "OK-1 CB (192135)",       "DELIVERY",      34.299, -99.750, "Hardeman", "TX", "Red River Border", "OK #1"),
    ("OKT-OK2-01", "Jackson T. Wilbarger",   "RECEIPT",       34.142, -99.098, "Wilbarger","TX", "Red River Border", "OK #2"),
    ("OKT-OK2-02", "OK-2 CB (192136)",       "DELIVERY",      34.150, -99.089, "Tillman",  "OK", "Red River Border", "OK #2"),
    ("OKT-OK3-01", "Jackson T. Wichita",     "RECEIPT",       34.128, -98.502, "Wichita",  "TX", "Red River Border", "OK #3"),
    ("OKT-OK3-02", "OK-3 Atmos FT3405",      "DELIVERY",      34.136, -98.492, "Tillman",  "OK", "Red River Border", "OK #3"),
    ("OKT-OK3-03", "OK-3 CB (192137)",       "DELIVERY",      34.124, -98.512, "Wichita",  "TX", "Red River Border", "OK #3"),
    ("OKT-OK4-01", "Atmos OK-4",             "BIDIRECTIONAL", 34.201, -98.204, "Cotton",   "OK", "Red River Border", "OK #4"),
    ("OKT-OK4-02", "OK-4 Rec",               "RECEIPT",       34.208, -98.192, "Cotton",   "OK", "Red River Border", "OK #4"),

    # ---- Western / Central Oklahoma cluster (the main red line) ----
    ("OKT-OK9-01", "WesTex Hemphill IC",     "BIDIRECTIONAL", 35.800, -100.240, "Hemphill", "TX", "Western Oklahoma", "OK #9"),
    ("OKT-OK9-02", "Reydon TBS",             "DELIVERY",      35.603, -99.770,  "Roger Mills","OK", "Western Oklahoma", "OK #9"),
    ("OKT-OK9-03", "OFS Viper Fuel Gas",     "DELIVERY",      35.869, -99.799,  "Roger Mills","OK", "Western Oklahoma", "OK #9"),
    ("OKT-OK9-04", "OFS Compressor Fuel",    "DELIVERY",      35.789, -99.472,  "Dewey",    "OK", "Western Oklahoma", "OK #9"),
    ("OKT-OK9-05", "OFS Crescendo Fuel Gas", "DELIVERY",      35.801, -99.451,  "Dewey",    "OK", "Western Oklahoma", "OK #9"),
    ("OKT-OK9-06", "OFS Leedy Plant",        "RECEIPT",       35.812, -99.462,  "Dewey",    "OK", "Western Oklahoma", "OK #9"),
    ("OKT-OK9-07", "OGT-Pool",               "DELIVERY",      35.749, -99.168,  "Custer",   "OK", "Western Oklahoma", "OK #9"),
    ("OKT-OK9-08", "OGT Aledo",              "DELIVERY",      35.916, -99.227,  "Dewey",    "OK", "Western Oklahoma", "OK #9"),
    ("OKT-OK9-09", "PEPL Aledo",             "DELIVERY",      35.899, -98.966,  "Blaine",   "OK", "Western Oklahoma", "OK #9"),
    # OK #12 — northern/eastern deliveries
    ("OKT-O12-01", "Enogex",                 "DELIVERY",      36.282, -98.260,  "Major",    "OK", "Central Oklahoma", "OK #12"),
    ("OKT-O12-02", "OGT Lefty",              "DELIVERY",      36.080, -98.183,  "Blaine",   "OK", "Central Oklahoma", "OK #12"),
    ("OKT-O12-03", "Mustang/Rodman Residue", "RECEIPT",       36.094, -97.787,  "Kingfisher","OK", "Central Oklahoma", "OK #12"),
    ("OKT-O12-04", "Southern Star",          "DELIVERY",      36.662, -98.044,  "Garfield", "OK", "Central Oklahoma", "OK #12"),
    # CAPROCK OK #11 — southern bi-directional spur
    ("OKT-O11-01", "OWT Red River",          "BIDIRECTIONAL", 35.381, -99.736,  "Roger Mills","OK", "Caprock Spur", "CAPROCK OK #11"),
    ("OKT-O11-02", "OGT Caprock",            "BIDIRECTIONAL", 35.242, -99.733,  "Beckham",  "OK", "Caprock Spur", "CAPROCK OK #11"),
]

# Capacity (Dth/d) by role — receipts/interconnects larger than local deliveries.
CAP_BY_TYPE = {"RECEIPT": (90000, 150000), "BIDIRECTIONAL": (70000, 130000), "DELIVERY": (25000, 80000)}
DIA_BY_TYPE = {"RECEIPT": 24, "BIDIRECTIONAL": 24, "DELIVERY": 16}

# ---------------------------------------------------------------------------
# Pipeline route as named segments (each drawn as its own polyline). Follows
# the red "OkTex Pipeline" line on the public overview map.
# ---------------------------------------------------------------------------
ROUTE_SEGMENTS = [
    ("West Texas — El Paso lateral", [
        (31.752, -106.443), (31.812, -106.520), (31.910, -106.606), (32.003, -106.603)]),
    ("Oklahoma mainline", [
        (35.800, -100.240), (35.869, -99.799), (35.801, -99.451), (35.749, -99.168),
        (35.916, -99.227), (35.899, -98.966), (36.282, -98.260), (36.662, -98.044)]),
    ("Enogex east spur", [
        (36.282, -98.260), (36.080, -98.183), (36.094, -97.787)]),
    ("Caprock spur (OK-11)", [
        (35.603, -99.770), (35.381, -99.736), (35.242, -99.733)]),
    ("Red River border feed", [
        (34.302, -99.742), (34.700, -99.760), (35.242, -99.733)]),
    ("Wilbarger/Wichita feed", [
        (34.128, -98.502), (34.142, -99.098), (34.700, -99.400), (35.603, -99.770)]),
]


def build_meters():
    random.seed(SEED)
    rows = []
    for (mid, name, mtype, lat, lon, county, state, region, group) in METERS:
        lo, hi = CAP_BY_TYPE[mtype]
        rows.append({
            "meter_id": mid,
            "meter_name": name,
            "meter_type": mtype,
            "latitude": lat,
            "longitude": lon,
            "county": county,
            "state": state,
            "segment": region,
            "station_group": group,
            "pipe_diameter_in": DIA_BY_TYPE[mtype],
            "capacity_dth": int(round(random.uniform(lo, hi), -3)),
            "operator": OPERATOR,
            "status": "ACTIVE",
        })
    return rows


def build_segments():
    rows = []
    seq = 0
    for name, pts in ROUTE_SEGMENTS:
        for (lat, lon) in pts:
            seq += 1
            rows.append({"seq": seq, "latitude": lat, "longitude": lon, "segment_name": name})
    return rows


def _season_factor(d: date) -> float:
    doy = d.timetuple().tm_yday
    seasonal = 1.0 + 0.18 * math.cos((doy - 15) / 365.0 * 2 * math.pi)
    weekday = 1.03 if d.weekday() < 5 else 0.95
    return seasonal * weekday


def build_measurements(meters):
    """Daily scheduled/actual quantities per meter for the last N_DAYS.

    Receipts (supply) balanced against deliveries + net bidirectional each day
    with realistic line-pack noise.
    """
    random.seed(SEED + 1)
    rows = []
    base_frac = {m["meter_id"]: random.uniform(0.55, 0.82) for m in meters}
    recv = [m for m in meters if m["meter_type"] == "RECEIPT"]
    demand = [m for m in meters if m["meter_type"] in ("DELIVERY", "BIDIRECTIONAL")]

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
        balance = (total_recv / total_dem) * random.uniform(0.985, 1.015) if total_dem else 1.0
        for mid in dem_sched:
            dem_sched[mid] *= balance

        for m in meters:
            mid = m["meter_id"]
            scheduled = recv_sched.get(mid, dem_sched.get(mid, 0.0))
            actual = scheduled * random.uniform(0.94, 1.06)
            variance = (actual - scheduled) / scheduled * 100 if scheduled else 0.0
            pressure = round(random.uniform(650, 900) * (0.9 + 0.2 * base_frac[mid]), 1)
            temp = round(50 + 45 * _season_factor(d) / 1.2 + random.uniform(-6, 6), 1)
            rows.append({
                "gas_day": d.isoformat(),
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
    print(f"meters={len(meters)} route_vertices={len(segments)} measurements={len(measurements)}")
    types = {}
    for m in meters:
        types[m["meter_type"]] = types.get(m["meter_type"], 0) + 1
    print("by type:", types)
    print(f"wrote CSVs to {here}")
