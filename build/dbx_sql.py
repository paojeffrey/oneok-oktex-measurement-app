"""Minimal Databricks SQL Statement Execution API client (stdlib only).

Auth uses a short-lived OAuth token fetched from the Databricks CLI profile,
so no PAT is stored in the repo.
"""
from __future__ import annotations
import json
import os
import ssl
import subprocess
import time
import urllib.request
import urllib.error
from pathlib import Path

PROFILE = "fe-vm-stable-classic-wg38i9"
HOST = "https://fevm-stable-classic-wg38i9.cloud.databricks.com"
WAREHOUSE_ID = "4c06524b26564b9c"
CATALOG = "stable_classic_wg38i9_catalog"
SCHEMA = "oneok_okt"


def _ca_bundle() -> str | None:
    """Return a path to a keychain-derived CA bundle (macOS), building it once."""
    env = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    if env and Path(env).exists():
        return env
    bundle = Path(__file__).resolve().parent / ".ca_bundle.pem"
    if bundle.exists():
        return str(bundle)
    keychains = [
        "/System/Library/Keychains/SystemRootCertificates.keychain",
        "/Library/Keychains/System.keychain",
    ]
    pem = b""
    for kc in keychains:
        try:
            pem += subprocess.check_output(
                ["security", "find-certificate", "-a", "-p", kc],
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass
    if b"BEGIN CERTIFICATE" in pem:
        bundle.write_bytes(pem)
        return str(bundle)
    return None


def _context() -> ssl.SSLContext:
    ca = _ca_bundle()
    if ca:
        return ssl.create_default_context(cafile=ca)
    return ssl.create_default_context()


_CTX = _context()


def get_token(profile: str = PROFILE) -> str:
    out = subprocess.check_output(
        ["databricks", "auth", "token", "--profile", profile],
        text=True,
    )
    return json.loads(out)["access_token"]


def _post(path: str, body: dict, token: str) -> dict:
    req = urllib.request.Request(
        HOST + path,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120, context=_CTX) as r:
        return json.loads(r.read().decode())


def _get(path: str, token: str) -> dict:
    req = urllib.request.Request(
        HOST + path, headers={"Authorization": f"Bearer {token}"}, method="GET"
    )
    with urllib.request.urlopen(req, timeout=120, context=_CTX) as r:
        return json.loads(r.read().decode())


def run_sql(statement: str, token: str | None = None, catalog: str = CATALOG,
            schema: str = SCHEMA):
    """Execute a SQL statement and return (rows, columns). Raises on error."""
    token = token or get_token()
    body = {
        "warehouse_id": WAREHOUSE_ID,
        "statement": statement,
        "catalog": catalog,
        "schema": schema,
        "wait_timeout": "50s",
        "disposition": "INLINE",
        "format": "JSON_ARRAY",
    }
    resp = _post("/api/2.0/sql/statements", body, token)
    stmt_id = resp.get("statement_id")
    state = resp.get("status", {}).get("state")
    # Poll if still running.
    while state in ("PENDING", "RUNNING"):
        time.sleep(1.5)
        resp = _get(f"/api/2.0/sql/statements/{stmt_id}", token)
        state = resp.get("status", {}).get("state")
    if state != "SUCCEEDED":
        err = resp.get("status", {}).get("error", {})
        raise RuntimeError(f"SQL {state}: {err.get('message', err)}\n---\n{statement[:500]}")
    cols = [c["name"] for c in resp.get("manifest", {}).get("schema", {}).get("columns", [])]
    rows = resp.get("result", {}).get("data_array", []) or []
    return rows, cols


def fmt_table(rows, cols, max_rows: int = 20) -> str:
    """Render rows/cols as a fixed-width text table (readable evidence)."""
    if not cols:
        return "(no columns)"
    display = rows[:max_rows]
    widths = [len(c) for c in cols]
    for r in display:
        for i, v in enumerate(r):
            widths[i] = max(widths[i], len(str(v)))
    line = " | ".join(c.ljust(widths[i]) for i, c in enumerate(cols))
    sep = "-+-".join("-" * widths[i] for i in range(len(cols)))
    body = "\n".join(
        " | ".join(str(v).ljust(widths[i]) for i, v in enumerate(r)) for r in display
    )
    extra = f"\n... ({len(rows) - max_rows} more rows)" if len(rows) > max_rows else ""
    return f"{line}\n{sep}\n{body}{extra}"
