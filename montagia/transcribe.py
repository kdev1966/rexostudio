"""Transcription locale via whisper.cpp (compile C, aucun depot Python)."""
from __future__ import annotations

import json
import os
import re

from . import config, tools

_SRT_TIME = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{1,3})")


def _srt_time_to_sec(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000.0


def _sec_to_srt_time(value: float) -> str:
    if value < 0:
        value = 0.0
    ms = int(round(value * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return "%02d:%02d:%02d,%03d" % (h, m, s, ms)


def parse_srt(text: str) -> list:
    """Parse un SRT en liste de segments {index, start, end, text}."""
    blocks = re.split(r"\n\s*\n", text.strip())
    segments = []
    for block in blocks:
        lines = [ln for ln in block.splitlines() if ln.strip() != ""]
        if len(lines) < 2:
            continue
        idx = 0
        if lines[0].strip().isdigit() and not "-->" in lines[0]:
            idx = int(lines[0].strip())
            lines = lines[1:]
        if not lines or "-->" not in lines[0]:
            continue
        m = _SRT_TIME.search(lines[0])
        if not m:
            continue
        start = _srt_time_to_sec(*m.group(1, 2, 3, 4))
        end = _srt_time_to_sec(*m.group(5, 6, 7, 8))
        body = " ".join(ln.strip() for ln in lines[1:]).strip()
        segments.append({
            "index": idx or (len(segments) + 1),
            "start": round(start, 3),
            "end": round(end, 3),
            "text": body,
        })
    return segments


def write_srt(segments: list, path: str) -> str:
    """Ecrit une liste de segments au format SRT."""
    out = []
    for i, seg in enumerate(segments, start=1):
        start = _sec_to_srt_time(float(seg.get("start", 0)))
        end = _sec_to_srt_time(float(seg.get("end", 0)))
        text = str(seg.get("text", "")).strip()
        out.append("%d\n%s --> %s\n%s\n" % (i, start, end, text))
    content = "\n".join(out)
    tools.ensure_parent(path)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path


def write_vtt(segments: list, path: str) -> str:
    out = ["WEBVTT", ""]
    for seg in segments:
        start = _sec_to_srt_time(float(seg.get("start", 0))).replace(",", ".")
        end = _sec_to_srt_time(float(seg.get("end", 0))).replace(",", ".")
        out.append("%s --> %s" % (start, end))
        out.append(str(seg.get("text", "")).strip())
        out.append("")
    content = "\n".join(out)
    tools.ensure_parent(path)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path


# --------------------------------------------------------------------------
# Extraction audio + appel whisper.cpp
# --------------------------------------------------------------------------

def extract_audio(source: str, dest: str) -> str:
    """Extrait l'audio en WAV 16 kHz mono (format attendu par whisper.cpp)."""
    ffmpeg = config.ffmpeg_bin()
    if not ffmpeg:
        raise RuntimeError("ffmpeg introuvable")
    tools.ensure_parent(dest)
    cmd = [
        ffmpeg, "-hide_banner", "-nostdin", "-y", "-i", source,
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", dest,
    ]
    tools.run(cmd, timeout=1800)
    return dest


def transcribe(source: str, model: str = None, language: str = "auto",
               workdir: str = None, on_log=None, speed: str = "standard") -> dict:
    """Transcrit un media et retourne les segments + chemins des fichiers.

    speed : "standard" (beam 5, meilleure qualite) ou "rapide" (beam 1).
    Retourne :
        {"segments": [...], "srt": path, "vtt": path, "txt": path,
         "json": path, "language": str, "model": str}
    """
    log = on_log or (lambda msg: None)

    model = model or config.best_whisper_model() or "base"
    model_path = config.whisper_model_path(model)
    if not model_path:
        raise RuntimeError(
            "Modele whisper '%s' introuvable. Lancez scripts/install_models.sh" % model)
    whisper = config.whisper_bin()
    if not whisper:
        raise RuntimeError("whisper-cli introuvable (voir scripts/install_models.sh)")

    workdir = workdir or config.CACHE_DIR
    os.makedirs(workdir, exist_ok=True)
    base = os.path.join(workdir, "transcription")
    audio = base + ".16k.wav"

    log("Extraction de la piste audio (16 kHz mono)...")
    extract_audio(source, audio)

    lang = config.WHISPER_LANGUAGES.get(language, language or "auto")
    cmd = [
        whisper,
        "-m", model_path,
        "-f", audio,
        "-l", lang,
        "-t", str(max(1, os.cpu_count() or 4)),
        "-osrt", "-ovtt", "-otxt", "-oj",
        "-of", base,
        "--no-prints",
    ]
    if speed == "rapide":
        cmd += ["-bs", "1", "-bo", "1"]
    vad = config.whisper_vad_model()
    if vad:
        cmd += ["--vad", "-vm", vad, "-vt", "0.5", "-vspd", "200", "-vsd", "300"]
        log("VAD actif (decoupe fine des segments de parole)")

    log("Transcription avec whisper.cpp (modele '%s')..." % model)
    proc = tools.run_streaming(cmd, on_line=lambda ln: log(ln) if ln.strip() else None,
                               timeout=7200)

    if os.path.exists(audio):
        os.remove(audio)

    srt_path = base + ".srt"
    json_path = base + ".json"
    txt_path = base + ".txt"

    segments = []
    detected_lang = lang
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            detected_lang = data.get("language", detected_lang)
            for item in data.get("transcription", []):
                offs = item.get("offsets") or {}
                ts = item.get("timestamps") or {}
                segments.append({
                    "start": round(float(offs.get("from", 0)) / 1000.0, 3),
                    "end": round(float(offs.get("to", 0)) / 1000.0, 3),
                    "text": (item.get("text") or "").strip(),
                    "start_ts": ts.get("from", ""),
                    "end_ts": ts.get("to", ""),
                })
        except (ValueError, OSError):
            segments = []

    if not segments and os.path.exists(srt_path):
        with open(srt_path, "r", encoding="utf-8") as fh:
            segments = parse_srt(fh.read())

    # Nettoyage des segments：[blanc], [MUSIQUE]... et recalage des index
    clean = []
    for seg in segments:
        text = seg.get("text", "").strip()
        if not text:
            continue
        clean.append({
            "index": len(clean) + 1,
            "start": seg["start"],
            "end": seg["end"],
            "text": text,
        })

    write_srt(clean, srt_path)
    write_vtt(clean, base + ".vtt")

    text = "\n".join(s["text"] for s in clean)
    if not os.path.exists(txt_path):
        with open(txt_path, "w", encoding="utf-8") as fh:
            fh.write(text)

    log("Transcription terminee : %d segments" % len(clean))
    return {
        "segments": clean,
        "srt": srt_path,
        "vtt": base + ".vtt",
        "txt": txt_path,
        "json": json_path,
        "language": detected_lang,
        "model": model,
        "chars": len(text),
    }


def transcript_text(segments: list, max_chars: int = 0) -> str:
    """Texte continu de la transcription, tronque si besoin."""
    text = " ".join(s.get("text", "") for s in segments).strip()
    if max_chars and len(text) > max_chars:
        text = text[:max_chars] + " ..."
    return text


# --------------------------------------------------------------------------
# Remappage de timeline
# --------------------------------------------------------------------------

def remap_segments(segments: list, plan: list) -> list:
    """Reconvertit des timecodes source vers la timeline du montage.

    Indispensable : apres une coupe, les sous-titres de la source ne sont
    plus alignes sur la video exportee. On les recale segment par segment.
    """
    if not plan:
        return [dict(s) for s in segments]

    out = []
    offset = 0.0
    for cut in plan:
        cut_start = float(cut["start"])
        cut_end = float(cut["end"])
        for seg in segments:
            start = float(seg.get("start", 0))
            end = float(seg.get("end", 0))
            if end <= cut_start or start >= cut_end:
                continue
            new_start = offset + max(0.0, start - cut_start)
            new_end = offset + max(0.0, min(end, cut_end) - cut_start)
            if new_end - new_start < 0.05:
                continue
            out.append({
                "index": len(out) + 1,
                "start": round(new_start, 3),
                "end": round(new_end, 3),
                "text": seg.get("text", ""),
            })
        offset += cut_end - cut_start
    return out
