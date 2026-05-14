"""Persist simulations + reports to Supabase so restarts never lose data."""
import os
from typing import Any, Optional
from supabase import create_client, Client

_client: Optional[Client] = None

def sb() -> Optional[Client]:
    global _client
    if _client is not None:
        return _client
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("[supabase_store] SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing — DB persistence disabled")
        return None
    _client = create_client(url, key)
    return _client

def upsert_simulation(simulation_id: str, user_id: Optional[str], patch: dict[str, Any]) -> None:
    c = sb()
    if not c: return
    row = {"simulation_id": simulation_id, **patch}
    if user_id:
        row["user_id"] = user_id
    try:
        c.table("reports").upsert(row, on_conflict="simulation_id").execute()
    except Exception as e:
        print(f"[supabase_store] upsert_simulation failed: {e}")

def save_report(simulation_id: str, markdown: str, outline: Any = None, title: str | None = None) -> None:
    c = sb()
    if not c: return
    patch = {
        "simulation_id": simulation_id,
        "status": "completed",
        "report_markdown": markdown,
        "report_outline": outline,
    }
    if title:
        patch["title"] = title
    try:
        c.table("reports").upsert(patch, on_conflict="simulation_id").execute()
    except Exception as e:
        print(f"[supabase_store] save_report failed: {e}")

def get_simulation(simulation_id: str) -> Optional[dict]:
    c = sb()
    if not c: return None
    try:
        r = c.table("reports").select("*").eq("simulation_id", simulation_id).maybe_single().execute()
        return r.data
    except Exception as e:
        print(f"[supabase_store] get_simulation failed: {e}")
        return None
