#!/bin/bash
# ---------------------------------------------------------------------------
# Installe Blender 3.6 LTS (moteur des scenes 3D de la chaine de production) et
# construit le decor d exemple (jardin de nuit) s il manque.
#
#   ~/Applications/Blender-3.6.app   Blender 3.6.23 macOS Intel, SHA-256 epingle
#   scenes/jardin_nuit.blend   (decor d exemple ; les vrais decors : python3 -m atelier scene ...)
#
# Pourquoi 3.6 et pas 4.x : Blender 4.x ne dessine qu'en Metal, et plante au demarrage
# sur l'Iris Pro 6200 de l'iMac late 2015 ; la 3.6 utilise OpenGL (EEVEE), mesure sur
# l'iMac le 16/11/2026 : 1,7 s par image 1080p en qualite normale.
# Rien n'est installe hors de ~/Applications et du dossier du projet. Relancable.
#
#   ./scripts/install_blender.sh
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")/.."

GREEN=$'\033[32m'; RED=$'\033[31m'; OFF=$'\033[0m'
ok()   { echo "${GREEN}●${OFF} $*"; }
fail() { echo "${RED}●${OFF} $*" >&2; exit 1; }

VERSION="3.6.23"
DMG="blender-${VERSION}-macos-x64.dmg"
URL="https://download.blender.org/release/Blender3.6/${DMG}"
SHA="910bd19e4d0f87be301df380a4fb03a08b9dcdb2b164dd0cabfb889a8dac03c2"
APP="${ATELIER_BLENDER_APP:-$HOME/Applications/Blender-3.6.app}"
# Blender 3.6 deja installe a la main dans /Applications (MacBook de developpement)
if [ -z "${ATELIER_BLENDER_APP:-}" ] && [ ! -d "$APP" ] && \
   /Applications/Blender.app/Contents/MacOS/Blender -b --version 2>/dev/null | grep -q "Blender ${VERSION}"; then
  APP="/Applications/Blender.app"
fi
SCENES="${ATELIER_SCENES_DIR:-$PWD/scenes}"
WORK="${TMPDIR:-/tmp}/rexo-blender-install"

[ "$(uname -s)" = "Darwin" ] || fail "Ce script vise macOS."
[ "$(uname -m)" = "x86_64" ] || fail "Version figee pour Mac Intel (x86_64) : a refaire pour $(uname -m)."

if [ -x "$APP/Contents/MacOS/Blender" ] && \
   "$APP/Contents/MacOS/Blender" -b --version 2>/dev/null | grep -q "Blender ${VERSION}"; then
  ok "Blender ${VERSION} deja installe : $APP"
else
  mkdir -p "$WORK"
  if [ ! -f "$WORK/$DMG" ] || [ "$(shasum -a 256 "$WORK/$DMG" | cut -d' ' -f1)" != "$SHA" ]; then
    echo "Telechargement de $DMG (environ 230 Mo)..."
    curl -fL --retry 3 -o "$WORK/$DMG" "$URL"
  fi
  [ "$(shasum -a 256 "$WORK/$DMG" | cut -d' ' -f1)" = "$SHA" ] || fail "Empreinte SHA-256 de $DMG incorrecte"
  ok "Empreinte verifiee"
  MNT="$(mktemp -d)"
  hdiutil attach -nobrowse -readonly -mountpoint "$MNT" "$WORK/$DMG" >/dev/null
  trap 'hdiutil detach "$MNT" >/dev/null 2>&1 || true' EXIT
  mkdir -p "$(dirname "$APP")"
  rm -rf "$APP.partiel"
  ditto "$MNT/Blender.app" "$APP.partiel"
  hdiutil detach "$MNT" >/dev/null
  trap - EXIT
  rm -rf "$APP"
  mv "$APP.partiel" "$APP"
  # Telecharge par curl : pas de quarantaine, mais on s'en assure
  xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true
  rm -f "$WORK/$DMG"
  ok "Blender ${VERSION} installe : $APP"
fi

mkdir -p "$SCENES"
if [ -f "$SCENES/jardin_nuit.blend" ]; then
  ok "Modele de scene present : $SCENES/jardin_nuit.blend"
else
  "$APP/Contents/MacOS/Blender" -b --factory-startup --python blender/build_template_jardin_nuit.py \
    -- "$SCENES/jardin_nuit.blend" >/dev/null
  [ -f "$SCENES/jardin_nuit.blend" ] || fail "Construction du modele de scene impossible"
  ok "Modele de scene construit : $SCENES/jardin_nuit.blend"
fi
