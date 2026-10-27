#!/usr/bin/env python3
"""Offline release manager; activation requires separate approval and infra."""
import argparse
import contextlib
import fcntl
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import urllib.request

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
LINK_RE = re.compile(r"^releases/[0-9a-f]{40}$")
DENIED = ("TELEGRAM_BOT_TOKEN", "DATABASE_URL", "TIMEWEB_SSH_PRIVATE_KEY",
          "TIMEWEB_SSH_HOST", "FORMIQ_TIMEWEB_REAL_DEPLOY_ENABLED")

def require_release(root, sha):
    if not SHA_RE.fullmatch(sha):
        raise ValueError("Release requires a full immutable Git SHA")
    root = Path(root).resolve(strict=True)
    folder = root / "releases" / sha
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError("Release directory is missing or a symlink")
    marker = folder / ".formiq-release-sha"
    if marker.is_symlink() or not marker.is_file() or marker.read_text().strip() != sha:
        raise ValueError("Release marker does not match approved SHA")
    return root

@contextlib.contextmanager
def exclusive_lock(root):
    fd = os.open(root / ".release-switch.lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

def atomic_current(root, target):
    current = root / "current"
    if target is not None and not LINK_RE.fullmatch(target):
        raise ValueError("Unsafe release link")
    if current.exists() and not current.is_symlink():
        raise ValueError("Cannot replace a real directory")
    if target is None:
        current.unlink(missing_ok=True)
        return
    staging = root / (".current-" + str(os.getpid()))
    if staging.exists() or staging.is_symlink():
        raise ValueError("Temporary link already exists")
    try:
        staging.symlink_to(target)
        os.replace(staging, current)
    finally:
        staging.unlink(missing_ok=True)

def switch_release(root, sha, restart, healthy):
    """Atomic web-only symlink swap, exact SHA probe, rollback and verification."""
    root = require_release(root, sha)
    with exclusive_lock(root):
        current = root / "current"
        if current.exists() and not current.is_symlink():
            raise ValueError("Unsafe current path")
        previous = os.readlink(current) if current.is_symlink() else None
        if previous is not None and not LINK_RE.fullmatch(previous):
            raise ValueError("Current link escapes releases")
        if previous:
            require_release(root, previous.split("/")[1])
        selected = "releases/" + sha
        if previous == selected:
            return {"previous": previous, "current": selected, "changed": False}
        atomic_current(root, selected)
        try:
            restart()
            if not healthy(sha):
                raise RuntimeError("Exact-SHA healthcheck failed")
        except Exception as exc:
            atomic_current(root, previous)
            if previous:
                try:
                    restart()
                    if not healthy(previous.split("/")[1]):
                        raise RuntimeError("Restored service is unhealthy")
                except Exception as rollback_error:
                    raise RuntimeError("Rollback failed; manual intervention required") from rollback_error
            raise RuntimeError("Release failed; prior release restored" if previous
                               else "Initial release failed; no previous version") from exc
        return {"previous": previous, "current": selected, "changed": True}

def simulate():
    if any(os.environ.get(k) for k in DENIED):
        raise RuntimeError("Offline pilot refused: production/deployment credentials present")
    a,b="a"*40,"b"*40
    with tempfile.TemporaryDirectory(prefix="formiq-timeweb-offline-") as tmp:
        root=Path(tmp)
        for sha in (a,b):
            folder=root/"releases"/sha
            folder.mkdir(parents=True)
            (folder/".formiq-release-sha").write_text(sha)
        switch_release(root,a,lambda:None,lambda _:True)
        switch_release(root,b,lambda:None,lambda _:True)
        assert os.readlink(root/"current")=="releases/"+b
        try:
            switch_release(root,a,lambda:None,lambda sha:sha!=a)
        except RuntimeError as error:
            assert "prior release restored" in str(error)
        else:
            raise AssertionError("Failed healthcheck was ignored")
        assert os.readlink(root/"current")=="releases/"+b
    print("Atomic SHA switch: PASS; healthcheck rollback: PASS; OFFLINE only")

def restart_web():
    subprocess.run(["/usr/bin/sudo","-n","/usr/bin/systemctl",
                    "restart","formiq-web.service"],check=True,timeout=35)

def live_health(expected):
    for _ in range(8):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8080/__timeweb_release_health",
                                        timeout=2) as result:
                release_ok = result.status == 200 and result.read(100).decode().strip() == expected
            if release_ok:
                with urllib.request.urlopen("http://127.0.0.1:8080/__timeweb_db_health",
                                            timeout=2) as result:
                    if result.status == 200 and result.read(100).decode().strip() == "DATABASE_READY":
                        return True
        except (OSError,ValueError,UnicodeError):
            pass
        time.sleep(1)
    return False

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("command",choices=("simulate","activate"))
    parser.add_argument("--root")
    parser.add_argument("--sha")
    parser.add_argument("--live",action="store_true")
    args=parser.parse_args()
    if args.command=="simulate":
        if args.root or args.sha or args.live:
            parser.error("Simulation cannot accept live options")
        simulate()
        return
    if not args.live or os.environ.get("FORMIQ_TIMEWEB_REAL_DEPLOY_ENABLED")!="1":
        parser.error("Live activation is disabled until separate infrastructure approval")
    if not args.root or not args.sha or Path(args.root).resolve()!=Path("/srv/formiq"):
        parser.error("Live activation requires /srv/formiq and an explicit immutable SHA")
    result=switch_release(args.root,args.sha,restart_web,live_health)
    print("Web release switched:",result["current"],"verified:",result["changed"])

if __name__=="__main__":
    main()
