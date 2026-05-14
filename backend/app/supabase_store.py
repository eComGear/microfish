# backend/app/supabase_store.py
"""
Supabase persistence layer for MicroFish backend.
Self-contained: does NOT import from app.models or any sibling that imports back.
"""
from __future__ import annotations

import os
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from supabase import create_client, Client

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = (
    os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    or os.environ.get("SUPABASE_KEY")
    or os.environ.get("SUPABASE_ANON_KEY")
    or ""
)

PROJECTS_TABLE = os.environ.get("SB_PROJECTS_TABLE", "engine_projects")
EXTRACTED_TEXTS_TABLE = os.environ.get("SB_EXTRACTED_TEXTS_TABLE", "engine_extracted_texts")
GRAPHS_TABLE = os.environ.get("SB_GRAPHS_TABLE", "engine_graphs")
TASKS_TABLE = os.environ.get("SB_TASKS_TABLE", "engine_tasks")

_client: Optional[Client] = None


def client() -> Client:
    global _client
    if _client is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError("SUPABASE_URL / SUPABASE_KEY env not set")
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_text(v: Any) -> str:
    """Coerce any stored value to a plain string. Prevents '.strip on list' errors."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, (list, tuple)):
        parts = []
        for item in v:
            parts.append(_as_text(item))
        return "\n\n".join(p for p in parts if p)
    if isinstance(v, dict):
        for k in ("content", "text", "extracted_text", "value"):
            if k in v:
                return _as_text(v[k])
        try:
            return json.dumps(v, ensure_ascii=False)
        except Exception:
            return str(v)
    return str(v)


def _coerce_id(value: Any, name: str = "id") -> str:
    """Accept str OR dict({'project_id': '...'}) — normalize to str."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for k in (name, "id", "project_id", "graph_id", "task_id"):
            if k in value and isinstance(value[k], str):
                return value[k]
    raise TypeError(f"{name} must be a string, got {type(value).__name__}: {value!r}")


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------
def save_project(project: Dict[str, Any]) -> Dict[str, Any]:
    pid = _coerce_id(project.get("project_id") or project.get("id"), "project_id")
    row = {
        "project_id": pid,
        "name": project.get("name"),
        "status": project.get("status", "created"),
        "data": project,
        "updated_at": _now(),
    }
    if "created_at" not in project:
        row["created_at"] = _now()
    client().table(PROJECTS_TABLE).upsert(row, on_conflict="project_id").execute()
    return project


def get_project(project_id: Any) -> Optional[Dict[str, Any]]:
    pid = _coerce_id(project_id, "project_id")
    res = client().table(PROJECTS_TABLE).select("data").eq("project_id", pid).limit(1).execute()
    rows = res.data or []
    if not rows:
        return None
    return rows[0].get("data") or None


def list_projects() -> List[Dict[str, Any]]:
    res = (
        client()
        .table(PROJECTS_TABLE)
        .select("data")
        .order("updated_at", desc=True)
        .execute()
    )
    return [r["data"] for r in (res.data or []) if r.get("data")]


def delete_project(project_id: Any) -> None:
    pid = _coerce_id(project_id, "project_id")
    client().table(PROJECTS_TABLE).delete().eq("project_id", pid).execute()
    client().table(EXTRACTED_TEXTS_TABLE).delete().eq("project_id", pid).execute()


# ---------------------------------------------------------------------------
# Extracted texts
# ---------------------------------------------------------------------------
def save_extracted_text(
    project_id: Any,
    content: Any,
    source_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    pid = _coerce_id(project_id, "project_id")
    text = _as_text(content)
    row = {
        "project_id": pid,
        "source_id": source_id or "default",
        "content": text,
        "metadata": metadata or {},
        "created_at": _now(),
    }
    try:
        client().table(EXTRACTED_TEXTS_TABLE).upsert(
            row, on_conflict="project_id,source_id"
        ).execute()
    except Exception as e:
        log.warning("upsert failed (%s); falling back to delete+insert", e)
        client().table(EXTRACTED_TEXTS_TABLE).delete().eq("project_id", pid).eq(
            "source_id", row["source_id"]
        ).execute()
        client().table(EXTRACTED_TEXTS_TABLE).insert(row).execute()


def get_extracted_text(project_id: Any) -> str:
    """Always returns a single concatenated string (never list/dict)."""
    pid = _coerce_id(project_id, "project_id")
    res = (
        client()
        .table(EXTRACTED_TEXTS_TABLE)
        .select("content,created_at")
        .eq("project_id", pid)
        .order("created_at", desc=False)
        .execute()
    )
    rows = res.data or []
    if not rows:
        return ""
    parts = [_as_text(r.get("content")) for r in rows]
    return "\n\n".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# Graphs
# ---------------------------------------------------------------------------
def save_graph(graph_id: Any, project_id: Any, data: Dict[str, Any]) -> None:
    gid = _coerce_id(graph_id, "graph_id")
    pid = _coerce_id(project_id, "project_id")
    row = {
        "graph_id": gid,
        "project_id": pid,
        "data": data,
        "updated_at": _now(),
    }
    client().table(GRAPHS_TABLE).upsert(row, on_conflict="graph_id").execute()


def get_graph(graph_id: Any) -> Optional[Dict[str, Any]]:
    gid = _coerce_id(graph_id, "graph_id")
    res = client().table(GRAPHS_TABLE).select("data").eq("graph_id", gid).limit(1).execute()
    rows = res.data or []
    if not rows:
        return None
    return rows[0].get("data") or None


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------
def save_task(task_id: Any, state: Dict[str, Any]) -> None:
    tid = _coerce_id(task_id, "task_id")
    row = {
        "task_id": tid,
        "state": state,
        "updated_at": _now(),
    }
    try:
        client().table(TASKS_TABLE).upsert(row, on_conflict="task_id").execute()
    except Exception as e:
        log.warning("save_task failed: %s", e)


def get_task(task_id: Any) -> Optional[Dict[str, Any]]:
    tid = _coerce_id(task_id, "task_id")
    try:
        res = client().table(TASKS_TABLE).select("state").eq("task_id", tid).limit(1).execute()
        rows = res.data or []
        if not rows:
            return None
        return rows[0].get("state") or None
    except Exception as e:
        log.warning("get_task failed: %s", e)
        return None


__all__ = [
    "client",
    "save_project",
    "get_project",
    "list_projects",
    "delete_project",
    "save_extracted_text",
    "get_extracted_text",
    "save_graph",
    "get_graph",
    "save_task",
    "get_task",
]

