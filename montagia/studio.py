"""Chaine de production : Rexo Studio orchestre, chaque outil ne fait que sa tache.

    Rexo (Vision, MobileSAM)  amelioration et detourage des maries
    Blender 3.6               scene 3D (modele .blend fait a part) et camera drone
    EffectCraft               titres (modele .ectemplate fait a part) et rendu final

Une « recette » enchaine ces etapes en tache de fond (un seul travail lourd a la fois
sur l'iMac, voir jobs.JobManager). Les fichiers intermediaires restent dans le cache
de l'evenement et sont effaces a la fin ; le resultat va dans 06_Rendus.
"""
from __future__ import annotations

import datetime
import os
import shutil

from . import blender, effectcraft, effects, tools

CLIPS_DIR = os.path.join("06_Rendus", "Clips_3D")
WORK_DIR = os.path.join(".rexo", "studio")
COUPLE_MAX = 2600            # px : largement assez pour des maries en 1080p

MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
          "septembre", "octobre", "novembre", "décembre")

RECIPES = {
    "clip-drone": {
        "label": "Clip drone 3D",
        "steps": ["Rexo : amélioration et détourage des mariés",
                  "Blender : scène 3D et caméra drone",
                  "EffectCraft : titre et rendu final"],
    },
}


class StudioError(RuntimeError):
    pass


def french_date(iso: str) -> str:
    try:
        day = datetime.date.fromisoformat(iso)
    except (TypeError, ValueError):
        return ""
    return "%d %s %d" % (day.day, MONTHS[day.month - 1], day.year)


def status() -> dict:
    """Ce dont la chaine dispose sur cette machine (pour l'interface)."""
    return {
        "blender": blender.installed(),
        "effectcraft": effectcraft.installed(),
        "detourage": effects.installed(),
        "scenes": [{"id": s["id"], "name": s["name"]} for s in blender.scenes()],
        "titles": [{"id": t["id"], "name": t["name"]} for t in effectcraft.titles()],
        "motions": [{"id": k, "label": v} for k, v in blender.MOTIONS.items()],
        "recipes": [{"id": k, "label": v["label"], "steps": v["steps"]} for k, v in RECIPES.items()],
    }


def couple_cutout(src: str, out_png: str, folder: str, key: str, log=None) -> str:
    """Maries seuls sur fond transparent, photo amelioree (etape Rexo)."""
    small = os.path.join(folder, key + "_reduite.png")
    refined = ""
    try:
        effects.segment(["orient", src, small, "--max", str(COUPLE_MAX)])
        refined = effects.refined_mask(small, folder, key, enhance=True, log=log, couple=True)
        args = ["cutout", small, out_png, "--enhance"] + (["--use-mask", refined] if refined else [])
        result = effects.segment(args)
        if not result.get("coverage"):
            raise StudioError("Aucune personne trouvée sur la photo")
        return out_png
    finally:
        for path in (small, refined):
            if path and os.path.exists(path):
                os.remove(path)


def clip_drone(job, event_dir: str, src: str, scene: str = blender.DEFAULT_SCENE,
               motion: str = "sequence", seconds: float = 9.0, quality: str = "normal",
               title: str = "", subtitle: str = "", title_model: str = effectcraft.DEFAULT_TITLE) -> dict:
    """Photo des maries -> video drone 3D titree, dans 06_Rendus/Clips_3D."""
    log = job.add_log
    if not os.path.isfile(src):
        raise StudioError("Photo introuvable")
    if not blender.installed():
        raise StudioError("Blender 3.6 n'est pas installé (./scripts/install_blender.sh)")
    if scene == blender.DEFAULT_SCENE and not blender.scenes():
        blender.build_default_scene(log)
    scene_file = blender.scene_path(scene)
    titled = bool(title.strip()) and effectcraft.installed()
    if title.strip() and not titled:
        log("EffectCraft absent : la vidéo sort sans titre")

    folder = os.path.join(event_dir, WORK_DIR)
    os.makedirs(folder, exist_ok=True)
    key = tools.safe_component(os.path.splitext(os.path.basename(src))[0], "photo")
    couple_png = os.path.join(folder, key + "_maries.png")
    scene_video = os.path.join(folder, key + "_scene.mp4")
    stem = "%s_clip_drone_%s" % (key, motion)
    out = tools.unique_path(tools.ensure_parent(os.path.join(event_dir, CLIPS_DIR, stem + ".mp4")))
    steps = RECIPES["clip-drone"]["steps"]
    try:
        job.set_progress(0.02, steps[0])
        couple_cutout(src, couple_png, folder, key, log)

        job.set_progress(0.10, steps[1])
        span = 0.75 if titled else 0.88
        done = blender.render(couple_png, scene_file, scene_video, motion, seconds, quality, log=log,
                              progress=lambda f: job.set_progress(0.10 + span * f))
        log("Blender : %d images en %.0f s (%.2f s par image)" % (done["frames"], done["seconds"],
                                                                  done["per_frame"]))
        if titled:
            job.set_progress(0.86, steps[2])
            client = effectcraft.connect(log)
            try:
                template = (effectcraft.title_path(title_model) if title_model != effectcraft.DEFAULT_TITLE
                            else effectcraft.ensure_default_title(client, log))
                effectcraft.title_over_video(client, scene_video, template, title.strip(), subtitle.strip(),
                                             out, log=log,
                                             progress=lambda f: job.set_progress(0.86 + 0.13 * f))
            finally:
                effectcraft.close(client, folder)
        else:
            shutil.move(scene_video, out)
    except (blender.BlenderError, effectcraft.EffectCraftError, effects.EffectError) as exc:
        if os.path.exists(out) and os.path.getsize(out) == 0:
            os.remove(out)
        raise StudioError(str(exc)) from exc
    finally:
        for path in (couple_png, scene_video):
            if os.path.exists(path):
                os.remove(path)
    rel = os.path.relpath(out, event_dir)
    log("Clip enregistré : %s" % rel)
    return {"path": rel, "seconds": seconds, "motion": motion, "scene": scene, "titled": titled}
