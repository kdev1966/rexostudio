"""Moteur de rendu : c'est ici que le montage est reellement execute.

Principe : le LLM ne fait AUCUN calcul. Il selectionne des segments ; c'est
ce module qui applique les decoupes, le recadrage, les sous-titres et
l'export, de maniere deterministe et verifiable.
"""
from __future__ import annotations

import os
import re

from . import config, media, tools

# --------------------------------------------------------------------------
# Encodage
# --------------------------------------------------------------------------

def encoder_args(encoder: str, quality: str = "standard") -> list:
    """Arguments d'encodage adaptes au materiel."""
    if encoder == "libx264":
        crf = {"haute": 18, "standard": 21, "rapide": 24}.get(quality, 21)
        preset = {"haute": "medium", "standard": "veryfast", "rapide": "ultrafast"}.get(quality, "veryfast")
        return ["-c:v", "libx264", "-preset", preset, "-crf", str(crf),
                "-pix_fmt", "yuv420p"]
    # VideoToolbox : encodeur materiel, ~12x temps reel sur cette machine.
    bitrate = {"haute": "8000k", "standard": "5000k", "rapide": "3000k"}.get(quality, "5000k")
    return ["-c:v", "h264_videotoolbox", "-b:v", bitrate,
            "-profile:v", "high", "-pix_fmt", "yuv420p",
            "-allow_sw", "1", "-realtime", "0"]


def audio_args() -> list:
    return ["-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2"]


# --------------------------------------------------------------------------
# Expressions de selection
# --------------------------------------------------------------------------

def _select_expr(segments: list) -> str:
    """Construit l'expression ffmpeg de selection des segments (frame-accurate)."""
    parts = []
    for seg in segments:
        start = max(0.0, float(seg["start"]))
        end = max(start + 0.04, float(seg["end"]))
        parts.append("gte(t\\,%s)*lt(t\\,%s)" % (_fmt(start), _fmt(end)))
    return "+".join(parts)


def _fmt(value: float) -> str:
    return ("%.3f" % value).rstrip("0").rstrip(".")


def normalize_segments(segments: list, duration: float = 0.0) -> list:
    """Nettoie le plan de coupe : ordre, bornes, chevauchements, minimums."""
    clean = []
    for seg in segments or []:
        try:
            start = float(seg.get("start", 0))
            end = float(seg.get("end", 0))
        except (TypeError, ValueError):
            continue
        if start < 0:
            start = 0.0
        if duration and end > duration:
            end = duration
        if end - start < 0.15:
            continue
        clean.append({"start": round(start, 3), "end": round(end, 3)})
    clean.sort(key=lambda s: s["start"])
    merged = []
    for seg in clean:
        if merged and seg["start"] < merged[-1]["end"] - 0.01:
            merged[-1]["end"] = max(merged[-1]["end"], seg["end"])
        else:
            merged.append(seg)
    return merged


def kept_duration(segments: list) -> float:
    return sum(s["end"] - s["start"] for s in segments)


# --------------------------------------------------------------------------
# Export principal
# --------------------------------------------------------------------------

def export(source: str, segments: list, out_path: str,
           fmt: str = "16:9", encoder: str = None, quality: str = "standard",
           subtitles: str = "", burn_subtitles: bool = False,
           focus_x: float = 0.5, normalize_audio: bool = False,
           on_log=None, on_progress=None) -> dict:
    """Applique le plan de coupe et exporte la video.

    fmt : "16:9" (horizontal) ou "9:16" (vertical Shorts/Reels).
    """
    log = on_log or (lambda _m: None)
    encoder = encoder or config.DEFAULT_ENCODER
    if encoder not in config.ENCODERS:
        encoder = "videotoolbox"

    info = media.probe(source)
    segments = normalize_segments(segments, info["duration"])
    tools.ensure_parent(out_path)

    if not segments:
        raise RuntimeError("Plan de coupe vide : rien a exporter.")

    kept = kept_duration(segments)
    total = info["duration"] or kept
    ratio = kept / total if total else 0.0

    # --- Raccourci : le plan ne retire presque rien et aucune transformation
    # n'est demandee -> simple copie, instantanee.
    needs_transform = (fmt == "9:16") or burn_subtitles or normalize_audio
    if ratio >= 0.995 and not needs_transform:
        log("Plan de coupe identique a la source -> copie directe (instantane).")
        import shutil
        shutil.copy2(source, out_path)
        if on_progress:
            on_progress(1.0, "Copie directe")
        return {"path": out_path, "duration": kept, "fast_path": True,
                "segments": len(segments)}

    ffmpeg = config.ffmpeg_bin()
    if not ffmpeg:
        raise RuntimeError("ffmpeg introuvable")

    # --- Chaine de filtres video
    vf = []
    expr = _select_expr(segments)
    vf.append("select='%s'" % expr)
    vf.append("setpts=N/FRAME_RATE/TB")

    if fmt == "9:16":
        vf.extend(_vertical_filters(info, focus_x))
        log("Recadrage vertical 9:16 (focus x=%.2f)" % focus_x)

    if burn_subtitles and subtitles and os.path.isfile(subtitles):
        vf.append(_subtitle_filter(subtitles))
        log("Sous-titres incrustes (libass)")

    vfilter = ",".join(vf)

    # --- Chaine de filtres audio
    af = []
    if info["has_audio"]:
        af.append("aselect='%s'" % expr)
        af.append("asetpts=N/SR/TB")
        if normalize_audio:
            af.append("loudnorm=I=-16:TP=-1.5:LRA=11")
            log("Normalisation audio EBU R128 (-16 LUFS)")
        afilter = ",".join(af)
    else:
        afilter = None

    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-i", source]
    cmd += ["-vf", vfilter]
    if afilter:
        cmd += ["-af", afilter]
    cmd += encoder_args(encoder, quality)
    cmd += audio_args()
    cmd += ["-fps_mode", "cfr", "-movflags", "+faststart", out_path]

    log("Rendu %s (%s, qualite %s)..." % (fmt, encoder, quality))
    log("Commande : %s" % " ".join(cmd[1:]))

    total_dur = max(kept, 0.1)

    def on_line(line):
        if not line:
            return
        m = re.search(r"time=(\d+):(\d+):(\d+\.\d+)", line)
        if m and on_progress:
            secs = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
            on_progress(min(0.99, secs / total_dur), "Encodage %.1f%%" % (100 * secs / total_dur))

    tools.run_streaming(cmd, on_line=on_line, timeout=14400)

    if on_progress:
        on_progress(1.0, "Rendu termine")
    return {"path": out_path, "duration": kept, "fast_path": False,
            "segments": len(segments), "encoder": encoder}


def _vertical_filters(info: dict, focus_x: float) -> list:
    """Filtres de recadrage vertical centres sur le sujet."""
    w = info.get("width") or 1920
    h = info.get("height") or 1080
    if not w or not h:
        return ["scale=1080:1920:flags=lanczos"]
    ratio = float(w) / float(h)
    if ratio > 9.0 / 16.0 + 0.001:
        # Source plus large que 9:16 -> on rogne les cotes puis on met a l'echelle.
        cw = int(h * 9 / 16 / 2) * 2
        x = int((w - cw) * max(0.0, min(1.0, focus_x)))
        return ["crop=%d:%d:%d:0" % (cw, h, x),
                "scale=1080:1920:flags=lanczos"]
    # Source deja verticale et plus etroite que 9:16 -> letterbox.
    return ["scale=1080:1920:force_original_aspect_ratio=decrease:flags=lanczos",
            "pad=1080:1920:(ow-iw)/2:(oh-ih)/2"]


def _subtitle_filter(srt_path: str) -> str:
    escaped = srt_path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    style = ("FontName=Helvetica,FontSize=22,PrimaryColour=&H00FFFFFF,"
             "OutlineColour=&H90000000,BorderStyle=1,Outline=2,Shadow=0,MarginV=42")
    return "subtitles='%s':force_style='%s'" % (escaped, style)


# --------------------------------------------------------------------------
# Operations annexes
# --------------------------------------------------------------------------

def extract_frame(source: str, timestamp: float, out_path: str) -> str:
    """Extrait une image JPEG (miniature / storyboard)."""
    ffmpeg = config.ffmpeg_bin()
    tools.ensure_parent(out_path)
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-ss", "%.3f" % timestamp,
           "-i", source, "-frames:v", "1", "-q:v", "3", out_path]
    tools.run(cmd, timeout=300)
    return out_path


def thumbnail(source: str, out_path: str, at_fraction: float = 0.15) -> str:
    info = media.probe(source)
    ts = max(0.0, (info.get("duration") or 1.0) * at_fraction)
    try:
        return extract_frame(source, ts, out_path)
    except Exception:
        return ""


def extract_audio_mp3(source: str, out_path: str, bitrate: str = "192k") -> str:
    ffmpeg = config.ffmpeg_bin()
    tools.ensure_parent(out_path)
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-i", source,
           "-vn", "-c:a", "libmp3lame", "-b:a", bitrate, out_path]
    tools.run(cmd, timeout=1800)
    return out_path


def merge_audio(source: str, extra_audio: str, out_path: str) -> str:
    """Mixe une piste audio additionnelle sous la piste originale."""
    ffmpeg = config.ffmpeg_bin()
    tools.ensure_parent(out_path)
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-i", source, "-i", extra_audio,
           "-filter_complex", "[0:a][1:a]amix=inputs=2:weights=1 0.3:duration=first[a]",
           "-map", "[a]", "-c:a", "aac", "-b:a", "160k", out_path]
    tools.run(cmd, timeout=1800)
    return out_path


def duration_of(path: str) -> float:
    try:
        return media.probe(path)["duration"]
    except Exception:
        return 0.0
