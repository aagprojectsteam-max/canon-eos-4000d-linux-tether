#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
python3 -m py_compile "$ROOT/app/aag_canon.py"
for f in "$ROOT/install.sh" "$ROOT/uninstall.sh" "$ROOT/bin/"*; do bash -n "$f"; done
echo 'Static tests: PASS'
