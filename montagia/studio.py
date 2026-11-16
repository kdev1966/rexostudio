"""Chaine de production : Rexo Studio orchestre, chaque outil ne fait que sa tache.

    Rexo (Vision, MobileSAM)  amelioration, detourage des maries, recadrage
    Blender 3.6               animation generique sans photo (modele .blend fait a part,
                              camera drone, emplacements), en composition After Effects ;
                              rendue une seule fois, rangee dans modeles/generiques
    EffectCraft               ouvre la composition, place les vraies photos dans les
                              emplacements, ajoute les titres, rend la video
    FilmCraft                 le clip rejoint le projet de l'evenement (chutier
                              « Génériques ») pour finir le montage

Une « recette » enchaine ces etapes en tache de fond (un seul travail lourd a la fois
sur l'iMac, voir jobs.JobManager). Les fichiers intermediaires restent dans le cache
de l'evenement et sont effaces a la fin ; le resultat va dans 06_Rendus.
"""
from __future__ import annotations

import datetime
import os
import time

from . import blender, effectcraft, effects, filmcraft, moments, tools

CLIPS_DIR = os.path.join("06_Rendus", "Clips_3D")
GENERIQUES_DIR = os.path.join("06_Rendus", "Generiques")
DETOURES_DIR = os.path.join("06_Rendus", "Videos_detourees")
WORK_DIR = os.path.join(".rexo", "studio")
COUPLE_MAX = 2600            # px : largement assez pour des maries en 1080p
FRAME_PHOTO_MAX = 2000       # px : photo d'un cadre (quelques centaines de px a l'ecran)

MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
          "septembre", "octobre", "novembre", "décembre")

RECIPES = {
    "clip-drone": {
        "label": "Clip drone 3D",
        "steps": ["Rexo : amélioration et détourage des mariés",
                  "Blender : animation générique (une seule fois par modèle)",
                  "EffectCraft : photos dans les emplacements, titre, rendu",
                  "FilmCraft : ajout au projet de l'événement"],
    },
    "generique": {
        "label": "Générique des moments forts",
        "steps": ["Rexo : recherche des moments forts dans les rushes gardés",
                  "EffectCraft : enchaînement en fondu, titre, rendu",
                  "FilmCraft : ajout au projet de l'événement"],
    },
    "detour-video": {
        "label": "Détourage vidéo",
        "steps": ["EffectCraft : suivi de la personne (SAM 2.1) et rendu avec transparence",
                  "FilmCraft : ajout au projet de l'événement"],
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
        "filmcraft": filmcraft.installed(),
        "scenes": [{"id": s["id"], "name": s["name"]} for s in blender.scenes()],
        "generics": [g["id"] for g in blender.generics()],
        "titles": [{"id": t["id"], "name": t["name"]} for t in effectcraft.titles()],
        "motions": [{"id": k, "label": v} for k, v in blender.MOTIONS.items()],
        "recipes": [{"id": k, "label": v["label"], "steps": v["steps"]} for k, v in RECIPES.items()],
    }


def couple_cutout(src: str, out_png: str, folder: str, key: str, log=None, box=None) -> str:
    """Maries seuls sur fond transparent, photo amelioree (etape Rexo). box : cadre trace
    autour des maries (proportions de l'image) ; PhotoCraft y selectionne l'objet entier,
    ce qui rattrape une robe a grande traine que Vision ne compte pas dans la personne."""
    small = os.path.join(folder, key + "_reduite.png")
    framed = os.path.join(folder, key + "_cadre.png")
    refined = ""
    try:
        effects.segment(["orient", src, small, "--max", str(COUPLE_MAX)])
        refined = effects.refined_mask(small, folder, key, enhance=True, log=log, couple=True)
        args = ["cutout", small, out_png, "--enhance"] + (["--use-mask", refined] if refined else [])
        if box is not None:
            if log:
                log("PhotoCraft : sélection des mariés dans le cadre tracé")
            effects.couple_mask(small, box, framed)
            args += ["--add-mask", framed]
        result = effects.segment(args)
        if not result.get("coverage"):
            raise StudioError("Aucune personne trouvée sur la photo")
        return out_png
    finally:
        for path in (small, refined, framed):
            if path and os.path.exists(path):
                os.remove(path)


def clip_drone(job, event_dir: str, src: str, scene: str = blender.DEFAULT_SCENE,
               motion: str = "sequence", seconds: float = 9.0, quality: str = "normal",
               title: str = "", subtitle: str = "", title_model: str = effectcraft.DEFAULT_TITLE,
               to_filmcraft: bool = True, box=None) -> dict:
    """Photo des maries -> clip drone 3D titre dans 06_Rendus/Clips_3D, puis dans FilmCraft.
    Emplacements : PHOTO_DEBOUT_MARIES recoit les maries detoures ; chaque PHOTO_CADRE_*
    recoit la photo elle-meme (amelioree)."""
    log = job.add_log
    started = time.time()
    if not os.path.isfile(src):
        raise StudioError("Photo introuvable")
    if not effectcraft.installed():
        raise StudioError("EffectCraft n'est pas installé : il place les photos dans la scène")
    steps = RECIPES["clip-drone"]["steps"]
    folder = os.path.join(event_dir, WORK_DIR)
    os.makedirs(folder, exist_ok=True)
    key = tools.safe_component(os.path.splitext(os.path.basename(src))[0], "photo")
    full_png = os.path.join(folder, key + "_maries_plein.png")
    couple_png = os.path.join(folder, key + "_maries.png")
    photo_jpg = os.path.join(folder, key + "_photo.jpg")
    small_jpg = os.path.join(folder, key + "_photo_reduite.jpg")
    out = tools.unique_path(tools.ensure_parent(
        os.path.join(event_dir, CLIPS_DIR, "%s_clip_drone_%s.mp4" % (key, motion))))
    result = {"seconds": seconds, "motion": motion, "scene": scene, "titled": False, "filmcraft": ""}
    try:
        job.set_progress(0.02, steps[0])
        couple_cutout(src, full_png, folder, key, log, box)
        if effects.trim(full_png, couple_png).get("cut_bottom"):
            log("Attention : les mariés touchent le bas de la photo (photo pas en pied) : dans la "
                "scène, ils sembleront coupés ; préférez une photo des mariés en entier")
        elif box is None:
            log("Conseil : si la robe ou la traîne manque dans le clip, tracez un cadre autour des "
                "mariés avant de relancer")
        # Photo des cadres : amelioree et reduite (une photo de 19 Mpx ralentit EffectCraft)
        # (Core Image lit l'image a la demande : jamais la meme entree et sortie)
        effects.segment(["orient", src, small_jpg, "--max", str(FRAME_PHOTO_MAX)])
        effects.segment(["enhance", small_jpg, photo_jpg])

        log("Rexo : photos prêtes en %.0f s" % (time.time() - started))
        job.set_progress(0.08, steps[1])
        generic_dir, info = blender.ensure_generic(scene, motion, seconds, quality, log=log,
                                                   progress=lambda f: job.set_progress(0.08 + 0.6 * f))
        photos = {}
        for place in info.get("placeholders", []):
            if place["kind"] == "debout" and place["name"] == "PHOTO_DEBOUT_MARIES":
                photos[place["name"]] = couple_png
            elif place["kind"] == "cadre":
                photos[place["name"]] = photo_jpg
        if "PHOTO_DEBOUT_MARIES" not in photos:
            raise StudioError("Le modèle « %s » n'a pas d'emplacement PHOTO_DEBOUT_MARIES" % scene)

        job.set_progress(0.70, steps[2])
        mark = time.time()
        client = effectcraft.connect(log)
        try:
            template = _title_template(client, title, title_model, log)
            effectcraft.compose(client, generic_dir, info, photos, out, title, subtitle, template, log=log,
                                progress=lambda f: job.set_progress(0.70 + 0.22 * f))
            result["titled"] = bool(template)
        finally:
            effectcraft.close(client, folder)
        log("EffectCraft : terminé en %.0f s" % (time.time() - mark))

        job.set_progress(0.94, steps[3])
        result["filmcraft"] = _send_to_filmcraft(event_dir, out, "Génériques", log, to_filmcraft)
    except Exception as exc:
        # Le nom etait reserve d'avance : pas de fichier vide laisse dans les Rendus
        if os.path.exists(out) and os.path.getsize(out) == 0:
            os.remove(out)
        if isinstance(exc, (blender.BlenderError, effectcraft.EffectCraftError, effects.EffectError)):
            raise StudioError(str(exc)) from exc
        raise
    finally:
        for path in (full_png, couple_png, photo_jpg, small_jpg):
            if os.path.exists(path):
                os.remove(path)
    result["path"] = os.path.relpath(out, event_dir)
    log("Clip enregistré : %s (%.0f s en tout)" % (result["path"], time.time() - started))
    return result


def _send_to_filmcraft(event_dir: str, path: str, bin_name: str, log, wanted: bool) -> str:
    """Le resultat rejoint le projet FilmCraft de l'evenement ; un echec n'annule rien."""
    if not (wanted and filmcraft.installed()):
        return ""
    try:
        sent = filmcraft.add_to_event_project(event_dir, [path], bin_name=bin_name, log=log)
        return os.path.relpath(sent["project"], event_dir)
    except filmcraft.FilmCraftError as exc:
        log("FilmCraft : envoi impossible (%s) ; le fichier reste dans 06_Rendus" % exc)
        return ""


def _title_template(client, title: str, title_model: str, log) -> str:
    if not title.strip():
        return ""
    if title_model != effectcraft.DEFAULT_TITLE:
        return effectcraft.title_path(title_model)
    return effectcraft.ensure_default_title(client, log)


def generique(job, event_dir: str, count: int = 6, window: float = moments.WINDOW, title: str = "",
              subtitle: str = "", title_model: str = effectcraft.DEFAULT_TITLE, to_filmcraft: bool = True) -> dict:
    """Moments forts des rushes gardes -> generique enchaine en fondu et titre, dans
    06_Rendus/Generiques, puis dans le chutier « Génériques » de FilmCraft."""
    log = job.add_log
    started = time.time()
    if not effectcraft.installed():
        raise StudioError("EffectCraft n'est pas installé : il enchaîne les moments forts")
    steps = RECIPES["generique"]["steps"]
    job.set_progress(0.01, steps[0])
    try:
        found = moments.find(event_dir, job, count=count, window=window)
    except moments.MomentError as exc:
        raise StudioError(str(exc)) from exc
    chosen = found["moments"]
    for m in chosen:
        log("  %s  %.1f-%.1f s  qualité %.2f, personnes %d %%" % (
            m["name"], m["start"], m["end"], m["score"], round(100 * m.get("people", 0))))
    size = moments.orientation(chosen)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    out = tools.unique_path(tools.ensure_parent(os.path.join(event_dir, GENERIQUES_DIR,
                                                             "Moments_forts_%s.mp4" % stamp)))
    folder = os.path.join(event_dir, WORK_DIR)
    os.makedirs(folder, exist_ok=True)
    result = {"moments": len(chosen), "size": list(size), "titled": False}
    try:
        job.set_progress(0.6, steps[1])
        client = effectcraft.connect(log)
        try:
            template = _title_template(client, title, title_model, log)
            done = effectcraft.assemble(
                client, [(os.path.join(event_dir, m["rel"]), m["start"], m["end"]) for m in chosen], out,
                size=size, title=title, subtitle=subtitle, title_template=template, log=log,
                progress=lambda f: job.set_progress(0.6 + 0.32 * f))
            result.update(titled=bool(template), duration=done["duration"])
        finally:
            effectcraft.close(client, folder)
    except Exception as exc:
        if os.path.exists(out) and os.path.getsize(out) == 0:
            os.remove(out)
        if isinstance(exc, effectcraft.EffectCraftError):
            raise StudioError(str(exc)) from exc
        raise
    job.set_progress(0.94, steps[2])
    result["filmcraft"] = _send_to_filmcraft(event_dir, out, "Génériques", log, to_filmcraft)
    result["path"] = os.path.relpath(out, event_dir)
    log("Générique enregistré : %s (%.0f s en tout)" % (result["path"], time.time() - started))
    return result


def detour_video(job, event_dir: str, rel: str, point, start: float = 0.0, duration: float = 10.0,
                 to_filmcraft: bool = True) -> dict:
    """Personne designee (point en proportions de l'image a l'instant start) detouree
    sur l'extrait, video avec transparence (ProRes 4444) dans 06_Rendus/Videos_detourees,
    puis dans le chutier « Détourages » de FilmCraft."""
    log = job.add_log
    started = time.time()
    if not effectcraft.installed():
        raise StudioError("EffectCraft n'est pas installé : il suit la personne d'image en image")
    try:
        x, y = float(point[0]), float(point[1])
    except (TypeError, ValueError, IndexError):
        raise StudioError("Point invalide : cliquez sur la personne à détourer") from None
    if not (0 <= x <= 1 and 0 <= y <= 1):
        raise StudioError("Point hors de l'image")
    src = os.path.join(event_dir, rel)
    if not os.path.isfile(src):
        raise StudioError("Rush introuvable")
    steps = RECIPES["detour-video"]["steps"]
    key = tools.safe_component(os.path.splitext(os.path.basename(rel))[0], "rush")
    out = tools.unique_path(tools.ensure_parent(os.path.join(
        event_dir, DETOURES_DIR, "%s_detoure_%ds.mov" % (key, int(start)))))
    folder = os.path.join(event_dir, WORK_DIR)
    os.makedirs(folder, exist_ok=True)
    job.set_progress(0.02, steps[0])
    try:
        client = effectcraft.connect(log)
        try:
            done = effectcraft.detour_video(client, src, (x, y), float(start), float(duration), out, log=log,
                                            progress=lambda f: job.set_progress(0.02 + 0.9 * f))
        finally:
            effectcraft.close(client, folder)
    except Exception as exc:
        if os.path.exists(out) and os.path.getsize(out) == 0:
            os.remove(out)
        if isinstance(exc, effectcraft.EffectCraftError):
            raise StudioError(str(exc)) from exc
        raise
    job.set_progress(0.94, steps[1])
    result = {"frames": done["frames"], "start": done["start"], "duration": done["duration"],
              "filmcraft": _send_to_filmcraft(event_dir, out, "Détourages", log, to_filmcraft),
              "path": os.path.relpath(out, event_dir)}
    log("Vidéo détourée : %s (%d images, %.0f s en tout)" % (result["path"], done["frames"], time.time() - started))
    return result
