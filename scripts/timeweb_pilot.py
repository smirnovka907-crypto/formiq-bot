#!/usr/bin/env python3
"""Issue #35: no-secrets offline pilot and package manifest guard."""
import argparse
import ast
import os
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
DENIED = (
    "TELEGRAM_BOT_TOKEN", "DATABASE_URL", "YANDEX_API_KEY",
    "FATSECRET_CLIENT_SECRET", "FATSECRET_OAUTH_CONSUMER_SECRET",
    "FORMIQ_INTEGRATION_ENCRYPTION_KEY", "FORMIQ_TIMEWEB_REAL_DEPLOY_ENABLED",
    "TIMEWEB_SSH_PRIVATE_KEY", "TIMEWEB_SSH_HOST", "TIMEWEB_SSH_USER",
)

def refuse_runtime_credentials(env=None):
    env = os.environ if env is None else env
    found = [name for name in DENIED if env.get(name)]
    if found:
        # Never print values, and do not reveal even which secret is populated.
        raise ValueError("Offline pilot refused: runtime or deployment credentials are present")

def static_entrypoint_check(root=ROOT):
    app = ast.parse((root / "main.py").read_text(encoding="utf-8"))
    top = [n for n in app.body if isinstance(n, ast.If)
           and isinstance(n.test, ast.Compare)
           and isinstance(n.test.left, ast.Name)
           and n.test.left.id == "__name__"]
    if len(top) != 1 or len(top[0].body) != 1 or not isinstance(top[0].body[0], ast.Expr):
        raise ValueError("Legacy Render __main__ isolation changed")
    stmt = top[0].body[0].value
    if not isinstance(stmt, ast.Call) or not isinstance(stmt.func, ast.Name) or stmt.func.id != "run_legacy_render":
        raise ValueError("Legacy Render startup changed")
    code = (root / "formiq_wsgi.py").read_text(encoding="utf-8")
    ast.parse(code)
    if "set_webhook" in code or "init_db(" in code or "replay_pending(" in code or "configure_formiq_bot_profile(" in code:
        # Comments/docstrings may mention APIs, but there must not be calls.
        tree = ast.parse(code)
        calls = [n.func for n in ast.walk(tree) if isinstance(n, ast.Call)]
        blocked = {"set_webhook", "init_db", "replay_pending", "configure_formiq_bot_profile"}
        if any(isinstance(n, ast.Name) and n.id in blocked or
               isinstance(n, ast.Attribute) and n.attr in blocked for n in calls):
            raise ValueError("WSGI import contains forbidden production side effects")
    return True

def inspect_package(files):
    for path in files:
        if pathlib.PurePosixPath(path).is_absolute() or ".." in pathlib.PurePosixPath(path).parts:
            raise ValueError("Unsafe release path")
        if (re.search(r'(^|/)(\.env[^/]*|\.git|__pycache__|private|secrets)(/|$)', path, re.I)
                or path.endswith((".pem", ".key", ".fiqenc", ".sql", ".sqlite"))):
            raise ValueError("Forbidden deployment package entry")
    return True

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="offline validation (the only pilot mode)")
    args = parser.parse_args()
    if not args.check:
        parser.error("issue #35 permits only --check")
    refuse_runtime_credentials()
    static_entrypoint_check()
    inspect_package(["main.py", "formiq_wsgi.py", "requirements-timeweb.txt",
                     "web/v5-live.js", "scripts/timeweb_release.py"])
    subprocess.run([sys.executable, "-m", "py_compile",
                    str(ROOT / "main.py"), str(ROOT / "formiq_wsgi.py"),
                    str(ROOT / "scripts/timeweb_release.py")],
                   check=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    print("Timeweb pilot: OFFLINE PASS; no Telegram, PostgreSQL, SSH or production calls")

if __name__ == "__main__":
    main()
