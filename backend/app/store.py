"""Supabase-backed store with in-memory fallback.

Adds `_sanitize_for_postgres` to strip NUL (\\x00 / \\u0000) from any string
before upserting — Postgres text/jsonb cannot store NUL and rejects with
`22P05 unsupported Unicode escape sequence`.
"""

from __future__ import annotations

import os
import threading
from collections import defaultdict
from typing import Any, Dict, Optional

_LOCK = threading.Lock()
_MEM: Dict[str, Dict[str, Any]] = defaultdict(dict)
_sb = None
_sb_err: Optional[str] = None


def _sanitize_for_postgres(value: Any):
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {k: _sanitize_for_postgres(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_for_postgres(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_for_postgres(v) for v in value)
    return value


def _client():
    global _sb, _sb_err
    if _sb is not None or _sb_err is not None:
        return _sb
    url = os.environ.get("SUPABASE_URL")
    key = (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_KEY")
    )
    if not url or not key:
        _sb_err = "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set"
        return None
    try:
        from supabase import create_client  # type: ignore
        _sb = create_client(url, key)
    except Exception as e:  # pragma: no cover
        _sb_err = f"supabase client init failed: {e}"
        _sb = None
    return _sb


def _upsert(table: str, record: Dict[str, Any], mem_bucket: str, key: str):
    record = _sanitize_for_postgres(record)
    with _LOCK:
        _MEM[mem_bucket][key] = record
    sb = _client()
    if not sb:
        return
    try:
        sb.table(table).upsert(record).execute()
    except Exception as e:
        # Surface to logs but don't break the pipeline (mem fallback wins)
        try:
            err = e.args[0] if e.args else str(e)
        except Exception:
            err = str(e)
        print(f"[store] upsert {table} failed: {err}", flush=True)


def _get(table: str, key_col: str, key: str, mem_bucket: str):
    sb = _client()
    if sb:
        try:
            res = sb.table(table).select("*").eq(key_col, key).limit(1).execute()
            data = getattr(res, "data", None) or []
            if data:
                return data[0]
        except Exception as e:
            print(f"[store] select {table} failed: {e}", flush=True)
    with _LOCK:
        return _MEM[mem_bucket].get(key)


def save_project(pid: str, payload: Dict[str, Any]):
    clean = _sanitize_for_postgres(payload)
    _upsert(
        "engine_projects",
        {"id": pid, "project_id": pid, "data": clean, **clean},
        "projects",
        pid,
    )


def get_project(pid: str):
    return _get("engine_projects", "id", pid, "projects")


def save_task(tid: str, payload: Dict[str, Any]):
    clean = _sanitize_for_postgres(payload)
    _upsert(
        "engine_tasks",
        {"id": tid, "task_id": tid, "state": clean, **clean},
        "tasks",
        tid,
    )


def get_task(tid: str):
    return _get("engine_tasks", "id", tid, "tasks")


def save_graph(gid: str, payload: Dict[str, Any]):
    clean = _sanitize_for_postgres(payload)
    _upsert(
        "engine_graphs",
        {"id": gid, "graph_id": gid, "data": clean, **clean},
        "graphs",
        gid,
    )


def get_graph(gid: str):
    return _get("engine_graphs", "id", gid, "graphs")


def save_report(rid: str, payload: Dict[str, Any]):
    clean = _sanitize_for_postgres(payload)
    _upsert(
        "engine_reports",
        {"id": rid, "report_id": rid, "data": clean, **clean},
        "reports",
        rid,
    )


def get_report(rid: str):
    return _get("engine_reports", "id", rid, "reports")
