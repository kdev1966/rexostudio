"""Musique du generique et du teaser (etape Rexo de la chaine de production, ffmpeg).

EffectCraft rend la video sans son ; Rexo y pose ensuite la musique choisie :
    depart     la ou le morceau « demarre » vraiment (energie EBU R128 mesuree toutes
               les 0,1 s) : une intro calme n'occupe pas un teaser de 25 s
    longueur   coupee a la duree exacte de la video, fondu d'entree et de sortie
    son        facultatif : le son des rushes (voix, youyous) est garde, et la musique
               baisse d'elle-meme quand on parle (compression declenchee par la bande
               des voix, « ducking »)
    niveau     normalise pour les reseaux (-14 LUFS)

Les morceaux viennent de la bibliotheque du studio (bibliotheque/musiques, morceaux
dont le studio a les droits) ou du dossier 03_Audio de l'evenement.
"""
from __future__ import annotations

import os
import re

from . import config, tools

MUSIC_EXT = {".mp3", ".m4a", ".aac", ".wav", ".aif", ".aiff", ".flac", ".ogg"}
STEP = 0.1                 # s entre deux mesures d'energie
FADE_IN = 0.8
FADE_OUT = 2.0
LOUDNESS = -14             # LUFS : niveau courant des reseaux sociaux
EVENT_AUDIO = "03_Audio"

_POINT = re.compile(r"pts_time:([\d.]+)")
_LEVEL = re.compile(r"lavfi\.r128\.M=(-?[\d.]+|-inf)")


class MusicError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# Morceaux disponibles
# --------------------------------------------------------------------------

def _tracks(base: str, prefix: str, label: str) -> list:
    found = []
    for root, dirs, files in os.walk(base) if os.path.isdir(base) else []:
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(files):
            if name.startswith(".") or os.path.splitext(name)[1].lower() not in MUSIC_EXT:
                continue
            rel = os.path.relpath(os.path.join(root, name), base)
            found.append({"id": prefix + rel, "name": os.path.splitext(rel)[0], "source": label,
                          "path": os.path.join(root, name)})
    return found


def library(event_dir: str = "") -> list:
    """Morceaux de la bibliotheque du studio, puis ceux de l'evenement."""
    items = _tracks(config.MUSIC_DIR, "bib:", "bibliothèque")
    if event_dir:
        items += _tracks(os.path.join(event_dir, EVENT_AUDIO), "evt:", "événement")
    return items


def resolve(event_dir: str, music_id: str) -> str:
    """Chemin d'un morceau designe par son id ; refuse tout ce qui sortirait de son dossier."""
    prefix, _, rel = (music_id or "").partition(":")
    base = {"bib": config.MUSIC_DIR, "evt": os.path.join(event_dir, EVENT_AUDIO)}.get(prefix)
    path = os.path.realpath(os.path.join(base, rel)) if base and rel else ""
    if (not path or not tools.is_within(os.path.realpath(base), path) or not os.path.isfile(path)
            or os.path.splitext(path)[1].lower() not in MUSIC_EXT):
        raise MusicError("Musique introuvable : %s" % music_id)
    return path


# --------------------------------------------------------------------------
# Depart : la ou le morceau prend de l'energie
# --------------------------------------------------------------------------

def loudness(path: str) -> list:
    """Sonie momentanee (LUFS, fenetre de 0,4 s) toutes les 0,1 s : [(t, M)]."""
    out = tools.run([config.ffmpeg_bin(), "-hide_banner", "-nostats", "-v", "error", "-nostdin", "-i", path,
                     "-vn", "-af", "aresample=48000,asetnsamples=4800,ebur128=metadata=1,"
                     "ametadata=mode=print:key=lavfi.r128.M:file=-", "-f", "null", "-"], timeout=600)
    series, at = [], None
    for line in out.splitlines():
        point = _POINT.search(line)
        if point:
            at = float(point.group(1))
            continue
        level = _LEVEL.search(line)
        if level and at is not None:
            value = level.group(1)
            series.append((at, -120.0 if value == "-inf" else float(value)))
            at = None
    return series


def start_offset(series: list, length: float) -> float:
    """Ou commencer le morceau pour une video de `length` secondes : le premier instant ou
    l'energie tient une seconde au niveau du corps du morceau (70e centile des passages
    non silencieux, moins 1 LU). Assez tot pour que le morceau couvre toute la video."""
    if not series:
        return 0.0
    duration = series[-1][0] + STEP
    latest = max(0.0, duration - length)
    if latest <= 0:
        return 0.0
    levels = sorted(m for _t, m in series if m > -70)
    if not levels:
        return 0.0
    target = levels[int(0.7 * (len(levels) - 1))] - 1.0
    span = int(round(1.0 / STEP))
    values = [m for _t, m in series]
    for i in range(len(values) - span + 1):
        window = values[i:i + span]
        if sum(window) / span >= target:
            return round(min(series[i][0], latest), 1)
    return 0.0


# --------------------------------------------------------------------------
# Mixage sur la video rendue par EffectCraft
# --------------------------------------------------------------------------

def _duration(path: str) -> float:
    out = tools.run([config.ffprobe_bin(), "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=nw=1:nk=1", path], timeout=60)
    return float(out.strip() or 0)


def _has_audio(path: str) -> bool:
    out = tools.run([config.ffprobe_bin(), "-v", "error", "-select_streams", "a", "-show_entries",
                     "stream=index", "-of", "csv=p=0", path], timeout=60)
    return bool(out.strip())


def soundtrack(video: str, music: str, parts: list = (), keep_sound: bool = False, fade: float = 0.4,
               log=None) -> dict:
    """Pose la musique sur la video (remplacee en place). parts : [(rush, debut, fin, ...)]
    dans l'ordre du montage, enchaines en fondu de `fade` s comme dans EffectCraft ; leur
    son est garde sous la musique si keep_sound."""
    log = log or (lambda _m: None)
    length = _duration(video)
    if length <= 0:
        raise MusicError("Vidéo sans durée : %s" % os.path.basename(video))
    series = loudness(music)
    music_length = series[-1][0] + STEP if series else 0.0
    offset = start_offset(series, length)
    if music_length - offset < length:
        log("Musique plus courte que la vidéo (%.0f s pour %.0f s) : elle s'arrête en fondu avant la fin"
            % (music_length, length))
    end = max(FADE_IN, min(length, music_length - offset))
    inputs = ["-i", video, "-i", music]
    chain = ["[1:a]atrim=start=%.2f:duration=%.2f,asetpts=PTS-STARTPTS,aresample=48000,"
             "aformat=channel_layouts=stereo,afade=t=in:d=%.2f,afade=t=out:st=%.2f:d=%.2f,volume=0.85[m]"
             % (offset, length, FADE_IN, max(0.0, end - FADE_OUT), FADE_OUT)]
    kept = 0
    if keep_sound and parts:
        labels = []
        for i, part in enumerate(parts):
            path, start, stop = part[0], float(part[1]), float(part[2])
            if _has_audio(path):
                inputs += ["-i", path]
                chain.append("[%d:a]atrim=start=%.3f:end=%.3f,asetpts=PTS-STARTPTS,aresample=48000,"
                             "aformat=channel_layouts=stereo[s%d]" % (len(inputs) // 2 - 1, start, stop, i))
                kept += 1
            else:
                chain.append("anullsrc=r=48000:cl=stereo,atrim=duration=%.3f[s%d]" % (stop - start, i))
            labels.append("[s%d]" % i)
        current = labels[0]
        for i, label in enumerate(labels[1:], 1):
            chain.append("%s%sacrossfade=d=%.3f[x%d]" % (current, label, fade, i))
            current = "[x%d]" % i
        # Le son des rushes declenche la baisse de la musique par sa bande des voix
        chain += ["%sapad,atrim=duration=%.2f,asplit[amb][key]" % (current, length),
                  "[key]highpass=f=300,lowpass=f=3400[voice]",
                  "[m][voice]sidechaincompress=threshold=0.04:ratio=8:attack=20:release=500[md]",
                  "[md][amb]amix=inputs=2:duration=first:normalize=0[mix]"]
        last = "[mix]"
    else:
        last = "[m]"
    chain.append("%sloudnorm=I=%d:TP=-1.5:LRA=11,aresample=48000[out]" % (last, LOUDNESS))
    tmp = video + ".musique.mp4"
    try:
        tools.run([config.ffmpeg_bin(), "-hide_banner", "-v", "error", "-nostdin", "-y"] + inputs +
                  ["-filter_complex", ";".join(chain), "-map", "0:v", "-map", "[out]", "-c:v", "copy",
                   "-c:a", "aac", "-b:a", "192k", "-t", "%.3f" % length, "-movflags", "+faststart", tmp],
                  timeout=1800)
        os.replace(tmp, video)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    log("Musique : %s, départ à %.1f s%s" % (os.path.basename(music), offset,
        ", son des rushes gardé (%d) sous la musique" % kept if keep_sound and parts else ""))
    return {"offset": offset, "kept_sound": kept, "duration": round(length, 2)}
