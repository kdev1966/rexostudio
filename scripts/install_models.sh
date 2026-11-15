#!/bin/bash
# ---------------------------------------------------------------------------
# Installe les outils locaux de transcription (whisper.cpp + modeles).
# Aucune dependance Python : tout est en C/C++ natif.
# ---------------------------------------------------------------------------
set -u
cd "$(dirname "$0")/.."

GREEN=$'\033[32m'; ORANGE=$'\033[38;5;208m'; RED=$'\033[31m'; OFF=$'\033[0m'
WHISPER_SRC="${WHISPER_SRC:-$HOME/Desktop/Studio_IA/whisper.cpp}"
MODELS_DIR="$PWD/models"
BIN_DIR="$PWD/bin"

mkdir -p "$MODELS_DIR" "$BIN_DIR"

echo "== 1/3  binaire whisper-cli =="
if [ -x "$BIN_DIR/whisper-cli" ]; then
  echo "${GREEN}●${OFF} déjà présent : bin/whisper-cli"
elif [ -x "$WHISPER_SRC/build/bin/whisper-cli" ]; then
  cp "$WHISPER_SRC/build/bin/whisper-cli" "$BIN_DIR/"
  chmod +x "$BIN_DIR/whisper-cli"
  echo "${GREEN}●${OFF} copié depuis $WHISPER_SRC"
else
  echo "${ORANGE}whisper.cpp introuvable. Clonez https://github.com/ggerganov/whisper.cpp"
  echo "  puis compilez :  cmake -B build && cmake --build build -j4"
fi

echo "== 2/3  modèles de transcription =="
for model in base small; do
  if [ -s "$MODELS_DIR/ggml-$model.bin" ]; then
    echo "${GREEN}●${OFF} ggml-$model.bin déjà présent"
    continue
  fi
  if [ -x "$WHISPER_SRC/models/download-ggml-model.sh" ]; then
    ( cd "$WHISPER_SRC/models" && ./download-ggml-model.sh "$model" "$MODELS_DIR" >/dev/null 2>&1 ) \
      && echo "${GREEN}●${OFF} ggml-$model.bin téléchargé" \
      || echo "${ORANGE}échec du téléchargement de ggml-$model.bin${OFF}"
  else
    echo "${ORANGE}script de téléchargement introuvable ($WHISPER_SRC/models/download-ggml-model.sh)${OFF}"
  fi
done

echo "== 3/3  modèle VAD (Silero) =="
if [ -s "$MODELS_DIR/ggml-silero-v6.2.0.bin" ]; then
  echo "${GREEN}●${OFF} modèle VAD déjà présent"
elif [ -x "$WHISPER_SRC/models/download-vad-model.sh" ]; then
  ( cd "$WHISPER_SRC/models" && ./download-vad-model.sh silero-v6.2.0 "$MODELS_DIR" >/dev/null 2>&1 ) \
    && echo "${GREEN}●${OFF} modèle VAD téléchargé" \
    || echo "${ORANGE}échec du téléchargement du modèle VAD${OFF}"
else
  echo "${ORANGE}script VAD introuvable${OFF}"
fi

echo ""
echo "Contenu de models/ :"
ls -lh "$MODELS_DIR" 2>/dev/null | tail -n +2
echo ""
echo "${GREEN}Installation terminée.${OFF}"
