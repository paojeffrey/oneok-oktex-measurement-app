"""Lakebase (Postgres) connection pool with fresh-per-connection OAuth tokens.

A custom psycopg Connection subclass mints a fresh Lakebase database credential
every time the pool opens or recycles a connection, so tokens never go stale.
max_lifetime is set below the 1-hour token TTL to force recycles before expiry.

The credential is minted via the REST endpoint POST /api/2.0/postgres/credentials
using the app's authenticated identity. This avoids depending on a specific
databricks-sdk version exposing `WorkspaceClient.postgres` (older SDKs do not).
"""
import os

import psycopg
from psycopg_pool import ConnectionPool
from databricks.sdk import WorkspaceClient

_IS_APP = bool(os.environ.get("DATABRICKS_APP_NAME"))


def _client() -> WorkspaceClient:
    if _IS_APP:
        return WorkspaceClient()
    return WorkspaceClient(profile=os.environ.get("DATABRICKS_PROFILE", "DEFAULT"))


def mint_db_token() -> str:
    """Generate a short-lived Lakebase credential for the configured endpoint."""
    endpoint = os.environ["ENDPOINT_NAME"]
    resp = _client().api_client.do(
        "POST", "/api/2.0/postgres/credentials", body={"endpoint": endpoint}
    )
    return resp["token"]


class OAuthConnection(psycopg.Connection):
    """psycopg Connection that injects a fresh Lakebase OAuth token as password."""

    @classmethod
    def connect(cls, conninfo="", **kwargs):
        kwargs["password"] = mint_db_token()
        return super().connect(conninfo, **kwargs)


def _conninfo() -> str:
    host = os.environ["PGHOST"]
    port = os.environ.get("PGPORT", "5432")
    user = os.environ["PGUSER"]
    database = os.environ.get("PGDATABASE", "oktex")
    sslmode = os.environ.get("PGSSLMODE", "require")
    return f"dbname={database} user={user} host={host} port={port} sslmode={sslmode}"


# Deferred open — opened explicitly in the FastAPI lifespan so startup fails
# fast if the database is unreachable. 45-min recycle beats the 1-hour token.
#
# The Lakebase Autoscaling endpoint scales to zero when idle, which silently
# kills pooled connections ("SSL error: unexpected eof while reading" on next
# use). `check=ConnectionPool.check_connection` pings each connection before
# handing it out and transparently discards/replaces dead ones; min_size=0 lets
# the pool drain to nothing while the endpoint is suspended.
pool = ConnectionPool(
    conninfo=_conninfo(),
    connection_class=OAuthConnection,
    min_size=0,
    max_size=8,
    max_lifetime=2700,
    check=ConnectionPool.check_connection,
    open=False,
)


def query(sql: str, params: tuple | None = None, _retries: int = 2) -> list[dict]:
    """Run a read query and return a list of dict rows.

    Retries transient connection failures — the first request after the
    Autoscaling endpoint wakes from scale-to-zero can still hit a stale socket.
    """
    last_exc = None
    for attempt in range(_retries + 1):
        try:
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, params or ())
                    cols = [c.name for c in cur.description]
                    return [dict(zip(cols, row)) for row in cur.fetchall()]
        except psycopg.OperationalError as exc:
            last_exc = exc
            if attempt < _retries:
                continue
            raise
    raise last_exc  # unreachable, keeps type checkers happy
