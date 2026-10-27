"""WSGI entrypoint for a *future* approved Timeweb deployment only.

Importing this module deliberately NEVER initializes PostgreSQL, replays
Telegram updates, changes branding, or sets any webhook. Current Render uses
'python main.py' unchanged. No production pilot is permitted from this file.
"""
import os
from pathlib import Path

if os.getenv("FORMIQ_RUNTIME_ROLE") != "timeweb-web":
    raise RuntimeError("Timeweb WSGI role must be explicitly selected")
base = os.getenv("RENDER_EXTERNAL_URL", "").strip()
if not base.startswith("https://") or "onrender.com" in base.lower():
    raise RuntimeError("A non-Render HTTPS base URL must be explicitly configured")
if not os.getenv("TELEGRAM_BOT_TOKEN") or not os.getenv("DATABASE_URL"):
    raise RuntimeError("Approved Timeweb runtime credentials are required")

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
