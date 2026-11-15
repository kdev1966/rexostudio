#!/bin/bash
# ---------------------------------------------------------------------------
# Installe les outils locaux de transcription, sans dependance externe :
#   1. bin/whisper-cli  : whisper.cpp compile en STATIQUE (un seul binaire,
#                         aucune bibliotheque .dylib a cote)
#   2. models/          : modele Whisper + modele VAD Silero
#   3. bin/ffmpeg, bin/ffprobe : builds statiques epingles par SHA-256
# Tout est verifie : somme SHA-256 de CMake et des modeles, commit Git de
# whisper.cpp. Relancable sans risque : ce qui est deja en place est garde.
#
#   ./scripts/install_models.sh            base + VAD
#   ./scripts/install_models.sh small      ajoute le modele small (488 Mo)
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")/.."

GREEN=$'\033[32m'; ORANGE=$'\033[38;5;208m'; RED=$'\033[31m'; OFF=$'\033[0m'
ok()   { echo "${GREEN}●${OFF} $*"; }
warn() { echo "${ORANGE}●${OFF} $*"; }
fail() { echo "${RED}●${OFF} $*"; exit 1; }

ROOT="$PWD"
MODELS_DIR="$ROOT/models"
BIN_DIR="$ROOT/bin"
BUILD_DIR="${MONTAGIA_BUILD_DIR:-$HOME/Library/Caches/MontageIA-build}"

# Versions figees (verifiees le 15/11/2026)
WHISPER_TAG="v1.9.5"
WHISPER_COMMIT="d2a764c648779feb36d44363f212a29b00aad1af"
CMAKE_VERSION="4.4.5"

mkdir -p "$MODELS_DIR" "$BIN_DIR"

# Telecharge $2 vers $1 et verifie la somme SHA-256 $3 (fichier garde s'il est deja bon).
fetch() {
  local dest="$1" url="$2" sha="$3"
  if [ -f "$dest" ] && echo "$sha  $dest" | shasum -a 256 -c - >/dev/null 2>&1; then
    ok "$(basename "$dest") deja present (SHA-256 verifie)"
    return
  fi
  curl -fL --progress-bar -o "$dest.part" "$url"
  echo "$sha  $dest.part" | shasum -a 256 -c - >/dev/null || { rm -f "$dest.part"; fail "SHA-256 incorrect pour $(basename "$dest")"; }
  mv "$dest.part" "$dest"
  ok "$(basename "$dest") telecharge (SHA-256 verifie)"
}

# --------------------------------------------------------------------------
echo "== 1/3  binaire whisper-cli =="
if "$BIN_DIR/whisper-cli" --help >/dev/null 2>&1; then
  ok "bin/whisper-cli fonctionne deja"
else
  [ -x "$BIN_DIR/whisper-cli" ] && warn "bin/whisper-cli present mais inutilisable (bibliotheque manquante) : recompilation"
  command -v clang >/dev/null || fail "compilateur absent : lancez  xcode-select --install"
  mkdir -p "$BUILD_DIR"; cd "$BUILD_DIR"

  CM="cmake-$CMAKE_VERSION-macos-universal"
  CMAKE="$BUILD_DIR/$CM/CMake.app/Contents/bin/cmake"
  if [ ! -x "$CMAKE" ]; then
    curl -fsSL -o cmake-sha.txt "https://github.com/Kitware/CMake/releases/download/v$CMAKE_VERSION/cmake-$CMAKE_VERSION-SHA-256.txt"
    curl -fL --progress-bar -o "$CM.tar.gz" "https://github.com/Kitware/CMake/releases/download/v$CMAKE_VERSION/$CM.tar.gz"
    grep " $CM.tar.gz\$" cmake-sha.txt | shasum -a 256 -c - >/dev/null || fail "SHA-256 de CMake incorrect"
    tar -xzf "$CM.tar.gz" && rm "$CM.tar.gz"
    ok "CMake $CMAKE_VERSION (SHA-256 verifie)"
  fi

  rm -rf whisper.cpp
  git -c advice.detachedHead=false clone -q --depth 1 --branch "$WHISPER_TAG" \
    https://github.com/ggml-org/whisper.cpp.git
  [ "$(git -C whisper.cpp rev-parse HEAD)" = "$WHISPER_COMMIT" ] || fail "commit whisper.cpp inattendu"
  ok "whisper.cpp $WHISPER_TAG (commit verifie)"

  # Jeu d'instructions commun aux Mac Intel 2015 (Haswell/Broadwell) :
  # GGML_NATIVE=OFF pour qu'un binaire compile sur l'iMac tourne aussi
  # sur le MacBook (qui n'a pas ADX), et inversement.
  "$CMAKE" -S whisper.cpp -B whisper.cpp/build -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_SHARED_LIBS=OFF -DGGML_NATIVE=OFF \
    -DGGML_AVX=ON -DGGML_AVX2=ON -DGGML_FMA=ON -DGGML_F16C=ON \
    -DWHISPER_BUILD_TESTS=OFF -DWHISPER_BUILD_SERVER=OFF \
    -DCMAKE_OSX_DEPLOYMENT_TARGET=12.0 >configure.log 2>&1 \
    || { tail -30 configure.log; fail "configuration CMake echouee"; }
  echo "Compilation (quelques minutes)..."
  "$CMAKE" --build whisper.cpp/build -j"$(sysctl -n hw.ncpu)" --target whisper-cli >build.log 2>&1 \
    || { tail -30 build.log; fail "compilation echouee (voir $BUILD_DIR/build.log)"; }

  install -m 755 whisper.cpp/build/bin/whisper-cli "$BIN_DIR/whisper-cli"
  cd "$ROOT"
  if otool -L "$BIN_DIR/whisper-cli" | grep -q "@rpath"; then
    fail "bin/whisper-cli depend encore de bibliotheques externes"
  fi
  "$BIN_DIR/whisper-cli" --help >/dev/null 2>&1 || fail "bin/whisper-cli ne demarre pas"
  ok "bin/whisper-cli compile (statique)"
fi

# --------------------------------------------------------------------------
echo "== 2/3  modeles =="
HF="https://huggingface.co"
fetch "$MODELS_DIR/ggml-base.bin" "$HF/ggerganov/whisper.cpp/resolve/main/ggml-base.bin" \
  60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe
fetch "$MODELS_DIR/ggml-silero-v6.2.0.bin" "$HF/ggml-org/whisper-vad/resolve/main/ggml-silero-v6.2.0.bin" \
  2aa269b785eeb53a82983a20501ddf7c1d9c48e33ab63a41391ac6c9f7fb6987
if [ "${1:-}" = "small" ]; then
  fetch "$MODELS_DIR/ggml-small.bin" "$HF/ggerganov/whisper.cpp/resolve/main/ggml-small.bin" \
    1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b
fi

# --------------------------------------------------------------------------
echo "== 3/3  ffmpeg / ffprobe =="
# Builds statiques macOS Intel d'evermeet.cx (libass, VideoToolbox, scdet),
# epingles par SHA-256 : un fichier different est refuse.
# Note : evermeet ne publie pas de somme ; celles-ci ont ete relevees et le
# binaire verifie (liens systeme uniquement, filtres et encodeurs) le 15/11/2026.
FFMPEG_VERSION="9.0.2"
for tool in ffmpeg ffprobe; do
  case "$tool" in
    ffmpeg)  sha=a45b462cf91ed89148ae218c4577e30896485d7a6792c3673bcf5f823fa01b63 ;;
    ffprobe) sha=a29f8c2e03553223a8b480b1a1f04c42f680c138fa952c20086718a075db38cb ;;
  esac
  if [ -x "$BIN_DIR/$tool" ] && echo "$sha  $BIN_DIR/$tool" | shasum -a 256 -c - >/dev/null 2>&1; then
    ok "bin/$tool deja present (SHA-256 verifie)"
    continue
  fi
  tmp="$(mktemp -d)"
  curl -fL --progress-bar -o "$tmp/$tool.zip" "https://evermeet.cx/ffmpeg/$tool-$FFMPEG_VERSION.zip"
  unzip -q "$tmp/$tool.zip" -d "$tmp"
  echo "$sha  $tmp/$tool" | shasum -a 256 -c - >/dev/null || { rm -rf "$tmp"; fail "SHA-256 incorrect pour $tool"; }
  install -m 755 "$tmp/$tool" "$BIN_DIR/$tool"
  rm -rf "$tmp"
  ok "bin/$tool $FFMPEG_VERSION installe (SHA-256 verifie)"
done

echo ""
ls -lh "$MODELS_DIR" | tail -n +2
echo ""
ok "Installation terminee."
