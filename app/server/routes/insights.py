"""AI insights endpoint — Claude summary of a day's flows via AI Gateway."""
from fastapi import APIRouter
from pydantic import BaseModel

from ..db import query
from ..llm import summarize_day

router = APIRouter()


class InsightRequest(BaseModel):
    flow_date: str | None = None


@router.post("/insights")
def insights(req: InsightRequest):
    """Generate an operational summary for the requested day."""
    if req.flow_date:
        target = req.flow_date
    else:
        latest = query("SELECT MAX(flow_date) AS d FROM fact_daily_measurements")
        target = latest[0]["d"].isoformat()

    rows = query("""
        SELECT d.meter_name, d.meter_type, d.county, d.state,
               m.scheduled_dth, m.actual_dth, m.pressure_psig, m.variance_pct
        FROM fact_daily_measurements m
        JOIN dim_meters d USING (meter_id)
        WHERE m.flow_date = %s
        ORDER BY m.actual_dth DESC
    """, (target,))

    receipts = sum(r["actual_dth"] for r in rows if r["meter_type"] == "RECEIPT")
    deliveries = sum(r["actual_dth"] for r in rows if r["meter_type"] in ("DELIVERY", "INTERCONNECT"))

    lines = [f"OkTex daily measurements for {target}:",
             f"System totals: receipts={receipts:,} Dth, "
             f"deliveries+interconnects={deliveries:,} Dth, "
             f"imbalance={receipts - deliveries:,} Dth.",
             "Per-meter (name | type | county,state | scheduled | actual | pressure_psig | variance_pct):"]
    for r in rows:
        lines.append(
            f"- {r['meter_name']} | {r['meter_type']} | {r['county']},{r['state']} | "
            f"{r['scheduled_dth']:,} | {r['actual_dth']:,} | {r['pressure_psig']} | {r['variance_pct']}%"
        )
    context = "\n".join(lines)

    try:
        summary = summarize_day(context)
        return {"flow_date": target, "summary": summary, "model_used": True}
    except Exception as exc:  # graceful fallback so the panel never hard-fails
        fallback = (
            f"On {target}, OkTex received {receipts:,} Dth and delivered {deliveries:,} Dth "
            f"(imbalance {receipts - deliveries:+,} Dth, "
            f"{(receipts - deliveries) / deliveries * 100:+.1f}% vs deliveries). "
            "AI summary is temporarily unavailable; showing computed totals."
        )
        return {"flow_date": target, "summary": fallback, "model_used": False,
                "error": str(exc)[:200]}
