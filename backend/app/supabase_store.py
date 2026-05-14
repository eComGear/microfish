"""Supabase storage layer for MiroFish backend.

All table names use the `engine_` prefix to match the actual schema.
Reads use `.limit(1).execute()` (never `.single()`/`.maybe_single()`)
to avoid PGRST116 when a row is missing. Writes upsert and then re-read
to verify and return the canonical row.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from supabase import Client, create_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Table names — MUST match actual Supabase schema (engine_ prefix)
# ---------------------------------------------------------------------------
PROJECTS_TABLE = "engine_projects"
SIMULATIONS_TABLE = "engine_simulations"
EXTRACTED_TEXTS_TABLE = "engine_extracted_texts"

# ---------------------------------------------------------------------------
# Column whitelists — only these are sent to Supabase on upsert
# ---------------------------------------------------------------------------
PROJECT_COLUMNS = {
    "project_id",
    "name",
    "description",
    "status",
    "ontology",
    "analysis_summary",
    "metadata",
    "created_at",
    "updated_at",
}

SIMULATION_COLUMNS = {
    "simulation_id",
    "project_id",
    "graph_id",
    "status",
    "config",
    "metadata",
    "created_at",
    "updated_at",
}

EXTRACTED_TEXT_COLUMNS = {
    "id",
    "project_id",
    "source_id",
    "content",
    "metadata",
    "created_at",
}


# ---------------------------------------------------------------------------
# Client singleton
# ---------------------------------------------------------------------------
_client: Optional[Client] = None


def _normalize_supabase_url(url: str) -> str:
    """Strip trailing /rest/v1 (and trailing slash) — supabase-py adds it itself.

    Without this, requests go to /rest/v1/rest/v1/<table> and Supabase returns
    PGRST125 "Invalid path specified in request URL".
    """
    url = url.rstrip("/")
    if url.endswith("/rest/v1"):
        url = url[: -len("/rest/v1")]
    return url


def client() -> Client:
    global _client
    if _client is None:
        url = _normalize_supabase_url(os.environ["SUPABASE_URL"])
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ["SUPABASE_KEY"]
        _client = create_client(url, key)
    return _client


def _filter(data: dict, allowed: set[str]) -> dict:
    return {k: v for k, v in data.items() if k in allowed and v is not None}


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------
def upsert_project(project_id: str, **fields: Any) -> dict:
    payload = _filter({"project_id": project_id, **fields}, PROJECT_COLUMNS)
    try:
        client().table(PROJECTS_TABLE).upsert(payload, on_conflict="project_id").execute()
    except Exception as exc:
        logger.error("upsert_project FAILED for %s: %s", project_id, exc)
        raise

    res = (
        client()
        .table(PROJECTS_TABLE)
        .select("*")
        .eq("project_id", project_id)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else payload


def get_project(project_id: str) -> Optional[dict]:
    res = (
        client()
        .table(PROJECTS_TABLE)
        .select("*")
        .eq("project_id", project_id)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# Simulations
# ---------------------------------------------------------------------------
def upsert_simulation(simulation_id: str, **fields: Any) -> dict:
    payload = _filter({"simulation_id": simulation_id, **fields}, SIMULATION_COLUMNS)
    try:
        client().table(SIMULATIONS_TABLE).upsert(
            payload, on_conflict="simulation_id"
        ).execute()
    except Exception as exc:
        logger.error("upsert_simulation FAILED for %s: %s", simulation_id, exc)
        raise

    res = (
        client()
        .table(SIMULATIONS_TABLE)
        .select("*")
        .eq("simulation_id", simulation_id)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else payload


def get_simulation(simulation_id: str) -> Optional[dict]:
    res = (
        client()
        .table(SIMULATIONS_TABLE)
        .select("*")
        .eq("simulation_id", simulation_id)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# Extracted texts
# ---------------------------------------------------------------------------
def save_extracted_text(project_id: str, content: str = "", **kwargs: Any) -> dict:
    """Save extracted text. Tolerates `text=` as alias for `content=`."""
    if not content and "text" in kwargs:
        content = kwargs.pop("text") or ""

    payload = _filter(
        {"project_id": project_id, "content": content, **kwargs},
        EXTRACTED_TEXT_COLUMNS,
    )
    try:
        res = client().table(EXTRACTED_TEXTS_TABLE).insert(payload).execute()
    except Exception as exc:
        logger.error("save_extracted_text FAILED for %s: %s", project_id, exc)
        raise

    rows = res.data or []
    return rows[0] if rows else payload


def get_extracted_text(project_id: str) -> Optional[dict]:
    res = (
        client()
        .table(EXTRACTED_TEXTS_TABLE)
        .select("*")
        .eq("project_id", project_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None
