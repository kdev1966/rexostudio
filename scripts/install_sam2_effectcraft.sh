#!/bin/bash
# ---------------------------------------------------------------------------
# Installe dans EffectCraft un modele SAM 2.1 (Meta, Apache-2.0) qui suit une personne
# d'image en image (detourage video de la chaine de production) : tiny (par defaut,
# 156 Mo), small (184 Mo) ou base-plus (323 Mo), plus precis mais plus lents.
# EffectCraft ne sait pas le telecharger lui-meme pour cette taille : on le prend sur
# Hugging Face a une revision figee, on verifie son empreinte (celle du registre
# d'EffectCraft), puis EffectCraft l'installe et le reverifie (roto.model.install).
#
#   ./scripts/install_sam2_effectcraft.sh [tiny|small|base-plus]
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")/.."

GREEN=$'\033[32m'; RED=$'\033[31m'; OFF=$'\033[0m'
ok()   { echo "${GREEN}●${OFF} $*"; }
fail() { echo "${RED}●${OFF} $*" >&2; exit 1; }

SIZE="${1:-tiny}"
case "$SIZE" in
  tiny)      REV=de431c4043854a71d8101e17995dfe596bf101a5; SHA=48c14467e5cf9e51870511feb72c89688e82dd74523142c0538b663e193ac2a7 ;;
  small)     REV=ee5bba1d82bb8749febdf90f45e84b687142ba03; SHA=0a4067b11ce1e23d5229203f11c718a823060d15a4b23fa2372a7d4b77cbbc60 ;;
  base-plus) REV=b7320756a13354e7530a63935656d35b2f91a290; SHA=2012733a0de5d03efd1bba550a2847c4551be9ef2e0d497c83074df66189f780 ;;
  *) echo "Taille inconnue : $SIZE (tiny, small ou base-plus)" >&2; exit 2 ;;
esac
ID="sam2.1-hiera-$SIZE"
URL="https://huggingface.co/facebook/$ID/resolve/$REV/model.safetensors"
WORK="${TMPDIR:-/tmp}/rexo-sam2-$SIZE"
DEST="$HOME/Library/Application Support/EffectCraft/models/$ID.safetensors"

[ -d /Applications/EffectCraft.app ] || [ -n "${REXO_EFFECTCRAFT_APP:-}" ] || fail "EffectCraft absent"
if [ -f "$DEST" ] && [ "$(shasum -a 256 "$DEST" | cut -d' ' -f1)" = "$SHA" ]; then
  ok "$ID deja installe dans EffectCraft"
  exit 0
fi
mkdir -p "$WORK"
echo "Telechargement de $ID..."
curl -fL --retry 3 -o "$WORK/model.safetensors" "$URL"
[ "$(shasum -a 256 "$WORK/model.safetensors" | cut -d' ' -f1)" = "$SHA" ] || fail "Empreinte SHA-256 incorrecte"
ok "Empreinte verifiee"
python3 - "$WORK/model.safetensors" "$ID" <<'PY'
import os, sys
sys.path.insert(0, os.getcwd())
from montagia import effectcraft
client = effectcraft.connect(print)
try:
    client.execute("roto.model.install", {"path": sys.argv[1], "id": sys.argv[2], "wait": True})
finally:
    effectcraft.close(client, os.path.dirname(sys.argv[1]))
PY
rm -rf "$WORK"
ok "$ID installe dans EffectCraft"
