"""
Supabase persistence for the MicroFish engine.

Two tables (separate from the frontend's `reports` table to avoid coupling):
  - engine_simulations  (one row per simulation_id, full state snapshot)
  - engine_reports      (one row per report_id, with simulation_id index)

All functions are best-effort: if env vars or the supabase package are
missing, every call becomes a no-op and returns None — the engine keeps
running on local disk.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

_SB = None
_INIT_TRIED = False


def _client():
    """Lazy singleton. Returns None if Supabase isn't configured."""
    global _SB, _INIT_TRIED
    if _SB is not None or _INIT_TRIED:
        return _SB
    _INIT_TRIED = True
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        log.info("supabase_store: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set — persistence disabled")
        return None
    try:
        from supabase import create_client  # type: ignore
        _SB = create_client(url, key)
        log.info("supabase_store: client initialized")
    except Exception as e:  # noqa: BLE001
        log.warning("supabase_store: failed to init client: %s", e)
        _SB = None
    return _SB


# ---------- simulations ----------

def upsert_simulation(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Mirror a simulation state dict to Supabase. Keyed by simulation_id."""
    sb = _client()
    if sb is None or not isinstance(state, dict):
        return None
    sim_id = state.get("simulation_id") or state.get("id")
    if not sim_id:
        return None
    row = {
        "simulation_id": str(sim_id),
        "status": state.get("status"),
        "topic": state.get("topic"),
        "user_id": state.get("user_id"),
        "state": state,  # full snapshot in jsonb
    }
    try:
        res = sb.table("engine_simulations").upsert(row, on_conflict="simulation_id").execute()
        return (res.data or [None])[0]
    except Exception as e:  # noqa: BLE001
        log.warning("supabase_store.upsert_simulation failed: %s", e)
        return None


def get_simulation(simulation_id: str) -> Optional[Dict[str, Any]]:
    sb = _client()
    if sb is None or not simulation_id:
        return None
    try:
        res = (
            sb.table("engine_simulations")
            .select("state")
            .eq("simulation_id", str(simulation_id))
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            return None
        return rows[0].get("state")
    except Exception as e:  # noqa: BLE001
        log.warning("supabase_store.get_simulation failed: %s", e)
        return None


# ---------- reports ----------

def save_report(report: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Upsert a report. Keyed by report_id."""
    sb = _client()
    if sb is None or not isinstance(report, dict):
        return None
    report_id = report.get("report_id") or report.get("id")
    if not report_id:
        return None
    row = {
        "report_id": str(report_id),
        "simulation_id": str(report.get("simulation_id") or ""),
        "status": report.get("status"),
        "title": report.get("title"),
        "topic": report.get("topic"),
        "markdown_content": report.get("markdown_content") or report.get("markdown"),
        "outline": report.get("outline"),
        "payload": report,  # full snapshot in jsonb
    }
    try:
        res = sb.table("engine_reports").upsert(row, on_conflict="report_id").execute()
        return (res.data or [None])[0]
    except Exception as e:  # noqa: BLE001
        log.warning("supabase_store.save_report failed: %s", e)
        return None


def get_report(report_id: str) -> Optional[Dict[str, Any]]:
    sb = _client()
    if sb is None or not report_id:
        return None
    try:
        res = (
            sb.table("engine_reports")
            .select("payload")
            .eq("report_id", str(report_id))
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            return None
        return rows[0].get("payload")
    except Exception as e:  # noqa: BLE001
        log.warning("supabase_store.get_report failed: %s", e)
        return None


def get_report_by_simulation(simulation_id: str) -> Optional[Dict[str, Any]]:
    sb = _client()
    if sb is None or not simulation_id:
        return None
    try:
        res = (
            sb.table("engine_reports")
            .select("payload, created_at")
            .eq("simulation_id", str(simulation_id))
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            return None
        return rows[0].get("payload")
    except Exception as e:  # noqa: BLE001
        log.warning("supabase_store.get_report_by_simulation failed: %s", e)
        return None


# Back-compat aliases (old call sites)
sb = _client

# ---------- projects ----------

def upsert_project(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Mirror a project dict to Supabase. Keyed by project_id."""
    sb = _client()
    if sb is None or not isinstance(state, dict):
        return None
    project_id = state.get("project_id")
    if not project_id:
        return None
    row = {
        "project_id": str(project_id),
        "name": state.get("name") or "Unnamed Project",
        "status": state.get("status") or "created",
        "files": state.get("files") or [],
        "total_text_length": state.get("total_text_length") or 0,
        "ontology": state.get("ontology"),
        "analysis_summary": state.get("analysis_summary"),
        "graph_id": state.get("graph_id"),
        "graph_build_task_id": state.get("graph_build_task_id"),
        "simulation_requirement": state.get("simulation_requirement"),
        "chunk_size": state.get("chunk_size") or 500,
        "chunk_overlap": state.get("chunk_overlap") or 50,
        "error": state.get("error"),
        "extracted_text": state.get("extracted_text"),
    }
    # Drop None so Postgres defaults / existing values stick.
    row = {k: v for k, v in row.items() if v is not None}
    try:
        res = sb.table("engine_projects").upsert(row, on_conflict="project_id").execute()
        return (res.data or [None])[0]
    except Exception as e:  # noqa: BLE001
        log.warning("supabase_store.upsert_project failed: %s", e)
        return None


def get_project(project_id: str) -> Optional[Dict[str, Any]]:
    sb = _client()
    if sb is None or not project_id:
        return None
    try:
        res = (
            sb.table("engine_projects")
            .select("*")
            .eq("project_id", str(project_id))
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None
    except Exception as e:  # noqa: BLE001
        log.warning("supabase_store.get_project failed: %s", e)
        return None


def list_projects(limit: int = 50) -> list:
    sb = _client()
    if sb is None:
        return []
    try:
        res = (
            sb.table("engine_projects")
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception as e:  # noqa: BLE001
        log.warning("supabase_store.list_projects failed: %s", e)
        return []


def delete_project(project_id: str) -> bool:
    sb = _client()
    if sb is None or not project_id:
        return False
    try:
        sb.table("engine_projects").delete().eq("project_id", str(project_id)).execute()
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("supabase_store.delete_project failed: %s", e)
        return False


def save_extracted_text(project_id: str, text: str) -> bool:
    """Convenience: just update the extracted_text column."""
    sb = _client()
    if sb is None or not project_id:
        return False
    try:
        sb.table("engine_projects").update({
            "extracted_text": text,
            "total_text_length": len(text),
        }).eq("project_id", str(project_id)).execute()
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("supabase_store.save_extracted_text failed: %s", e)
        return False


def get_extracted_text(project_id: str) -> Optional[str]:
    sb = _client()
    if sb is None or not project_id:
        return None
    try:
        res = (
            sb.table("engine_projects")
            .select("extracted_text")
            .eq("project_id", str(project_id))
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            return None
        return rows[0].get("extracted_text")
    except Exception as e:  # noqa: BLE001
        log.warning("supabase_store.get_extracted_text failed: %s", e)
        return None


