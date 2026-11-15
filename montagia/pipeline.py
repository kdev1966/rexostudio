"""Orchestration : chaque etape du workflow IA, de bout en bout."""
from __future__ import annotations

import hashlib
import json
import os
import time

from . import ai, config, edit, kdenlive, media, prompts, tools, transcribe

AI_CACHE_DIR = os.path.join(config.CACHE_DIR, "ai")


# --------------------------------------------------------------------------
# Cache des resultats IA (inutile de recalculer la meme chose)
# --------------------------------------------------------------------------

def _cache_key(task: str, payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(("%s|%s" % (task, blob)).encode("utf-8")).hexdigest()


def cached_ai(task: str, payload: dict, compute):
    """Retourne le resultat en cache ou le calcule puis le stocke."""
    os.makedirs(AI_CACHE_DIR, exist_ok=True)
    key = _cache_key(task, payload)
    path = os.path.join(AI_CACHE_DIR, "%s_%s.json" % (task, key[:10]))
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (ValueError, OSError):
            pass
    result = compute()
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=1)
    except OSError:
        pass
    return result


# --------------------------------------------------------------------------
# Etape 1 : analyse du media
# --------------------------------------------------------------------------

def analyze_media(job, path: str, noise_db: float = None,
                  min_dur: float = None) -> dict:
    """Silence + metadonnees + segments de parole."""
    job.set_progress(0.05, "Analyse du media")
    info = media.probe(path)
    job.add_log("Media : %s | %dx%d | %.1f fps | %s | %s"
                % (os.path.basename(path), info["width"], info["height"],
                   info["fps"], info["vcodec"], info["acodec"]))
    job.set_progress(0.25, "Detection des silences")
    silences = media.detect_silence(path, noise_db, min_dur)
    job.add_log("Silences detectes : %d (total %.1f s)"
                % (len(silences), sum(s["duration"] for s in silences)))
    segments = media.speech_segments(info["duration"], silences)
    job.set_progress(1.0, "Analyse terminee")
    return {"info": info, "silences": silences, "speech_segments": segments}


# --------------------------------------------------------------------------
# Etape 2 : transcription
# --------------------------------------------------------------------------

def transcribe_media(job, path: str, model: str = None, language: str = "auto") -> dict:
    job.set_progress(0.05, "Extraction audio")
    result = transcribe.transcribe(
        path, model=model, language=language,
        workdir=os.path.join(config.CACHE_DIR, "audio"),
        on_log=lambda m: job.add_log(m))
    job.set_progress(1.0, "Transcription terminee")
    return result


# --------------------------------------------------------------------------
# Candidats au plan de coupe
# --------------------------------------------------------------------------

def build_candidates(segments: list, min_duration: float = 1.5,
                     max_count: int = prompts.MAX_CANDIDATES) -> list:
    """Transforme les segments de transcription en candidats numerotes S1, S2...

    Les segments trop courts sont fusionnes avec le suivant : moins de candidats
    = prompt plus court = reponse plus rapide et plus fiable.
    """
    if not segments:
        return []
    merged = []
    for seg in segments:
        duration = float(seg["end"]) - float(seg["start"])
        if duration < min_duration and merged:
            merged[-1]["end"] = seg["end"]
            merged[-1]["text"] = (merged[-1]["text"] + " " + seg["text"]).strip()
        else:
            merged.append({
                "start": float(seg["start"]),
                "end": float(seg["end"]),
                "text": seg.get("text", ""),
            })

    if len(merged) > max_count:
        step = len(merged) / float(max_count)
        compact = []
        for i in range(max_count):
            lo = int(i * step)
            hi = int((i + 1) * step) or lo + 1
            chunk = merged[lo:hi]
            if not chunk:
                continue
            compact.append({
                "start": chunk[0]["start"],
                "end": chunk[-1]["end"],
                "text": " ".join(c["text"] for c in chunk),
            })
        merged = compact

    out = []
    for idx, seg in enumerate(merged, start=1):
        out.append({
            "id": "S%d" % idx,
            "start": round(seg["start"], 3),
            "end": round(seg["end"], 3),
            "text": seg["text"],
            "duration": round(seg["end"] - seg["start"], 3),
        })
    return out


def resolve_selection(selection: list, candidates: list) -> list:
    """Recalcule les vrais timecodes a partir des identifiants renvoyes par l'IA."""
    by_id = {c["id"]: c for c in candidates}
    resolved = []
    for item in selection or []:
        cid = str(item.get("id", "")).strip().upper()
        cand = by_id.get(cid)
        if not cand:
            continue
        start = float(cand["start"])
        end = float(cand["end"])
        try:
            trim_start = float(item.get("trim_start") or 0)
        except (TypeError, ValueError):
            trim_start = 0
        try:
            trim_end = float(item.get("trim_end") or 0)
        except (TypeError, ValueError):
            trim_end = 0
        start = min(start + max(0.0, trim_start), end - 0.15)
        end = max(end - max(0.0, trim_end), start + 0.15)
        resolved.append({
            "start": round(start, 3),
            "end": round(end, 3),
            "id": cid,
            "reason": (item.get("reason") or "")[:200],
        })
    resolved.sort(key=lambda s: s["start"])
    return resolved


# --------------------------------------------------------------------------
# Etape 3 : taches IA
# --------------------------------------------------------------------------

def ai_cut_plan(job, candidates: list, duration: float, transcript: str,
                instruction: str = "", style: str = "") -> dict:
    job.set_progress(0.1, "Analyse IA du plan de coupe")
    system = prompts.system_message(transcript, prompts.SYS_EDITOR)
    user = prompts.build_cut_plan_prompt(candidates, duration, instruction, style)
    payload = {"candidates": [[c["id"], c["start"], c["end"]] for c in candidates],
               "duration": duration, "instruction": instruction, "style": style,
               "transcript": transcript[:prompts.CONTEXT_CHARS]}

    def compute():
        return ai.chat_json(system, user, prompts.SCHEMA_CUT_PLAN, temperature=0.25)

    result = cached_ai("cutplan", payload, compute)
    job.set_progress(0.85, "Application du plan de coupe")
    segments = resolve_selection(result.get("segments", []), candidates)
    if not segments:
        raise RuntimeError("L'IA n'a selectionne aucun segment valide.")
    job.set_progress(1.0, "Plan de coupe pret")
    return {
        "segments": segments,
        "rationale": result.get("rationale", ""),
        "style": result.get("style", style),
        "kept_duration": round(sum(s["end"] - s["start"] for s in segments), 2),
        "source_duration": round(duration, 2),
    }


def ai_trailer(job, candidates: list, duration: float, transcript: str,
               target_seconds: float = 30.0, instruction: str = "") -> dict:
    job.set_progress(0.1, "Recherche des meilleurs moments")
    system = prompts.system_message(transcript, prompts.SYS_EDITOR)
    user = prompts.build_trailer_prompt(candidates, duration, target_seconds, instruction)
    payload = {"candidates": [[c["id"], c["start"], c["end"]] for c in candidates],
               "target": target_seconds, "instruction": instruction,
               "transcript": transcript[:prompts.CONTEXT_CHARS]}

    def compute():
        return ai.chat_json(system, user, prompts.SCHEMA_TRAILER, temperature=0.35)

    result = cached_ai("trailer", payload, compute)
    job.set_progress(0.85, "Selection des moments")
    segments = resolve_selection(result.get("segments", []), candidates)
    segments.sort(key=lambda s: s["start"])
    job.set_progress(1.0, "Trailer selectionne")
    return {"segments": segments, "rationale": result.get("rationale", "")}


def ai_pack(job, transcript: str, segments: list, duration: float,
            tone: str = "", extra: str = "") -> dict:
    job.set_progress(0.1, "Redaction du pack de publication")
    system = prompts.system_message(transcript, prompts.SYS_MARKETING)
    user = prompts.build_pack_prompt(segments, duration, tone, extra)
    payload = {"tone": tone, "extra": extra, "duration": duration,
               "transcript": transcript[:prompts.CONTEXT_CHARS]}

    def compute():
        return ai.chat_json(system, user, prompts.SCHEMA_PACK, temperature=0.7)

    result = cached_ai("pack", payload, compute)
    job.set_progress(1.0, "Pack pret")
    return result


def ai_summary(job, transcript: str, duration: float) -> dict:
    job.set_progress(0.1, "Resume de la video")
    system = prompts.system_message(transcript, prompts.SYS_ANALYST)
    user = prompts.build_summary_prompt(duration)
    payload = {"duration": duration, "transcript": transcript[:prompts.CONTEXT_CHARS]}

    def compute():
        return ai.chat_json(system, user, prompts.SCHEMA_SUMMARY, temperature=0.3)

    result = cached_ai("summary", payload, compute)
    job.set_progress(1.0, "Resume pret")
    return result


def ai_fix_subtitles(job, segments: list, chunk_size: int = 25) -> dict:
    """Corrige les sous-titres par lots de 25 lignes (controle du contexte)."""
    if not segments:
        return {"segments": [], "fixed": 0}
    fixed = []
    total = len(segments)
    done = 0
    for start in range(0, total, chunk_size):
        chunk = segments[start:start + chunk_size]
        job.set_progress(0.1 + 0.8 * (start / float(total)),
                         "Correction des sous-titres (%d/%d)" % (start + 1, total))
        system = prompts.system_message("", prompts.SYS_SUBTITLES)
        user = prompts.build_subtitle_chunk_prompt(chunk)
        payload = {"lines": [[ln["index"], ln["text"]] for ln in chunk]}

        def compute():
            return ai.chat_json(system, user, prompts.SCHEMA_SUBTITLES, temperature=0.2)

        result = cached_ai("subs", payload, compute)
        by_index = {}
        for line in result.get("lines", []):
            try:
                by_index[int(line.get("index"))] = str(line.get("text", "")).strip()
            except (TypeError, ValueError):
                continue
        for seg in chunk:
            new_text = by_index.get(seg["index"])
            if new_text:
                fixed.append(dict(seg, text=new_text, corrected=new_text != seg["text"]))
            else:
                fixed.append(seg)
        done += len(chunk)
    job.set_progress(1.0, "Sous-titres corriges")
    return {"segments": fixed, "fixed": done}


def ai_chat(job, question: str, transcript: str, duration: float):
    """Chat en flux sur la transcription. Yield des fragments de texte."""
    system = prompts.system_message(transcript, prompts.SYS_ANALYST)
    user = prompts.build_chat_prompt(question, duration)
    buffer = []
    for piece in ai.chat_stream(system, user, temperature=0.6):
        buffer.append(piece)
        yield piece
    text = "".join(buffer)
    cached_ai("chat", {"q": question, "t": transcript[:prompts.CONTEXT_CHARS]},
              lambda: {"answer": text})


# --------------------------------------------------------------------------
# Etape 4 : rendu et export
# --------------------------------------------------------------------------

def render_video(job, source: str, segments: list, out_path: str, fmt: str = "16:9",
                 encoder: str = None, quality: str = "standard",
                 subtitles: str = "", burn_subtitles: bool = False,
                 focus_x: float = 0.5, normalize_audio: bool = False,
                 subtitle_segments: list = None) -> dict:
    job.set_progress(0.02, "Preparation du rendu")

    # Les sous-titres doivent suivre la timeline du montage, pas celle de la
    # source : on les regenere sur les timecodes re-calcules.
    if burn_subtitles and subtitle_segments:
        remapped = transcribe.remap_segments(subtitle_segments, segments)
        srt_dir = os.path.join(config.CACHE_DIR, "subs")
        os.makedirs(srt_dir, exist_ok=True)
        subtitles = transcribe.write_srt(
            remapped, os.path.join(srt_dir, "remapped.srt"))
        job.add_log("Sous-titres recalcules sur la timeline du montage (%d lignes)"
                    % len(remapped))

    result = edit.export(
        source, segments, out_path, fmt=fmt, encoder=encoder, quality=quality,
        subtitles=subtitles, burn_subtitles=burn_subtitles, focus_x=focus_x,
        normalize_audio=normalize_audio,
        on_log=lambda m: job.add_log(m),
        on_progress=lambda v, s: job.set_progress(v, s))
    job.set_progress(1.0, "Export termine")
    return result


def build_kdenlive_job(job, source: str, segments: list, out_path: str,
                        profile: str = "16:9", srt_path: str = "",
                        title: str = "Projet MontageIA", notes: str = "",
                        subtitle_segments: list = None) -> dict:
    job.set_progress(0.3, "Ecriture du projet Kdenlive")
    # La piste de sous-titres doit suivre la timeline du montage.
    if subtitle_segments:
        remapped = transcribe.remap_segments(subtitle_segments, segments)
        srt_dir = os.path.join(config.CACHE_DIR, "subs")
        os.makedirs(srt_dir, exist_ok=True)
        srt_path = transcribe.write_srt(
            remapped, os.path.join(srt_dir, "kdenlive_remapped.srt"))
        job.add_log("Piste de sous-titres recalee sur le montage (%d lignes)"
                    % len(remapped))
    path = kdenlive.build_project(source, segments, out_path, profile=profile,
                                  srt_path=srt_path, title=title, notes=notes)
    job.add_log("Projet : %s" % path)
    job.set_progress(0.7, "Validation par MLT")
    check = kdenlive.validate(path)
    job.add_log(check.get("message", ""))
    job.set_progress(1.0, "Projet Kdenlive pret")
    return {"path": path, "valid": check.get("ok", False),
            "message": check.get("message", "")}


def save_subs(segments: list, path: str) -> str:
    return transcribe.write_srt(segments, path)
