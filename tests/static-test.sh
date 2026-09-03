#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
EXPECTED_B64_SHA256='d3239d838a5ee0cfb853e7823a7a23c32bca9fd97c140fda8b01471f74b7863a'
EXPECTED_SOURCE_SHA256='5e3843a1f70e98eb70e11fe9ee521968625484188d56ca6617cb263bb128824b'
python3 -m py_compile "$ROOT/app/aag_canon.py"
for f in "$ROOT/install.sh" "$ROOT/uninstall.sh" "$ROOT/bin/"* "$ROOT/dist/"*.run; do bash -n "$f"; done
B64_TMP="$(mktemp)"; SRC_TMP="$(mktemp)"; trap 'rm -f "$B64_TMP" "$SRC_TMP"' EXIT
cat "$ROOT"/app/canonical/aag_canon.py.gz.b64.part* > "$B64_TMP"
[[ "$(sha256sum "$B64_TMP" | awk '{print $1}')" == "$EXPECTED_B64_SHA256" ]]
base64 --decode "$B64_TMP" | gzip -dc > "$SRC_TMP"
[[ "$(sha256sum "$SRC_TMP" | awk '{print $1}')" == "$EXPECTED_SOURCE_SHA256" ]]
python3 -m py_compile "$SRC_TMP"
if grep -RniE 'aag-linux|023070006323|f17acb8b|/mnt/data/MyProjects|Adir Avraham|Gal-on' "$ROOT" --exclude-dir=.git; then
  echo 'ERROR: private/development-only identifier found' >&2
  exit 1
fi
echo 'Static tests: PASS'
