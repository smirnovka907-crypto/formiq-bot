#!/usr/bin/env bash
# Strictly OFFLINE source-package demo. No login, SSH, Render API or secrets.
set -euo pipefail
for secret in TELEGRAM_BOT_TOKEN DATABASE_URL YANDEX_API_KEY TIMEWEB_SSH_PRIVATE_KEY TIMEWEB_SSH_HOST FORMIQ_TIMEWEB_REAL_DEPLOY_ENABLED; do
  if [[ -n "$(printenv "$secret" || true)" ]]; then
    echo 'REFUSED: offline packaging received runtime credentials' >&2
    exit 2
  fi
done
sha="$(git rev-parse HEAD)"
[[ "$sha" =~ ^[0-9a-f]{40}$ ]] || exit 2
root="$(git rev-parse --show-toplevel)"
out="$(realpath -m "${1:-${RUNNER_TEMP:-/tmp}/formiq-timeweb-offline-${sha}.tar.gz}")"
test ! -e "$out" || { echo 'Refusing to overwrite an archive' >&2; exit 2; }
temp="$(mktemp -d)"
trap 'rm -rf "$temp"' EXIT
mkdir -p "$temp/tree"
# Strictly tracked, allowlisted runtime files. Excludes docs, workflows and local keys.
git -C "$root" archive "$sha" main.py formiq_wsgi.py approved_assets.py welcome_art.py weight_import.py requirements.txt requirements-timeweb.txt assets web integrations | tar -x -C "$temp/tree"
printf '%s\n' "$sha" > "$temp/tree/.formiq-release-sha"
tar --sort=name --owner=0 --group=0 --numeric-owner -C "$temp/tree" -czf "$out" .
python - "$out" <<'PY'
import sys, tarfile
from scripts.timeweb_pilot import inspect_package
with tarfile.open(sys.argv[1], 'r:gz') as archive:
    entries=archive.getmembers()
    inspect_package([e.name.removeprefix('./') for e in entries])
    if any(e.issym() or e.islnk() or e.isdev() for e in entries):
        raise SystemExit('Package cannot contain symlinks, links or devices')
print('Offline allowlisted release archive verified')
PY
sha256sum "$out"
echo 'No remote transfer, real deployment, Render or Telegram operations'
