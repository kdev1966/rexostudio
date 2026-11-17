"""Chaine de production : Rexo Studio orchestre, chaque outil ne fait que sa tache.

    Rexo (Vision, MobileSAM)  amelioration, detourage des maries, recadrage
    Bibliotheque              animations 3D toutes pretes, livrees par l'atelier (projet
                              atelier/ du depot, a part : decors Blender, textures) ; Rexo
                              Studio ne fait jamais de 3D lui-meme (montagia/animations.py)
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
import shutil
import time

from . import animations, effectcraft, effects, filmcraft, moments, rushes, tools, transcribe

CLIPS_DIR = os.path.join("06_Rendus", "Clips_3D")
GENERIQUES_DIR = os.path.join("06_Rendus", "Generiques")
TEASERS_DIR = os.path.join("06_Rendus", "Teasers")
TEASER_SIZE = (1080, 1920)          # 9:16, Instagram, TikTok, Reels, Shorts
DETOURES_DIR = os.path.join("06_Rendus", "Videos_detourees")
SUBTITLES_DIR = os.path.join("06_Rendus", "Sous-titres")
# Rendus de la chaine, dans l'ordre de l'onglet Montage, et leur chutier FilmCraft
RENDER_KINDS = (
    (GENERIQUES_DIR, "Génériques", "Générique"),
    (TEASERS_DIR, "Teasers", "Teaser"),
    (CLIPS_DIR, "Génériques", "Clip 3D"),
    (DETOURES_DIR, "Détourages", "Détourage"),
    (SUBTITLES_DIR, "", "Sous-titres"),
)
WORK_DIR = os.path.join(".rexo", "studio")
COUPLE_MAX = 2600            # px : largement assez pour des maries en 1080p
FRAME_PHOTO_MAX = 2000       # px : photo d'un cadre (quelques centaines de px a l'ecran)

MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
          "septembre", "octobre", "novembre", "décembre")

RECIPES = {
    "clip-drone": {
        "label": "Clip drone 3D",
        "steps": ["Rexo : amélioration et détourage des mariés",
                  "Bibliothèque : animation 3D choisie",
                  "EffectCraft : photos dans les emplacements, titre, rendu",
                  "FilmCraft : ajout au projet de l'événement"],
    },
    "generique": {
        "label": "Générique des moments forts",
        "steps": ["Rexo : recherche des moments forts dans les rushes gardés",
                  "EffectCraft : enchaînement en fondu, titre, rendu",
                  "FilmCraft : ajout au projet de l'événement"],
    },
    "teaser": {
        "label": "Teaser vertical",
        "steps": ["Rexo : moments forts des rushes gardés",
                  "Rexo : cadrage vertical sur les personnes (Apple Vision)",
                  "EffectCraft : enchaînement 9:16, titre, rendu",
                  "FilmCraft : ajout au projet de l'événement"],
    },
    "detour-video": {
        "label": "Détourage vidéo",
        "steps": ["EffectCraft : suivi de la personne (SAM 2.1) et rendu avec transparence",
                  "FilmCraft : ajout au projet de l'événement"],
    },
    "sous-titres": {
        "label": "Sous-titres d'un discours",
        "steps": ["Rexo : transcription de la parole (whisper.cpp)",
                  "Rexo : fichier de sous-titres dans 06_Rendus/Sous-titres"],
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
        "effectcraft": effectcraft.installed(),
        "detourage": effects.installed(),
        "filmcraft": filmcraft.installed(),
        "animations": animations.catalog(),
        "titles": [{"id": t["id"], "name": t["name"]} for t in effectcraft.titles()],
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


def clip_drone(job, event_dir: str, src: str, animation: str, title: str = "", subtitle: str = "",
               title_model: str = effectcraft.DEFAULT_TITLE, to_filmcraft: bool = True, box=None) -> dict:
    """Photo des maries + animation de la bibliotheque -> clip drone 3D titre dans
    06_Rendus/Clips_3D, puis dans FilmCraft. Emplacements : PHOTO_DEBOUT_MARIES recoit les
    maries detoures ; chaque PHOTO_CADRE_* recoit la photo elle-meme (amelioree)."""
    log = job.add_log
    started = time.time()
    if not os.path.isfile(src):
        raise StudioError("Photo introuvable")
    try:
        animation_dir, info = animations.get(animation)
    except animations.AnimationError as exc:
        raise StudioError(str(exc)) from exc
    if not any(e["name"] == "PHOTO_DEBOUT_MARIES" for e in info["emplacements"]):
        raise StudioError("L'animation « %s » n'a pas d'emplacement PHOTO_DEBOUT_MARIES" % info.get("titre"))
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
        os.path.join(event_dir, CLIPS_DIR, "%s_%s.mp4" % (key, tools.safe_component(animation, "animation")))))
    result = {"animation": animation, "seconds": info.get("duree"), "titled": False, "filmcraft": ""}
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
        job.set_progress(0.10, steps[1])
        log("Bibliothèque : %s" % info.get("titre", animation))
        photos = {}
        for place in info["emplacements"]:
            if place["kind"] == "debout" and place["name"] == "PHOTO_DEBOUT_MARIES":
                photos[place["name"]] = couple_png
            elif place["kind"] == "cadre":
                photos[place["name"]] = photo_jpg

        job.set_progress(0.15, steps[2])
        mark = time.time()
        client = effectcraft.connect(log)
        try:
            template = _title_template(client, title, title_model, log)
            effectcraft.compose(client, animation_dir, info, photos, out, title, subtitle, template, log=log,
                                progress=lambda f: job.set_progress(0.15 + 0.77 * f))
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
        if isinstance(exc, (effectcraft.EffectCraftError, effects.EffectError)):
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
    chosen = _chosen_moments(job, event_dir, count, window)
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


def _chosen_moments(job, event_dir: str, count: int, window: float) -> list:
    """Moments forts choisis dans l'onglet Video, sinon cherches maintenant."""
    found = moments.load(event_dir)
    if found:
        job.add_log("Moments forts déjà choisis (onglet Vidéo) : %d" % len(found["moments"]))
    else:
        try:
            found = moments.find(event_dir, job, count=count, window=window)
        except moments.MomentError as exc:
            raise StudioError(str(exc)) from exc
    return found["moments"]


def teaser(job, event_dir: str, count: int = 8, window: float = moments.WINDOW, title: str = "",
           subtitle: str = "", title_model: str = effectcraft.DEFAULT_TITLE, to_filmcraft: bool = True) -> dict:
    """Teaser vertical 9:16 pour les reseaux : les moments forts, chacun cadre sur les
    personnes quand le rush est horizontal (panoramique lent si elles se deplacent),
    enchaines en fondu, titre a la fin, sans le son (la musique se pose dans FilmCraft).
    Dans 06_Rendus/Teasers, puis dans le chutier « Teasers » de FilmCraft."""
    log = job.add_log
    started = time.time()
    if not effectcraft.installed():
        raise StudioError("EffectCraft n'est pas installé : il monte le teaser")
    steps = RECIPES["teaser"]["steps"]
    job.set_progress(0.01, steps[0])
    chosen = _chosen_moments(job, event_dir, count, window)
    job.set_progress(0.5, steps[1])
    work = os.path.join(event_dir, WORK_DIR, "cadrage")
    os.makedirs(work, exist_ok=True)
    parts, reframed = [], 0
    try:
        for i, m in enumerate(chosen):
            path = os.path.join(event_dir, m["rel"])
            framing = moments.focus(dict(m, path=path), work)
            if framing:
                reframed += 1
                log("  %s  %.1f-%.1f s  cadrage %s" % (
                    m["name"], m["start"], m["end"], "fixe à %d %%" % round(100 * framing[0])
                    if framing[0] == framing[1] else "de %d %% à %d %%" % (round(100 * framing[0]),
                                                                          round(100 * framing[1]))))
            parts.append((path, m["start"], m["end"], framing))
            job.set_progress(0.5 + 0.1 * (i + 1) / len(chosen))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    log("Rexo : %d moment(s), %d recadré(s) sur les personnes" % (len(parts), reframed))
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    out = tools.unique_path(tools.ensure_parent(os.path.join(event_dir, TEASERS_DIR, "Teaser_%s.mp4" % stamp)))
    folder = os.path.join(event_dir, WORK_DIR)
    result = {"moments": len(parts), "reframed": reframed, "titled": False}
    try:
        job.set_progress(0.62, steps[2])
        client = effectcraft.connect(log)
        try:
            template = _title_template(client, title, title_model, log)
            done = effectcraft.assemble(
                client, parts, out, size=TEASER_SIZE, title=title, subtitle=subtitle, title_template=template,
                name="Teaser", log=log, progress=lambda f: job.set_progress(0.62 + 0.3 * f))
            result.update(titled=bool(template), duration=done["duration"])
        finally:
            effectcraft.close(client, folder)
    except Exception as exc:
        if os.path.exists(out) and os.path.getsize(out) == 0:
            os.remove(out)
        if isinstance(exc, effectcraft.EffectCraftError):
            raise StudioError(str(exc)) from exc
        raise
    job.set_progress(0.94, steps[3])
    result["filmcraft"] = _send_to_filmcraft(event_dir, out, "Teasers", log, to_filmcraft)
    result["path"] = os.path.relpath(out, event_dir)
    log("Teaser enregistré : %s (%.0f s en tout)" % (result["path"], time.time() - started))
    return result


def detour_video(job, event_dir: str, rel: str, point=None, start: float = 0.0, duration: float = 10.0,
                 to_filmcraft: bool = True, box=None) -> dict:
    """Personne designee a l'instant start (proportions de l'image) detouree sur
    l'extrait, video avec transparence (ProRes 4444) dans 06_Rendus/Videos_detourees,
    puis dans le chutier « Détourages » de FilmCraft. point : un clic sur la personne ;
    box : [x, y, largeur, hauteur], un cadre autour d'elle, qui laisse dehors un voisin
    colle a elle (sans point, le centre du cadre sert de point)."""
    log = job.add_log
    started = time.time()
    if not effectcraft.installed():
        raise StudioError("EffectCraft n'est pas installé : il suit la personne d'image en image")
    if box is not None:
        try:
            bx, by, bw, bh = (float(v) for v in box)
        except (TypeError, ValueError):
            raise StudioError("Cadre invalide") from None
        if not (0 <= bx < 1 and 0 <= by < 1 and 0.02 < bw <= 1 - bx + 1e-6 and 0.02 < bh <= 1 - by + 1e-6):
            raise StudioError("Cadre hors de l'image ou trop petit")
        box = (bx, by, bw, bh)
    if point is None and box is not None:
        point = (box[0] + box[2] / 2, box[1] + box[3] / 2)
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
                                            progress=lambda f: job.set_progress(0.02 + 0.9 * f), box=box)
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


def subtitles(job, event_dir: str, rel: str, language: str = "auto") -> dict:
    """Discours d'un rush -> sous-titres .srt dans 06_Rendus/Sous-titres (a poser au
    montage dans FilmCraft)."""
    src = os.path.join(event_dir, rel)
    if not os.path.isfile(src):
        raise StudioError("Rush introuvable : %s" % rel)
    steps = RECIPES["sous-titres"]["steps"]
    job.set_progress(0.02, steps[0])
    try:
        result = transcribe.transcribe(src, language=language,
                                       workdir=os.path.join(event_dir, WORK_DIR, "transcription"),
                                       on_log=job.add_log)
    except RuntimeError as exc:
        raise StudioError("Transcription impossible : %s" % exc) from exc
    if not result["segments"]:
        raise StudioError("Aucune parole reconnue dans ce rush")
    job.set_progress(0.95, steps[1])
    key = tools.safe_component(os.path.splitext(os.path.basename(rel))[0], "rush")
    out = tools.unique_path(tools.ensure_parent(os.path.join(event_dir, SUBTITLES_DIR, key + ".srt")))
    transcribe.write_srt(result["segments"], out)
    job.add_log("Sous-titres : %d lignes (%s) -> %s" % (len(result["segments"]), result["language"],
                                                        os.path.relpath(out, event_dir)))
    return {"path": os.path.relpath(out, event_dir), "lines": len(result["segments"]),
            "language": result["language"]}


def renders(event_dir: str) -> list:
    """Rendus de la chaine de production (onglet Montage), du plus recent au plus ancien
    dans chaque famille."""
    items = []
    for folder, bin_name, label in RENDER_KINDS:
        base = os.path.join(event_dir, folder)
        names = sorted(os.listdir(base)) if os.path.isdir(base) else []
        found = []
        for name in names:
            path = os.path.join(base, name)
            if name.startswith(".") or not os.path.isfile(path) or os.path.getsize(path) == 0:
                continue
            st = os.stat(path)
            found.append({"rel": os.path.join(folder, name), "name": name, "path": path, "kind": label,
                          "bin": bin_name, "size": st.st_size, "mtime": st.st_mtime})
        items.extend(sorted(found, key=lambda r: -r["mtime"]))
    return items


class _Scaled(object):
    """Progression d'une sous-etape ramenee a la tranche [start, end] du travail."""

    def __init__(self, job, start: float, end: float):
        self.job, self.start, self.end = job, start, end
        self.add_log = job.add_log

    def set_progress(self, value, step=""):
        self.job.set_progress(self.start + (self.end - self.start) * value, step)


def finish_in_filmcraft(job, event_dir: str) -> dict:
    """Fin du travail dans Rexo : les rushes gardes en sequence (dans l'ordre du tournage)
    et les rendus de la chaine dans leurs chutiers, un seul projet FilmCraft ouvert pour
    finir le film (effets, post-production, etalonnage)."""
    result = rushes.send_to_filmcraft(event_dir, _Scaled(job, 0.0, 0.8))
    by_bin = {}
    for item in renders(event_dir):
        if item["bin"]:
            by_bin.setdefault(item["bin"], []).append(item["path"])
    added = 0
    for bin_name, paths in by_bin.items():
        job.set_progress(0.85, "FilmCraft : chutier « %s » (%d)" % (bin_name, len(paths)))
        try:
            sent = filmcraft.add_to_event_project(event_dir, paths, bin_name=bin_name, log=job.add_log)
            added += len(sent["items"])
        except filmcraft.FilmCraftError as exc:
            job.add_log("FilmCraft : chutier « %s » impossible (%s)" % (bin_name, exc))
    filmcraft.open_in_app()
    job.set_progress(1.0, "Projet ouvert dans FilmCraft")
    result["renders"] = added
    return result
