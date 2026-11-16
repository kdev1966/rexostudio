"""Moments forts des rushes d'un evenement (etape Rexo de la chaine de production).

Chaque rush garde est mesure image par image (une passe ffmpeg sur l'image reduite :
luminance et nettete a 4 i/s, mouvement de camera a 12 i/s), puis decoupe en fenetres
de quelques secondes notees sur la qualite de l'image :
    nettete   (blurdetect)        un plan flou n'est jamais un moment fort
    stabilite (tremblement)       camera posee ou mouvement regulier
    exposition (luminance)        ni sombre ni brule
La meilleure fenetre de chaque rush est ensuite verifiee par Apple Vision (place des
personnes dans l'image) : un mariage se raconte par ses gens. On garde les meilleurs
moments, un par rush, dans l'ordre du tournage ; EffectCraft les enchaine ensuite.

Resultat dans <evenement>/.rexo/moments.json (chemins relatifs a l'evenement).
"""
from __future__ import annotations

import json
import os
import shutil
import statistics
import tempfile
import time

from . import config, effects, rushes, tools

WINDOW = 3.0            # duree d'un moment (s)
STEP = 0.5              # pas entre deux fenetres candidates (s)
STATE_FILE = os.path.join(".rexo", "moments.json")


class MomentError(RuntimeError):
    pass


def measure_series(path: str, duration: float) -> dict:
    """Mesures par image : luminance et nettete (4 i/s), mouvement (12 i/s)."""
    ffmpeg = config.ffmpeg_bin()
    if not ffmpeg:
        raise MomentError("ffmpeg introuvable")
    work = tempfile.mkdtemp(prefix="rexo-moments-")
    try:
        graph = ("[0:v]scale=480:-2,split[a][b];"
                 "[a]fps=4,signalstats,blurdetect=block_width=32:block_height=32,"
                 "metadata=print:file=meta.txt[o1];"
                 "[b]fps=12,vidstabdetect=result=motion.trf:fileformat=1:shakiness=5[o2]")
        tools.run([ffmpeg, "-hide_banner", "-v", "error", "-nostdin", "-i", path,
                   "-filter_complex", graph, "-map", "[o1]", "-f", "null", "-",
                   "-map", "[o2]", "-f", "null", "-"],
                  timeout=max(300, int(duration * 4)), cwd=work)
        with open(os.path.join(work, "meta.txt"), encoding="utf-8", errors="replace") as fh:
            frames = rushes.parse_frames(fh.read())
        with open(os.path.join(work, "motion.trf"), encoding="utf-8", errors="replace") as fh:
            motions = rushes.parse_motion(fh.read())
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return {"luma": [f.get("YAVG") for f in frames], "blur": [f.get("blur") for f in frames],
            "motion": motions}


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def window_scores(series: dict, duration: float, window: float = WINDOW, step: float = STEP) -> list:
    """Note de qualite (0 a 1) de chaque fenetre [debut, fin] du rush."""
    if duration < window:
        return []
    out = []
    start = 0.0
    while start + window <= duration + 1e-6:
        a, b = int(start * 4), int((start + window) * 4)
        lumas = [v for v in series["luma"][a:b] if v is not None]
        blurs = [v for v in series["blur"][a:b] if v is not None]
        moves = series["motion"][int(start * 12):int((start + window) * 12)]
        if lumas and blurs:
            luma, blur = statistics.median(lumas), statistics.median(blurs)
            shake = rushes.shake_index(moves, 480)
            sharp = _clamp(1 - blur / rushes.BLUR_LIMIT)
            stable = _clamp(1 - shake / rushes.SHAKE_LIMIT)
            if luma < rushes.DARK_LUMA:
                expo = _clamp((luma - rushes.BLACK_LUMA) / float(rushes.DARK_LUMA - rushes.BLACK_LUMA)) * 0.5
            elif luma > rushes.BRIGHT_LUMA:
                expo = 0.3
            else:
                expo = 1.0 - abs(luma - 120) / 150.0
            out.append({"start": round(start, 2), "end": round(start + window, 2),
                        "score": round(0.4 * sharp + 0.35 * stable + 0.25 * expo, 4),
                        "luma": round(luma, 1), "blur": round(blur, 2), "shake": shake})
        start += step
    return out


def people_share(path: str, at: float, work: str) -> float:
    """Part de l'image occupee par des personnes (Apple Vision) a l'instant at."""
    frame = os.path.join(work, "image.jpg")
    mask = os.path.join(work, "masque.png")
    try:
        tools.run([config.ffmpeg_bin(), "-hide_banner", "-v", "error", "-nostdin", "-y",
                   "-ss", "%.2f" % at, "-i", path, "-frames:v", "1", "-vf", "scale=640:-2", frame],
                  timeout=60)
        return float(effects.segment(["mask", frame, mask]).get("coverage") or 0.0)
    except (tools.CommandError, effects.EffectError):
        return 0.0
    finally:
        for p in (frame, mask):
            if os.path.exists(p):
                os.remove(p)


def candidates(event_dir: str) -> list:
    """Rushes a explorer : ceux gardes (choix du monteur ou proposition)."""
    clips = [c for c in rushes.clip_list(event_dir) if c["analyzed"] and c["kept"]
             and (c.get("duration") or 0) >= WINDOW]
    if not clips:
        raise MomentError("Aucun rush gardé assez long : analysez les rushes et gardez-en au moins un.")
    return clips


def find(event_dir: str, job=None, count: int = 6, window: float = WINDOW) -> dict:
    """Cherche les moments forts (au plus un par rush) et les enregistre."""
    log = job.add_log if job else (lambda _m: None)
    clips = candidates(event_dir)
    started = time.time()
    work = tempfile.mkdtemp(prefix="rexo-gens-")
    best = []
    try:
        for i, clip in enumerate(clips):
            if job:
                job.set_progress(0.9 * i / len(clips), "Moments forts : %s (%d/%d)" % (clip["name"], i + 1, len(clips)))
            try:
                series = measure_series(clip["path"], clip["duration"])
            except (tools.CommandError, MomentError) as exc:
                log("%s : mesure impossible (%s)" % (clip["name"], exc))
                continue
            windows = sorted(window_scores(series, clip["duration"], window), key=lambda w: -w["score"])
            if not windows:
                continue
            # Les 3 meilleures fenetres, departagees par la place des personnes
            for w in windows[:3]:
                w["people"] = round(people_share(clip["path"], (w["start"] + w["end"]) / 2, work), 3)
                w["total"] = round(w["score"] + 0.3 * _clamp(w["people"] / 0.2), 4)
            top = max(windows[:3], key=lambda w: w["total"])
            best.append(dict(top, rel=clip["rel"], name=clip["name"], shot_at=clip["shot_at"],
                             width=clip["width"], height=clip["height"]))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if not best:
        raise MomentError("Aucun moment fort trouvé dans les rushes gardés")
    chosen = sorted(best, key=lambda m: -m["total"])[:count]
    chosen.sort(key=lambda m: (m["shot_at"] or "", m["rel"], m["start"]))
    result = {"window": window, "moments": chosen, "explored": len(clips),
              "seconds": round(time.time() - started, 1)}
    path = os.path.join(event_dir, STATE_FILE)
    tools.ensure_parent(path)
    with open(path + ".tmp", "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    os.replace(path + ".tmp", path)
    log("Moments forts : %d retenus sur %d rushes explorés en %.0f s" % (len(chosen), len(clips), result["seconds"]))
    return result


def orientation(moments: list) -> tuple:
    """Taille du generique : celle de la majorite des rushes (vertical ou horizontal)."""
    vertical = sum(1 for m in moments if (m.get("height") or 0) > (m.get("width") or 0))
    return (1080, 1920) if vertical > len(moments) / 2.0 else (1920, 1080)
