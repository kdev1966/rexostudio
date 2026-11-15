"""Serveur web local de MontageIA.

Stdlib uniquement (http.server + urllib) : aucune dependance a installer,
un demarrage instantane, et un fonctionnement stable sur Python 3.9 / macOS 12.
"""
from __future__ import annotations

import json
import mimetypes
import os
import posixpath
import queue
import subprocess
import sys
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from montagia import ai, config, filmcraft, media, pipeline, project, tools, transcribe  # noqa: E402
from montagia.jobs import MANAGER  # noqa: E402

MAX_BODY = config.MAX_UPLOAD_BYTES

_FINAL_STATUSES = ("done", "error", "cancelled")


def _candidates(proj) -> list:
    """Candidats au plan de coupe : parole, plus plans visuels si peu parle."""
    return pipeline.build_candidates(
        proj.transcript_segments, duration=(proj.info or {}).get("duration") or 0.0,
        scenes=proj.scenes, words=proj.transcript_words)


def _parse_range(header, size: int):
    """En-tete Range -> (debut, fin) inclus, None (fichier entier) ou "invalid".

    Gere une seule plage : "bytes=a-b", "bytes=a-" et "bytes=-n" (n derniers
    octets). Plusieurs plages ou une syntaxe inconnue -> fichier entier.
    """
    if not header or not header.startswith("bytes=") or "," in header:
        return None
    first, _, last = header[len("bytes="):].strip().partition("-")
    try:
        if first == "":
            if not last:
                return None
            length = int(last)
            if length <= 0:
                return "invalid"
            return max(0, size - length), size - 1
        start = int(first)
        end = int(last) if last else size - 1
    except ValueError:
        return None
    if start >= size or start > end:
        return "invalid"
    return start, min(end, size - 1)


def _final_event(summary: dict):
    """Evenement terminal equivalent a l'etat d'un job deja fini, sinon None."""
    status = summary.get("status")
    if status == "done":
        return {"type": "done", "result": summary.get("result"), "status": status}
    if status == "error":
        return {"type": "error", "error": summary.get("error"), "status": status}
    if status == "cancelled":
        return {"type": "status", "status": status}
    return None


class StudioHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"       # necessaire pour le streaming SSE
    disable_nagle_algorithm = True       # reponse plus reactive

    server_version = "MontageIA/1.0"

    # -- utilitaires --------------------------------------------------------
    def log_message(self, fmt, *args):  # noqa: A003
        if os.environ.get("MONTAGIA_VERBOSE"):
            sys.stderr.write("[server] " + (fmt % args) + "\n")

    def _send(self, code, body=b"", content_type="application/json; charset=utf-8",
              extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data, code=200):
        self._send(code, json.dumps(data, ensure_ascii=False))

    def _error(self, message, code=400):
        self._json({"error": str(message)}, code)

    def _request_allowed(self, route: str = "", post: bool = False) -> bool:
        """Refuse les requetes envoyees par un autre site (CSRF) ou via DNS rebinding.

        Le serveur ecoute sur 127.0.0.1, mais n'importe quelle page ouverte dans
        le navigateur peut y envoyer des requetes : sans ce controle, un site
        externe pouvait lancer /api/open ou remplir le disque via /api/upload.
        """
        port = self.server.server_address[1]
        hosts = {"127.0.0.1:%d" % port, "localhost:%d" % port}
        if (self.headers.get("Host") or "") not in hosts:
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin not in {"http://" + h for h in hosts}:
            return False
        if post and route != "/api/upload":
            # application/json impose une requete de pre-verification (CORS) au
            # navigateur : un formulaire d'un autre site ne peut pas l'envoyer.
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype != "application/json":
                return False
        return True

    def _reject(self):
        self.close_connection = True       # le corps eventuel n'a pas ete lu
        return self._error("Requete refusee (origine non autorisee)", 403)

    def _start_sse(self):
        """En-tetes d'un flux SSE. La connexion est fermee a la fin du flux :
        sans Content-Length, c'est le seul moyen pour le client de savoir que
        la reponse est terminee (sinon fetch/EventSource attendent sans fin)."""
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

    def _sse(self, data):
        self.wfile.write(("data: %s\n\n" % json.dumps(
            data, ensure_ascii=False)).encode("utf-8"))
        self.wfile.flush()

    def _body_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            return {}

    # -- routing -----------------------------------------------------------
    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        if not self._request_allowed(route):
            return self._reject()
        try:
            if route == "/":
                return self._serve_static("index.html")
            if route.startswith("/static/"):
                return self._serve_static(route[len("/static/"):])
            if route == "/api/status":
                return self._api_status()
            if route == "/api/projects":
                return self._json({"projects": project.STORE.list()})
            if route == "/api/project":
                pid = (query.get("id") or [""])[0]
                proj = project.STORE.get(pid)
                if not proj:
                    return self._error("Projet introuvable", 404)
                return self._json({"project": proj.to_dict()})
            if route.startswith("/api/jobs/"):
                rest = route[len("/api/jobs/"):]
                if rest.endswith("/events"):
                    return self._job_events(rest[:-len("/events")])
                return self._job_status(rest)
            if route == "/api/jobs":
                return self._json({"jobs": MANAGER.list()})
            if route == "/api/file":
                return self._serve_file(query)
            return self._error("Route inconnue : %s" % route, 404)
        except BrokenPipeError:
            return None
        except Exception as exc:           # noqa: BLE001
            self._error("%s" % exc, 500)

    def do_POST(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        if not self._request_allowed(route, post=True):
            return self._reject()
        try:
            if route == "/api/upload":
                return self._api_upload(query)
            if route == "/api/analyze":
                return self._api_analyze()
            if route == "/api/transcribe":
                return self._api_transcribe()
            if route == "/api/plan":
                return self._api_plan()
            if route == "/api/pack":
                return self._api_pack()
            if route == "/api/summary":
                return self._api_summary()
            if route == "/api/trailer":
                return self._api_trailer()
            if route == "/api/fixsubs":
                return self._api_fixsubs()
            if route == "/api/chat":
                return self._api_chat()
            if route == "/api/render":
                return self._api_render()
            if route == "/api/filmcraft":
                return self._api_filmcraft()
            if route == "/api/subs":
                return self._api_subs()
            if route == "/api/open":
                return self._api_open()
            return self._error("Route inconnue : %s" % route, 404)
        except BrokenPipeError:
            return None
        except Exception as exc:           # noqa: BLE001
            self._error("%s" % exc, 500)

    # -- statique ----------------------------------------------------------
    def _serve_static(self, name: str):
        name = posixpath.normpath(name).lstrip("/")
        if name in ("", "."):
            name = "index.html"
        path = os.path.join(config.STATIC_DIR, name)
        if not tools.is_within(config.STATIC_DIR, path) or not os.path.isfile(path):
            return self._error("Fichier introuvable", 404)
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as fh:
            data = fh.read()
        self._send(200, data, ctype, {"Cache-Control": "no-cache"})
        return None

    def _serve_file(self, query):
        target = (query.get("path") or [""])[0]
        if not target:
            return self._error("Chemin manquant")
        target = os.path.abspath(target)
        if not tools.is_within(config.WORKSPACE, target):
            return self._error("Acces refuse (hors espace de travail)", 403)
        if not os.path.isfile(target):
            return self._error("Fichier introuvable", 404)
        ctype = mimetypes.guess_type(target)[0] or "application/octet-stream"
        size = os.path.getsize(target)
        # Requetes partielles (Range) : indispensables pour se deplacer dans
        # une video, et Safari refuse de lire un <video> sans elles.
        span = _parse_range(self.headers.get("Range"), size)
        if span == "invalid":
            self.send_response(416)
            self.send_header("Content-Range", "bytes */%d" % size)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        start, end = span or (0, size - 1)
        self.send_response(206 if span else 200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(max(0, end - start + 1)))
        if span:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
        # Nom encode (RFC 5987) : aucun caractere du nom ne peut casser l'en-tete.
        self.send_header("Content-Disposition", "inline; filename*=UTF-8''%s"
                         % urllib.parse.quote(os.path.basename(target)))
        self.end_headers()
        if self.command == "HEAD" or size == 0:
            return None
        remaining = end - start + 1
        with open(target, "rb") as fh:
            fh.seek(start)
            while remaining > 0:
                chunk = fh.read(min(512 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)
        return None

    # -- API ---------------------------------------------------------------
    def _api_status(self):
        whisper_models = []
        for name in ("tiny", "base", "small", "medium"):
            path = config.whisper_model_path(name)
            if path:
                whisper_models.append({"name": name, "size": os.path.getsize(path)})
        info = {
            "ollama": ai.stats(),
            "ffmpeg": config.ffmpeg_bin(),
            "ffprobe": config.ffprobe_bin(),
            "whisper": config.whisper_bin(),
            "whisper_models": whisper_models,
            "vad_model": config.whisper_vad_model(),
            "filmcraft": filmcraft.installed(),
            "model": config.LLM_MODEL,
            "num_ctx": config.LLM_NUM_CTX,
            "workspace": config.WORKSPACE,
            "python": sys.version.split()[0],
            "cpu_count": os.cpu_count(),
            "encoders": list(config.ENCODERS),
            "jobs_waiting": MANAGER.waiting(),
        }
        return self._json(info)

    def _api_upload(self, query):
        name = (query.get("name") or ["video.mp4"])[0]
        name = os.path.basename(name)
        stem, ext = os.path.splitext(name)
        if ext.lower() not in config.VIDEO_EXTENSIONS:
            return self._error("Format non supporte : %s" % ext)
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return self._error("Aucun fichier recu")
        if length > MAX_BODY:
            self.close_connection = True        # corps non lu
            return self._error("Fichier trop volumineux (max %s)" % tools.human_size(MAX_BODY))

        safe = tools.safe_component(stem, "media") + ext.lower()
        target_dir = os.path.join(config.MEDIA_DIR, time.strftime("%Y%m%d"))
        os.makedirs(target_dir, exist_ok=True)
        # Nom reserve de facon unique : un 2e upload du meme nom le meme jour
        # ecrasait le fichier, parfois en cours d'utilisation par un projet.
        target = tools.unique_path(os.path.join(target_dir, safe))
        partial = target + ".part"

        written = 0
        try:
            with open(partial, "wb") as fh:
                while written < length:
                    chunk = self.rfile.read(min(1024 * 1024, length - written))
                    if not chunk:
                        break
                    fh.write(chunk)
                    written += len(chunk)
            if written < length:
                raise OSError("transfert interrompu")
            os.replace(partial, target)         # fichier complet ou rien
        except OSError:
            for leftover in (partial, target):
                try:
                    os.remove(leftover)
                except OSError:
                    pass
            self.close_connection = True
            return self._error("Transfert interrompu")

        try:
            info = media.probe(target)
        except Exception as exc:           # noqa: BLE001
            os.remove(target)
            return self._error("Fichier illisible : %s" % exc)

        proj = project.STORE.create(target, name)
        proj.info = info
        project.STORE.save(proj)
        return self._json({"project": proj.to_dict(),
                           "size": written,
                           "size_human": tools.human_size(written)})

    def _run_job(self, job, proj, func, heavy=True):
        """Lance un job de projet ; le projet est enregistre a la fin, que le
        job reussisse ou non (persistance apres redemarrage). Les jobs lourds
        passent un par un (voir JobManager)."""
        def wrapper(j):
            try:
                return func(j)
            finally:
                try:
                    project.STORE.save(proj)
                except OSError as exc:
                    j.add_log("Enregistrement du projet impossible : %s" % exc)
        MANAGER.run_async(job, wrapper, heavy=heavy)

    def _get_project(self, data):
        pid = data.get("project_id") or ""
        proj = project.STORE.get(pid)
        if not proj:
            raise ValueError("Projet introuvable (reexploitez le fichier)")
        return proj

    def _api_analyze(self):
        data = self._body_json()
        proj = self._get_project(data)
        job = MANAGER.create("analyze", "Analyse de %s" % proj.name)

        def run(j):
            result = pipeline.analyze_media(j, proj.path,
                                            data.get("noise_db"),
                                            data.get("min_dur"))
            proj.info = result["info"]
            proj.silences = result["silences"]
            proj.speech_segments = result["speech_segments"]
            proj.scenes = result["scenes"]
            if proj.transcript_segments:
                # Analyse faite apres la transcription : les plans detectes
                # completent les candidats (videos peu parlees).
                proj.candidates = _candidates(proj)
            return result

        self._run_job(job, proj, run)
        return self._json({"job_id": job.id})

    def _api_transcribe(self):
        data = self._body_json()
        proj = self._get_project(data)
        job = MANAGER.create("transcribe", "Transcription de %s" % proj.name)

        def run(j):
            result = pipeline.transcribe_media(
                j, proj.path, data.get("model") or None,
                data.get("language") or "auto")
            proj.transcript_segments = result["segments"]
            proj.transcript_words = result.get("words") or []
            proj.transcript = transcribe.transcript_text(result["segments"])
            proj.language = result.get("language", "")
            proj.model = result.get("model", "")
            proj.candidates = _candidates(proj)
            srt_path = os.path.join(
                config.EXPORTS_DIR,
                "%s.srt" % tools.safe_component(proj.name.rsplit(".", 1)[0], "sous-titres"))
            transcribe.write_srt(result["segments"], srt_path)
            proj.srt_path = srt_path
            j.add_log("Sous-titres : %s" % srt_path)
            return result

        self._run_job(job, proj, run)
        return self._json({"job_id": job.id})

    def _api_plan(self):
        data = self._body_json()
        proj = self._get_project(data)
        candidates = data.get("candidates")
        if not candidates and proj.transcript_words:
            # Reconstruits a chaque plan depuis les mots (deterministe, quasi
            # instantane) : un projet ancien profite du decoupage a jour.
            candidates = proj.candidates = _candidates(proj)
        candidates = candidates or proj.candidates or _candidates(proj)
        transcript = data.get("transcript") or proj.transcript
        duration = (proj.info or {}).get("duration") or 0.0
        job = MANAGER.create("plan", "Plan de coupe IA")

        def run(j):
            result = pipeline.ai_cut_plan(
                j, candidates, duration, transcript,
                data.get("instruction", ""), data.get("style", ""))
            proj.plan = result["segments"]
            proj.results["plan_rationale"] = result.get("rationale", "")
            proj.results["plan_decisions"] = result.get("decisions", [])
            proj.results["plan_style"] = result.get("style", "")
            return result

        self._run_job(job, proj, run)
        return self._json({"job_id": job.id})

    def _api_pack(self):
        data = self._body_json()
        proj = self._get_project(data)
        job = MANAGER.create("pack", "Pack de publication")

        def run(j):
            result = pipeline.ai_pack(
                j, proj.transcript, proj.candidates,
                (proj.info or {}).get("duration", 0),
                data.get("tone", ""), data.get("extra", ""))
            proj.results["pack"] = result
            return result

        self._run_job(job, proj, run)
        return self._json({"job_id": job.id})

    def _api_summary(self):
        data = self._body_json()
        proj = self._get_project(data)
        job = MANAGER.create("summary", "Resume de la video")

        def run(j):
            result = pipeline.ai_summary(
                j, proj.transcript, (proj.info or {}).get("duration", 0))
            proj.results["summary"] = result
            return result

        self._run_job(job, proj, run)
        return self._json({"job_id": job.id})

    def _api_trailer(self):
        data = self._body_json()
        proj = self._get_project(data)
        candidates = data.get("candidates") or proj.candidates
        if not candidates:
            candidates = _candidates(proj)
        job = MANAGER.create("trailer", "Recherche des meilleurs moments")

        def run(j):
            result = pipeline.ai_trailer(
                j, candidates, (proj.info or {}).get("duration", 0),
                proj.transcript, float(data.get("target_seconds", 30)),
                data.get("instruction", ""))
            proj.results["trailer"] = result
            return result

        self._run_job(job, proj, run)
        return self._json({"job_id": job.id})

    def _api_fixsubs(self):
        data = self._body_json()
        proj = self._get_project(data)
        job = MANAGER.create("fixsubs", "Correction des sous-titres")

        def run(j):
            result = pipeline.ai_fix_subtitles(j, proj.transcript_segments)
            proj.results["corrected_segments"] = result["segments"]
            srt_path = os.path.join(
                config.EXPORTS_DIR,
                "%s.srt" % tools.safe_component(proj.name.rsplit(".", 1)[0], "sous-titres"))
            transcribe.write_srt(result["segments"], srt_path)
            proj.srt_path = srt_path
            j.add_log("Sous-titres corriges : %s" % srt_path)
            return result

        self._run_job(job, proj, run)
        return self._json({"job_id": job.id})

    def _api_chat(self):
        """Chat en flux (SSE)."""
        data = self._body_json()
        proj = self._get_project(data)
        question = (data.get("question") or "").strip()
        if not question:
            return self._error("Question vide")
        self._start_sse()
        try:
            for piece in pipeline.ai_chat(None, question, proj.transcript,
                                         (proj.info or {}).get("duration", 0)):
                self._sse({"token": piece})
            self._sse({"done": True})
        except (BrokenPipeError, ConnectionResetError):
            return None
        except Exception as exc:           # noqa: BLE001
            self._sse({"error": str(exc)})
        return None

    def _api_render(self):
        data = self._body_json()
        proj = self._get_project(data)
        segments = data.get("segments") or proj.plan
        if not segments:
            return self._error("Aucun segment a rendre")
        fmt = data.get("format", "16:9")
        base = tools.safe_component(proj.name.rsplit(".", 1)[0], "montage")
        suffix = {"16:9": "16x9", "9:16": "9x16"}.get(fmt, fmt)
        out_name = "%s_%s.mp4" % (base, suffix)
        out_path = os.path.join(config.EXPORTS_DIR,
                                time.strftime("%Y%m%d-%H%M%S") + "_" + out_name)
        job = MANAGER.create("render", "Rendu %s" % fmt)
        subs = proj.results.get("corrected_segments") or proj.transcript_segments
        # Sous-titres corriges par l'IA : par ligne ; sinon mot par mot (exact).
        sub_words = None if proj.results.get("corrected_segments") else proj.transcript_words

        def run(j):
            result = pipeline.render_video(
                j, proj.path, segments, out_path, fmt=fmt,
                encoder=data.get("encoder"), quality=data.get("quality", "standard"),
                subtitles=data.get("srt") or proj.srt_path,
                burn_subtitles=bool(data.get("burn_subtitles")),
                focus_x=float(data.get("focus_x", 0.5)),
                normalize_audio=bool(data.get("normalize_audio")),
                subtitle_segments=subs, subtitle_words=sub_words)
            proj.add_export(out_path)
            return result

        self._run_job(job, proj, run)
        return self._json({"job_id": job.id, "output": out_path})

    def _api_filmcraft(self):
        data = self._body_json()
        proj = self._get_project(data)
        segments = data.get("segments") or proj.plan
        if not segments:
            return self._error("Aucun segment : rien a mettre dans le projet")
        base = tools.safe_component(proj.name.rsplit(".", 1)[0], "projet")
        out_path = os.path.join(config.EXPORTS_DIR, base + ".fcproj")
        job = MANAGER.create("filmcraft", "Projet FilmCraft")
        subs = proj.results.get("corrected_segments") or proj.transcript_segments
        # Sous-titres corriges par l'IA : par ligne ; sinon mot par mot (exact).
        sub_words = None if proj.results.get("corrected_segments") else proj.transcript_words
        notes = proj.results.get("plan_rationale", "")

        def run(j):
            result = pipeline.build_filmcraft_job(
                j, proj.path, segments, out_path,
                profile=data.get("profile", "16:9"),
                title=data.get("title") or ("%s - MontageIA" % proj.name),
                notes=notes, subtitle_segments=subs, subtitle_words=sub_words)
            proj.add_export(out_path)
            return result

        self._run_job(job, proj, run, heavy=False)   # pilotage : pas de calcul lourd
        return self._json({"job_id": job.id, "output": out_path})

    def _api_subs(self):
        """Enregistre le plan de coupe courant et regenere le SRT."""
        data = self._body_json()
        proj = self._get_project(data)
        if data.get("segments") is not None:
            proj.plan = data["segments"]
        if data.get("candidates") is not None:
            proj.candidates = data["candidates"]
        srt_source = proj.results.get("corrected_segments") or proj.transcript_segments
        if not srt_source:
            return self._error("Aucune transcription disponible")
        srt_path = os.path.join(config.EXPORTS_DIR,
                                "%s.srt" % tools.safe_component(proj.name.rsplit(".", 1)[0], "sous-titres"))
        transcribe.write_srt(srt_source, srt_path)
        proj.srt_path = srt_path
        project.STORE.save(proj)
        return self._json({"srt_path": srt_path})

    def _api_open(self):
        data = self._body_json()
        target = data.get("target") or "finder"
        path = os.path.abspath(data.get("path") or "")
        if not path:
            return self._error("Chemin manquant")
        # Uniquement l'espace de travail (is_within resout les liens et les "..").
        if not tools.is_within(config.WORKSPACE, path):
            return self._error("Acces refuse", 403)
        if target == "filmcraft":
            if not path.endswith(".fcproj") or not os.path.isfile(path):
                return self._error("Projet FilmCraft introuvable", 404)
            filmcraft.open_project(path)
            return self._json({"ok": True})
        if target == "reveal":
            subprocess.Popen(["open", "-R", path])
            return self._json({"ok": True})
        subprocess.Popen(["open", path])
        return self._json({"ok": True})

    # -- jobs --------------------------------------------------------------
    def _job_status(self, job_id):
        job = MANAGER.get(job_id)
        if not job:
            return self._error("Job introuvable", 404)
        return self._json(job.summary())

    def _job_events(self, job_id):
        job = MANAGER.get(job_id)
        if not job:
            return self._error("Job introuvable", 404)
        self._start_sse()
        q = job.subscribe()
        try:
            snapshot = job.summary()
            self._sse({"type": "snapshot", "job": snapshot})
            # Job deja termine avant l'abonnement (analyse d'une video courte :
            # ~0,3 s) : aucun evenement ne viendra plus, on envoie l'etat final.
            final = _final_event(snapshot)
            if final:
                self._sse(final)
                return None
            deadline = time.time() + 3600
            while time.time() < deadline:
                try:
                    event = q.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")     # garde la connexion ouverte
                    self.wfile.flush()
                    continue
                self._sse(event)
                # Un evenement "status" n'est terminal que s'il annule le job
                # ("running" en est un aussi, et ne doit pas couper le flux).
                if event.get("type") in ("done", "error") or (
                        event.get("type") == "status"
                        and event.get("status") in _FINAL_STATUSES):
                    break
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            job.unsubscribe(q)


def main():
    config.ensure_dirs()
    restored = project.STORE.enable_persistence(config.PROJECTS_DIR)
    status = ai.stats()
    print("")
    print("  \033[1m\033[38;5;208mMontageIA\033[0m  -  assistant de montage video IA (100% local)")
    print("  " + "-" * 62)
    print("  Interface   : http://%s:%d" % (config.HOST, config.PORT))
    print("  Modele IA   : %s %s" % (config.LLM_MODEL, "(pret)" if status.get("up") else "(HORS LIGNE)"))
    print("  ffmpeg      : %s" % (config.ffmpeg_bin() or "INTROUVABLE"))
    print("  whisper.cpp : %s" % (config.whisper_bin() or "INTROUVABLE"))
    print("  FilmCraft   : %s" % ("installe" if filmcraft.installed() else "absent"))
    print("  Espace      : %s" % config.WORKSPACE)
    print("  Projets     : %d repris du disque" % restored)
    print("  " + "-" * 62)
    print("  Ctrl+C pour arreter.")
    print("")
    if not status.get("up"):
        print("  [!] Ollama ne repond pas. Lancez 'ollama serve' dans un autre terminal.")
        print("")
    httpd = ThreadingHTTPServer((config.HOST, config.PORT), StudioHandler)
    httpd.daemon_threads = True
    # MONTAGIA_NO_BROWSER=1 : lancement a distance (SSH), pas de navigateur
    # ouvert sur l'ecran de la machine.
    if not os.environ.get("MONTAGIA_NO_BROWSER"):
        try:
            webbrowser.open("http://%s:%d" % (config.HOST, config.PORT))
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Arret.")
        httpd.shutdown()


if __name__ == "__main__":
    main()
