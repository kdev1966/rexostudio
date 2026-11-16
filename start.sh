#!/bin/bash
# ---------------------------------------------------------------------------
# MontageIA - lanceur principal.
#   ./start.sh              -> interface web sur http://127.0.0.1:8080
#   ./start.sh --cli        -> mode terminal (assistante au montage)
#   ./start.sh --cli <video> [commande...] -> une seule commande (plan, render 9:16...)
# ---------------------------------------------------------------------------
set -u
cd "$(dirname "$0")"

GREEN=$'\033[32m'; ORANGE=$'\033[38;5;208m'; RED=$'\033[31m'; DIM=$'\033[2m'; OFF=$'\033[0m'

PY="$(command -v python3)"
if [ -z "$PY" ]; then
  echo "${RED}Python 3 introuvable.${OFF}"
  exit 1
fi

# --- Moteur IA -----------------------------------------------------------
# llama.cpp (bin/llama-server + modele GGUF) : demarre par MontageIA a la
# premiere demande, rien a lancer ici. Sinon, Ollama en secours.
GGUF="models/${MONTAGIA_GGUF:-gemma-4-E2B-it-Q4_0.gguf}"
if [ "${MONTAGIA_LLM_BACKEND:-auto}" != "ollama" ] && [ -x bin/llama-server ] && [ -f "$GGUF" ]; then
  echo "${GREEN}●${OFF} IA locale : llama.cpp ($(basename "$GGUF" .gguf))"
else
  if ! curl -s --max-time 2 http://127.0.0.1:11434/api/version >/dev/null 2>&1; then
    echo "${ORANGE}Démarrage d'Ollama...${OFF}"
    ( ollama serve >/tmp/montagia-ollama.log 2>&1 & )
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      sleep 1
      curl -s --max-time 2 http://127.0.0.1:11434/api/version >/dev/null 2>&1 && break
    done
  fi
  if curl -s --max-time 2 http://127.0.0.1:11434/api/version >/dev/null 2>&1; then
    echo "${GREEN}●${OFF} IA locale : Ollama"
  else
    echo "${RED}●${OFF} Aucune IA locale : lancez ./scripts/install_models.sh (ou 'ollama serve')"
  fi
fi

# --- Vérifications --------------------------------------------------------
missing=0
for tool in ffmpeg ffprobe whisper-cli; do
  if [ -x "./bin/$tool" ]; then
    echo "${GREEN}●${OFF} $tool"
  else
    echo "${RED}●${OFF} $tool absent de bin/"
    missing=1
  fi
done
[ "$missing" = 1 ] && echo "${ORANGE}Lancez ./scripts/install_models.sh pour installer les outils manquants.${OFF}"

echo "${DIM}------------------------------------------------------------${OFF}"

if [ "${1:-}" = "--cli" ]; then
  shift
  exec "$PY" -m montagia.cli "$@"     # ./start.sh --cli video.mp4 render 9:16
fi

exec "$PY" -m montagia
