"""Orchestration : chaque etape du workflow IA, de bout en bout."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile

from . import ai, config, cutting, edit, filmcraft, media, prompts, transcribe

AI_CACHE_DIR = os.path.join(config.CACHE_DIR, "ai")


# --------------------------------------------------------------------------
# Cache des resultats IA (inutile de recalculer la meme chose)
# --------------------------------------------------------------------------

def _cache_key(task: str, payload: dict) -> str:
    # La version des prompts entre dans la cle : changer un prompt invalide
    # les résultats mis en cache (sinon on ressortait l'ancienne reponse).
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(
        ("%s|%s|%s" % (task, prompts.PROMPT_VERSION, blob)).encode("utf-8")).hexdigest()


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
    """Silences + changements de plan + metadonnees + segments de parole."""
    job.set_progress(0.05, "Analyse du media")
    info = media.probe(path)
    job.add_log("Media : %s | %dx%d | %.1f fps | %s | %s"
                % (os.path.basename(path), info["width"], info["height"],
                   info["fps"], info["vcodec"], info["acodec"]))
    silences = []
    if info.get("has_audio"):
        job.set_progress(0.2, "Detection des silences")
        silences = media.detect_silence(path, noise_db, min_dur)
        job.add_log("Silences detectes : %d (total %.1f s)"
                    % (len(silences), sum(s["duration"] for s in silences)))
    scenes = []
    if info.get("has_video"):
        job.set_progress(0.45, "Detection des changements de plan")
        scenes = media.detect_scenes(path)
        job.add_log("Changements de plan : %d" % len(scenes))
    segments = media.speech_segments(info["duration"], silences)
    job.set_progress(1.0, "Analyse terminee")
    return {"info": info, "silences": silences, "speech_segments": segments,
            "scenes": scenes}


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

# Une video est consideree "peu parlee" quand la parole couvre moins de la
# moitie de sa duree : on propose alors aussi les plans sans parole a l'IA.
# Les videos parlees (vlog, tuto, interview) gardent exactement le
# comportement precedent : seuls les segments de parole sont candidats.
VISUAL_SPEECH_COVERAGE = 0.5
VISUAL_MIN_SECONDS = 1.0       # plus court : pas un plan exploitable
VISUAL_MAX_SECONDS = 8.0       # plan plus long : decoupe en morceaux


def build_candidates(segments: list, min_duration: float = 1.5,
                     max_count: int = prompts.MAX_CANDIDATES,
                     duration: float = 0.0, scenes: list = None,
                     words: list = None) -> list:
    """Candidats au plan de coupe, numerotes S1, S2... dans l'ordre.

    Avec les mots (transcription recente) : une proposition par candidat et
    les regles sures deja appliquees (cutting.speech_candidates : champ
    "rule"). Sans les mots (ancien projet) : segments whisper, les trop
    courts fusionnes avec le suivant.

    Video peu parlee (musique, plans de coupe, sans voix) : les intervalles
    sans parole sont decoupes aux changements de plan (scenes) et proposes
    comme candidats "visuels", pour que l'IA puisse aussi les monter.
    """
    if words:
        merged = cutting.speech_candidates(words)
    else:
        merged = []
        for seg in segments or []:
            seg_duration = float(seg["end"]) - float(seg["start"])
            if seg_duration < min_duration and merged:
                merged[-1]["end"] = seg["end"]
                merged[-1]["text"] = (merged[-1]["text"] + " " + seg["text"]).strip()
            else:
                merged.append({"start": float(seg["start"]), "end": float(seg["end"]),
                               "text": seg.get("text", ""), "kind": "parole",
                               "rule": None})
        if len(merged) > max_count:
            merged = _compact(merged, max_count)

    speech = sum(m["end"] - m["start"] for m in merged if m.get("rule") != "hesitation")
    if duration and speech < VISUAL_SPEECH_COVERAGE * duration:
        merged = sorted(merged + visual_candidates(merged, duration, scenes or []),
                        key=lambda m: m["start"])

    out = []
    for idx, seg in enumerate(merged, start=1):
        out.append({
            "id": "S%d" % idx,
            "start": round(seg["start"], 3),
            "end": round(seg["end"], 3),
            "text": seg["text"],
            "kind": seg["kind"],
            "rule": seg.get("rule"),
            "duration": round(seg["end"] - seg["start"], 3),
        })
    return out


def _compact(merged: list, max_count: int) -> list:
    """Regroupe des segments voisins pour ne pas depasser max_count."""
    step = len(merged) / float(max_count)
    compact = []
    for i in range(max_count):
        lo = int(i * step)
        hi = int((i + 1) * step) or lo + 1
        chunk = merged[lo:hi]
        if chunk:
            compact.append({"start": chunk[0]["start"], "end": chunk[-1]["end"],
                            "text": " ".join(c["text"] for c in chunk),
                            "kind": "parole", "rule": None})
    return compact


def visual_candidates(speech: list, duration: float, scenes: list) -> list:
    """Plans sans parole : les trous entre segments de parole, coupes aux
    changements de plan puis en morceaux de VISUAL_MAX_SECONDS au plus."""
    gaps, cursor = [], 0.0
    for seg in sorted(speech, key=lambda s: s["start"]):
        if seg["start"] - cursor >= VISUAL_MIN_SECONDS:
            gaps.append((cursor, seg["start"]))
        cursor = max(cursor, seg["end"])
    if duration - cursor >= VISUAL_MIN_SECONDS:
        gaps.append((cursor, duration))

    out = []
    for gap_start, gap_end in gaps:
        bounds = [gap_start] + [t for t in sorted(scenes) if gap_start < t < gap_end] + [gap_end]
        for shot_start, shot_end in zip(bounds, bounds[1:]):
            pieces = max(1, int(-(-(shot_end - shot_start) // VISUAL_MAX_SECONDS)))
            size = (shot_end - shot_start) / pieces
            for k in range(pieces):
                a, b = shot_start + k * size, shot_start + (k + 1) * size
                if b - a >= VISUAL_MIN_SECONDS:
                    out.append({"start": a, "end": b, "text": "", "kind": "visuel"})
    return out


def resolve_selection(selection: list, candidates: list) -> list:
    """Recalcule les vrais timecodes a partir des identifiants renvoyes par l'IA."""
    by_id = {c["id"]: c for c in candidates}
    resolved = []
    seen = set()
    for item in selection or []:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("id", "")).strip().upper()
        cand = by_id.get(cid)
        # Le modele 3B repete parfois un identifiant : on ne le garde qu'une fois.
        if not cand or cid in seen:
            continue
        seen.add(cid)
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

CUT_BATCH = 40     # passages classes par appel (contexte borne a 4096 tokens)


def ai_cut_plan(job, candidates: list, duration: float, transcript: str = "",
                instruction: str = "", style: str = "") -> dict:
    """Plan de coupe : regles sures (deja dans candidates[i]["rule"]), puis
    l'IA classe chaque passage restant ; on garde contenu / introduction /
    conclusion / illustration (cutting.KEEP_TYPES).

    Le LLM ne donne jamais de temps : il classe des identifiants, et les
    timecodes viennent des candidats (calcules par le code).
    """
    if not candidates:
        raise RuntimeError("Aucun passage a monter : transcrivez d'abord la video.")
    for index, cand in enumerate(candidates):
        cand["_index"] = index
    decisions = {}
    for cand in candidates:
        if cand.get("rule"):
            decisions[cand["id"]] = {"type": cand["rule"], "by": "regle"}

    batches = [candidates[i:i + CUT_BATCH] for i in range(0, len(candidates), CUT_BATCH)]
    for number, batch in enumerate(batches, start=1):
        todo = [c["id"] for c in batch if c["id"] not in decisions]
        if not todo:
            continue
        job.set_progress(0.1 + 0.75 * (number - 1) / len(batches),
                         "Classement des passages par l'IA (%d/%d)" % (number, len(batches)))
        ruled = [(c["id"], cutting.RULE_LABELS.get(c["rule"], c["rule"]))
                 for c in batch if c.get("rule")]
        system = prompts.system_message(prompts.numbered_passages(batch), prompts.SYS_EDITOR)
        user = prompts.build_decision_prompt(todo, ruled, duration, instruction, style)
        payload = {"passages": [[c["id"], c["kind"], c.get("text", ""), c.get("rule")]
                                for c in batch],
                   "duration": duration, "instruction": instruction, "style": style,
                   "model": config.LLM_MODEL}

        def compute(system=system, user=user, todo=todo):
            # Le modele met le JSON en forme (espaces, retours a la ligne) :
            # ~25 tokens par passage. La limite n'est qu'un plafond, il
            # s'arrete de lui-meme : on la prend large.
            try:
                return ai.chat_json(system, user, prompts.SCHEMA_DECISIONS,
                                    temperature=0.1, num_predict=200 + 40 * len(todo))
            except ai.OllamaError as exc:
                salvaged = _salvage_decisions(exc.raw)
                if not salvaged:
                    raise
                job.add_log("Reponse de l'IA tronquee : %d decisions recuperees sur %d"
                            % (len(salvaged), len(todo)))
                return {"decisions": salvaged, "partial": True}

        result = cached_ai("cutplan", payload, compute)
        if result.get("partial"):
            # Pas de cache pour une reponse incomplete : on retentera la prochaine fois.
            _forget_cache("cutplan", payload)
        allowed = {c["id"]: c for c in batch if c["id"] in todo}
        for item in result.get("decisions") or []:
            cid = str((item or {}).get("id", "")).strip().upper()
            kind = str((item or {}).get("type", "")).strip()
            if cid not in allowed or kind not in prompts.CUT_TYPES or cid in decisions:
                continue
            if allowed[cid]["kind"] == "parole" and kind in ("illustration", "remplissage"):
                kind = "contenu"            # categories reservees aux plans sans parole
            elif allowed[cid]["kind"] == "visuel" and kind != "remplissage":
                # L'IA ne voit pas les images : elle ne coupe un plan visuel que
                # s'il est explicitement du remplissage (pas de "digression").
                kind = "illustration"
            decisions[cid] = {"type": kind, "by": "ia"}

    # Passage que l'IA n'a pas classe : garde (on ne coupe pas a l'aveugle).
    for cand in candidates:
        decisions.setdefault(cand["id"], {"type": "contenu", "by": "defaut"})
    keep = {cid: d["type"] in cutting.KEEP_TYPES for cid, d in decisions.items()}

    job.set_progress(0.9, "Application du plan de coupe")
    segments = cutting.merge_kept(candidates, keep)
    for cand in candidates:
        cand.pop("_index", None)
    if not segments:
        raise RuntimeError("Tous les passages ont ete coupes : precisez la consigne.")

    rationale = _cut_summary(candidates, decisions, keep, segments, duration)
    job.set_progress(1.0, "Plan de coupe pret")
    return {
        "segments": segments,
        "rationale": rationale,
        "style": style,
        "decisions": [dict(id=c["id"], keep=keep[c["id"]], **decisions[c["id"]])
                      for c in candidates],
        "kept_duration": round(sum(s["end"] - s["start"] for s in segments), 2),
        "source_duration": round(duration, 2),
    }


_DECISION_RE = re.compile(r'"id"\s*:\s*"(S\d+)"\s*,\s*"type"\s*:\s*"([a-z_]+)"')


def _salvage_decisions(raw: str) -> list:
    """Decisions completes d'une reponse JSON tronquee (plafond de tokens)."""
    return [{"id": cid, "type": kind} for cid, kind in _DECISION_RE.findall(raw or "")]


def _forget_cache(task: str, payload: dict) -> None:
    key = _cache_key(task, payload)
    try:
        os.remove(os.path.join(AI_CACHE_DIR, "%s_%s.json" % (task, key[:10])))
    except OSError:
        pass


def _cut_summary(candidates, decisions, keep, segments, duration) -> str:
    """Justification FACTUELLE du plan (calculee, pas redigee par l'IA, qui
    decrivait parfois l'inverse de ce qu'elle avait fait)."""
    kept = sum(s["end"] - s["start"] for s in segments)
    by_source = {"regle": {}, "ia": {}}
    for cand in candidates:
        d = decisions[cand["id"]]
        if not keep[cand["id"]] and d["by"] in by_source:
            counts = by_source[d["by"]]
            counts[d["type"]] = counts.get(d["type"], 0) + 1
    parts = []
    for source, label in (("regle", "regles"), ("ia", "IA")):
        if by_source[source]:
            parts.append("%s par %s" % (", ".join(
                "%d %s" % (n, t.replace("_", " "))
                for t, n in sorted(by_source[source].items())), label))
    text = "Garde %.1f s sur %.1f s." % (kept, duration)
    if parts:
        text += " Coupe : %s." % " ; ".join(parts)
    return text


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

        # system/user sont lies par defaut : sans cela la closure capturerait
        # la variable de boucle (reluee au tour suivant) et non sa valeur.
        def compute(system=system, user=user):
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

def prepare_plan(source: str, segments: list) -> list:
    """Plan de coupe normalise (tri, bornes, fusion des chevauchements)."""
    plan = edit.normalize_segments(segments, media.probe(source)["duration"])
    if not plan:
        raise RuntimeError("Plan de coupe vide : rien a exporter.")
    return plan


def render_video(job, source: str, segments: list, out_path: str, fmt: str = "16:9",
                 encoder: str = None, quality: str = "standard",
                 subtitles: str = "", burn_subtitles: bool = False,
                 focus_x: float = 0.5, normalize_audio: bool = False,
                 subtitle_segments: list = None, subtitle_words: list = None) -> dict:
    job.set_progress(0.02, "Preparation du rendu")
    # Plan normalise UNE fois : le rendu et les sous-titres recales doivent
    # utiliser exactement la meme timeline (sinon decalage des sous-titres
    # des qu'un segment est en double ou chevauche le precedent).
    segments = prepare_plan(source, segments)

    # Les sous-titres doivent suivre la timeline du montage, pas celle de la
    # source : on les regenere sur les timecodes re-calcules, dans un fichier
    # propre a ce rendu (deux rendus simultanes ne s'ecrasent plus).
    temp_srt = ""
    if burn_subtitles and (subtitle_words or subtitle_segments):
        remapped = _remap_subtitles(subtitle_segments, subtitle_words, segments)
        temp_srt = subtitles = _temp_srt(remapped, "rendu")
        job.add_log("Sous-titres recalcules sur la timeline du montage (%d lignes)"
                    % len(remapped))
    try:
        result = edit.export(
            source, segments, out_path, fmt=fmt, encoder=encoder, quality=quality,
            subtitles=subtitles, burn_subtitles=burn_subtitles, focus_x=focus_x,
            normalize_audio=normalize_audio,
            on_log=lambda m: job.add_log(m),
            on_progress=lambda v, s: job.set_progress(v, s))
    finally:
        _remove(temp_srt)
    job.set_progress(1.0, "Export termine")
    return result


def build_filmcraft_job(job, source: str, segments: list, out_path: str,
                        profile: str = "16:9", title: str = "Montage MontageIA",
                        notes: str = "", subtitle_segments: list = None,
                        subtitle_words: list = None) -> dict:
    """Envoie le plan de coupe dans FilmCraft et enregistre le projet .fcproj."""
    job.set_progress(0.05, "Preparation du projet FilmCraft")
    info = media.probe(source)
    segments = edit.normalize_segments(segments, info["duration"])
    fps = filmcraft.fps_fraction(info.get("fps") or 0)
    # Plan cale sur les images : c'est la timeline que FilmCraft construira,
    # et donc celle sur laquelle les sous-titres doivent etre recales.
    plan = filmcraft.frame_plan(segments, fps)
    if not plan:
        raise RuntimeError("Plan de coupe vide : rien a envoyer a FilmCraft.")

    temp_srt = ""
    if subtitle_words or subtitle_segments:
        remapped = _remap_subtitles(subtitle_segments, subtitle_words, plan)
        temp_srt = _temp_srt(remapped, "filmcraft")
        job.add_log("Sous-titres recales sur la timeline (%d lignes)" % len(remapped))
    try:
        job.set_progress(0.15, "Connexion a FilmCraft")
        client = filmcraft.connect(log=job.add_log)
        job.set_progress(0.3, "Construction de la timeline dans FilmCraft")
        result = filmcraft.build_project(
            client, source, plan, out_path, fps, info, profile=profile,
            srt_path=temp_srt, title=title, notes=notes, log=job.add_log)
    finally:
        _remove(temp_srt)

    job.set_progress(0.9, "Verification du projet enregistre")
    summary = filmcraft.read_project(result["path"])
    expected = round(sum(p["frames"] for p in plan) / float(fps), 3)
    seq = next((s for s in summary["sequences"] if s["clips"] == len(plan)), None)
    valid = bool(seq) and abs(seq["duration"] - expected) < 0.05
    message = ("Projet FilmCraft verifie : %d clips, %.2f s, %d sous-titres, %d marqueurs"
               % (seq["clips"], seq["duration"], seq["captions"], seq["markers"])
               if valid else "Le projet enregistre ne correspond pas au plan de coupe")
    job.add_log(message)
    job.set_progress(1.0, "Projet FilmCraft pret")
    return {"path": result["path"], "valid": valid, "message": message,
            "clips": result["clips"], "captions": result["captions"]}


def _remap_subtitles(lines: list, words: list, plan: list) -> list:
    """Sous-titres sur la timeline du montage : mot par mot quand on a les
    mots (texte exact de ce qui est garde), sinon ligne par ligne."""
    if words:
        return transcribe.remap_words(words, plan)
    return transcribe.remap_segments(lines or [], plan)


def _temp_srt(segments: list, prefix: str) -> str:
    """SRT temporaire unique (cache/subs), a supprimer apres usage."""
    srt_dir = os.path.join(config.CACHE_DIR, "subs")
    os.makedirs(srt_dir, exist_ok=True)
    fd, path = tempfile.mkstemp(prefix=prefix + "_", suffix=".srt", dir=srt_dir)
    os.close(fd)
    return transcribe.write_srt(segments, path)


def _remove(path: str) -> None:
    if path:
        try:
            os.remove(path)
        except OSError:
            pass


def save_subs(segments: list, path: str) -> str:
    return transcribe.write_srt(segments, path)
