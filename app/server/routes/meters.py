"""Meter dimension + pipeline route geometry endpoints."""
from fastapi import APIRouter

from ..db import query

router = APIRouter()


@router.get("/meters")
def get_meters():
    """All meter stations (static dimension) read live from Lakebase."""
    rows = query("""
        SELECT meter_id, meter_name, meter_type, latitude, longitude,
               county, state, segment, pipe_diameter_in, capacity_dth,
               operator, status, commissioned_year
        FROM dim_meters
        ORDER BY meter_id
    """)
    return {"meters": rows}


@router.get("/route")
def get_route():
    """Ordered mainline vertices for the map polyline."""
    rows = query("""
        SELECT seq, latitude, longitude, segment_name
        FROM pipeline_segments
        ORDER BY seq
    """)
    return {"route": rows}
