"""OkTex Pipeline Measurement App — FastAPI entry point.

Serves a static single-page frontend (Leaflet map + React-from-CDN) and a
small JSON API backed live by Lakebase Postgres, plus an AI insights endpoint
that calls Claude through the Databricks AI Gateway.
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from server.db import pool
from server.routes import meters, measurements, insights

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail fast if Lakebase is unreachable at startup.
    pool.open(wait=True, timeout=30.0)
    try:
        yield
    finally:
        pool.close()


app = FastAPI(title="OkTex Pipeline Measurements", lifespan=lifespan)

app.include_router(meters.router, prefix="/api")
app.include_router(measurements.router, prefix="/api")
app.include_router(insights.router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok"}


# Static frontend (mounted last so /api/* wins).
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index():
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))
