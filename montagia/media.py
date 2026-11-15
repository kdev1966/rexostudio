"""Analyse media : metadonnees, detection de silences, loudness."""
from __future__ import annotations

import json
import os
import re

from . import config, tools

_SILENCE_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SILENCE_END = re.compile(r"silence_end:\s*(-?[\d.]+)")


def probe(path: str) -> dict:
    """Retourne les metadonnees du media via ffprobe."""
    ffprobe = config.ffprobe_bin()
    if not ffprobe:
        raise RuntimeError("ffprobe introuvable (lancez scripts/install_models.sh)")
    cmd = [
        ffprobe, "-hide_banner", "-v", "error",
        "-print_format", "json",
        "-show_format", "-show_streams", path,
    ]
    out = tools.run(cmd, timeout=120)
    data = json.loads(out)
    fmt = data.get("format", {})
    streams = data.get("streams", [])

    info = {
        "path": path,
        "name": os.path.basename(path),
        "size": int(fmt.get("size") or 0),
        "duration": float(fmt.get("duration") or 0.0),
        "bit_rate": int(fmt.get("bit_rate") or 0),
        "format_name": fmt.get("format_name", ""),
        "has_video": False,
        "has_audio": False,
        "width": 0,
        "height": 0,
        "fps": 0.0,
        "vcodec": "",
        "acodec": "",
        "sample_rate": 0,
        "channels": 0,
    }

    for st in streams:
        kind = st.get("codec_type")
        if kind == "video" and not info["has_video"]:
            info["has_video"] = True
            info["width"] = int(st.get("width") or 0)
            info["height"] = int(st.get("height") or 0)
            info["vcodec"] = st.get("codec_name", "")
            info["fps"] = _parse_fps(st.get("avg_frame_rate") or st.get("r_frame_rate"))
        elif kind == "audio" and not info["has_audio"]:
            info["has_audio"] = True
            info["acodec"] = st.get("codec_name", "")
            info["sample_rate"] = int(st.get("sample_rate") or 0)
            info["channels"] = int(st.get("channels") or 0)

    if not info["duration"] and info["has_video"]:
        info["duration"] = _duration_fallback(path)
    return info


def _parse_fps(value: str) -> float:
    try:
        if not value or "/" not in value:
            return float(value or 0)
        num, den = value.split("/")
        den_f = float(den)
        return float(num) / den_f if den_f else 0.0
    except (TypeError, ValueError):
        return 0.0


def _duration_fallback(path: str) -> float:
    ffprobe = config.ffprobe_bin()
    cmd = [ffprobe, "-hide_banner", "-v", "error", "-show_entries",
           "format=duration", "-of", "csv=p=0", path]
    try:
        return float(tools.run(cmd, timeout=60).strip())
    except (ValueError, tools.CommandError):
        return 0.0


# --------------------------------------------------------------------------
# Detection de silences
# --------------------------------------------------------------------------

def detect_silence(path: str, noise_db: float = None, min_dur: float = None,
                   on_progress=None) -> list:
    """Detecte les silences avec le filtre silencedetect de ffmpeg.

    Retourne une liste de dicts {"start": float, "end": float, "duration": float}.
    Analyse uniquement l'audio : tres rapide, pas de re-encodage.
    """
    ffmpeg = config.ffmpeg_bin()
    if not ffmpeg:
        raise RuntimeError("ffmpeg introuvable")
    noise_db = config.SILENCE_NOISE_DB if noise_db is None else noise_db
    min_dur = config.SILENCE_MIN_DUR if min_dur is None else min_dur

    cmd = [
        ffmpeg, "-hide_banner", "-nostdin", "-i", path,
        "-vn", "-map", "0:a:0",        # audio seul : 24x plus rapide (mesure)
        "-af", "silencedetect=noise=%sdB:d=%s" % (noise_db, min_dur),
        "-f", "null", "-",
    ]
    proc_out = tools.run_streaming(cmd, on_line=None, timeout=3600)

    silences = []
    pending_start = None
    for line in proc_out.splitlines():
        m = _SILENCE_START.search(line)
        if m:
            pending_start = max(0.0, float(m.group(1)))
            continue
        m = _SILENCE_END.search(line)
        if m and pending_start is not None:
            end = float(m.group(1))
            silences.append({
                "start": round(pending_start, 3),
                "end": round(end, 3),
                "duration": round(end - pending_start, 3),
            })
            pending_start = None
    if pending_start is not None and on_progress:
        on_progress("Silence en cours a la fin du media")

    silences.sort(key=lambda s: s["start"])
    return silences


def speech_segments(duration: float, silences: list, pad: float = None) -> list:
    """Deduit les segments de parole (a garder) a partir des silences detectes."""
    pad = config.SILENCE_PAD if pad is None else pad
    kept = []
    cursor = 0.0
    for sil in silences:
        start = max(0.0, sil["start"] - pad)
        end = min(duration, sil["end"] + pad)
        if start - cursor > 0.12:
            kept.append({"start": round(cursor, 3), "end": round(start, 3)})
        cursor = max(cursor, end)
    if duration - cursor > 0.12:
        kept.append({"start": round(cursor, 3), "end": round(duration, 3)})
    return kept


# --------------------------------------------------------------------------
# Changements de plan (videos sans parole)
# --------------------------------------------------------------------------

_SCENE = re.compile(r"lavfi\.scd\.score:\s*([\d.]+),\s*lavfi\.scd\.time:\s*([\d.]+)")

SCENE_THRESHOLD = 10.0      # score scdet (0-100) : 10 = coupe franche


def detect_scenes(path: str, threshold: float = SCENE_THRESHOLD,
                  min_gap: float = 0.5) -> list:
    """Instants des changements de plan (secondes), via le filtre scdet.

    L'image est reduite a 320 px de large avant l'analyse : la detection
    reste fiable et le calcul est bien plus leger. Deux coupes a moins de
    min_gap secondes (flash, fondu) ne comptent que pour une.
    """
    ffmpeg = config.ffmpeg_bin()
    if not ffmpeg:
        raise RuntimeError("ffmpeg introuvable")
    cmd = [
        ffmpeg, "-hide_banner", "-nostdin", "-i", path,
        "-an", "-sn", "-dn",
        "-vf", "scale=320:-2,scdet=threshold=%s" % threshold,
        "-f", "null", "-",
    ]
    out = tools.run_streaming(cmd, on_line=None, timeout=3600)
    cuts = []
    for line in out.splitlines():
        m = _SCENE.search(line)
        if not m:
            continue
        t = round(float(m.group(2)), 3)
        if not cuts or t - cuts[-1] >= min_gap:
            cuts.append(t)
    return cuts


# --------------------------------------------------------------------------
# Loudness (normalisation EBU R128)
# --------------------------------------------------------------------------

def loudness(path: str) -> dict:
    """Mesure la loudness EBU R128 (integrated, true peak, LRA)."""
    ffmpeg = config.ffmpeg_bin()
    cmd = [
        ffmpeg, "-hide_banner", "-nostdin", "-i", path,
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
        "-f", "null", "-",
    ]
    try:
        out = tools.run_streaming(cmd, on_line=None, timeout=1800)
    except tools.CommandError:
        return {}
    match = re.search(r"\{[^{}]*\}", out, re.S)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return {}
    return {
        "integrated": data.get("input_i", ""),
        "true_peak": data.get("input_tp", ""),
        "lra": data.get("input_lra", ""),
    }


def has_audio(path: str) -> bool:
    try:
        return probe(path)["has_audio"]
    except Exception:
        return False
