# backend/app/supabase_store.py
import os
import json
import logging
from typing import Any, Optional
from supabase import create_client, Client

log = logging.getLogger(__name__)

PROJECTS_TABLE = "engine_projects"
SIMULATIONS_TABLE = "engine_simulations"
EXTRACTED_TEXTS_TABLE = "engine_extracted_texts"
REPORTS_TABLE = "engine_reports"

PROJECT_COLUMNS = {
    "project_id", "name", "status", "files",
    "total_text_length", "ontology", "graph_id",
    "created_at", "updated_at",
}
SIMULATION_COLUMNS = {
    "simulation_id", "project_id", "graph_id", "status",
    "config", "created_at", "updated_at",
}
EXTRACTED_TEXT_COLUMNS = {
    "project_id", "source_id", "content", "metadata",
    "created_at", "updated_at",
}

_client: Optional[Client] = None


def _normalize_supabase_url(url: str) -> str:
    if not url:
        return url
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


def _coerce_id(value: Any, field: str) -> str:
    """Guard: never let a dict/list become the primary key."""
    if isinstance(value, (dict, list)):
        raise ValueError(f"{field} must be a string, got {type(value).__name__}: {value!r}")
    if value is None:
        raise ValueError(f"{field} is required")
    return str(value)


def _filter(payload: dict, allowed: set) -> dict:
    return {k: v for k, v in payload.items() if k in allowed and v is not None}


# ---------------- projects ----------------

def upsert_project(project_id: str, **fields) -> dict:
    pid = _coerce_id(project_id, "project_id")
    # If caller accidentally passed the whole payload as project_id, unpack it.
    if isinstance(project_id, dict):  # extra safety
        fields = {**project_id, **fields}
        pid = _coerce_id(fields.pop("project_id", None), "project_id")

    row = _filter({**fields, "project_id": pid}, PROJECT_COLUMNS)
    try:
        client().table(PROJECTS_TABLE).upsert(row, on_conflict="project_id").execute()
    except Exception as e:
        log.error("upsert_project FAILED for %s: %s", pid, e)
        raise

    res = (
        client()
        .table(PROJECTS_TABLE)
        .select("*")
        .eq("project_id", pid)
        .limit(1)
        .execute()
    )
    return (res.data or [{}])[0]


def get_project(project_id: str) -> Optional[dict]:
    pid = _coerce_id(project_id, "project_id")
    res = (
        client()
        .table(PROJECTS_TABLE)
        .select("*")
        .eq("project_id", pid)
        .limit(1)
        .execute()
    )
    return (res.data or [None])[0]


# ---------------- simulations ----------------

def upsert_simulation(simulation_id: str, **fields) -> dict:
    sid = _coerce_id(simulation_id, "simulation_id")
    if "project_id" in fields:
        fields["project_id"] = _coerce_id(fields["project_id"], "project_id")

    row = _filter({**fields, "simulation_id": sid}, SIMULATION_COLUMNS)
    client().table(SIMULATIONS_TABLE).upsert(row, on_conflict="simulation_id").execute()

    res = (
        client()
        .table(SIMULATIONS_TABLE)
        .select("simulation_id, project_id, graph_id, status, created_at, updated_at, config")
        .eq("simulation_id", sid)
        .limit(1)
        .execute()
    )
    return (res.data or [{}])[0]


def get_simulation(simulation_id: str) -> Optional[dict]:
    sid = _coerce_id(simulation_id, "simulation_id")
    res = (
        client()
        .table(SIMULATIONS_TABLE)
        .select("simulation_id, project_id, graph_id, status, created_at, updated_at, config")
        .eq("simulation_id", sid)
        .limit(1)
        .execute()
    )
    return (res.data or [None])[0]


# ---------------- extracted texts ----------------

def save_extracted_text(project_id: str, content: str = "", **kwargs) -> dict:
    # tolerate text= alias
    if "text" in kwargs and not content:
        content = kwargs.pop("text")
    pid = _coerce_id(project_id, "project_id")
    row = _filter(
        {
            "project_id": pid,
            "content": content or "",
            "source_id": kwargs.get("source_id"),
            "metadata": kwargs.get("metadata"),
        },
        EXTRACTED_TEXT_COLUMNS,
    )
    client().table(EXTRACTED_TEXTS_TABLE).insert(row).execute()
    return row


def get_extracted_text(project_id: str) -> list[dict]:
    pid = _coerce_id(project_id, "project_id")
    res = (
        client()
        .table(EXTRACTED_TEXTS_TABLE)
        .select("*")
        .eq("project_id", pid)
        .execute()
    )
    return res.data or []
