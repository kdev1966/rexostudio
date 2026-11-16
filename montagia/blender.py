"""Blender 3.6 LTS, moteur des scenes 3D de la chaine de production.

Blender ne fait qu'une chose : l'animation generique d'un modele de scene (.blend fait
a part, contrat dans blender/build_template_jardin.py), sans aucune photo : le decor
filme par la camera drone, exporte en composition After Effects (.jsx) avec un nul par
emplacement de photo. Chaque animation n'est rendue qu'une fois et rangee dans la
bibliotheque (config.GENERICS_DIR) ; EffectCraft y place ensuite les vraies photos.
Il tourne sans interface (blender -b), en
processus separe ; les mouvements sont definis dans blender/render_template.py.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time

from . import config, tools

EXPORT_SCRIPT = os.path.join(config.BLENDER_SCRIPTS_DIR, "export_generic.py")
BUILD_SCRIPT = os.path.join(config.BLENDER_SCRIPTS_DIR, "build_template_jardin.py")

MOTIONS = {
    "sequence": "Séquence drone (approche, tour, envol)",
    "approche": "Approche depuis le ciel",
    "orbite": "Tour autour des mariés",
    "envol": "Envol au-dessus des mariés",
    "spirale": "Spirale descendante",
}
QUALITIES = ("brouillon", "normal", "fin")
DEFAULT_SCENE = "jardin_nuit"
FPS = 30

_FRAME = re.compile(r"^IMAGE (\d+)")
_MEASURE = re.compile(r"MESURE .*: (\d+) image\(s\) en ([\d.]+) s")


class BlenderError(RuntimeError):
    pass


def installed() -> bool:
    return os.path.isfile(config.BLENDER_BIN) and os.access(config.BLENDER_BIN, os.X_OK)


def scenes() -> list:
    """Modeles de scenes 3D disponibles (un .blend par scene)."""
    folder = config.SCENES_3D_DIR
    if not os.path.isdir(folder):
        return []
    items = []
    for name in sorted(os.listdir(folder)):
        if name.lower().endswith(".blend") and not name.startswith("."):
            stem = name[:-6]
            items.append({"id": stem, "name": stem.replace("_", " ").capitalize(),
                          "path": os.path.join(folder, name)})
    return items


def scene_path(scene_id: str) -> str:
    for item in scenes():
        if item["id"] == scene_id:
            return item["path"]
    raise BlenderError("Scène 3D introuvable : %s (dossier %s)" % (scene_id, config.SCENES_3D_DIR))


def build_default_scene(log=None) -> str:
    """Construit le premier modele simple (jardin de nuit) s'il manque."""
    out = os.path.join(config.SCENES_3D_DIR, DEFAULT_SCENE + ".blend")
    if os.path.isfile(out):
        return out
    if not installed():
        raise BlenderError("Blender 3.6 introuvable (%s) : ./scripts/install_blender.sh" % config.BLENDER_APP)
    tools.ensure_parent(out)
    if log:
        log("Blender : construction du modèle de scène « %s »" % DEFAULT_SCENE)
    proc = subprocess.run([config.BLENDER_BIN, "-b", "--factory-startup", "--python", BUILD_SCRIPT,
                           "--", out], capture_output=True, text=True, timeout=600)
    if proc.returncode != 0 or not os.path.isfile(out):
        raise BlenderError("Construction de la scène impossible : %s" % _tail(proc.stdout + proc.stderr))
    return out


def _tail(text: str, lines: int = 6) -> str:
    rows = [r for r in (text or "").strip().splitlines() if r.strip()]
    return " | ".join(rows[-lines:]) or "aucun message"


def generic_id(scene: str, motion: str, seconds: float, quality: str) -> str:
    return "%s__%s__%gs__%s" % (scene, motion, seconds, quality)


def generic_info(folder: str):
    """scene.json d'une animation generique complete, sinon None."""
    try:
        with open(os.path.join(folder, "scene.json"), "r", encoding="utf-8") as fh:
            info = json.load(fh)
    except (OSError, ValueError):
        return None
    needed = ["decor.mp4", "composition.jsx"] + (["premier_plan.mov"] if info.get("premier_plan") else [])
    if all(os.path.isfile(os.path.join(folder, n)) and os.path.getsize(os.path.join(folder, n)) > 0
           for n in needed):
        return info
    return None


def generics() -> list:
    """Animations generiques deja rendues (bibliotheque)."""
    root = config.GENERICS_DIR
    items = []
    for name in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        info = generic_info(os.path.join(root, name))
        if info:
            items.append({"id": name, "path": os.path.join(root, name), "scene": info.get("scene"),
                          "motion": info.get("motion"), "duration": info.get("duration"),
                          "quality": info.get("quality"),
                          "placeholders": [p["name"] for p in info.get("placeholders", [])]})
    return items


def ensure_generic(scene: str, motion: str = "sequence", seconds: float = 9.0, quality: str = "normal",
                   log=None, progress=None, timeout: float = 3 * 3600) -> tuple:
    """(dossier, scene.json) de l'animation generique ; Blender la rend si elle manque
    (plusieurs minutes, une seule fois)."""
    if motion not in MOTIONS:
        raise BlenderError("Mouvement inconnu : %s" % motion)
    if quality not in QUALITIES:
        raise BlenderError("Qualité inconnue : %s" % quality)
    folder = os.path.join(config.GENERICS_DIR, generic_id(scene, motion, seconds, quality))
    info = generic_info(folder)
    blend_file = os.path.join(config.SCENES_3D_DIR, scene + ".blend")
    if info and os.path.isfile(blend_file) and \
            os.path.getmtime(blend_file) > os.path.getmtime(os.path.join(folder, "scene.json")):
        info = None                     # modele retouche depuis : l'animation est a refaire
        if log:
            log("Blender : le modèle « %s » a changé, nouvelle animation générique" % scene)
    if info:
        if log:
            log("Blender : animation générique déjà prête (%s)" % os.path.basename(folder))
        return folder, info
    if not installed():
        raise BlenderError("Blender 3.6 introuvable (%s) : ./scripts/install_blender.sh" % config.BLENDER_APP)
    if scene == DEFAULT_SCENE and not os.path.isfile(os.path.join(config.SCENES_3D_DIR, scene + ".blend")):
        build_default_scene(log)
    blend = os.path.abspath(scene_path(scene))
    work = folder + ".partiel"
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    frames = max(2, int(round(seconds * FPS)))
    if log:
        log("Blender : animation générique « %s », %s, %d images (%s) — une seule fois"
            % (scene, MOTIONS[motion].lower(), frames, quality))
    cmd = [config.BLENDER_BIN, "-b", blend, "--python", EXPORT_SCRIPT, "--", work, motion,
           "%g" % seconds, quality]
    started = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            stdin=subprocess.DEVNULL)
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
                raise BlenderError("Blender dépasse %d min : arrêté" % (timeout // 60))
        proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        proc.stdout.close()
    info = generic_info(work) if proc.returncode == 0 else None
    if not info:
        shutil.rmtree(work, ignore_errors=True)
        raise BlenderError("Animation générique impossible : %s" % _tail("".join(tail)))
    # Les chemins des videos sont ecrits dans le .jsx : on les corrige pour le dossier final
    jsx = os.path.join(work, "composition.jsx")
    with open(jsx, "r", encoding="utf-8") as fh:
        text = fh.read()
    with open(jsx, "w", encoding="utf-8") as fh:
        fh.write(text.replace(json.dumps(work)[1:-1], json.dumps(folder)[1:-1]))
    shutil.rmtree(folder, ignore_errors=True)
    os.rename(work, folder)
    if log and measure:
        log("Blender : %d images en %.0f s (%.2f s par image)" % (measure[0], measure[1], measure[1] / measure[0]))
    return folder, info
