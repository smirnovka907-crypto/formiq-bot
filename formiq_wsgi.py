"""WSGI entrypoint for a *future* approved Timeweb deployment only.

Importing this module deliberately NEVER initializes PostgreSQL, replays
Telegram updates, changes branding, or sets any webhook. Current Render uses
'python main.py' unchanged. No production pilot is permitted from this file.
"""
import os
from pathlib import Path
from urllib.parse import urlsplit

if os.getenv("FORMIQ_RUNTIME_ROLE") != "timeweb-web":
    raise RuntimeError("Timeweb WSGI role must be explicitly selected")
base = os.getenv("RENDER_EXTERNAL_URL", "").strip()
if not base.startswith("https://") or "onrender.com" in base.lower():
    raise RuntimeError("A non-Render HTTPS base URL must be explicitly configured")
if not os.getenv("TELEGRAM_BOT_TOKEN") or not os.getenv("DATABASE_URL"):
    raise RuntimeError("Approved Timeweb runtime credentials are required")

# Refuse cross-cloud access to the still-live Render production database.
host = urlsplit(os.environ["DATABASE_URL"]).hostname or ""
if host == "render.com" or host.endswith(".render.com"):
    raise RuntimeError("Timeweb WSGI cannot connect to existing Render PostgreSQL")

from main import APP as application  # noqa: E402  (no __main__ side effects)


@application.get("/__timeweb_release_health")
def timeweb_release_health():
    """Local reverse-proxy probe; identifies the actual code release, not DB."""
    marker = Path(__file__).resolve().with_name(".formiq-release-sha")
    try:
        sha = marker.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        return "release missing", 503
    if len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha):
        return "release invalid", 503
    return sha + "\n", 200, {"Cache-Control": "no-store"}


@application.get("/__timeweb_db_health")
def timeweb_db_health():
    """Loopback-only read-only PG18/schema readiness; never expose user data."""
    from flask import request
    if request.remote_addr not in ("127.0.0.1", "::1"):
        return "not found", 404
    try:
        from main import db
        with db() as conn:
            conn.execute("SET TRANSACTION READ ONLY")
            ok = conn.execute("""
                SELECT (current_setting('server_version_num')::int / 10000 = 18)
                  AND to_regclass('public.profiles') IS NOT NULL
                  AND to_regclass('public.workouts') IS NOT NULL
                  AND to_regclass('public.training_cycles') IS NOT NULL
                  AND to_regclass('public.scheduled_sessions') IS NOT NULL
            """).fetchone()[0]
        if not ok:
            return "database not ready", 503
        return "DATABASE_READY\n", 200, {"Cache-Control": "no-store"}
    except Exception:
        # Never disclose DSN, credentials, SQL error details or data.
        return "database unavailable", 503
