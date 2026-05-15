"""Supabase-backed persistence for projects / tasks / graphs / reports.
Falls back to in-memory dicts if SUPABASE_URL is not set (local dev)."""
import os
import json
import threading
from datetime import datetime, timezone
from typing import Any, Optional

_LOCK = threading.Lock()
_MEM = {"projects": {}, "tasks": {}, "graphs": {}, "reports": {}}

_SUPABASE = None

def _client():
    global _SUPABASE
    if _SUPABASE is not None:
        return _SUPABASE
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        return None
    try:
        from supabase import create_client
        _SUPABASE = create_client(url, key)
        return _SUPABASE
    except Exception:
        return None

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _serialize(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        if isinstance(v, (dict, list)):
            out[k] = json.loads(json.dumps(v, default=str))
        elif isinstance(v, datetime):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out

# ---------- generic helpers ----------
def _upsert(table: str, record: dict, mem_bucket: str, key: str):
    record = _serialize(record)
    record["updated_at"] = _now()
    sb = _client()
    if sb:
        sb.table(table).upsert(record).execute()
    with _LOCK:
        _MEM[mem_bucket][key] = record

def _get(table: str, mem_bucket: str, key: str) -> Optional[dict]:
    sb = _client()
    if sb:
        try:
            r = sb.table(table).select("*").eq("id", key).maybe_single().execute()
            if r and r.data:
                return r.data
        except Exception:
            pass
    with _LOCK:
        return _MEM[mem_bucket].get(key)

# ---------- public API ----------
def save_project(pid: str, payload: dict):
    _upsert("engine_projects", {"id": pid, **payload}, "projects", pid)

def get_project(pid: str) -> Optional[dict]:
    return _get("engine_projects", "projects", pid)

def save_task(tid: str, payload: dict):
    _upsert("engine_tasks", {"id": tid, **payload}, "tasks", tid)

def get_task(tid: str) -> Optional[dict]:
    return _get("engine_tasks", "tasks", tid)

def save_graph(gid: str, payload: dict):
    _upsert("engine_graphs", {"id": gid, **payload}, "graphs", gid)

def get_graph(gid: str) -> Optional[dict]:
    return _get("engine_graphs", "graphs", gid)

def save_report(rid: str, payload: dict):
    _upsert("engine_reports", {"id": rid, **payload}, "reports", rid)

def get_report(rid: str) -> Optional[dict]:
    return _get("engine_reports", "reports", rid)
