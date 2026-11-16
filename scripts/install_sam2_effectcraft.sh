#!/bin/bash
# ---------------------------------------------------------------------------
# Installe dans EffectCraft le modele SAM 2.1 Tiny (Meta, Apache-2.0) qui suit une
# personne d'image en image (detourage video de la chaine de production).
# EffectCraft ne sait pas le telecharger lui-meme pour cette taille : on le prend sur
# Hugging Face a une revision figee, on verifie son empreinte (celle du registre
# d'EffectCraft), puis EffectCraft l'installe et le reverifie (roto.model.install).
#
#   ./scripts/install_sam2_effectcraft.sh
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")/.."

GREEN=$'\033[32m'; RED=$'\033[31m'; OFF=$'\033[0m'
ok()   { echo "${GREEN}●${OFF} $*"; }
fail() { echo "${RED}●${OFF} $*" >&2; exit 1; }

URL="https://huggingface.co/facebook/sam2.1-hiera-tiny/resolve/de431c4043854a71d8101e17995dfe596bf101a5/model.safetensors"
SHA="48c14467e5cf9e51870511feb72c89688e82dd74523142c0538b663e193ac2a7"
WORK="${TMPDIR:-/tmp}/rexo-sam2"
DEST="$HOME/Library/Application Support/EffectCraft/models/sam2.1-hiera-tiny.safetensors"

[ -d /Applications/EffectCraft.app ] || [ -n "${REXO_EFFECTCRAFT_APP:-}" ] || fail "EffectCraft absent"
if [ -f "$DEST" ] && [ "$(shasum -a 256 "$DEST" | cut -d' ' -f1)" = "$SHA" ]; then
  ok "SAM 2.1 Tiny deja installe dans EffectCraft"
  exit 0
fi
mkdir -p "$WORK"
echo "Telechargement de SAM 2.1 Tiny (156 Mo)..."
curl -fL --retry 3 -o "$WORK/model.safetensors" "$URL"
[ "$(shasum -a 256 "$WORK/model.safetensors" | cut -d' ' -f1)" = "$SHA" ] || fail "Empreinte SHA-256 incorrecte"
ok "Empreinte verifiee"
python3 - "$WORK/model.safetensors" <<'PY'
import os, sys
sys.path.insert(0, os.getcwd())
from montagia import effectcraft
client = effectcraft.connect(print)
try:
    client.execute("roto.model.install", {"path": sys.argv[1], "id": "sam2.1-hiera-tiny", "wait": True})
    client.execute("roto.model.select", {"id": "sam2.1-hiera-tiny", "wait": True})
finally:
    effectcraft.close(client, os.path.dirname(sys.argv[1]))
PY
rm -rf "$WORK"
ok "SAM 2.1 Tiny installe et choisi dans EffectCraft"
