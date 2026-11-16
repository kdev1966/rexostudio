"""Serveur llama.cpp (bin/llama-server) : demarre a la demande, arrete apres
inactivite ou a la sortie de MontageIA.

Un processus a part, comme whisper-cli : un plantage du moteur n'emporte
pas l'interface (lecon de Montora, docs/robustness-macos.md), et sa memoire
(~2,8 Go avec Gemma 4 E2B) est rendue au systeme en l'arretant. Meme schema
que Codewright / Waypoint / FerroLink : port libre sur 127.0.0.1, attente de
/health, arret propre puis force.
"""
from __future__ import annotations

import atexit
import contextlib
import json
import os
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request

from . import config

START_TIMEOUT = 120.0       # chargement du modele (2,8 Go lus sur le disque)
WATCH_INTERVAL = 15.0


class LlamaServerError(RuntimeError):
    pass


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class LlamaServer(object):
    def __init__(self, binary: str = None, model: str = None, log_path: str = None,
                 idle_seconds: float = None):
        self.binary = binary or config.LLAMA_SERVER_BIN
        self.model = model or config.LLM_GGUF
        self.log_path = log_path or os.path.join(config.CACHE_DIR, "llama-server.log")
        self.idle_seconds = config.LLM_IDLE_SECONDS if idle_seconds is None else idle_seconds
        self._lock = threading.RLock()
        self._proc = None
        self._port = 0
        self._active = 0
        self._last_used = 0.0
        self._watcher = None

    # -- etat --------------------------------------------------------------
    def installed(self) -> bool:
        return os.access(self.binary, os.X_OK) and os.path.isfile(self.model)

    def running(self) -> bool:
        # Sans verrou : l'etat est lu pendant un demarrage (jusqu'a 2 min)
        # par la page d'etat, qui ne doit pas rester bloquee.
        proc = self._proc
        return proc is not None and proc.poll() is None

    @property
    def url(self) -> str:
        return "http://127.0.0.1:%d" % self._port

    # -- demarrage / arret -------------------------------------------------
    def _command(self, port: int) -> list:
        return [self.binary, "-m", self.model, "--host", "127.0.0.1", "--port", str(port),
                "-c", str(config.LLM_NUM_CTX), "-np", "1", "-t", str(config.LLM_THREADS),
                "-fa", "on", "--jinja", "--no-webui"]

    def _healthy(self, timeout: float = 2.0) -> bool:
        try:
            with urllib.request.urlopen(self.url + "/health", timeout=timeout) as resp:
                return resp.status == 200
        except (urllib.error.URLError, OSError, ValueError):
            return False

    def _log_tail(self, lines: int = 8) -> str:
        try:
            with open(self.log_path, encoding="utf-8", errors="replace") as fh:
                return " | ".join(ln.strip() for ln in fh.readlines()[-lines:] if ln.strip())
        except OSError:
            return ""

    def ensure(self) -> str:
        """Demarre le serveur s'il ne tourne pas ; retourne son adresse."""
        with self._lock:
            if self.running():
                return self.url
            if not self.installed():
                raise LlamaServerError(
                    "Moteur IA absent (bin/llama-server ou le modèle) : lancez "
                    "./scripts/install_models.sh")
            os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
            self._port = _free_port()
            with open(self.log_path, "w", encoding="utf-8") as log:
                # Le processus garde sa propre copie du descripteur.
                self._proc = subprocess.Popen(self._command(self._port), stdin=subprocess.DEVNULL,
                                              stdout=log, stderr=subprocess.STDOUT)
            deadline = time.time() + START_TIMEOUT
            while time.time() < deadline:
                if self._proc.poll() is not None:
                    self._proc = None
                    raise LlamaServerError("Le moteur IA s'est arrêté au démarrage : %s"
                                           % self._log_tail())
                if self._healthy():
                    self._last_used = time.time()
                    self._start_watcher()
                    return self.url
                time.sleep(0.25)
            self.stop()
            raise LlamaServerError("Le moteur IA n'a pas répondu en %d s" % START_TIMEOUT)

    def stop(self) -> None:
        with self._lock:
            proc, self._proc = self._proc, None
        if proc is None or proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)

    # -- utilisation -------------------------------------------------------
    @contextlib.contextmanager
    def session(self):
        """Une requete en cours : le serveur n'est pas arrete pendant ce temps."""
        with self._lock:
            url = self.ensure()
            self._active += 1
        try:
            yield url
        finally:
            with self._lock:
                self._active -= 1
                self._last_used = time.time()

    def stop_if_idle(self) -> bool:
        with self._lock:
            idle = (self.running() and self._active == 0
                    and time.time() - self._last_used >= self.idle_seconds)
        if idle:
            self.stop()
        return idle

    def _start_watcher(self) -> None:
        if self._watcher and self._watcher.is_alive():
            return

        def watch():
            while True:
                time.sleep(WATCH_INTERVAL)
                if not self.running():
                    return
                self.stop_if_idle()

        self._watcher = threading.Thread(target=watch, name="llama-server-idle", daemon=True)
        self._watcher.start()

    # -- requetes ----------------------------------------------------------
    def post(self, path: str, body: dict, timeout: float = None):
        """POST JSON ; retourne la reponse decodee."""
        with self.session() as url:
            req = urllib.request.Request(url + path, data=json.dumps(body).encode("utf-8"),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout or config.LLM_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))

    def stream(self, path: str, body: dict, timeout: float = None):
        """POST en flux (SSE) ; genere les objets JSON des lignes 'data:'."""
        with self.session() as url:
            req = urllib.request.Request(url + path, data=json.dumps(body).encode("utf-8"),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout or config.LLM_TIMEOUT) as resp:
                for raw in resp:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        return
                    try:
                        yield json.loads(data)
                    except ValueError:
                        continue


SERVER = LlamaServer()
atexit.register(SERVER.stop)
