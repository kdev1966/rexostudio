#!/bin/bash
# ---------------------------------------------------------------------------
# Verifie une installation de Rexo Studio, composant par composant, avec de
# vrais essais (aucune photo de client : images synthetiques).
#
#   ./scripts/check_install.sh                  tout verifier
#   ./scripts/check_install.sh --photo P.jpg    + effets sur une vraie photo,
#                                               resultats dans un dossier temporaire
#   ./scripts/check_install.sh --quick          sans les tests unitaires
#
# ● vert = pret ; ● orange = facultatif absent ; ● rouge = a corriger.
# Code de sortie 1 si un element obligatoire manque ou echoue.
# Guide complet : docs/DEPLOIEMENT.md
# ---------------------------------------------------------------------------
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"

GREEN=$'\033[32m'; ORANGE=$'\033[38;5;208m'; RED=$'\033[31m'; OFF=$'\033[0m'
FAILED=0
ok()   { echo "${GREEN}●${OFF} $*"; }
warn() { echo "${ORANGE}●${OFF} $*"; }
bad()  { echo "${RED}●${OFF} $*"; FAILED=1; }

PHOTO=""; QUICK=0
while [ $# -gt 0 ]; do
  case "$1" in
    --photo) PHOTO="$2"; shift 2 ;;
    --quick) QUICK=1; shift ;;
    *) echo "option inconnue : $1" >&2; exit 2 ;;
  esac
done

TMP="$(mktemp -d "${TMPDIR:-/tmp}/rexo-check.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

echo "== Machine"
ok "$(sysctl -n machdep.cpu.brand_string 2>/dev/null), $(( $(sysctl -n hw.memsize) / 1073741824 )) Go, macOS $(sw_vers -productVersion)"
case "$PWD" in
  "$HOME/Desktop"*|"$HOME/Documents"*|"$HOME/Downloads"*)
    bad "Projet dans un dossier protege ($PWD) : l'icone ne pourra pas le lire" ;;
esac

echo "== Coeur (Python 3.9, bibliotheque standard)"
PYV="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)"
if [ -n "$PYV" ]; then ok "python3 $PYV"; else bad "python3 introuvable"; fi
if [ "$QUICK" = 0 ]; then
  if OUT="$(python3 -m unittest discover -s tests 2>&1)"; then
    ok "Tests unitaires : $(echo "$OUT" | grep -E '^Ran ' | sed 's/^Ran //')"
  else
    bad "Tests unitaires en echec :"; echo "$OUT" | tail -15
  fi
fi

echo "== Outils du projet (bin/, models/)"
for b in ffmpeg ffprobe whisper-cli llama-server; do
  if [ -x "bin/$b" ]; then ok "bin/$b"; else bad "bin/$b absent : ./scripts/install_models.sh"; fi
done
GGUF="$(python3 -c 'from montagia import config; print(config.LLM_GGUF)' 2>/dev/null)"
if [ -n "$GGUF" ] && [ -f "$GGUF" ]; then ok "Modele IA $(basename "$GGUF")"; else bad "Modele IA absent : ./scripts/install_models.sh"; fi
if ls models/ggml-*.bin >/dev/null 2>&1; then ok "Modeles Whisper : $(cd models && ls ggml-*.bin | tr '\n' ' ')"; else bad "Modeles Whisper absents"; fi

# Image d'essai synthetique (PNG ecrit par la bibliotheque standard)
python3 - "$TMP/essai.png" <<'PY'
import struct, sys, zlib
w, h = 320, 240
rows = b"".join(b"\x00" + bytes(v for x in range(w) for v in
                (40 + x * 160 // w, 90, 220 if (x - 160) ** 2 + (y - 120) ** 2 < 3600 else 60))
                for y in range(h))
chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
open(sys.argv[1], "wb").write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                              + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))
PY

echo "== Effets photo : Apple Vision (bin/rexo-segment)"
if [ -x bin/rexo-segment ] && [ ! native/segment.swift -nt bin/rexo-segment ]; then
  if R="$(bin/rexo-segment blur "$TMP/essai.png" "$TMP/flou.jpg")" && [ -s "$TMP/flou.jpg" ]; then
    ok "rexo-segment : $R"
  else
    bad "rexo-segment echoue : $R"
  fi
else
  bad "bin/rexo-segment absent ou plus ancien que sa source : ./scripts/build_native.sh"
fi

echo "== Applications pilotees"
FC="$(python3 -c 'from montagia import config; print(config.FILMCRAFT_APP)')"
if [ -d "$FC" ]; then ok "FilmCraft $(defaults read "$FC/Contents/Info" CFBundleShortVersionString 2>/dev/null)"; else warn "FilmCraft absent (envoi des selections indisponible)"; fi
PC="$(python3 -c 'from montagia import config; print(config.PHOTOCRAFT_CLI)')"
if [ -x "$PC" ]; then
  if "$PC" run "$TMP/essai.png" --cmd select.object --params '{"rect":[100,40,140,160]}' \
       --cmd layer.layerMask.revealSelection --out "$TMP/objet.png" >/dev/null 2>&1 && [ -s "$TMP/objet.png" ]; then
    ok "PhotoCraft $("$PC" --version 2>/dev/null | awk '{print $2}') : selection d'objet dans un cadre"
  else
    bad "PhotoCraft present mais l'essai de selection echoue"
  fi
  # PSD a calques (bouton « Affiner dans PhotoCraft ») : masque tire d'un PNG transparent
  if R="$(python3 - "$TMP" <<'PY' 2>&1
import json, os, struct, subprocess, sys, zlib
tmp = sys.argv[1]
w, h = 320, 240
def png(path, rgba):
    rows = b"".join(b"\x00" + bytes(v for x in range(w) for v in rgba(x, y)) for y in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    open(path, "wb").write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))
png(os.path.join(tmp, "alpha.png"), lambda x, y: (255, 255, 255, 255 if (x - 160) ** 2 + (y - 120) ** 2 < 3600 else 0))
sys.path.insert(0, os.getcwd())
from montagia import config, photocraft
out = os.path.join(tmp, "psd", "essai.psd")
photocraft.layered_psd(os.path.join(tmp, "essai.png"), os.path.join(tmp, "flou.jpg"),
                       os.path.join(tmp, "alpha.png"), "outside", "Fond", out, [tmp])
info = json.loads(subprocess.run([config.PHOTOCRAFT_CLI, "info", out], capture_output=True, text=True).stdout)
masks = [l["hasMask"] for l in info["layers"]]
assert masks == [True, False], masks
print("%d calques, masque modifiable" % len(masks))
PY
)"; then
    ok "PhotoCraft : PSD a calques ($R)"
  else
    bad "PhotoCraft : PSD a calques en echec : $(echo "$R" | tail -1)"
  fi
else
  warn "PhotoCraft absent (cadre autour des maries et retouche indisponibles)"
fi

echo "== Environnement d'effets (.effets : ONNX Runtime + modeles)"
EPY="$ROOT/.effets/venv/bin/python"
if [ -x "$EPY" ]; then
  export PYTHONPATH="$ROOT/vendor/embedkit"
  export EMBEDKIT_CACHE="${KDEV_MODELS_DIR:-$HOME/.local/share/kdev-models}/embedkit"
  ok "$("$EPY" -c 'import platform, onnxruntime, numpy, cv2; print("Python", platform.python_version(), "| onnxruntime", onnxruntime.__version__, "| numpy", numpy.__version__, "| opencv", cv2.__version__)')"
  if "$EPY" -m embedkit.cli models verify mobilesam migan-512 depth-anything-v2-small >/dev/null 2>&1; then
    ok "Modeles intacts (SHA-256) dans $EMBEDKIT_CACHE"
  else
    bad "Modeles manquants ou abimes : ./scripts/install_effects_env.sh"
  fi
  ARGS=()
  if [ -n "$PHOTO" ]; then
    RES="$(mktemp -d "${TMPDIR:-/tmp}/rexo-photo.XXXXXX")"
    ARGS=(--photo "$PHOTO" --out "$RES")
  fi
  if OUT="$("$EPY" scripts/effets_smoke.py "${ARGS[@]+"${ARGS[@]}"}" 2>&1)"; then
    echo "$OUT" | sed 's/^/    /'
    ok "Essais reels des modeles reussis"
  else
    echo "$OUT" | tail -8 | sed 's/^/    /'
    bad "Essai des modeles en echec"
  fi
else
  bad "Environnement d'effets absent : ./scripts/install_effects_env.sh"
fi

echo "== Chaine de production (bibliotheque d'animations + EffectCraft)"
# Les animations 3D sont fabriquees par l'atelier (projet RexoAtelier) et livrees a part
N="$(python3 scripts/installer_animations.py --liste 2>/dev/null | grep -c '^  [^(]')"
if [ "$N" -gt 0 ]; then
  ok "Bibliotheque d'animations : $N animation(s)"
else
  warn "Bibliotheque d'animations vide (clip drone indisponible) : python3 scripts/installer_animations.py <livraison.zip>"
fi
EC="${REXO_EFFECTCRAFT_APP:-/Applications/EffectCraft.app}"
if [ -d "$EC" ]; then
  ok "EffectCraft $(defaults read "$EC/Contents/Info" CFBundleShortVersionString 2>/dev/null) (commandes verifiees a chaque clip)"
else
  warn "EffectCraft absent (clip drone, generique et detourage video indisponibles)"
fi

echo
if [ "$FAILED" = 0 ]; then ok "Installation complete et verifiee."; else bad "Installation incomplete : voir les points rouges."; exit 1; fi
