# backend/app/supabase_store.py
import os
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
    "total_text_length", "ontology", "analysis_summary",
    "graph_id", "graph_build_task_id",
    "simulation_requirement", "chunk_size", "chunk_overlap",
    "error", "created_at", "updated_at",
}
SIMULATION_COLUMNS = {
    "simulation_id", "project_id", "graph_id", "status",
    "config", "error", "created_at", "updated_at",
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
        key = (
            os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
            or os.environ.get("SUPABASE_KEY")
            or ""
        )
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_KEY) must be set")
        _client = create_client(url, key)
    return _client


def _coerce_id(value: Any, field: str) -> str:
    if isinstance(value, (dict, list)) or value is None:
        raise ValueError(f"{field} must be a string, got {type(value).__name__}: {value!r}")
    return str(value)


def _filter(payload: dict, allowed: set) -> dict:
    return {k: v for k, v in payload.items() if k in allowed and v is not None}


def _as_text(v: Any) -> str:
    """Coerce arbitrary stored shapes into a single text blob."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        parts = []
        for item in v:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("content") or item.get("text") or ""))
            else:
                parts.append(str(item))
        return "\n\n".join(p for p in parts if p)
    if isinstance(v, dict):
        return str(v.get("content") or v.get("text") or "")
    return str(v)


# ---------------- projects ----------------

def upsert_project(project_id, *args, **fields) -> dict:
    """
    Tolerates caller shapes:
      upsert_project("proj_xxx", name=..., status=...)
      upsert_project({"project_id": "proj_xxx", "name": ..., ...})
      upsert_project("proj_xxx", {"name": ..., ...})
    """
    if isinstance(project_id, dict):
        merged = {**project_id, **fields}
        pid = merged.pop("project_id", None)
    else:
        pid = project_id
        merged = dict(fields)
        if args and isinstance(args[0], dict):
            merged = {**args[0], **merged}

    pid = _coerce_id(pid, "project_id")

    row = _filter({**merged, "project_id": pid}, PROJECT_COLUMNS)
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


def get_project(project_id) -> Optional[dict]:
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

def upsert_simulation(simulation_id, *args, **fields) -> dict:
    if isinstance(simulation_id, dict):
        merged = {**simulation_id, **fields}
        sid = merged.pop("simulation_id", None)
    else:
        sid = simulation_id
        merged = dict(fields)
        if args and isinstance(args[0], dict):
            merged = {**args[0], **merged}

    sid = _coerce_id(sid, "simulation_id")
    if "project_id" in merged and merged["project_id"] is not None:
        merged["project_id"] = _coerce_id(merged["project_id"], "project_id")

    row = _filter({**merged, "simulation_id": sid}, SIMULATION_COLUMNS)
    try:
        client().table(SIMULATIONS_TABLE).upsert(row, on_conflict="simulation_id").execute()
    except Exception as e:
        log.error("upsert_simulation FAILED for %s: %s", sid, e)
        raise

    res = (
        client()
        .table(SIMULATIONS_TABLE)
        .select("*")
        .eq("simulation_id", sid)
        .limit(1)
        .execute()
    )
    return (res.data or [{}])[0]


def get_simulation(simulation_id) -> Optional[dict]:
    sid = _coerce_id(simulation_id, "simulation_id")
    res = (
        client()
        .table(SIMULATIONS_TABLE)
        .select("*")
        .eq("simulation_id", sid)
        .limit(1)
        .execute()
    )
    return (res.data or [None])[0]


# ---------------- extracted texts ----------------

def save_extracted_text(project_id, content: Any = "", **kwargs) -> dict:
    # tolerate text= alias
    if "text" in kwargs and not content:
        content = kwargs.pop("text")
    pid = _coerce_id(project_id, "project_id")
    text = _as_text(content)
    row = {
        "project_id": pid,
        "content": text,
        "source_id": kwargs.get("source_id") or pid,  # used as upsert key
        "metadata": kwargs.get("metadata"),
    }
    row = _filter(row, EXTRACTED_TEXT_COLUMNS)
    # ensure source_id is present so on_conflict has something to match
    row.setdefault("source_id", pid)
    try:
        # Upsert on (project_id, source_id) so re-running the upload step
        # replaces the prior row instead of stacking duplicates.
        client().table(EXTRACTED_TEXTS_TABLE).upsert(
            row, on_conflict="project_id,source_id"
        ).execute()
    except Exception as e:
        # Fallback: delete-then-insert if the unique index isn't present yet.
        log.warning("save_extracted_text upsert failed (%s); falling back to delete+insert", e)
        try:
            client().table(EXTRACTED_TEXTS_TABLE).delete().eq("project_id", pid).execute()
            client().table(EXTRACTED_TEXTS_TABLE).insert(row).execute()
        except Exception as e2:
            log.error("save_extracted_text FAILED for %s: %s", pid, e2)
            raise
    return row


def get_extracted_text(project_id) -> str:
    """
    Returns the concatenated text blob for a project as a single string.
    Callers (graph build, simulation prep) expect str, not list.
    """
    pid = _coerce_id(project_id, "project_id")
    try:
        res = (
            client()
            .table(EXTRACTED_TEXTS_TABLE)
            .select("content,created_at")
            .eq("project_id", pid)
            .order("created_at", desc=False)
            .execute()
        )
    except Exception as e:
        log.error("get_extracted_text FAILED for %s: %s", pid, e)
        raise
    rows = res.data or []
    if not rows:
        return ""
    parts = [_as_text(r.get("content")) for r in rows]
    return "\n\n".join(p for p in parts if p)


def get_extracted_text_rows(project_id) -> list[dict]:
    """Raw rows accessor, kept for any caller that needs metadata."""
    pid = _coerce_id(project_id, "project_id")
    res = (
        client()
        .table(EXTRACTED_TEXTS_TABLE)
        .select("*")
        .eq("project_id", pid)
        .execute()
    )
    return res.data or []



