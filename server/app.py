"""Serveur web local de Rexo Studio.

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
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from montagia import (ai, animations, assistant, config, effectcraft, effects, events,  # noqa: E402
                      filmcraft, moments, photocraft, rushes, studio, tools, trash)
from montagia.jobs import MANAGER  # noqa: E402

_FINAL_STATUSES = ("done", "error", "cancelled")


class _Stage(object):
    """Progression d'une etape ramenee a sa part [low, high] du travail entier."""

    def __init__(self, job, low: float, high: float):
        self.job, self.low, self.high = job, low, high

    def set_progress(self, value: float, step: str = "") -> None:
        self.job.set_progress(self.low + (self.high - self.low) * value, step)

    def add_log(self, message: str) -> None:
        self.job.add_log(message)


def _do_import(job, event_dir: str, data: dict) -> dict:
    """Copie verifiee d'une carte, puis analyse des nouveaux rushes."""
    result = rushes.import_card(event_dir, str(data.get("source") or ""), _Stage(job, 0.0, 0.8))
    result["analysis"] = rushes.analyze(event_dir, _Stage(job, 0.8, 1.0))
    return result


def _do_moments(job, event_dir: str, data: dict) -> dict:
    count = min(12, max(2, int(data.get("count") or 6)))
    try:
        return moments.find(event_dir, job, count=count)
    except moments.MomentError as exc:
        raise RuntimeError(str(exc)) from exc


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


class StudioServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        # Le navigateur ouvre des connexions d'avance puis les abandonne :
        # "Connection reset by peer" n'est pas une panne, pas de trace.
        if isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError)):
            return
        super().handle_error(request, client_address)


class StudioHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"       # necessaire pour le streaming SSE
    disable_nagle_algorithm = True       # reponse plus reactive

    server_version = "RexoStudio/1.0"

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

    def _request_allowed(self, post: bool = False) -> bool:
        """Refuse les requetes envoyees par un autre site (CSRF) ou via DNS rebinding.

        Le serveur ecoute sur 127.0.0.1, mais n'importe quelle page ouverte dans
        le navigateur peut y envoyer des requetes : sans ce controle, un site
        externe pourrait ouvrir des dossiers, lancer des traitements ou mettre des
        fichiers a la Corbeille.
        """
        port = self.server.server_address[1]
        hosts = {"127.0.0.1:%d" % port, "localhost:%d" % port}
        if (self.headers.get("Host") or "") not in hosts:
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin not in {"http://" + h for h in hosts}:
            return False
        if post:
            # application/json impose une requete de pre-verification (CORS) au
            # navigateur : un formulaire d'un autre site ne peut pas l'envoyer.
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype != "application/json":
                return False
        return True

    def _reject(self):
        self.close_connection = True       # le corps eventuel n'a pas ete lu
        return self._error("Requête refusée (origine non autorisée)", 403)

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
        if not self._request_allowed():
            return self._reject()
        try:
            if route == "/":
                return self._serve_static("index.html")
            if route.startswith("/static/"):
                return self._serve_static(route[len("/static/"):])
            if route == "/api/status":
                return self._api_status()
            if route == "/api/events":
                return self._api_events()
            if route == "/api/events/detail":
                return self._api_event_detail(query)
            if route == "/api/sources":
                return self._json({"sources": rushes.list_sources()})
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
        if not self._request_allowed(post=True):
            return self._reject()
        try:
            if route == "/api/events/create":
                return self._api_event_create()
            if route == "/api/events/open":
                return self._api_event_open()
            if route == "/api/events/import":
                return self._event_job("import", "Import de carte", _do_import)
            if route == "/api/events/analyze":
                return self._event_job("rushes", "Analyse des rushes",
                                       lambda j, d, data: rushes.analyze(d, j, bool(data.get("force"))))
            if route == "/api/events/proxies":
                return self._event_job("proxies", "Proxies",
                                       lambda j, d, _data: rushes.make_proxies(d, j))
            if route == "/api/events/moments":
                return self._event_job("moments", "Moments forts", _do_moments)
            if route == "/api/events/filmcraft":
                return self._event_job("filmcraft", "Fin du montage dans FilmCraft",
                                       lambda j, d, _data: studio.finish_in_filmcraft(j, d))
            if route == "/api/events/photo":
                return self._api_event_photo()
            if route == "/api/events/keep":
                return self._api_event_keep()
            if route == "/api/events/delete":
                return self._api_event_delete()
            if route == "/api/events/trash":
                return self._api_event_trash()
            if route == "/api/events/effect":
                return self._api_event_effect()
            if route == "/api/events/effect/save":
                return self._api_event_effect_save()
            if route == "/api/events/photocraft":
                return self._api_event_photocraft()
            if route == "/api/events/assistant/plan":
                return self._api_assistant_plan()
            if route == "/api/events/assistant/run":
                return self._api_assistant_run()
            if route == "/api/events/assistant/save":
                return self._api_assistant_save()
            if route == "/api/events/studio":
                return self._api_studio_run()
            if route == "/api/quit":
                return self._api_quit()
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
        if not (tools.is_within(config.WORKSPACE, target)
                or tools.is_within(config.EVENTS_DIR, target)
                or tools.is_within(config.ANIMATIONS_DIR, target)):     # vignettes de la bibliotheque
            return self._error("Accès refusé (hors espace de travail)", 403)
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
            "llm": ai.stats(),
            "ffmpeg": config.ffmpeg_bin(),
            "ffprobe": config.ffprobe_bin(),
            "whisper": config.whisper_bin(),
            "whisper_models": whisper_models,
            "vad_model": config.whisper_vad_model(),
            "filmcraft": filmcraft.installed(),
            "photocraft": photocraft.installed(),
            "effects": effects.installed(),
            "effects_env": effects.env_installed(),
            "model": config.LLM_MODEL,
            "num_ctx": config.LLM_NUM_CTX,
            "workspace": config.WORKSPACE,
            "python": sys.version.split()[0],
            "cpu_count": os.cpu_count(),
            "encoders": list(config.ENCODERS),
            "jobs_waiting": MANAGER.waiting(),
        }
        return self._json(info)

    def _api_quit(self):
        """Decharge le modele IA puis arrete le serveur (bouton Quitter)."""
        if MANAGER.busy():
            return self._error("Un traitement est en cours : attendez la fin avant de quitter", 409)
        self._json({"ok": True})
        server = self.server

        def stop():
            ai.unload()
            server.shutdown()
        threading.Thread(target=stop, daemon=True).start()
        return None

    def _api_events(self):
        return self._json({
            "root": config.EVENTS_DIR,
            "types": [{"key": k, "label": v} for k, v in events.TYPES],
            "events": events.list_events(config.EVENTS_DIR),
        })

    def _api_event_create(self):
        data = self._body_json()
        try:
            event = events.create(config.EVENTS_DIR, data.get("type", ""), data.get("date", ""),
                                  data.get("names", ""), data.get("place", ""),
                                  data.get("notes", ""))
        except events.EventError as exc:
            return self._error(exc)
        return self._json(event)

    def _api_event_open(self):
        """Ouvre l'evenement (ou un de ses sous-dossiers) dans le Finder."""
        data = self._body_json()
        try:
            path = events.event_path(config.EVENTS_DIR, data.get("id", ""), data.get("sub", ""))
        except events.EventError as exc:
            return self._error(exc, 404)
        subprocess.Popen(["open", path])
        return self._json({"ok": True})

    @staticmethod
    def _event_dir(event_id) -> str:
        return events.event_path(config.EVENTS_DIR, str(event_id or ""))

    def _api_event_detail(self, query):
        event_id = (query.get("id") or [""])[0]
        try:
            event_dir = self._event_dir(event_id)
        except events.EventError as exc:
            return self._error(exc, 404)
        state = rushes.load_state(event_dir)
        return self._json({
            "event": events.summary(config.EVENTS_DIR, event_id),
            "clips": rushes.clip_list(event_dir),
            "photos": rushes.photo_list(event_dir),
            "cards": rushes.card_list(event_dir),
            "issues": rushes.ISSUES,
            "imports": state.get("imports", []),
            "effects": effects.catalog(),
            "studio": studio.status(),
            "moments": moments.load(event_dir),
            "renders": studio.renders(event_dir),
        })

    def _api_event_photo(self):
        """Photo choisie (ou non) pour le montage ; cadre autour des maries garde pour le clip."""
        data = self._body_json()
        try:
            event_dir = self._event_dir(data.get("id"))
            options = {}
            if "montage" in data:
                options["montage"] = bool(data["montage"])
            if "box" in data:
                options["box"] = data["box"] or None
            result = rushes.set_photo(event_dir, str(data.get("rel") or ""), **options)
        except events.EventError as exc:
            return self._error(exc, 404)
        except rushes.RushError as exc:
            return self._error(exc, 400)
        return self._json(result)

    def _event_photo(self, data):
        """(dossier de l'evenement, chemin verifie de la photo designee par rel)."""
        event_id = str(data.get("id") or "")
        event_dir = self._event_dir(event_id)
        return event_dir, events.item_path(config.EVENTS_DIR, event_id, str(data.get("rel") or ""))

    def _api_event_effect(self):
        """Apercu d'un effet photo (quelques secondes : calcule pendant la requete)."""
        data = self._body_json()
        try:
            event_dir, src = self._event_photo(data)
            box = data.get("box")
            result = effects.preview(event_dir, src, str(data.get("effect") or ""),
                                     box if box else None, enhance=bool(data.get("enhance")),
                                     couple=bool(data.get("couple")))
        except events.EventError as exc:
            return self._error(exc, 404)
        except effects.EffectError as exc:
            return self._error(exc, 409 if "en cours" in str(exc) else 400)
        return self._json(result)

    def _api_event_effect_save(self):
        data = self._body_json()
        try:
            event_dir, src = self._event_photo(data)
            rel = effects.save(event_dir, src, str(data.get("effect") or ""),
                               bool(data.get("framed")), bool(data.get("enhanced")),
                               bool(data.get("couple")))
        except events.EventError as exc:
            return self._error(exc, 404)
        except effects.EffectError as exc:
            return self._error(exc, 400)
        return self._json({"ok": True, "rel": rel, "path": os.path.join(event_dir, rel)})

    def _api_event_photocraft(self):
        """Ouvre dans PhotoCraft : apres un effet, un PSD a calques (photo originale +
        calque d'effet avec masque modifiable) ; sinon la photo ou le rendu designe."""
        data = self._body_json()
        try:
            event_dir, path = self._event_photo(data)
            if not os.path.isfile(path):
                return self._error("Fichier introuvable", 404)
            if data.get("assistant"):
                path = assistant.export_psd(event_dir, path)
            elif data.get("effect"):
                path = effects.export_psd(event_dir, path, str(data["effect"]),
                                          bool(data.get("framed")),
                                          enhanced=bool(data.get("enhanced")),
                                          couple=bool(data.get("couple")))
            photocraft.open_in_app(path)
        except events.EventError as exc:
            return self._error(exc, 404)
        except (effects.EffectError, assistant.AssistantError) as exc:
            return self._error(exc, 400)
        except photocraft.PhotoCraftError as exc:
            return self._error(exc, 500)
        return self._json({"ok": True, "rel": os.path.relpath(path, config.EVENTS_DIR)})

    # -- assistant a consigne (M5) --------------------------------------------
    def _api_assistant_plan(self):
        """Consigne -> plan d'etapes (IA locale, quelques secondes)."""
        data = self._body_json()
        try:
            return self._json(assistant.plan(str(data.get("text") or "")))
        except assistant.AssistantError as exc:
            return self._error(exc, 400)

    def _api_assistant_run(self):
        """Execute un plan sur une photo (apercu) ou sur toute la serie (en tache de fond)."""
        data = self._body_json()
        try:
            event_dir = self._event_dir(data.get("id"))
            steps = assistant.check_plan(data.get("steps") or [], data.get("boxes") or {})
            if data.get("enhance"):
                steps = assistant.with_enhance(steps)
            couple = bool(data.get("couple"))
            if data.get("all"):
                photos = [p["path"] for p in rushes.photo_list(event_dir)]
                if not photos:
                    return self._error("Aucune photo dans l'événement", 400)
                title = "Assistant : %d photos" % len(photos)
                func = lambda j: assistant.run_all(event_dir, photos, steps, j, couple)  # noqa: E731
            else:
                _event_dir, src = self._event_photo(data)
                title = "Assistant : %s" % os.path.basename(src)
                func = lambda j: assistant.run_photo(event_dir, src, steps, j, couple)  # noqa: E731
        except events.EventError as exc:
            return self._error(exc, 404)
        except assistant.AssistantError as exc:
            return self._error(exc, 400)
        job = MANAGER.create("assistant", title)
        MANAGER.run_async(job, func)
        return self._json({"job_id": job.id})

    def _api_assistant_save(self):
        data = self._body_json()
        try:
            event_dir, src = self._event_photo(data)
            rel = assistant.save(event_dir, src)
        except events.EventError as exc:
            return self._error(exc, 404)
        except assistant.AssistantError as exc:
            return self._error(exc, 400)
        return self._json({"ok": True, "rel": rel, "path": os.path.join(event_dir, rel)})

    # -- chaine de production (Rexo + bibliotheque d'animations + EffectCraft) ----
    def _api_studio_run(self):
        """Recette de la chaine de production, en tache de fond (minutes) :
        clip-drone (une photo), generique (moments forts des rushes), detour-video et
        sous-titres (un rush)."""
        data = self._body_json()
        recipe = str(data.get("recipe") or "")
        if recipe not in studio.RECIPES:
            return self._error("Recette inconnue : %s" % recipe, 400)
        try:
            event_dir = self._event_dir(data.get("id"))
            fiche = events.summary(config.EVENTS_DIR, os.path.basename(event_dir))
            title = fiche.get("names", "") if data.get("title") is None else str(data["title"])
            subtitle = (studio.french_date(fiche.get("date", "")) if data.get("subtitle") is None
                        else str(data["subtitle"]))
            to_fc = data.get("filmcraft") is not False
            title_model = str(data.get("title_model") or effectcraft.DEFAULT_TITLE)
            if title_model != effectcraft.DEFAULT_TITLE and title_model not in [
                    t["id"] for t in effectcraft.titles()]:
                return self._error("Modèle de titre introuvable : %s" % title_model, 400)
            if recipe == "clip-drone":
                _event_dir, src = self._event_photo(data)
                try:
                    animations.get(str(data.get("animation") or ""))
                except animations.AnimationError as exc:
                    return self._error(exc, 400)
                options = {
                    "animation": str(data.get("animation") or ""),
                    "title": title, "subtitle": subtitle, "to_filmcraft": to_fc, "title_model": title_model,
                    "box": data.get("box") or rushes.photo_box(event_dir, os.path.relpath(src, event_dir)),
                }
                name = os.path.basename(src)
                func = lambda j: studio.clip_drone(j, event_dir, src, **options)  # noqa: E731
            elif recipe == "generique":
                count = min(12, max(2, int(data.get("count") or 6)))
                name = os.path.basename(event_dir)
                func = lambda j: studio.generique(j, event_dir, count=count, title=title,  # noqa: E731
                                                  subtitle=subtitle, to_filmcraft=to_fc,
                                                  title_model=title_model)
            elif recipe == "sous-titres":
                rel = str(data.get("rel") or "")
                events.item_path(config.EVENTS_DIR, os.path.basename(event_dir), rel)   # chemin verifie
                language = str(data.get("language") or "auto")
                if language not in ("auto", "fr", "ar", "en"):
                    return self._error("Langue inconnue : %s" % language, 400)
                name = os.path.basename(rel)
                func = lambda j: studio.subtitles(j, event_dir, rel, language)  # noqa: E731
            else:
                rel = str(data.get("rel") or "")
                events.item_path(config.EVENTS_DIR, os.path.basename(event_dir), rel)   # chemin verifie
                point = data.get("point") or None
                box = data.get("box") or None
                start = max(0.0, float(data.get("start") or 0))
                duration = min(20.0, max(1.0, float(data.get("duration") or 10)))
                name = os.path.basename(rel)
                func = lambda j: studio.detour_video(j, event_dir, rel, point, start, duration,  # noqa: E731
                                                     to_filmcraft=to_fc, box=box)
        except events.EventError as exc:
            return self._error(exc, 404)
        except (TypeError, ValueError):
            return self._error("Paramètres invalides", 400)
        job = MANAGER.create("studio", "%s : %s" % (studio.RECIPES[recipe]["label"], name))
        MANAGER.run_async(job, func)
        return self._json({"job_id": job.id})

    def _event_job(self, kind: str, title: str, func):
        """Traitement de fond sur un evenement : func(job, dossier, donnees)."""
        data = self._body_json()
        try:
            event_dir = self._event_dir(data.get("id"))
        except events.EventError as exc:
            return self._error(exc, 404)
        job = MANAGER.create(kind, "%s : %s" % (title, os.path.basename(event_dir)))
        MANAGER.run_async(job, lambda j: func(j, event_dir, data))
        return self._json({"job_id": job.id})

    def _api_event_delete(self):
        """Tout l'evenement a la Corbeille (recuperable tant qu'elle n'est pas videe)."""
        data = self._body_json()
        if MANAGER.busy():
            return self._error("Un traitement est en cours : attendez la fin", 409)
        try:
            path = events.trash_event(config.EVENTS_DIR, str(data.get("id") or ""), trash.to_trash)
        except events.EventError as exc:
            return self._error(exc, 404)
        except trash.TrashError as exc:
            return self._error(exc, 500)
        return self._json({"ok": True, "trashed": [path]})

    def _api_event_trash(self):
        """Un rush, une photo, un dossier ou une carte entiere a la Corbeille."""
        data = self._body_json()
        if MANAGER.busy():
            return self._error("Un traitement est en cours : attendez la fin", 409)
        try:
            event_dir = self._event_dir(data.get("id"))
        except events.EventError as exc:
            return self._error(exc, 404)
        try:
            if data.get("card"):
                targets = rushes.card_paths(event_dir, str(data["card"]))
                for path in targets:
                    trash.to_trash(path)
            else:
                rel = str(data.get("rel") or "")
                related = rushes.related_paths(event_dir, rel)
                targets = events.trash_item(config.EVENTS_DIR, data.get("id"), rel, trash.to_trash)
                for path in related:
                    if os.path.exists(path):
                        trash.to_trash(path)
                        targets.append(path)
        except (events.EventError, rushes.RushError) as exc:
            return self._error(exc, 404)
        except trash.TrashError as exc:
            return self._error(exc, 500)
        finally:
            rushes.forget_missing(event_dir)
        return self._json({"ok": True, "trashed": targets})

    def _api_event_keep(self):
        data = self._body_json()
        try:
            event_dir = self._event_dir(data.get("id"))
            clip = rushes.set_keep(event_dir, str(data.get("rel") or ""), data.get("keep"))
        except (events.EventError, rushes.RushError) as exc:
            return self._error(exc, 404)
        return self._json({"keep": clip.get("keep"), "kept": rushes.is_kept(clip)})

    # -- jobs --------------------------------------------------------------
    def _job_status(self, job_id):
        job = MANAGER.get(job_id)
        if not job:
            return self._error("Traitement introuvable", 404)
        return self._json(job.summary())

    def _job_events(self, job_id):
        job = MANAGER.get(job_id)
        if not job:
            return self._error("Traitement introuvable", 404)
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
    status = ai.stats()
    print("")
    print("  \033[1m\033[38;5;208mRexo Studio\033[0m  -  derushage et post-production assistes par IA (100% local)")
    print("  " + "-" * 62)
    print("  Interface   : http://%s:%d" % (config.HOST, config.PORT))
    engine = "llama.cpp" if config.LLM_BACKEND == "llama" else "Ollama"
    print("  Modele IA   : %s via %s %s" % (config.LLM_MODEL, engine,
                                            "(pret)" if status.get("up") else "(INDISPONIBLE)"))
    print("  ffmpeg      : %s" % (config.ffmpeg_bin() or "INTROUVABLE"))
    print("  whisper.cpp : %s" % (config.whisper_bin() or "INTROUVABLE"))
    print("  FilmCraft   : %s" % ("installe" if filmcraft.installed() else "absent"))
    print("  Espace      : %s" % config.WORKSPACE)
    print("  Evenements  : %s (%d)" % (config.EVENTS_DIR,
                                     len(events.list_events(config.EVENTS_DIR))))
    print("  " + "-" * 62)
    print("  Ctrl+C pour arreter.")
    print("")
    if not status.get("up"):
        if config.LLM_BACKEND == "llama":
            print("  [!] Moteur IA absent : lancez ./scripts/install_models.sh")
        else:
            print("  [!] Ollama ne repond pas. Lancez 'ollama serve' dans un autre terminal.")
        print("")
    httpd = StudioServer((config.HOST, config.PORT), StudioHandler)
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
        ai.unload()
        print("\n  Arret.")
    httpd.server_close()


if __name__ == "__main__":
    main()
