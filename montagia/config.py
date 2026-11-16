"""Configuration centrale de Rexo Studio.

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
# Un evenement = un dossier (docs/adr/0001) ; REXO_EVENTS_DIR pour une autre racine.
EVENTS_DIR = os.environ.get("REXO_EVENTS_DIR") or os.path.join(PROJECT_DIR, "Evenements")
MODELS_DIR = os.path.join(PROJECT_DIR, "models")
BIN_DIR = os.path.join(PROJECT_DIR, "bin")
STATIC_DIR = os.path.join(PROJECT_DIR, "server", "static")

ALL_DIRS = [WORKSPACE, MEDIA_DIR, PROJECTS_DIR, EXPORTS_DIR, CACHE_DIR, MODELS_DIR, BIN_DIR,
            EVENTS_DIR]


def ensure_dirs() -> None:
    for d in ALL_DIRS:
        os.makedirs(d, exist_ok=True)


# --------------------------------------------------------------------------
# Serveur
# --------------------------------------------------------------------------
HOST = "127.0.0.1"
PORT = int(os.environ.get("MONTAGIA_PORT", "8080"))

# --------------------------------------------------------------------------
# IA locale : llama.cpp (bin/llama-server + modele GGUF), Ollama en secours
# --------------------------------------------------------------------------
# Mesure du 16/11/2026 sur l'iMac (plan de coupe, memes appels) :
#   Ollama + qwen2.5:3b        film002 180 s, cafe 40 s
#   llama.cpp + gemma-4-E2B    film002  82 s, cafe 16 s, references conformes
# MONTAGIA_LLM_BACKEND=llama|ollama force un moteur ; par defaut llama.cpp
# s'il est installe (scripts/install_models.sh), sinon Ollama.
LLAMA_SERVER_BIN = os.path.join(BIN_DIR, "llama-server")
LLM_GGUF = os.path.join(MODELS_DIR, os.environ.get("MONTAGIA_GGUF", "gemma-4-E2B-it-Q4_0.gguf"))
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")


def _llm_backend() -> str:
    choice = os.environ.get("MONTAGIA_LLM_BACKEND", "auto")
    if choice in ("llama", "ollama"):
        return choice
    ready = os.access(LLAMA_SERVER_BIN, os.X_OK) and os.path.isfile(LLM_GGUF)
    return "llama" if ready else "ollama"


def _physical_cores() -> int:
    """Coeurs physiques : au-dela, llama.cpp ne va pas plus vite (mesure
    Codewright, docs/VISION.md : 8 fils jamais plus rapides que 4 sur 4 coeurs)."""
    try:
        out = subprocess.run(["sysctl", "-n", "hw.physicalcpu"], capture_output=True,
                             text=True, timeout=3).stdout.strip()
        if out.isdigit():
            return int(out)
    except (OSError, subprocess.SubprocessError):
        pass
    return max(1, (os.cpu_count() or 2) // 2)


LLM_BACKEND = _llm_backend()
# Nom du modele : etiquette affichee, et partie de la cle du cache IA.
LLM_MODEL = os.environ.get("MONTAGIA_MODEL") or (
    os.path.splitext(os.path.basename(LLM_GGUF))[0] if LLM_BACKEND == "llama" else "qwen2.5:3b")
# 8192 : la demande des meilleurs moments de film002 (7 min d'arabe) fait
# 4415 tokens avec Gemma, qui decoupe l'arabe plus finement que Qwen.
# Cout memoire faible (Gemma 4 E2B, flash attention).
LLM_NUM_CTX = int(os.environ.get("MONTAGIA_NUM_CTX", "8192"))
LLM_THREADS = int(os.environ.get("MONTAGIA_LLM_THREADS", "0")) or _physical_cores()
# Modele garde en memoire 5 min apres sa derniere utilisation (enchainements
# rapides), puis decharge (llama-server arrete, ou keep_alive d'Ollama).
LLM_IDLE_SECONDS = int(os.environ.get("MONTAGIA_LLM_IDLE", "300"))
LLM_KEEP_ALIVE = "%ds" % LLM_IDLE_SECONDS
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
# PhotoCraft (editeur photo du meme editeur que FilmCraft, voir montagia/photocraft.py)
# --------------------------------------------------------------------------
PHOTOCRAFT_APP = os.environ.get("REXO_PHOTOCRAFT_APP", "/Applications/PhotoCraft.app")
# Moteur sans interface livre dans l'application : run, batch, serve...
PHOTOCRAFT_CLI = os.path.join(PHOTOCRAFT_APP, "Contents", "MacOS", "photocraft-cli")

# --------------------------------------------------------------------------
# Effets photo (M5) : bin/rexo-segment, compile par scripts/build_native.sh
# --------------------------------------------------------------------------
SEGMENT_BIN = os.path.join(BIN_DIR, "rexo-segment")

# Environnement d'effets (Python 3.11 + ONNX Runtime, processus separe),
# installe par scripts/install_effects_env.sh ; ses programmes sont dans effects_worker/.
EFFECTS_ENV_DIR = os.path.join(PROJECT_DIR, ".effets")
EFFECTS_PYTHON = os.path.join(EFFECTS_ENV_DIR, "venv", "bin", "python")
EFFECTS_WORKER_DIR = os.path.join(PROJECT_DIR, "effects_worker")
EMBEDKIT_DIR = os.path.join(PROJECT_DIR, "vendor", "embedkit")
EMBEDKIT_CACHE = os.environ.get("EMBEDKIT_CACHE") or os.path.join(
    os.environ.get("KDEV_MODELS_DIR") or os.path.expanduser("~/.local/share/kdev-models"),
    "embedkit")


# --------------------------------------------------------------------------
# Chaine de production (montagia/studio.py) : chaque outil ne fait que sa tache
# --------------------------------------------------------------------------
# Blender 3.6 LTS (EEVEE en OpenGL : Blender 4.x exige Metal, qui plante sur l'Iris
# Pro de l'iMac), installe par scripts/install_blender.sh
BLENDER_APP = os.environ.get("REXO_BLENDER_APP") or next(
    (p for p in (os.path.expanduser("~/Applications/Blender-3.6.app"),
                 "/Applications/Blender-3.6.app", "/Applications/Blender.app") if os.path.isdir(p)),
    os.path.expanduser("~/Applications/Blender-3.6.app"))
BLENDER_BIN = os.path.join(BLENDER_APP, "Contents", "MacOS", "Blender")
BLENDER_SCRIPTS_DIR = os.path.join(PROJECT_DIR, "blender")
# Modeles de scenes 3D (.blend, faits a part dans Blender) : hors du depot
SCENES_3D_DIR = os.environ.get("REXO_SCENES_DIR") or os.path.join(PROJECT_DIR, "modeles", "scenes_3d")
# Animations generiques rendues par Blender (une par modele, mouvement, duree, qualite)
GENERICS_DIR = os.environ.get("REXO_GENERICS_DIR") or os.path.join(PROJECT_DIR, "modeles", "generiques")
# Modeles de titres EffectCraft (.ectemplate, champs « Title » et « Subtitle »)
TITLES_DIR = os.environ.get("REXO_TITLES_DIR") or os.path.join(PROJECT_DIR, "modeles", "titres")

# Textures PBR des modeles (une sous-dossier par materiau), faites par TextureCraft
TEXTURES_DIR = os.environ.get("REXO_TEXTURES_DIR") or os.path.join(PROJECT_DIR, "modeles", "textures")
TEXTURECRAFT_APP = os.environ.get("REXO_TEXTURECRAFT_APP", "/Applications/TextureCraft.app")
TEXTURECRAFT_BIN = os.path.join(TEXTURECRAFT_APP, "Contents", "MacOS", "TextureCraft")
TEXTURECRAFT_PORT = int(os.environ.get("REXO_TEXTURECRAFT_PORT", "9881"))

# EffectCraft (motion design, meme editeur que PhotoCraft et FilmCraft) : serveur de
# controle local, une requete JSON par ligne (voir montagia/effectcraft.py)
EFFECTCRAFT_APP = os.environ.get("REXO_EFFECTCRAFT_APP", "/Applications/EffectCraft.app")
EFFECTCRAFT_BIN = os.path.join(EFFECTCRAFT_APP, "Contents", "MacOS", "EffectCraft")
EFFECTCRAFT_PORT = int(os.environ.get("REXO_EFFECTCRAFT_PORT", "9879"))


def effects_env() -> dict:
    """Variables d'environnement d'un programme de l'environnement d'effets :
    embedkit du projet, magasin de modeles, aucun acces reseau."""
    env = dict(os.environ, PYTHONPATH=EMBEDKIT_DIR, EMBEDKIT_CACHE=EMBEDKIT_CACHE,
               EMBEDKIT_OFFLINE="1")
    env.pop("PYTHONHOME", None)
    return env

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
