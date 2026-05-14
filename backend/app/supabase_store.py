"""Supabase storage layer for MiroFish backend.

All reads use .limit(1).execute() instead of .single() / .maybe_single() to
avoid PGRST125 ("Invalid path specified in request URL") seen in some
supabase-py versions. All writes filter to known columns and re-read after
upsert to confirm the row landed.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional
from urllib.parse import urlparse, urlunparse

from supabase import Client, create_client

logger = logging.getLogger(__name__)

# ---------- client ----------

_client: Optional[Client] = None


def _normalize_supabase_url(raw_url: str) -> str:
    """Strip trailing /rest/v1 if present — supabase-py appends it itself."""
    url = (raw_url or "").strip().rstrip("/")
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return url
    path = parsed.path.rstrip("/")
    marker = "/rest/v1"
    if path == marker or path.endswith(marker) or f"{marker}/" in path:
        path = path.split(marker, 1)[0]
    normalized = urlunparse((parsed.scheme, parsed.netloc, path.rstrip("/"), "", "", ""))
    return normalized.rstrip("/")


def client() -> Client:
    global _client
    if _client is not None:
        return _client
    raw_url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY", "")
    url = _normalize_supabase_url(raw_url)
    if url != raw_url:
        logger.warning(f"SUPABASE_URL normalized: {raw_url!r} -> {url!r}")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set")
    _client = create_client(url, key)
    return _client


# ---------- column whitelists ----------

PROJECT_COLUMNS = {
    "project_id", "name", "description", "status",
    "ontology", "analysis_summary", "files",
    "simulation_requirement", "additional_context",
    "total_text_length", "graph_id",
    "created_at", "updated_at",
}

SIMULATION_COLUMNS = {
    "simulation_id", "project_id", "graph_id", "name", "status",
    "num_agents", "num_rounds", "current_round", "config",
    "enable_twitter", "enable_reddit",
    "created_at", "updated_at",
}

EXTRACTED_TEXT_COLUMNS = {
    "project_id", "filename", "content", "size", "created_at",
}


def _filter(row: dict, allowed: set[str]) -> dict:
    return {k: v for k, v in (row or {}).items() if k in allowed and v is not None}


# ---------- projects ----------

def upsert_project(row: dict) -> dict:
    pid = (row or {}).get("project_id")
    if not isinstance(pid, str) or not pid:
        raise ValueError(f"upsert_project: invalid project_id={pid!r}")

    payload = _filter(row, PROJECT_COLUMNS)
    payload["project_id"] = pid

    logger.info(f"upsert_project -> {pid} keys={list(payload.keys())}")
    try:
        res = (
            client()
            .table("engine_projects")
            .upsert(payload, on_conflict="project_id")
            .execute()
        )
        data = res.data or []
        if not data:
            check = (
                client()
                .table("engine_projects")
                .select("*")
                .eq("project_id", pid)
                .limit(1)
                .execute()
            )
            data = check.data or []
        if not data:
            raise RuntimeError(f"upsert_project: row not visible after write pid={pid}")
        logger.info(f"upsert_project OK {pid}")
        return data[0]
    except Exception as e:
        logger.error(f"upsert_project FAILED {pid}: {e}")
        raise


def get_project(project_id: str) -> Optional[dict]:
    if not isinstance(project_id, str) or not project_id:
        logger.warning(f"get_project: invalid id={project_id!r}")
        return None
    logger.info(f"get_project -> {project_id}")
    try:
        res = (
            client()
            .table("engine_projects")
            .select("*")
            .eq("project_id", project_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            logger.warning(f"get_project: NOT FOUND {project_id}")
            return None
        return rows[0]
    except Exception as e:
        logger.error(f"get_project FAILED {project_id}: {e}")
        raise


# ---------- simulations ----------

def upsert_simulation(row: dict) -> dict:
    sid = (row or {}).get("simulation_id")
    if not isinstance(sid, str) or not sid:
        raise ValueError(f"upsert_simulation: invalid simulation_id={sid!r}")

    payload = _filter(row, SIMULATION_COLUMNS)
    payload["simulation_id"] = sid

    logger.info(f"upsert_simulation -> {sid} keys={list(payload.keys())}")
    try:
        res = (
            client()
            .table("engine_simulations")
            .upsert(payload, on_conflict="simulation_id")
            .execute()
        )
        data = res.data or []
        if not data:
            check = (
                client()
                .table("engine_simulations")
                .select("*")
                .eq("simulation_id", sid)
                .limit(1)
                .execute()
            )
            data = check.data or []
        if not data:
            raise RuntimeError(f"upsert_simulation: row not visible after write sid={sid}")
        logger.info(f"upsert_simulation OK {sid}")
        return data[0]
    except Exception as e:
        logger.error(f"upsert_simulation FAILED {sid}: {e}")
        raise


def get_simulation(simulation_id: str) -> Optional[dict]:
    if not isinstance(simulation_id, str) or not simulation_id:
        logger.warning(f"get_simulation: invalid id={simulation_id!r}")
        return None
    logger.info(f"get_simulation -> {simulation_id}")
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
            logger.warning(f"get_simulation: NOT FOUND {simulation_id}")
            return None
        return rows[0]
    except Exception as e:
        logger.error(f"get_simulation FAILED {simulation_id}: {e}")
        raise


# ---------- extracted text ----------

def save_extracted_text(project_id: str, filename: str, content: str, size: int = 0) -> dict:
    if not project_id or not filename:
        raise ValueError(f"save_extracted_text: bad args pid={project_id!r} fn={filename!r}")
    payload = {
        "project_id": project_id,
        "filename": filename,
        "content": content,
        "size": size or len(content or ""),
    }
    logger.info(f"save_extracted_text -> {project_id}/{filename} size={payload['size']}")
    try:
        res = client().table("engine_extracted_texts").insert(payload).execute()
        data = res.data or []
        if not data:
            raise RuntimeError(f"save_extracted_text: no row returned for {project_id}/{filename}")
        return data[0]
    except Exception as e:
        logger.error(f"save_extracted_text FAILED {project_id}/{filename}: {e}")
        raise


def get_extracted_text(project_id: str) -> list[dict]:
    if not project_id:
        return []
    try:
        res = (
            client()
            .table("engine_extracted_texts")
            .select("*")
            .eq("project_id", project_id)
            .execute()
        )
        return res.data or []
    except Exception as e:
        logger.error(f"get_extracted_text FAILED {project_id}: {e}")
        raise


__all__ = [
    "client",
    "upsert_project", "get_project",
    "upsert_simulation", "get_simulation",
    "save_extracted_text", "get_extracted_text",
]

