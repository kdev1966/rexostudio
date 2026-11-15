#!/bin/bash
# ---------------------------------------------------------------------------
# MontageIA - lanceur principal.
#   ./start.sh              -> interface web sur http://127.0.0.1:8080
#   ./start.sh --cli        -> mode terminal (assistante au montage)
# ---------------------------------------------------------------------------
set -u
cd "$(dirname "$0")"

GREEN=$'\033[32m'; ORANGE=$'\033[38;5;208m'; RED=$'\033[31m'; DIM=$'\033[2m'; OFF=$'\033[0m'

# ffmpeg / ffprobe / melt : on privilege ceux de Kdenlive
export PATH="/Applications/kdenlive.app/Contents/MacOS:$PATH"

PY="$(command -v python3)"
if [ -z "$PY" ]; then
  echo "${RED}Python 3 introuvable.${OFF}"
  exit 1
fi

# --- Ollama ---------------------------------------------------------------
if ! curl -s --max-time 2 http://127.0.0.1:11434/api/version >/dev/null 2>&1; then
  echo "${ORANGE}Démarrage d'Ollama...${OFF}"
  ( ollama serve >/tmp/montagia-ollama.log 2>&1 & )
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    sleep 1
    curl -s --max-time 2 http://127.0.0.1:11434/api/version >/dev/null 2>&1 && break
  done
fi

if curl -s --max-time 2 http://127.0.0.1:11434/api/version >/dev/null 2>&1; then
  echo "${GREEN}●${OFF} Ollama prêt"
else
  echo "${RED}●${OFF} Ollama injoignable — lancez 'ollama serve' dans un autre terminal"
fi

# --- Vérifications --------------------------------------------------------
if [ -x "/Applications/kdenlive.app/Contents/MacOS/ffmpeg" ]; then
  echo "${GREEN}●${OFF} ffmpeg (Kdenlive)"
else
  echo "${RED}●${OFF} ffmpeg introuvable — installez Kdenlive ou ffmpeg"
fi

if [ ! -x "./bin/whisper-cli" ]; then
  echo "${ORANGE}whisper-cli absent — lancez ./scripts/install_models.sh${OFF}"
fi

echo "${DIM}------------------------------------------------------------${OFF}"

if [ "${1:-}" = "--cli" ]; then
  exec "$PY" -m montagia.cli
fi

exec "$PY" -m montagia
