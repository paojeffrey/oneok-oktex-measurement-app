"""Daily measurement endpoints — the quantities shown on hover + KPIs."""
from datetime import date

from fastapi import APIRouter, Query

from ..db import query

router = APIRouter()


@router.get("/dates")
def get_dates():
    """Available flow dates (for the date picker)."""
    rows = query("SELECT DISTINCT gas_day FROM fact_daily_measurements ORDER BY gas_day DESC")
    return {"dates": [r["gas_day"].isoformat() for r in rows]}


@router.get("/measurements")
def get_measurements(gas_day: str | None = Query(default=None)):
    """Per-meter measured quantities for a given day (defaults to latest)."""
    if gas_day:
        target = gas_day
    else:
        latest = query("SELECT MAX(gas_day) AS d FROM fact_daily_measurements")
        target = latest[0]["d"].isoformat()

    rows = query("""
        SELECT m.meter_id, d.meter_name, d.meter_type, d.latitude, d.longitude,
               d.county, d.state, d.segment, d.capacity_dth,
               m.gas_day, m.scheduled_dth, m.actual_dth,
               m.pressure_psig, m.temperature_f, m.variance_pct
        FROM fact_daily_measurements m
        JOIN dim_meters d USING (meter_id)
        WHERE m.gas_day = %s
        ORDER BY m.actual_dth DESC
    """, (target,))
    for r in rows:
        r["gas_day"] = r["gas_day"].isoformat()

    receipts = sum(r["actual_dth"] for r in rows if r["meter_type"] == "RECEIPT")
    deliveries = sum(r["actual_dth"] for r in rows if r["meter_type"] in ("DELIVERY", "BIDIRECTIONAL"))
    return {
        "gas_day": target,
        "meters": rows,
        "kpis": {
            "total_receipts_dth": receipts,
            "total_deliveries_dth": deliveries,
            "imbalance_dth": receipts - deliveries,
            "imbalance_pct": round((receipts - deliveries) / deliveries * 100, 2) if deliveries else 0.0,
            "active_meters": len(rows),
        },
    }


@router.get("/trend")
def get_trend():
    """System-wide daily receipts vs deliveries over the full history."""
    rows = query("""
        SELECT m.gas_day,
               SUM(CASE WHEN d.meter_type='RECEIPT' THEN m.actual_dth ELSE 0 END) AS receipts_dth,
               SUM(CASE WHEN d.meter_type IN ('DELIVERY','BIDIRECTIONAL') THEN m.actual_dth ELSE 0 END) AS deliveries_dth
        FROM fact_daily_measurements m
        JOIN dim_meters d USING (meter_id)
        GROUP BY m.gas_day
        ORDER BY m.gas_day
    """)
    for r in rows:
        r["gas_day"] = r["gas_day"].isoformat()
    return {"trend": rows}


@router.get("/meter/{meter_id}/history")
def get_meter_history(meter_id: str):
    """Full daily history for a single meter (drill-down)."""
    rows = query("""
        SELECT gas_day, scheduled_dth, actual_dth, pressure_psig, variance_pct
        FROM fact_daily_measurements
        WHERE meter_id = %s
        ORDER BY gas_day
    """, (meter_id,))
    for r in rows:
        r["gas_day"] = r["gas_day"].isoformat()
    return {"meter_id": meter_id, "history": rows}
