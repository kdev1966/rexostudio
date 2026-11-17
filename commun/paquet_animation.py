"""Format « rexo-animation » : le contrat entre l'atelier (qui fabrique et livre les
paquets) et Rexo Studio (qui les installe et les utilise).

Un paquet est un dossier <id>/ :
    animation.json     description : format, version, id, titre, scene, mouvement, duree,
                       largeur, hauteur, fps, images, pixels_par_metre, premier_plan,
                       emplacements de photos (nom, type, taille en metres)...
    decor.mp4          le decor filme par la camera drone, sans aucune photo
    composition.jsx    la composition After Effects pour EffectCraft ; les videos y sont
                       designees par {{DOSSIER}}/..., remplace par le dossier du paquet
    vignette.jpg       une image du decor, pour le catalogue
    premier_plan.mov   ce qui passe devant les photos, avec transparence (si premier_plan)
"""
from __future__ import annotations

import json
import os

FORMAT = "rexo-animation"
VERSION = 1                 # version ecrite par l'atelier
VERSIONS = (1,)             # versions que Rexo Studio sait lire
TOKEN = "{{DOSSIER}}"
FILES = ("animation.json", "decor.mp4", "composition.jsx", "vignette.jpg")
FOREGROUND = "premier_plan.mov"


def read(folder: str):
    """animation.json d'un paquet complet, dans un format connu et avec au moins un
    emplacement de photo ; sinon None."""
    try:
        with open(os.path.join(folder, "animation.json"), "r", encoding="utf-8") as fh:
            info = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(info, dict) or info.get("format") != FORMAT or info.get("version") not in VERSIONS:
        return None
    needed = list(FILES) + ([FOREGROUND] if info.get("premier_plan") else [])
    if not all(os.path.isfile(os.path.join(folder, n)) and os.path.getsize(os.path.join(folder, n)) > 0
               for n in needed):
        return None
    if not info.get("emplacements"):
        return None
    return info
