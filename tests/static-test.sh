#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
python3 -m py_compile "$ROOT/app/aag_canon.py"
for f in "$ROOT/install.sh" "$ROOT/uninstall.sh" "$ROOT/bin/"*; do bash -n "$f"; done
TMP="$(mktemp)"; trap 'rm -f "$TMP"' EXIT
base64 --decode "$ROOT/app/aag_canon.py.gz.b64" | gzip -dc > "$TMP"
python3 -m py_compile "$TMP"
if grep -RniE 'aag-linux|023070006323|f17acb8b|/mnt/data/MyProjects|Adir Avraham|Gal-on' "$ROOT" --exclude-dir=.git; then
  echo 'ERROR: private/development-only identifier found' >&2
  exit 1
fi
echo 'Static tests: PASS'
