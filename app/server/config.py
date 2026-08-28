"""Environment detection + auth helpers (dual-mode: Databricks App vs local)."""
import os
from functools import lru_cache

from databricks.sdk import WorkspaceClient

# Databricks Apps set DATABRICKS_APP_NAME in the runtime environment.
IS_DATABRICKS_APP = bool(os.environ.get("DATABRICKS_APP_NAME"))


@lru_cache(maxsize=1)
def get_workspace_client() -> WorkspaceClient:
    """Authenticated WorkspaceClient.

    Remote: uses the app's auto-injected service-principal credentials.
    Local:  uses a Databricks CLI profile (DATABRICKS_PROFILE env var).
    """
    if IS_DATABRICKS_APP:
        return WorkspaceClient()
    profile = os.environ.get("DATABRICKS_PROFILE", "DEFAULT")
    return WorkspaceClient(profile=profile)


def get_oauth_token() -> str:
    """OAuth bearer token for the current identity."""
    client = get_workspace_client()
    headers = client.config.authenticate()
    if headers and "Authorization" in headers:
        return headers["Authorization"].replace("Bearer ", "")
    # Fallback for PAT-style configs.
    return client.config.token or ""


def get_workspace_host() -> str:
    """Workspace host URL with https:// scheme."""
    if IS_DATABRICKS_APP:
        host = os.environ.get("DATABRICKS_HOST", "")
        if host and not host.startswith("http"):
            host = f"https://{host}"
        return host
    return get_workspace_client().config.host
