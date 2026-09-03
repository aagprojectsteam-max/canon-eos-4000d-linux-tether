#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "$ROOT" <<'PY'
import base64
import gzip
import hashlib
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
parts = sorted((root / 'app' / 'canonical').glob('aag_canon.py.gz.b64.part*'))
assert len(parts) == 5, f'expected 5 canonical parts, got {len(parts)}'
encoded = ''.join(p.read_text(encoding='ascii').strip() for p in parts)
compressed = base64.b64decode(encoded, validate=True)
source = gzip.decompress(compressed)
expected = '5e3843a1f70e98eb70e11fe9ee521968625484188d56ca6617cb263bb128824b'
actual = hashlib.sha256(source).hexdigest()
assert actual == expected, f'canonical source hash mismatch: {actual}'
compile(source, 'aag_canon.py', 'exec')
print('Canonical source integrity: PASS')
PY

python3 -m py_compile "$ROOT/app/aag_canon.py"
for f in "$ROOT/install.sh" "$ROOT/uninstall.sh" "$ROOT/bin/"* "$ROOT/dist/"*.run; do
  bash -n "$f"
done

# Scan public payload/docs for known private development identifiers. Exclude this
# test file itself because the forbidden patterns necessarily appear in its rule.
if grep -RniE 'aag-linux|023070006323|f17acb8b|/mnt/data/MyProjects|Adir Avraham|Gal-on' \
  "$ROOT/app" "$ROOT/bin" "$ROOT/docs" "$ROOT/README.md" "$ROOT/CHANGELOG.md" \
  "$ROOT/CONTRIBUTING.md" "$ROOT/SECURITY.md" "$ROOT/install.sh" "$ROOT/uninstall.sh" \
  "$ROOT/dist"; then
  echo 'ERROR: private/development-only identifier found' >&2
  exit 1
fi

echo 'Privacy scan: PASS'
echo 'Static tests: PASS'
