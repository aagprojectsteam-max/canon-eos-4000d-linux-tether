#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="${AAG_CANON_ROOT:-${XDG_DATA_HOME:-$HOME/.local/share}/aag-canon-4000d}"
"$HOME/.local/bin/aag-canon-stop" 2>/dev/null || true
rm -f "$HOME/.local/bin/aag-canon" "$HOME/.local/bin/aag-canon-stop" "$HOME/.local/bin/aag-canon-status" "$HOME/.local/bin/aag-canon-diagnose" "$HOME/.local/share/applications/aag-canon-4000d.desktop"
rm -rf -- "$ROOT"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
echo 'AAG Canon EOS 4000D Manager removed. System packages and camera images were left untouched.'
