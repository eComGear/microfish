"""Shared Supabase URL normalisation. Import from here in every module
that builds a Supabase client, so PGRST125 (Invalid path) cannot recur."""
import os
import re
from typing import Optional


def normalize_supabase_url(raw: Optional[str]) -> Optional[str]:
    """Strip trailing slash, /rest/v1[/...], and convert dashboard URLs."""
    if not raw:
        return None
    url = raw.strip().rstrip("/")
    # Remove user-supplied /rest/v1 or /rest/v1/anything
    url = re.sub(r"/rest/v1(/.*)?$", "", url, flags=re.IGNORECASE)
    # Convert https://supabase.com/dashboard/project/<ref>/... -> https://<ref>.supabase.co
    url = re.sub(
        r"^https?://supabase\.com/dashboard/project/([^/]+).*$",
        r"https://\1.supabase.co",
        url,
        flags=re.IGNORECASE,
    )
    return url.rstrip("/")


def get_supabase_url() -> Optional[str]:
    """Read SUPABASE_URL from env and return a normalised value."""
    return normalize_supabase_url(os.getenv("SUPABASE_URL"))


def get_supabase_key() -> Optional[str]:
    """Prefer service-role key; fall back to anon key."""
    return os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
