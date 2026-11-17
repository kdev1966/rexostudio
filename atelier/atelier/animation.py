"""Fabrication des animations livrees a Rexo Studio.

    decor .blend (scenes/)  --Blender-->  paquet d'animation (livraison/<id>/)  --zip-->  Rexo Studio

Un paquet d'animation (format « rexo-animation », version 1) est un dossier :
    animation.json     description : titre, scene, mouvement, duree, dimensions,
                       emplacements de photos (nom, type, taille en metres)
    decor.mp4          le decor filme par la camera drone, sans aucune photo
    premier_plan.mov   ce qui passe devant les photos, avec transparence (facultatif)
    composition.jsx    la composition After Effects pour EffectCraft ; les videos y sont
                       designees par {{DOSSIER}}/..., que Rexo Studio remplace par le
                       dossier ou il a installe le paquet
    vignette.jpg       une image du decor, pour le catalogue de Rexo Studio
Blender tourne sans interface (blender -b), en processus separe.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import subprocess
import time
import zipfile

from . import config

FORMAT, VERSION = "rexo-animation", 1
EXPORT_SCRIPT = os.path.join(config.BLENDER_SCRIPTS_DIR, "export_generic.py")
MOTIONS = {
    "sequence": "Séquence drone (approche, tour, envol)",
    "approche": "Approche depuis le ciel",
    "orbite": "Tour autour des mariés",
    "envol": "Envol au-dessus des mariés",
    "spirale": "Spirale descendante",
}
QUALITIES = ("brouillon", "normal", "fin")
FPS = 30
FILES = ("animation.json", "decor.mp4", "composition.jsx", "vignette.jpg")

_FRAME = re.compile(r"^IMAGE (\d+)")
_MEASURE = re.compile(r"MESURE .*: (\d+) image\(s\) en ([\d.]+) s")


class AnimationError(RuntimeError):
    pass


def blender_installed() -> bool:
    return os.path.isfile(config.BLENDER_BIN) and os.access(config.BLENDER_BIN, os.X_OK)


def _tail(text: str, lines: int = 6) -> str:
    rows = [r for r in (text or "").strip().splitlines() if r.strip()]
    return " | ".join(rows[-lines:]) or "aucun message"


# --------------------------------------------------------------------------
# Decors (scenes/<nom>.blend), construits par blender/build_template_<nom>.py
# ou faits a la main
# --------------------------------------------------------------------------

def scenes() -> list:
    folder = config.SCENES_DIR
    if not os.path.isdir(folder):
        return []
    return sorted(n[:-6] for n in os.listdir(folder) if n.endswith(".blend") and not n.startswith("."))


def builders() -> list:
    return sorted(n[len("build_template_"):-3] for n in os.listdir(config.BLENDER_SCRIPTS_DIR)
                  if n.startswith("build_template_") and n.endswith(".py"))


def build_scene(name: str, log=print) -> str:
    """(Re)construit scenes/<name>.blend a partir de son script."""
    script = os.path.join(config.BLENDER_SCRIPTS_DIR, "build_template_%s.py" % name)
    if not os.path.isfile(script):
        raise AnimationError("Pas de script pour la scène « %s » (scripts : %s)" % (name, ", ".join(builders())))
    out = os.path.join(config.SCENES_DIR, "%s.blend" % name)
    os.makedirs(config.SCENES_DIR, exist_ok=True)
    env = dict(os.environ, REXO_TEXTURES_DIR=config.TEXTURES_DIR)
    proc = subprocess.run([config.BLENDER_BIN, "-b", "--factory-startup", "--python", script, "--", out],
                          capture_output=True, text=True, timeout=1800, env=env)
    if proc.returncode != 0 or not os.path.isfile(out):
        raise AnimationError("Construction de « %s » impossible : %s" % (name, _tail(proc.stdout + proc.stderr)))
    log("Scène construite : %s" % out)
    return out


# --------------------------------------------------------------------------
# Paquets d'animation (livraison/<id>/)
# --------------------------------------------------------------------------

def package_id(scene: str, motion: str, seconds: float) -> str:
    return "%s__%s__%gs" % (scene, motion, seconds)


def read_package(folder: str):
    """animation.json d'un paquet complet et valide, sinon None."""
    try:
        with open(os.path.join(folder, "animation.json"), "r", encoding="utf-8") as fh:
            info = json.load(fh)
    except (OSError, ValueError):
        return None
    if info.get("format") != FORMAT:
        return None
    needed = list(FILES) + (["premier_plan.mov"] if info.get("premier_plan") else [])
    if all(os.path.isfile(os.path.join(folder, n)) and os.path.getsize(os.path.join(folder, n)) > 0
           for n in needed):
        return info
    return None


def packages() -> list:
    root = config.LIVRAISON_DIR
    found = []
    for name in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        info = read_package(os.path.join(root, name))
        if info:
            found.append(info)
    return found


def render(scene: str, motion: str = "sequence", seconds: float = 9.0, quality: str = "normal",
           title: str = "", log=print, progress=None, timeout: float = 4 * 3600) -> str:
    """Rend le paquet d'animation du decor (plusieurs minutes) ; retourne son dossier."""
    if motion not in MOTIONS:
        raise AnimationError("Mouvement inconnu : %s (%s)" % (motion, ", ".join(MOTIONS)))
    if quality not in QUALITIES:
        raise AnimationError("Qualité inconnue : %s (%s)" % (quality, ", ".join(QUALITIES)))
    blend = os.path.join(config.SCENES_DIR, "%s.blend" % scene)
    if not os.path.isfile(blend):
        raise AnimationError("Décor introuvable : %s (construire : python3 -m atelier scene %s)" % (blend, scene))
    if not blender_installed():
        raise AnimationError("Blender 3.6 introuvable (%s) : ./scripts/install_blender.sh" % config.BLENDER_APP)
    pid = package_id(scene, motion, seconds)
    folder = os.path.join(config.LIVRAISON_DIR, pid)
    work = folder + ".partiel"
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    frames = max(2, int(round(seconds * FPS)))
    log("Blender : « %s », %s, %d images (%s)" % (scene, MOTIONS[motion].lower(), frames, quality))
    started = time.time()
    proc = subprocess.Popen([config.BLENDER_BIN, "-b", blend, "--python", EXPORT_SCRIPT, "--", work, motion,
                             "%g" % seconds, quality],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, stdin=subprocess.DEVNULL)
    tail, measure, done = [], None, 0.0
    try:
        for line in proc.stdout:
            tail = (tail + [line])[-40:]
            match = _FRAME.search(line)
            if match and progress:
                done = max(done, min(1.0, int(match.group(1)) / float(frames)))
                progress(done)
            match = _MEASURE.search(line)
            if match:
                measure = (int(match.group(1)), float(match.group(2)))
            if time.time() - started > timeout:
                proc.kill()
                raise AnimationError("Blender dépasse %d min : arrêté" % (timeout // 60))
        proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        proc.stdout.close()
    try:
        with open(os.path.join(work, "scene.json"), "r", encoding="utf-8") as fh:
            scene_info = json.load(fh)
    except (OSError, ValueError):
        scene_info = None
    if proc.returncode != 0 or not scene_info:
        shutil.rmtree(work, ignore_errors=True)
        raise AnimationError("Rendu impossible : %s" % _tail("".join(tail)))
    info = {
        "format": FORMAT, "version": VERSION, "id": pid,
        "titre": title or "%s — %s (%g s)" % (scene.replace("_", " ").capitalize(), MOTIONS[motion], seconds),
        "scene": scene, "mouvement": motion, "duree": scene_info["duration"], "qualite": quality,
        "largeur": scene_info["width"], "hauteur": scene_info["height"], "fps": scene_info["fps"],
        "images": scene_info["frames"], "pixels_par_metre": scene_info["pixels_per_meter"],
        "premier_plan": scene_info["premier_plan"], "emplacements": scene_info["placeholders"],
        "fabrique_le": datetime.datetime.now().isoformat(timespec="seconds"),
        "secondes_de_rendu": round(measure[1], 1) if measure else round(time.time() - started, 1),
    }
    os.remove(os.path.join(work, "scene.json"))
    with open(os.path.join(work, "animation.json"), "w", encoding="utf-8") as fh:
        json.dump(info, fh, ensure_ascii=False, indent=2)
    if not read_package(work):
        shutil.rmtree(work, ignore_errors=True)
        raise AnimationError("Paquet incomplet après le rendu (fichiers attendus : %s)" % ", ".join(FILES))
    shutil.rmtree(folder, ignore_errors=True)
    os.rename(work, folder)
    log("Paquet prêt : %s (%.0f s de rendu)" % (folder, info["secondes_de_rendu"]))
    return folder


def deliver(ids: list = None, out: str = None, log=print) -> str:
    """Zip de livraison des paquets (tous par defaut), a installer dans Rexo Studio."""
    chosen = [p for p in packages() if not ids or p["id"] in ids]
    missing = sorted(set(ids or []) - {p["id"] for p in chosen})
    if missing:
        raise AnimationError("Paquets introuvables : %s" % ", ".join(missing))
    if not chosen:
        raise AnimationError("Aucun paquet à livrer : python3 -m atelier animation <scène> ...")
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    out = out or os.path.join(config.LIVRAISON_DIR, "animations_%s.zip" % stamp)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_STORED) as z:     # videos deja compressees
        for info in chosen:
            folder = os.path.join(config.LIVRAISON_DIR, info["id"])
            for name in sorted(os.listdir(folder)):
                z.write(os.path.join(folder, name), "%s/%s" % (info["id"], name))
    log("Livraison : %s (%d animation(s))" % (out, len(chosen)))
    return out
