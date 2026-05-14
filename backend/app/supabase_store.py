"""
Supabase-backed persistence for projects, simulations, and extracted text.
This is the SOURCE OF TRUTH across all Fly machines — local memory is only
a per-request cache.
"""
import os
import json
import logging
from typing import Any, Optional
from supabase import create_client, Client

log = logging.getLogger(__name__)

_client: Optional[Client] = None


def client() -> Client:
    """Lazy singleton Supabase client using the service-role key."""
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set"
            )
        _client = create_client(url, key)
        log.info(f"Supabase client initialized: {url}")
    return _client


# ---------- Projects ----------

PROJECT_COLUMNS = [
    "project_id", "name", "status", "files", "total_text_length",
    "ontology", "analysis_summary", "graph_id", "graph_build_task_id",
    "simulation_requirement", "chunk_size", "chunk_overlap",
    "error", "extracted_text",
]


def upsert_project(project: dict) -> None:
    """Mirror the in-memory project dict to Supabase."""
    pid = project.get("project_id") or project.get("id")
    if not pid:
        raise ValueError(f"upsert_project: missing project_id in {list(project.keys())}")

    row = {"project_id": pid}
    for col in PROJECT_COLUMNS:
        if col == "project_id":
            continue
        if col in project:
            row[col] = project[col]

    log.info(f"upsert_project: {pid} (cols={list(row.keys())})")
    try:
        res = client().table("engine_projects").upsert(row, on_conflict="project_id").execute()
        log.info(f"upsert_project OK: {pid}")
    except Exception as e:
        log.error(f"upsert_project FAILED for {pid}: {e}")
        raise


def get_project(project_id: str) -> Optional[dict]:
    """Load a project by id from Supabase. Returns None if missing."""
    log.info(f"get_project called with: {repr(project_id)} (type={type(project_id).__name__})")

    if not project_id or not isinstance(project_id, str):
        log.error(f"get_project: invalid project_id {repr(project_id)}")
        return None

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
            log.warning(f"get_project: not found in Supabase: {project_id}")
            return None
        log.info(f"get_project OK: {project_id}")
        return rows[0]
    except Exception as e:
        log.error(f"get_project FAILED for {project_id}: {e}")
        return None


def list_projects(limit: int = 100) -> list[dict]:
    try:
        res = (
            client()
            .table("engine_projects")
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception as e:
        log.error(f"list_projects FAILED: {e}")
        return []


def delete_project(project_id: str) -> None:
    if not project_id:
        return
    try:
        client().table("engine_projects").delete().eq("project_id", project_id).execute()
        log.info(f"delete_project OK: {project_id}")
    except Exception as e:
        log.error(f"delete_project FAILED for {project_id}: {e}")


# ---------- Extracted text helpers ----------

def save_extracted_text(project_id: str, text: str) -> None:
    if not project_id:
        raise ValueError("save_extracted_text: project_id is required")
    try:
        client().table("engine_projects").upsert(
            {"project_id": project_id, "extracted_text": text},
            on_conflict="project_id",
        ).execute()
        log.info(f"save_extracted_text OK: {project_id} ({len(text)} chars)")
    except Exception as e:
        log.error(f"save_extracted_text FAILED for {project_id}: {e}")
        raise


def get_extracted_text(project_id: str) -> Optional[str]:
    p = get_project(project_id)
    if not p:
        return None
    return p.get("extracted_text")

