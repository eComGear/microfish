# backend/app/supabase_store.py
"""
Supabase persistence layer for MicroFish backend.
URL is normalised so SUPABASE_URL may include /rest/v1, trailing slash, or
a Supabase dashboard URL — supabase-py always receives the bare project URL.
"""
from __future__ import annotations

import os
import re
import json
import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from supabase import create_client, Client

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# URL / key normalisation (inline so this file is self-contained)
# ---------------------------------------------------------------------------
def _normalize_supabase_url(raw: Optional[str]) -> str:
    if not raw:
        return ""
    url = raw.strip().rstrip("/")
    # Strip user-supplied /rest/v1 or /rest/v1/<anything>
    url = re.sub(r"/rest/v1(/.*)?$", "", url, flags=re.IGNORECASE)
    # Convert dashboard URL to project URL
    url = re.sub(
        r"^https?://supabase\.com/dashboard/project/([^/]+).*$",
        r"https://\1.supabase.co",
        url,
        flags=re.IGNORECASE,
    )
    return url.rstrip("/")


def _read_url() -> str:
    return _normalize_supabase_url(os.environ.get("SUPABASE_URL"))


def _read_key() -> str:
    return (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_KEY")
        or os.environ.get("SUPABASE_ANON_KEY")
        or ""
    )


SUPABASE_URL = _read_url()
SUPABASE_KEY = _read_key()

PROJECTS_TABLE = os.environ.get("SB_PROJECTS_TABLE", "engine_projects")
EXTRACTED_TEXTS_TABLE = os.environ.get("SB_EXTRACTED_TEXTS_TABLE", "engine_extracted_texts")
GRAPHS_TABLE = os.environ.get("SB_GRAPHS_TABLE", "engine_graphs")
TASKS_TABLE = os.environ.get("SB_TASKS_TABLE", "engine_tasks")
REPORTS_TABLE = os.environ.get("SB_REPORTS_TABLE", "engine_reports")

_client: Optional[Client] = None


def client() -> Client:
    global _client
    if _client is None:
        url = SUPABASE_URL or _read_url()
        key = SUPABASE_KEY or _read_key()
        if not url or not key:
            raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY env not set")
        _client = create_client(url, key)
        log.info("[supabase_store] client ready: %s", url)
    return _client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, (list, tuple)):
        return "\n\n".join(p for p in (_as_text(x) for x in v) if p)
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
    res = (
        client()
        .table(PROJECTS_TABLE)
        .select("project_id,name,status,data,created_at,updated_at")
        .eq("project_id", pid)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        return None
    row = rows[0]
    data = dict(row.get("data") or {})
    # guarantee the id round-trips even if older rows stored data without it
    data.setdefault("project_id", row.get("project_id") or pid)
    data.setdefault("name", row.get("name"))
    data.setdefault("status", row.get("status", "created"))
    data.setdefault("created_at", row.get("created_at"))
    data.setdefault("updated_at", row.get("updated_at"))
    return data


def list_projects(limit: int = 100) -> List[Dict[str, Any]]:
    res = (
        client()
        .table(PROJECTS_TABLE)
        .select("project_id,name,status,data,created_at,updated_at")
        .order("updated_at", desc=True)
        .limit(limit)
        .execute()
    )
    out: List[Dict[str, Any]] = []
    for row in res.data or []:
        data = dict(row.get("data") or {})
        data.setdefault("project_id", row.get("project_id"))
        data.setdefault("name", row.get("name"))
        data.setdefault("status", row.get("status", "created"))
        data.setdefault("created_at", row.get("created_at"))
        data.setdefault("updated_at", row.get("updated_at"))
        out.append(data)
    return out


def upsert_project(project: Dict[str, Any]) -> Dict[str, Any]:
    return save_project(project)


def delete_project(project_id: Any) -> bool:
    pid = _coerce_id(project_id, "project_id")
    try:
        client().table(PROJECTS_TABLE).delete().eq("project_id", pid).execute()
        client().table(EXTRACTED_TEXTS_TABLE).delete().eq("project_id", pid).execute()
        return True
    except Exception as e:
        log.warning("delete_project failed: %s", e)
        return False


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
    row = {
        "project_id": pid,
        "source_id": source_id or "default",
        "content": _as_text(content),
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
    return "\n\n".join(p for p in (_as_text(r.get("content")) for r in rows) if p)


# ---------------------------------------------------------------------------
# Graphs
# ---------------------------------------------------------------------------
def save_graph(graph_id: Any, project_id: Any, data: Dict[str, Any]) -> None:
    gid = _coerce_id(graph_id, "graph_id")
    pid = _coerce_id(project_id, "project_id")
    client().table(GRAPHS_TABLE).upsert(
        {"graph_id": gid, "project_id": pid, "data": data, "updated_at": _now()},
        on_conflict="graph_id",
    ).execute()


def get_graph(graph_id: Any) -> Optional[Dict[str, Any]]:
    gid = _coerce_id(graph_id, "graph_id")
    res = client().table(GRAPHS_TABLE).select("data").eq("graph_id", gid).limit(1).execute()
    rows = res.data or []
    return rows[0].get("data") if rows else None


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------
def save_task(task_id: Any, state: Dict[str, Any]) -> None:
    tid = _coerce_id(task_id, "task_id")
    try:
        client().table(TASKS_TABLE).upsert(
            {"task_id": tid, "state": state, "updated_at": _now()},
            on_conflict="task_id",
        ).execute()
    except Exception as e:
        log.warning("save_task failed: %s", e)


def get_task(task_id: Any) -> Optional[Dict[str, Any]]:
    tid = _coerce_id(task_id, "task_id")
    try:
        res = client().table(TASKS_TABLE).select("state").eq("task_id", tid).limit(1).execute()
        rows = res.data or []
        return rows[0].get("state") if rows else None
    except Exception as e:
        log.warning("get_task failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Simulations
# ---------------------------------------------------------------------------
def compute_input_hash(payload: dict) -> str:
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def get_cached_simulation(project_id: str, input_hash: str):
    r = (
        client()
        .table("simulations")
        .select("*")
        .eq("project_id", project_id)
        .eq("input_hash", input_hash)
        .maybe_single()
        .execute()
    )
    return r.data if r and r.data else None


def upsert_simulation(
    project_id: str,
    input_hash: str,
    *,
    config=None,
    result=None,
    status="pending",
    error=None,
    simulation_id=None,
    task_id=None,
):
    row = {
        "project_id": project_id,
        "input_hash": input_hash,
        "config": config,
        "result": result,
        "status": status,
        "error": error,
        "simulation_id": simulation_id,
        "task_id": task_id,
        "updated_at": "now()",
    }
    row = {
        k: v
        for k, v in row.items()
        if v is not None or k in ("config", "result", "error", "status")
    }
    return (
        client()
        .table("simulations")
        .upsert(row, on_conflict="project_id,input_hash")
        .execute()
    )


def list_simulations(project_id: str, limit: int = 50):
    r = (
        client()
        .table("simulations")
        .select("*")
        .eq("project_id", project_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return r.data or []


def upsert_simulation_meta(
    simulation_id: str,
    project_id: str,
    *,
    graph_id=None,
    enable_twitter=True,
    enable_reddit=False,
) -> None:
    try:
        client().table("simulations_meta").upsert(
            {
                "simulation_id": simulation_id,
                "project_id": project_id,
                "graph_id": graph_id,
                "enable_twitter": enable_twitter,
                "enable_reddit": enable_reddit,
            },
            on_conflict="simulation_id",
        ).execute()
    except Exception as e:
        log.warning("upsert_simulation_meta failed: %s", e)


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
def save_report(report: Dict[str, Any]) -> None:
    rid = report.get("report_id") or report.get("id")
    if not rid:
        return
    row = {
        "report_id": rid,
        "simulation_id": report.get("simulation_id"),
        "project_id": report.get("project_id"),
        "status": str(report.get("status", "pending")).lower().split(".")[-1],
        "title": report.get("title"),
        "markdown_content": report.get("markdown_content") or report.get("markdown"),
        "outline": report.get("outline"),
        "data": report,
        "updated_at": _now(),
    }
    try:
        client().table(REPORTS_TABLE).upsert(row, on_conflict="report_id").execute()
    except Exception as e:
        log.warning("save_report failed: %s", e)


def get_report(report_id: str) -> Optional[Dict[str, Any]]:
    try:
        r = client().table(REPORTS_TABLE).select("data").eq("report_id", report_id).limit(1).execute()
        rows = r.data or []
        return rows[0].get("data") if rows else None
    except Exception as e:
        log.warning("get_report failed: %s", e)
        return None


def get_report_by_simulation(simulation_id: str) -> Optional[Dict[str, Any]]:
    try:
        r = (
            client()
            .table(REPORTS_TABLE)
            .select("data")
            .eq("simulation_id", simulation_id)
            .order("updated_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = r.data or []
        return rows[0].get("data") if rows else None
    except Exception as e:
        log.warning("get_report_by_simulation failed: %s", e)
        return None


def list_reports(simulation_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    try:
        q = client().table(REPORTS_TABLE).select("data")
        if simulation_id:
            q = q.eq("simulation_id", simulation_id)
        r = q.order("updated_at", desc=True).limit(limit).execute()
        return [row["data"] for row in (r.data or []) if row.get("data")]
    except Exception as e:
        log.warning("list_reports failed: %s", e)
        return []


__all__ = [
    "client",
    "save_project", "get_project", "list_projects", "upsert_project", "delete_project",
    "save_extracted_text", "get_extracted_text",
    "save_graph", "get_graph",
    "save_task", "get_task",
    "compute_input_hash", "get_cached_simulation", "upsert_simulation",
    "list_simulations", "upsert_simulation_meta",
    "save_report", "get_report", "get_report_by_simulation", "list_reports",
]


