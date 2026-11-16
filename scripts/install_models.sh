#!/bin/bash
# ---------------------------------------------------------------------------
# Installe les outils locaux de transcription, sans dependance externe :
#   1. bin/whisper-cli  : whisper.cpp compile en STATIQUE (un seul binaire,
#                         aucune bibliotheque .dylib a cote)
#   2. models/          : modele Whisper + modele VAD Silero
#   3. bin/ffmpeg, bin/ffprobe : builds statiques epingles par SHA-256
#   4. bin/llama-server + modele GGUF (Gemma 4 E2B) : l'IA locale
# Tout est verifie : somme SHA-256 de CMake et des modeles, commit Git de
# whisper.cpp et llama.cpp. Relancable sans risque : ce qui est deja en
# place est garde.
#
#   ./scripts/install_models.sh
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
LLAMA_TAG="b12428"
LLAMA_COMMIT="b4c0e00a4fcc0287d0bb32fd7cb0d8b286af73ed"
GGUF_FILE="gemma-4-E2B-it-Q4_0.gguf"
GGUF_SHA="8e30dff3ac4c8434c49a7036fa15564bdbb6044e42bf04550bf1a096ad7e6a52"
# Magasin de modeles partage par les projets du developpeur (s'il existe) :
# un modele deja present et verifie y est copie au lieu d'etre retelecharge.
SHARED_MODELS="${KDEV_MODELS_DIR:-$HOME/.local/share/kdev-models}"

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


# Installe CMake (archive officielle, SHA-256 verifie) dans $BUILD_DIR.
ensure_cmake() {
  mkdir -p "$BUILD_DIR"
  local CM="cmake-$CMAKE_VERSION-macos-universal"
  CMAKE="$BUILD_DIR/$CM/CMake.app/Contents/bin/cmake"
  [ -x "$CMAKE" ] && return
  ( cd "$BUILD_DIR"
    curl -fsSL -o cmake-sha.txt "https://github.com/Kitware/CMake/releases/download/v$CMAKE_VERSION/cmake-$CMAKE_VERSION-SHA-256.txt"
    curl -fL --progress-bar -o "$CM.tar.gz" "https://github.com/Kitware/CMake/releases/download/v$CMAKE_VERSION/$CM.tar.gz"
    grep " $CM.tar.gz\$" cmake-sha.txt | shasum -a 256 -c - >/dev/null || fail "SHA-256 de CMake incorrect"
    tar -xzf "$CM.tar.gz" && rm "$CM.tar.gz" ) || exit 1
  ok "CMake $CMAKE_VERSION (SHA-256 verifie)"
}

# Jeu d'instructions commun aux Mac Intel 2015 (Haswell/Broadwell) :
# GGML_NATIVE=OFF pour qu'un binaire compile sur l'iMac tourne aussi sur le
# MacBook (qui n'a pas ADX), et inversement. Mac Apple : instructions natives.
# LLAMA_GPU : sur Mac Intel, l'IA tourne sur le processeur (la puce graphique
# Iris Pro est plus lente, et Metal a fait planter Montora sur Mac Intel).
if [ "$(uname -m)" = "arm64" ]; then
  GGML_CPU_FLAGS=(-DGGML_NATIVE=ON)
  LLAMA_GPU=(-DGGML_METAL=ON)
else
  GGML_CPU_FLAGS=(-DGGML_NATIVE=OFF -DGGML_AVX=ON -DGGML_AVX2=ON -DGGML_FMA=ON -DGGML_F16C=ON)
  LLAMA_GPU=(-DGGML_METAL=OFF)
fi

# --------------------------------------------------------------------------
echo "== 1/4  binaire whisper-cli =="
if "$BIN_DIR/whisper-cli" --help >/dev/null 2>&1; then
  ok "bin/whisper-cli fonctionne deja"
else
  [ -x "$BIN_DIR/whisper-cli" ] && warn "bin/whisper-cli present mais inutilisable (bibliotheque manquante) : recompilation"
  command -v clang >/dev/null || fail "compilateur absent : lancez  xcode-select --install"
  mkdir -p "$BUILD_DIR"; cd "$BUILD_DIR"

  ensure_cmake

  rm -rf whisper.cpp
  git -c advice.detachedHead=false clone -q --depth 1 --branch "$WHISPER_TAG" \
    https://github.com/ggml-org/whisper.cpp.git
  [ "$(git -C whisper.cpp rev-parse HEAD)" = "$WHISPER_COMMIT" ] || fail "commit whisper.cpp inattendu"
  ok "whisper.cpp $WHISPER_TAG (commit verifie)"

  "$CMAKE" -S whisper.cpp -B whisper.cpp/build -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_SHARED_LIBS=OFF "${GGML_CPU_FLAGS[@]}" \
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
echo "== 2/4  modeles whisper =="
HF="https://huggingface.co"
fetch "$MODELS_DIR/ggml-base.bin" "$HF/ggerganov/whisper.cpp/resolve/main/ggml-base.bin" \
  60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe
fetch "$MODELS_DIR/ggml-silero-v6.2.0.bin" "$HF/ggml-org/whisper-vad/resolve/main/ggml-silero-v6.2.0.bin" \
  2aa269b785eeb53a82983a20501ddf7c1d9c48e33ab63a41391ac6c9f7fb6987
# small : modele du profil arabe (config.WHISPER_PROFILES), installe d'office.
fetch "$MODELS_DIR/ggml-small.bin" "$HF/ggerganov/whisper.cpp/resolve/main/ggml-small.bin" \
  1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b

# --------------------------------------------------------------------------
echo "== 3/4  ffmpeg / ffprobe =="
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

# --------------------------------------------------------------------------
echo "== 4/4  IA locale : llama-server + $GGUF_FILE =="
if "$BIN_DIR/llama-server" --version 2>&1 | grep -q "commit ${LLAMA_COMMIT:0:7}"; then
  ok "bin/llama-server $LLAMA_TAG deja en place"
else
  command -v clang >/dev/null || fail "compilateur absent : lancez  xcode-select --install"
  ensure_cmake
  cd "$BUILD_DIR"
  rm -rf llama.cpp
  git -c advice.detachedHead=false clone -q --depth 1 --branch "$LLAMA_TAG" \
    https://github.com/ggml-org/llama.cpp.git
  [ "$(git -C llama.cpp rev-parse HEAD)" = "$LLAMA_COMMIT" ] || fail "commit llama.cpp inattendu"
  ok "llama.cpp $LLAMA_TAG (commit verifie)"
  # Binaire autonome : pas d'OpenSSL ni de curl (les modeles sont telecharges
  # par ce script) ; Accelerate d'Apple pour la lecture du prompt.
  "$CMAKE" -S llama.cpp -B llama.cpp/build -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_SHARED_LIBS=OFF "${GGML_CPU_FLAGS[@]}" "${LLAMA_GPU[@]}" -DGGML_ACCELERATE=ON -DGGML_BLAS=ON \
    -DGGML_BLAS_VENDOR=Apple -DLLAMA_CURL=OFF -DLLAMA_OPENSSL=OFF \
    -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_SERVER=ON \
    -DCMAKE_OSX_DEPLOYMENT_TARGET=12.0 >llama-configure.log 2>&1 \
    || { tail -30 llama-configure.log; fail "configuration CMake de llama.cpp echouee"; }
  echo "Compilation de llama-server (quelques minutes)..."
  "$CMAKE" --build llama.cpp/build -j"$(sysctl -n hw.ncpu)" --target llama-server >llama-build.log 2>&1 \
    || { tail -30 llama-build.log; fail "compilation echouee (voir $BUILD_DIR/llama-build.log)"; }
  install -m 755 llama.cpp/build/bin/llama-server "$BIN_DIR/llama-server"
  cd "$ROOT"
  if otool -L "$BIN_DIR/llama-server" | grep -q -E "@rpath|/usr/local|/opt/"; then
    fail "bin/llama-server depend de bibliotheques externes"
  fi
  "$BIN_DIR/llama-server" --version >/dev/null 2>&1 || fail "bin/llama-server ne demarre pas"
  ok "bin/llama-server $LLAMA_TAG compile (autonome)"
fi

if [ -f "$SHARED_MODELS/$GGUF_FILE" ] && [ ! -f "$MODELS_DIR/$GGUF_FILE" ] \
   && echo "$GGUF_SHA  $SHARED_MODELS/$GGUF_FILE" | shasum -a 256 -c - >/dev/null 2>&1; then
  cp "$SHARED_MODELS/$GGUF_FILE" "$MODELS_DIR/$GGUF_FILE"
  ok "$GGUF_FILE repris de $SHARED_MODELS (SHA-256 verifie)"
fi
fetch "$MODELS_DIR/$GGUF_FILE" "$HF/ggml-org/gemma-4-E2B-it-GGUF/resolve/main/$GGUF_FILE" "$GGUF_SHA"

echo ""
ls -lh "$MODELS_DIR" | tail -n +2
echo ""
ok "Installation terminee."
