# backend/app/store.py
"""Durable storage layer for MiroFish.

- Primary: Supabase (engine_projects / engine_tasks / engine_graphs / engine_reports)
- Fallback: in-process memory dict (so the API never crashes when Supabase is
  unreachable or mis-configured).

This file is tolerant of common SUPABASE_URL mistakes — trailing slash,
appended `/rest/v1`, or a pasted dashboard URL — by normalising before
handing the value to supabase-py.
"""

from __future__ import annotations

import os
import re
import threading
from typing import Any, Dict, Optional

# --------------------------------------------------------------------------- #
# In-memory fallback                                                          #
# --------------------------------------------------------------------------- #

_LOCK = threading.RLock()
_MEM: Dict[str, Dict[str, Any]] = {
    "projects": {},
    "tasks": {},
    "graphs": {},
    "reports": {},
}

_sb = None
_sb_err: Optional[str] = None


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #

def _normalize_supabase_url(raw: Optional[str]) -> Optional[str]:
    """Accept any of these and return the canonical project URL:

    - https://abc.supabase.co
    - https://abc.supabase.co/
    - https://abc.supabase.co/rest/v1
    - https://abc.supabase.co/rest/v1/
    - https://supabase.com/dashboard/project/abc/...
    """
    if not raw:
        return None
    url = raw.strip().rstrip("/")

    # dashboard URL → project URL
    m = re.match(
        r"^https?://supabase\.com/dashboard/project/([^/]+).*$",
        url,
        flags=re.IGNORECASE,
    )
    if m:
        return f"https://{m.group(1)}.supabase.co"

    # strip a trailing /rest/v1 (with or without subpath)
    url = re.sub(r"/rest/v1(/.*)?$", "", url, flags=re.IGNORECASE)

    return url.rstrip("/")


def _sanitize_for_postgres(value: Any):
    """PostgreSQL text/jsonb cannot store NUL (\x00 / \u0000)."""
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {k: _sanitize_for_postgres(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_for_postgres(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_for_postgres(v) for v in value)
    return value


# --------------------------------------------------------------------------- #
# Supabase client (lazy)                                                      #
# --------------------------------------------------------------------------- #

def _client():
    """Return a cached Supabase client, or None if not configured / unreachable."""
    global _sb, _sb_err
    if _sb is not None:
        return _sb
    if _sb_err is not None:
        return None
    try:
        from supabase import create_client  # type: ignore

        url = _normalize_supabase_url(os.getenv("SUPABASE_URL"))
        key = (
            os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            or os.getenv("SUPABASE_ANON_KEY")
        )
        if not url or not key:
            _sb_err = "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing"
            print(f"[store] supabase disabled: {_sb_err}")
            return None

        _sb = create_client(url, key)
        print(f"[store] supabase client ready: {url}")
    except Exception as e:  # pragma: no cover - defensive
        _sb_err = str(e)
        print(f"[store] supabase init failed: {e}")
        _sb = None
    return _sb


# --------------------------------------------------------------------------- #
# Generic upsert / get                                                        #
# --------------------------------------------------------------------------- #

def _upsert(table: str, record: Dict[str, Any], mem_bucket: str, key: str):
    record = _sanitize_for_postgres(record)
    with _LOCK:
        _MEM[mem_bucket][key] = record

    sb = _client()
    if sb is None:
        return

    try:
        sb.table(table).upsert(record).execute()
    except Exception as e:
        # Supabase REST errors come back as dict-like exception args
        msg = getattr(e, "args", [str(e)])[0]
        print(f"[store] upsert {table} failed: {msg}")


def _get(table: str, key_col: str, key: str, mem_bucket: str):
    sb = _client()
    if sb is not None:
        try:
            res = (
                sb.table(table)
                .select("*")
                .eq(key_col, key)
                .limit(1)
                .execute()
            )
            rows = getattr(res, "data", None) or []
            if rows:
                return rows[0]
        except Exception as e:
            msg = getattr(e, "args", [str(e)])[0]
            print(f"[store] select {table} failed: {msg}")

    with _LOCK:
        return _MEM[mem_bucket].get(key)


# --------------------------------------------------------------------------- #
# Public API                                                                  #
# --------------------------------------------------------------------------- #

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


# --------------------------------------------------------------------------- #
# Diagnostics (used by /api/graph/health etc.)                                #
# --------------------------------------------------------------------------- #

def status() -> Dict[str, Any]:
    sb = _client()
    return {
        "supabase": sb is not None,
        "supabase_error": _sb_err,
        "supabase_url": _normalize_supabase_url(os.getenv("SUPABASE_URL")),
        "mem_counts": {k: len(v) for k, v in _MEM.items()},
    }
