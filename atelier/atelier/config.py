"""Chemins et outils de l'atelier. Tout ce que fabrique l'atelier reste dans son dossier
(scenes, textures, livraison) ; Rexo Studio ne recoit que les paquets livres."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLENDER_SCRIPTS_DIR = os.path.join(ROOT, "blender")
SCENES_DIR = os.environ.get("ATELIER_SCENES_DIR") or os.path.join(ROOT, "scenes")         # decors .blend
TEXTURES_DIR = os.environ.get("ATELIER_TEXTURES_DIR") or os.path.join(ROOT, "textures")   # cartes PBR
LIVRAISON_DIR = os.environ.get("ATELIER_LIVRAISON_DIR") or os.path.join(ROOT, "livraison")  # paquets
CACHE_DIR = os.path.join(ROOT, ".cache")

# Blender 3.6 LTS (EEVEE en OpenGL ; Blender 4.x exige Metal, qui plante sur l'Iris Pro)
BLENDER_APP = os.environ.get("ATELIER_BLENDER_APP") or next(
    (p for p in (os.path.expanduser("~/Applications/Blender-3.6.app"), "/Applications/Blender-3.6.app",
                 "/Applications/Blender.app") if os.path.isdir(p)),
    "/Applications/Blender.app")
BLENDER_BIN = os.path.join(BLENDER_APP, "Contents", "MacOS", "Blender")

TEXTURECRAFT_APP = os.environ.get("ATELIER_TEXTURECRAFT_APP", "/Applications/TextureCraft.app")
TEXTURECRAFT_BIN = os.path.join(TEXTURECRAFT_APP, "Contents", "MacOS", "TextureCraft")
TEXTURECRAFT_PORT = int(os.environ.get("ATELIER_TEXTURECRAFT_PORT", "9881"))
MATERIALCRAFT_APP = os.environ.get("ATELIER_MATERIALCRAFT_APP", "/Applications/MaterialCraft.app")
MATERIALCRAFT_BIN = os.path.join(MATERIALCRAFT_APP, "Contents", "MacOS", "MaterialCraft")
MATERIALCRAFT_PORT = int(os.environ.get("ATELIER_MATERIALCRAFT_PORT", "9883"))

# Carte graphique : toujours la carte econome (integree). Sur le MacBook Pro a deux cartes,
# la Radeon dediee cause des erreurs de rendu.
CRAFT_GPU_ENV = {"WGPU_POWER_PREF": "low"}
