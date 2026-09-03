#!/usr/bin/env bash
set -Eeuo pipefail
SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
USER_NAME="${SUDO_USER:-$USER}"
USER_HOME="$(getent passwd "$USER_NAME" | cut -d: -f6)"
ROOT="${AAG_CANON_ROOT:-${XDG_DATA_HOME:-$USER_HOME/.local/share}/aag-canon-4000d}"
STAMP="$(date +%Y%m%d-%H%M%S)"
PARTS=("$SOURCE_DIR"/app/canonical/aag_canon.py.gz.b64.part*)
EXPECTED_B64_SHA256='d3239d838a5ee0cfb853e7823a7a23c32bca9fd97c140fda8b01471f74b7863a'
EXPECTED_SOURCE_SHA256='5e3843a1f70e98eb70e11fe9ee521968625484188d56ca6617cb263bb128824b'

echo "AAG Canon EOS 4000D Linux Manager v1.1.0"
echo "Install root: $ROOT"
[[ -f "$SOURCE_DIR/app/aag_canon.py" ]] || { echo 'ERROR: package incomplete' >&2; exit 1; }
[[ ${#PARTS[@]} -eq 5 ]] || { echo 'ERROR: canonical production payload parts missing' >&2; exit 1; }

sudo apt-get update
sudo apt-get install -y gphoto2 python3-gphoto2 python3-tk python3-pil.imagetk usbutils libglib2.0-bin

if [[ -d "$ROOT" && -n "$(find "$ROOT" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
  BACKUP="$ROOT/backups/$STAMP"; mkdir -p "$BACKUP"
  for item in app bin README.md docs uninstall.sh; do [[ -e "$ROOT/$item" ]] && cp -a "$ROOT/$item" "$BACKUP/" || true; done
  echo "Backup: $BACKUP"
fi

mkdir -p "$ROOT/app" "$ROOT/bin" "$ROOT/logs" "$ROOT/config" "$ROOT/backups"
cp -a "$SOURCE_DIR/app/." "$ROOT/app/"
B64_TMP="$(mktemp)"; SRC_TMP="$(mktemp)"
trap 'rm -f "$B64_TMP" "$SRC_TMP"' EXIT
cat "${PARTS[@]}" > "$B64_TMP"
[[ "$(sha256sum "$B64_TMP" | awk '{print $1}')" == "$EXPECTED_B64_SHA256" ]] || { echo 'ERROR: canonical payload checksum mismatch' >&2; exit 20; }
base64 --decode "$B64_TMP" | gzip -dc > "$SRC_TMP"
[[ "$(sha256sum "$SRC_TMP" | awk '{print $1}')" == "$EXPECTED_SOURCE_SHA256" ]] || { echo 'ERROR: production source checksum mismatch' >&2; exit 21; }
python3 -m py_compile "$SRC_TMP"
install -m 0755 "$SRC_TMP" "$ROOT/app/aag_canon.py"

cp -a "$SOURCE_DIR/bin/." "$ROOT/bin/"
cp -a "$SOURCE_DIR/docs" "$ROOT/"
cp -a "$SOURCE_DIR/README.md" "$ROOT/"
cp -a "$SOURCE_DIR/uninstall.sh" "$ROOT/"
chmod +x "$ROOT/bin/"* "$ROOT/uninstall.sh"

mkdir -p "$USER_HOME/.local/bin" "$USER_HOME/.local/share/applications"
for cmd in aag-canon aag-canon-stop aag-canon-status aag-canon-diagnose; do ln -sfn "$ROOT/bin/$cmd" "$USER_HOME/.local/bin/$cmd"; done
cat > "$USER_HOME/.local/share/applications/aag-canon-4000d.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=AAG Canon EOS 4000D
Comment=Live View, autofocus, capture and download for Canon EOS 4000D
Exec=$USER_HOME/.local/bin/aag-canon
Icon=camera-photo
Terminal=false
Categories=Graphics;Photography;
StartupNotify=true
EOF
chmod 0644 "$USER_HOME/.local/share/applications/aag-canon-4000d.desktop"
update-desktop-database "$USER_HOME/.local/share/applications" 2>/dev/null || true
python3 -m py_compile "$ROOT/app/aag_canon.py"
python3 - <<'PYCHECK'
import gphoto2, tkinter
from PIL import Image, ImageTk
print('Runtime dependencies: OK')
PYCHECK
"$USER_HOME/.local/bin/aag-canon-status" || true

echo
echo 'INSTALLATION COMPLETE'
echo 'Camera: MENU -> Setup -> Auto power off -> Disable'
echo 'Start: aag-canon'
