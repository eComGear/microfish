"""
Supabase storage helpers for MiroFish backend.

All reads use .limit(1).execute() instead of .single()/.maybe_single() to avoid
PGRST116 noise. All writes upsert and then re-read to verify the row landed.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional
from urllib.parse import urlparse, urlunparse

from supabase import Client, create_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

_client: Optional[Client] = None


def _normalize_supabase_url(raw_url: str) -> str:
    """
    supabase-py expects https://<project>.supabase.co (no /rest/v1 suffix).
    If the env var was misconfigured with /rest/v1, strip it; otherwise PostgREST
    returns PGRST125 'Invalid path specified in request URL'.
    """
    url = (raw_url or "").strip().rstrip("/")
    if not url:
        return url
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return url
    path = parsed.path.rstrip("/")
    marker = "/rest/v1"
    if path == marker or path.endswith(marker) or f"{marker}/" in path:
        path = path.split(marker, 1)[0]
    normalized = urlunparse(
        (parsed.scheme, parsed.netloc, path.rstrip("/"), "", "", "")
    )
    normalized = normalized.rstrip("/")
    if normalized != url:
        logger.warning(
            f"SUPABASE_URL normalized: {url!r} -> {normalized!r} (stripped /rest/v1)"
        )
    return normalized


def client() -> Client:
    global _client
    if _client is not None:
        return _client

    raw_url = os.environ.get("SUPABASE_URL", "")
    key = (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_SERVICE_KEY")
        or os.environ.get("SUPABASE_KEY", "")
    )
    url = _normalize_supabase_url(raw_url)
    if not url or not key:
        raise RuntimeError(
            "Supabase env missing: need SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY"
        )

    _client = create_client(url, key)
    logger.info(f"Supabase client initialized url={url}")
    return _client


# ---------------------------------------------------------------------------
# Column whitelists  (only fields we actually persist)
# ---------------------------------------------------------------------------

PROJECT_COLUMNS = {
    "project_id",
    "user_id",
    "name",
    "title",
    "description",
    "status",
    "graph_id",
    "metadata",
    "created_at",
    "updated_at",
}

SIMULATION_COLUMNS = {
    "simulation_id",
    "project_id",
    "graph_id",
    "name",
    "title",
    "status",
    "config",
    "result",
    "metadata",
    "created_at",
    "updated_at",
}

EXTRACTED_TEXT_COLUMNS = {
    "project_id",
    "source_id",
    "content",
    "text",
    "metadata",
    "created_at",
    "updated_at",
}


def _filter(payload: dict, allowed: set[str]) -> dict:
    return {k: v for k, v in (payload or {}).items() if k in allowed and v is not None}


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


def upsert_project(row: dict) -> dict:
    pid = (row or {}).get("project_id")
    if not isinstance(pid, str) or not pid:
        raise ValueError(f"upsert_project: invalid project_id={pid!r}")

    payload = _filter(row, PROJECT_COLUMNS)
    try:
        client().table("projects").upsert(payload, on_conflict="project_id").execute()
        check = (
            client()
            .table("projects")
            .select("*")
            .eq("project_id", pid)
            .limit(1)
            .execute()
        )
        if not check.data:
            raise RuntimeError(
                f"upsert_project: row not visible after write project_id={pid}"
            )
        logger.info(f"upsert_project OK {pid}")
        return check.data[0]
    except Exception as e:
        logger.error(f"upsert_project FAILED for {pid}: {e}")
        raise


def get_project(project_id: str) -> Optional[dict]:
    if not isinstance(project_id, str) or not project_id:
        return None
    try:
        res = (
            client()
            .table("projects")
            .select("*")
            .eq("project_id", project_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None
    except Exception as e:
        logger.error(f"get_project FAILED {project_id}: {e}")
        return None


# ---------------------------------------------------------------------------
# Simulations
# ---------------------------------------------------------------------------


def upsert_simulation(row: dict) -> dict:
    sim_id = (row or {}).get("simulation_id")
    if not isinstance(sim_id, str) or not sim_id:
        raise ValueError(f"upsert_simulation: invalid simulation_id={sim_id!r}")

    payload = _filter(row, SIMULATION_COLUMNS)
    try:
        client().table("engine_simulations").upsert(
            payload, on_conflict="simulation_id"
        ).execute()
        check = (
            client()
            .table("engine_simulations")
            .select("*")
            .eq("simulation_id", sim_id)
            .limit(1)
            .execute()
        )
        if not check.data:
            raise RuntimeError(
                f"upsert_simulation: row not visible after write sim_id={sim_id}"
            )
        logger.info(f"upsert_simulation OK {sim_id}")
        return check.data[0]
    except Exception as e:
        logger.error(f"upsert_simulation FAILED {sim_id}: {e}")
        raise


def get_simulation(simulation_id: str) -> Optional[dict]:
    if not isinstance(simulation_id, str) or not simulation_id:
        return None
    try:
        res = (
            client()
            .table("engine_simulations")
            .select("*")
            .eq("simulation_id", simulation_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            logger.warning(f"get_simulation: not found {simulation_id}")
            return None
        return rows[0]
    except Exception as e:
        logger.error(f"get_simulation FAILED {simulation_id}: {e}")
        return None


def list_simulations_for_project(project_id: str, limit: int = 50) -> list[dict]:
    if not isinstance(project_id, str) or not project_id:
        return []
    try:
        res = (
            client()
            .table("engine_simulations")
            .select("*")
            .eq("project_id", project_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception as e:
        logger.error(f"list_simulations_for_project FAILED {project_id}: {e}")
        return []


# ---------------------------------------------------------------------------
# Extracted text
# ---------------------------------------------------------------------------


def save_extracted_text(project_id: str, content: str = "", **kwargs: Any) -> dict:
    """
    Backwards-compatible signature:
        save_extracted_text(project_id, content)
        save_extracted_text(project_id=..., content=..., source_id=..., metadata=...)
        save_extracted_text(project_id)                # content defaults to ""
        save_extracted_text(project_id, text="...")    # tolerate text= kwarg
    """
    if not isinstance(project_id, str) or not project_id:
        raise ValueError(f"save_extracted_text: invalid project_id={project_id!r}")

    if not content and "text" in kwargs:
        content = kwargs.pop("text") or ""

    payload: dict = {"project_id": project_id, "content": content or ""}
    for k, v in kwargs.items():
        if k in EXTRACTED_TEXT_COLUMNS and v is not None:
            payload[k] = v

    try:
        client().table("extracted_texts").upsert(
            payload, on_conflict="project_id"
        ).execute()
        check = (
            client()
            .table("extracted_texts")
            .select("*")
            .eq("project_id", project_id)
            .limit(1)
            .execute()
        )
        logger.info(
            f"save_extracted_text OK project={project_id} len={len(payload['content'])}"
        )
        return (check.data or [{}])[0]
    except Exception as e:
        logger.error(f"save_extracted_text FAILED project={project_id}: {e}")
        raise


def get_extracted_text(project_id: str) -> Optional[dict]:
    if not isinstance(project_id, str) or not project_id:
        return None
    try:
        res = (
            client()
            .table("extracted_texts")
            .select("*")
            .eq("project_id", project_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None
    except Exception as e:
        logger.error(f"get_extracted_text FAILED project={project_id}: {e}")
        return None
