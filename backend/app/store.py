# backend/app/store.py
import os
import threading
from typing import Any, Dict, Optional

_LOCK = threading.Lock()
_MEM: Dict[str, Dict[str, Any]] = {
    "projects": {},
    "tasks": {},
    "graphs": {},
    "reports": {},
}

_sb = None
_sb_err: Optional[str] = None


def _client():
    """Lazy Supabase client. Returns None if not configured or unreachable."""
    global _sb, _sb_err
    if _sb is not None or _sb_err is not None:
        return _sb
    url = (os.environ.get("SUPABASE_URL") or "").strip().rstrip("/")
    key = (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_KEY")
        or ""
    ).strip()
    if not url or not key:
        _sb_err = "supabase env not set"
        return None
    if not url.startswith("http"):
        _sb_err = f"bad SUPABASE_URL: {url!r}"
        return None
    # strip accidental /rest/v1 suffix
    for suffix in ("/rest/v1", "/rest"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
    try:
        from supabase import create_client
        _sb = create_client(url, key)
    except Exception as e:
        _sb_err = f"create_client failed: {e}"
        _sb = None
    return _sb


def _upsert(table: str, record: Dict[str, Any], mem_bucket: str, key: str):
    with _LOCK:
        _MEM[mem_bucket][key] = record
    sb = _client()
    if sb is None:
        return
    try:
        sb.table(table).upsert(record).execute()
    except Exception as e:
        # Never crash the request because of persistence
        print(f"[store] upsert {table} failed: {e}", flush=True)


def _get(table: str, key_col: str, key: str, mem_bucket: str):
    with _LOCK:
        cached = _MEM[mem_bucket].get(key)
    if cached is not None:
        return cached
    sb = _client()
    if sb is None:
        return None
    try:
        res = sb.table(table).select("*").eq(key_col, key).limit(1).execute()
        rows = res.data or []
        if rows:
            with _LOCK:
                _MEM[mem_bucket][key] = rows[0]
            return rows[0]
    except Exception as e:
        print(f"[store] get {table} failed: {e}", flush=True)
    return None


def save_project(pid: str, payload: Dict[str, Any]):
    _upsert("engine_projects", {"id": pid, **payload}, "projects", pid)

def get_project(pid: str):
    return _get("engine_projects", "id", pid, "projects")

def save_task(tid: str, payload: Dict[str, Any]):
    _upsert("engine_tasks", {"id": tid, **payload}, "tasks", tid)

def get_task(tid: str):
    return _get("engine_tasks", "id", tid, "tasks")

def save_graph(gid: str, payload: Dict[str, Any]):
    _upsert("engine_graphs", {"id": gid, **payload}, "graphs", gid)

def get_graph(gid: str):
    return _get("engine_graphs", "id", gid, "graphs")

def save_report(rid: str, payload: Dict[str, Any]):
    _upsert("engine_reports", {"id": rid, **payload}, "reports", rid)

def get_report(rid: str):
    return _get("engine_reports", "id", rid, "reports")

