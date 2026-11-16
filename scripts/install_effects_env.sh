#!/bin/bash
# ---------------------------------------------------------------------------
# Installe l'environnement d'effets de Rexo Studio (M5), isole du systeme :
#   .effets/python   Python 3.11.17 autonome (python-build-standalone, SHA-256 epingle)
#   .effets/venv     ONNX Runtime, NumPy, OpenCV, PyYAML (versions et empreintes
#                    figees dans scripts/effets-requirements.txt, aucun paquet
#                    compile depuis les sources)
#   modeles          MobileSAM (detourage par clic ou cadre), MI-GAN (effacer un
#                    objet), Depth Anything V2 Small (profondeur) : SHA-256 verifies
#                    par embedkit (vendor/embedkit), dans le magasin partage
#                    ~/.local/share/kdev-models/embedkit (KDEV_MODELS_DIR pour un autre)
#
# Le coeur de Rexo Studio reste en Python 3.9 sans dependance : il lance cet
# environnement dans un processus separe. Rien n'est installe hors du dossier du
# projet et du magasin de modeles ; supprimer .effets/ suffit a tout retirer.
# Relancable sans risque : ce qui est deja en place et verifie est garde.
#
#   ./scripts/install_effects_env.sh
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")/.."

GREEN=$'\033[32m'; RED=$'\033[31m'; OFF=$'\033[0m'
ok()   { echo "${GREEN}●${OFF} $*"; }
fail() { echo "${RED}●${OFF} $*" >&2; exit 1; }

ROOT="$PWD"
ENV_DIR="$ROOT/.effets"
PY_RELEASE="20261021"
PY_VERSION="3.11.17"
PY_FILE="cpython-${PY_VERSION}+${PY_RELEASE}-x86_64-apple-darwin-install_only.tar.gz"
PY_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PY_RELEASE}/cpython-${PY_VERSION}%2B${PY_RELEASE}-x86_64-apple-darwin-install_only.tar.gz"
PY_SHA="c647c272312c03301e399f0e0fdb2b876fed213ee6985cd2d232d588a316483f"
MODELS=(mobilesam migan-512 depth-anything-v2-small)
MODELS_STORE="${KDEV_MODELS_DIR:-$HOME/.local/share/kdev-models}/embedkit"

[ "$(uname -s)" = "Darwin" ] || fail "Ce script vise macOS."
[ "$(uname -m)" = "x86_64" ] || fail "Versions figees pour Mac Intel (x86_64) : a refaire pour $(uname -m)."
mkdir -p "$ENV_DIR"

# 1. Python autonome
if [ ! -x "$ENV_DIR/python/bin/python3" ] || \
   [ "$("$ENV_DIR/python/bin/python3" -c 'import platform; print(platform.python_version())')" != "$PY_VERSION" ]; then
  echo "Telechargement de Python $PY_VERSION..."
  curl -fL --retry 3 -o "$ENV_DIR/$PY_FILE.part" "$PY_URL"
  echo "$PY_SHA  $ENV_DIR/$PY_FILE.part" | shasum -a 256 -c - >/dev/null \
    || fail "Empreinte SHA-256 de Python incorrecte : fichier refuse."
  mv "$ENV_DIR/$PY_FILE.part" "$ENV_DIR/$PY_FILE"
  rm -rf "$ENV_DIR/python.new"
  mkdir -p "$ENV_DIR/python.new"
  tar xzf "$ENV_DIR/$PY_FILE" -C "$ENV_DIR/python.new"
  rm -rf "$ENV_DIR/python"
  mv "$ENV_DIR/python.new/python" "$ENV_DIR/python"
  rmdir "$ENV_DIR/python.new"
  rm -f "$ENV_DIR/$PY_FILE"
  rm -rf "$ENV_DIR/venv"            # lie a l'ancien Python
fi
ok "Python $("$ENV_DIR/python/bin/python3" -c 'import platform; print(platform.python_version())')"

# 2. Paquets (empreintes verifiees, paquets compiles seulement)
if [ ! -x "$ENV_DIR/venv/bin/python" ]; then
  "$ENV_DIR/python/bin/python3" -m venv "$ENV_DIR/venv"
fi
"$ENV_DIR/venv/bin/python" -m pip install -q --disable-pip-version-check \
  --require-hashes --only-binary :all: -r scripts/effets-requirements.txt
ok "Paquets : $("$ENV_DIR/venv/bin/python" -c 'import onnxruntime, numpy, cv2; print("onnxruntime", onnxruntime.__version__, "numpy", numpy.__version__, "opencv", cv2.__version__)')"

# 3. Modeles (magasin partage ; un cache embedkit deja present sur la machine est repris)
export PYTHONPATH="$ROOT/vendor/embedkit"
export EMBEDKIT_CACHE="$MODELS_STORE"
mkdir -p "$MODELS_STORE"
for m in "${MODELS[@]}"; do
  if [ ! -d "$MODELS_STORE/$m" ] && [ -d "$HOME/.cache/embedkit/$m" ]; then
    cp -R "$HOME/.cache/embedkit/$m" "$MODELS_STORE/$m"
  fi
  "$ENV_DIR/venv/bin/python" -m embedkit.cli models pull "$m" >/dev/null
  "$ENV_DIR/venv/bin/python" -m embedkit.cli models verify "$m" >/dev/null \
    || fail "Modele $m : empreinte incorrecte."
  ok "Modele $m (SHA-256 verifie)"
done

ok "Environnement d'effets pret : $ENV_DIR (verifier avec ./scripts/check_install.sh)"
