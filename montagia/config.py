"""Configuration centrale de MontageIA.

Tout est auto-detecte pour tourner sur n'importe quelle machine :
rien n'est code en dur dans le code metier, tout passe par ce module.
"""
from __future__ import annotations

import os
import shutil
import subprocess

# --------------------------------------------------------------------------
# Chemins
# --------------------------------------------------------------------------
# config.py vit dans montagia/ -> la racine du projet est son parent.
PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(PACKAGE_DIR)
WORKSPACE = os.path.join(PROJECT_DIR, "workspace")
MEDIA_DIR = os.path.join(WORKSPACE, "media")
PROJECTS_DIR = os.path.join(WORKSPACE, "projects")
EXPORTS_DIR = os.path.join(WORKSPACE, "exports")
CACHE_DIR = os.path.join(WORKSPACE, "cache")
MODELS_DIR = os.path.join(PROJECT_DIR, "models")
BIN_DIR = os.path.join(PROJECT_DIR, "bin")
STATIC_DIR = os.path.join(PROJECT_DIR, "server", "static")

ALL_DIRS = [WORKSPACE, MEDIA_DIR, PROJECTS_DIR, EXPORTS_DIR, CACHE_DIR, MODELS_DIR, BIN_DIR]


def ensure_dirs() -> None:
    for d in ALL_DIRS:
        os.makedirs(d, exist_ok=True)


# --------------------------------------------------------------------------
# Serveur
# --------------------------------------------------------------------------
HOST = "127.0.0.1"
PORT = int(os.environ.get("MONTAGIA_PORT", "8080"))

# --------------------------------------------------------------------------
# IA (Ollama local)
# --------------------------------------------------------------------------
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
LLM_MODEL = os.environ.get("MONTAGIA_MODEL", "qwen2.5:3b")
# 4096 suffit largement et evite d'exploser la RAM (16 Go) avec le cache KV.
LLM_NUM_CTX = int(os.environ.get("MONTAGIA_NUM_CTX", "4096"))
# Modele garde en memoire 5 min apres sa derniere utilisation (enchainements
# rapides), puis decharge par Ollama : ~2,4 Go rendus au systeme.
LLM_KEEP_ALIVE = os.environ.get("MONTAGIA_KEEP_ALIVE", "5m")
LLM_TIMEOUT = 600

# --------------------------------------------------------------------------
# Transcription (whisper.cpp)
# --------------------------------------------------------------------------
WHISPER_BIN = os.path.join(BIN_DIR, "whisper-cli")

# Ordre de preference : le plus petit modele dispo (rapide) -> le plus gros (precis).
WHISPER_MODEL_PREFERENCE = ["base", "small", "tiny", "medium"]

# Metal (GPU) pour whisper : DESACTIVE par defaut. Mesure sur l'iMac 2015
# (Iris Pro 6200, modele base) : CPU seul 1,4 s contre 2,7 s avec Metal, et
# Metal compile ses shaders au premier lancement (~55 s). MONTAGIA_WHISPER_GPU=1
# pour le reactiver sur une machine ou le GPU est plus rapide.
WHISPER_USE_GPU = os.environ.get("MONTAGIA_WHISPER_GPU", "0") == "1"

# Profil de transcription par langue (mesures sur l'iMac, 15/11/2026, sur
# 2 min de podcast en arabe tunisien melange d'anglais et de francais) :
#   base                 x5,7  mots tres deformes, boucles
#   small + -mc 0        x2,2  fidele au dialecte, anglais garde en latin,
#                              ponctuation ; -mc 0 supprime les boucles
#   medium-q5_0          x0,4  reecrit le dialecte en arabe standard
#   large-v3-turbo-q5_0  x0,9  traduit les passages anglais en arabe
# "no_context" = option -mc 0 (le modele ne s'appuie pas sur son texte
# precedent : evite les boucles de repetition).
WHISPER_PROFILES = {
    "ar": {"model": "small", "no_context": True},
}
WHISPER_DEFAULT_PROFILE = {"model": "", "no_context": False}

# Langues ou les coupes de l'IA sont seulement PROPOSEES (a valider dans
# l'interface) : en arabe tunisien, le modele 3B coupait l'annonce du sujet
# comme "digression" (film002). Les regles sures restent appliquees.
SUGGEST_ONLY_LANGUAGES = ("ar",)

WHISPER_LANGUAGES = {
    "auto": "auto", "fr": "fr", "en": "en", "ar": "ar", "es": "es",
    "de": "de", "it": "it", "pt": "pt", "nl": "nl", "ru": "ru", "zh": "zh",
}

# --------------------------------------------------------------------------
# Rendu
# --------------------------------------------------------------------------
# "videotoolbox" : encodeur materiel macOS, ~12x temps reel sur ce Mac.
# "libx264"       : qualite maximale, ~5x temps reel.
DEFAULT_ENCODER = os.environ.get("MONTAGIA_ENCODER", "videotoolbox")
ENCODERS = ("videotoolbox", "libx264")

CRF_LABELS = {
    "viral": "Aiguilles et punchy",
    "storytelling": "Narratif et posé",
    "tuto": "Clair et pédagogique",
    "podcast": "Voix seule et posé",
}

# Detection de silence (de-rushage)
SILENCE_NOISE_DB = -30.0       # seuil de bruit en dB
SILENCE_MIN_DUR = 0.35         # duree min d'un silence en secondes
SILENCE_PAD = 0.12             # marge conservee autour de la parole

# --------------------------------------------------------------------------
# Fichiers
# --------------------------------------------------------------------------
VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm",
    ".mpg", ".mpeg", ".wmv", ".flv", ".3gp", ".ts", ".mts",
}

MAX_UPLOAD_BYTES = 8 * 1024 ** 3   # 8 Go (rushs longs)

# --------------------------------------------------------------------------
# FilmCraft (editeur video pilote en direct, voir montagia/filmcraft.py)
# --------------------------------------------------------------------------
FILMCRAFT_APP = os.environ.get("MONTAGIA_FILMCRAFT_APP", "/Applications/FilmCraft.app")
FILMCRAFT_BIN = os.path.join(FILMCRAFT_APP, "Contents", "MacOS", "FilmCraft")
# Port du serveur de controle local de FilmCraft (127.0.0.1 uniquement).
FILMCRAFT_PORT = int(os.environ.get("MONTAGIA_FILMCRAFT_PORT", "9877"))

# --------------------------------------------------------------------------
# Decouverte des binaires
# --------------------------------------------------------------------------
_BINARY_EXTRA_PATHS = [
    BIN_DIR,                     # binaires livres avec le projet (prioritaires)
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/usr/bin",
    "/bin",
]


def find_binary(name: str) -> str:
    """Chemin d'un binaire : bin/ du projet, puis les dossiers usuels et le PATH."""
    for folder in _BINARY_EXTRA_PATHS:
        candidate = os.path.join(folder, name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    found = shutil.which(name)
    if found:
        return found
    return ""


def ffmpeg_bin() -> str:
    return find_binary("ffmpeg")


def ffprobe_bin() -> str:
    return find_binary("ffprobe")


def whisper_bin() -> str:
    """whisper-cli du projet (compile en statique par scripts/install_models.sh)."""
    if os.path.isfile(WHISPER_BIN) and os.access(WHISPER_BIN, os.X_OK):
        return WHISPER_BIN
    return ""


def whisper_model_path(name: str = "base") -> str:
    """Chemin du modele whisper.cpp (local en priorite)."""
    path = os.path.join(MODELS_DIR, "ggml-%s.bin" % name)
    if os.path.isfile(path) and os.path.getsize(path) > 5 * 1024 * 1024:
        return path
    return ""


def best_whisper_model() -> str:
    for name in WHISPER_MODEL_PREFERENCE:
        if whisper_model_path(name):
            return name
    return ""


def whisper_vad_model() -> str:
    """Modele VAD (Silero) : ameliore la decoupe des segments de parole.

    Mesure : avec VAD, la transcription d'une video de 3 min passe de 66 s
    a 9 s (base + beam 5), et la qualite s'ameliore (plus de marqueurs
    [MUSIC] parasites, phrases regroupees).
    """
    candidates = [
        os.path.join(MODELS_DIR, "ggml-silero-v6.2.0.bin"),
    ]
    for c in candidates:
        if os.path.isfile(c) and os.path.getsize(c) > 100 * 1024:
            return c
    return ""


def ollama_available() -> bool:
    try:
        out = subprocess.run(
            ["curl", "-s", "--max-time", "3", os.path.join(OLLAMA_URL, "api/version")],
            capture_output=True, text=True, timeout=6)
        return "version" in (out.stdout or "")
    except Exception:
        return False
