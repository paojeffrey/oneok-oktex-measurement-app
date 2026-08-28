"""Foundation Model (Claude) access via Databricks Model Serving.

Uses the workspace serving-endpoints OpenAI-compatible path. (The legacy
ai-gateway/mlflow path is deprecated in this workspace in favor of Unity
Catalog model services, so we target the serving endpoint directly.)
"""
import os

from openai import OpenAI

from .config import get_oauth_token, get_workspace_host


def _client() -> OpenAI:
    base = os.environ.get("SERVING_BASE_URL")
    if not base:
        base = f"{get_workspace_host().rstrip('/')}/serving-endpoints"
    token = os.environ.get("DATABRICKS_TOKEN") or get_oauth_token()
    return OpenAI(api_key=token, base_url=base)


def summarize_day(context: str, model: str | None = None) -> str:
    """Ask Claude for a concise operational summary of the day's flows."""
    model = model or os.environ.get("SERVING_ENDPOINT", "databricks-claude-sonnet-5")
    system = (
        "You are a natural-gas pipeline operations analyst for the OkTex (OKT) "
        "system. Given a table of today's meter measurements, write a concise, "
        "professional 3-4 sentence operational summary. Call out total receipts vs "
        "deliveries and system balance, any meters with notably high scheduled-vs-"
        "actual variance, and one actionable observation. Use Dth units. "
        "All data is synthetic demo data."
    )
    resp = _client().chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": context},
        ],
        max_tokens=400,
    )
    return resp.choices[0].message.content.strip()
