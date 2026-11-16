"""Envoi du plan de coupe vers FilmCraft (editeur video), pilote en direct.

FilmCraft expose un serveur de controle local : une requete JSON par ligne
sur 127.0.0.1:<port>, authentifiee par un jeton de 64 caracteres hex
(FILMCRAFT_CONTROL_TOKEN). Rexo Studio lance FilmCraft avec ce serveur, puis :
importe la video, cree une sequence, place chaque segment retenu, importe
les sous-titres recales en vraie piste de sous-titres, ajoute un marqueur
par segment (avec la raison donnee par l'IA) et enregistre le .fcproj.
L'utilisateur retrouve le projet ouvert dans FilmCraft et continue a monter.

Toutes les durees sont envoyees en ticks entiers (254 016 000 000 par
seconde) et calees sur les images : les sous-titres sont recales sur ces
memes valeurs, donc ils restent synchrones avec la timeline de FilmCraft.
"""
from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import threading
import time
from fractions import Fraction

from . import config, tools

TICKS_PER_SECOND = 254016000000
AUTHOR = "Rexo Studio"

# Une seule construction de projet a la fois : FilmCraft n'a qu'un projet
# ouvert, deux envois simultanes se marcheraient dessus.
_LOCK = threading.Lock()


class FilmCraftError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# Temps : images et ticks
# --------------------------------------------------------------------------

def fps_fraction(fps: float) -> Fraction:
    """Cadence exacte : 30 -> 30/1, 29.97 -> 30000/1001, 23.976 -> 24000/1001."""
    if not fps or fps <= 0:
        return Fraction(30, 1)
    if abs(fps - round(fps)) < 0.01:
        return Fraction(int(round(fps)), 1)
    return Fraction(int(round(fps * 1.001)) * 1000, 1001)


def frames_to_ticks(frames: int, fps: Fraction) -> int:
    return int(round(Fraction(frames) * TICKS_PER_SECOND / fps))


def frame_plan(segments: list, fps: Fraction) -> list:
    """Cale chaque segment sur les images de la source.

    Retourne, pour chaque segment : image d'entree, nombre d'images, position
    sur la timeline (en images), et les temps source EFFECTIFS en secondes
    (ceux que FilmCraft utilisera reellement), pour recaler les sous-titres.
    """
    out = []
    position = 0
    for seg in segments:
        first = int(round(float(seg["start"]) * fps))
        last = int(round(float(seg["end"]) * fps))
        count = last - first
        if count <= 0:
            continue
        out.append({
            "source_frame": first,
            "frames": count,
            "timeline_frame": position,
            "start": float(Fraction(first) / fps),
            "end": float(Fraction(last) / fps),
            "id": seg.get("id", ""),
            "reason": seg.get("reason", ""),
        })
        position += count
    return out


def sequence_size(info: dict, profile: str) -> tuple:
    """Taille de la sequence : la source si elle est horizontale, sinon 1080p."""
    if profile == "9:16":
        return 1080, 1920
    width, height = int(info.get("width") or 0), int(info.get("height") or 0)
    if width >= height > 0:
        return width, height
    return 1920, 1080


# --------------------------------------------------------------------------
# Client du protocole de controle
# --------------------------------------------------------------------------

class Client(object):
    def __init__(self, port: int, token: str, host: str = "127.0.0.1",
                 timeout: float = 120.0):
        self.host = host
        self.port = int(port)
        self.token = token
        self.timeout = timeout
        self._next_id = 0

    def call(self, method: str, params: dict = None):
        """Une requete = une connexion (le serveur ferme apres une erreur)."""
        self._next_id += 1
        request = {"id": self._next_id, "token": self.token, "method": method}
        if params is not None:
            request["params"] = params
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as exc:
            raise FilmCraftError("FilmCraft injoignable sur le port %d (%s)"
                                 % (self.port, exc)) from exc
        try:
            sock.sendall((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = sock.recv(1 << 20)
                if not chunk:
                    break
                buf += chunk
        except OSError as exc:
            raise FilmCraftError("Echange avec FilmCraft interrompu (%s)" % exc) from exc
        finally:
            sock.close()
        try:
            reply = json.loads(buf.decode("utf-8"))
        except ValueError as exc:
            raise FilmCraftError("Reponse illisible de FilmCraft") from exc
        if not reply.get("ok"):
            raise FilmCraftError("FilmCraft (%s) : %s" % (
                (params or {}).get("command", method), reply.get("error", "erreur inconnue")))
        return reply.get("result")

    def execute(self, command: str, params: dict = None):
        return self.call("engine.execute", {"command": command, "params": params or {}})

    def ping(self) -> bool:
        try:
            self.call("perf.stats")
            return True
        except FilmCraftError:
            return False


# --------------------------------------------------------------------------
# Session : lancer FilmCraft ou reprendre celui deja lance par Rexo Studio
# --------------------------------------------------------------------------

def _session_file() -> str:
    return os.path.join(config.CACHE_DIR, "filmcraft-session.json")


def _load_session():
    try:
        with open(_session_file(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return int(data["port"]), str(data["token"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _save_session(port: int, token: str) -> None:
    """Le jeton donne le controle total de FilmCraft : fichier lisible par
    l'utilisateur seul (0600), jamais dans les logs ni dans l'interface."""
    path = _session_file()
    tools.ensure_parent(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"port": port, "token": token}, fh)


def _port_in_use(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def _filmcraft_running() -> bool:
    try:
        out = subprocess.run(["pgrep", "-x", "FilmCraft"], capture_output=True,
                             text=True, timeout=5)
        return bool(out.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return False


def installed() -> bool:
    return os.path.isfile(config.FILMCRAFT_BIN) and os.access(config.FILMCRAFT_BIN, os.X_OK)


def connect(log=None, launch: bool = True, wait: float = 90.0) -> Client:
    """Client vers le FilmCraft pilote par Rexo Studio (le lance si besoin)."""
    log = log or (lambda _m: None)
    port = config.FILMCRAFT_PORT
    saved = _load_session()
    if saved and saved[0] == port:
        client = Client(port, saved[1])
        if client.ping():
            return client
    if _port_in_use(port):
        raise FilmCraftError(
            "Le port %d est deja utilise par un autre programme "
            "(changez MONTAGIA_FILMCRAFT_PORT)." % port)
    if not launch:
        raise FilmCraftError("FilmCraft n'est pas lance par Rexo Studio.")
    if not installed():
        raise FilmCraftError("FilmCraft introuvable (%s)." % config.FILMCRAFT_APP)
    if _filmcraft_running():
        raise FilmCraftError(
            "FilmCraft est deja ouvert sans le pilotage de Rexo Studio : enregistrez "
            "votre travail et quittez FilmCraft, Rexo Studio le relancera.")

    token = secrets.token_hex(32)
    _save_session(port, token)
    env = dict(os.environ, FILMCRAFT_CONTROL_TOKEN=token)
    log_path = os.path.join(config.CACHE_DIR, "filmcraft.log")
    tools.ensure_parent(log_path)
    log("Lancement de FilmCraft (pilotage sur le port %d)..." % port)
    with open(log_path, "ab") as out:
        subprocess.Popen(
            [config.FILMCRAFT_BIN, "--control", str(port), "--empty", "--no-recover"],
            env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=out,
            start_new_session=True, close_fds=True)

    client = Client(port, token)
    deadline = time.time() + wait
    while time.time() < deadline:
        if client.ping():
            return client
        time.sleep(0.5)
    raise FilmCraftError("FilmCraft ne repond pas apres %d s (voir %s)." % (wait, log_path))


# --------------------------------------------------------------------------
# Construction du projet
# --------------------------------------------------------------------------

def build_project(client: Client, source: str, plan: list, out_path: str,
                  fps: Fraction, info: dict, profile: str = "16:9",
                  srt_path: str = "", title: str = "Montage Rexo Studio",
                  notes: str = "", log=None) -> dict:
    """Construit le projet dans FilmCraft a partir d'un plan cale sur les images
    (voir frame_plan) et l'enregistre en .fcproj."""
    log = log or (lambda _m: None)
    if not plan:
        raise FilmCraftError("Aucun segment : rien a envoyer a FilmCraft.")
    with _LOCK:
        # Version de secours du projet ouvert (modifications eventuelles de
        # l'utilisateur) : file.newProject remplace le projet sans demander.
        try:
            backup = client.execute("file.autoSaveNow").get("path", "")
            if backup:
                log("Copie de secours du projet precedent : %s" % backup)
        except FilmCraftError as exc:
            log("Copie de secours impossible (%s)" % exc)

        client.execute("file.newProject", {"name": title})
        imported = client.execute("file.import", {"paths": [os.path.abspath(source)]})
        if imported.get("errors") or not imported.get("items"):
            raise FilmCraftError("Import refuse par FilmCraft : %s" % imported.get("errors"))
        item = imported["items"][0]

        width, height = sequence_size(info, profile)
        sequence = client.execute("file.newSequence", {
            "name": title, "width": width, "height": height, "fps": float(fps),
        }).get("sequence")
        log("Sequence %dx%d a %.3f i/s" % (width, height, float(fps)))

        has_audio = bool(info.get("has_audio"))
        video_clips = []
        for seg in plan:
            params = {
                "item": item, "track": "V1",
                "time": frames_to_ticks(seg["timeline_frame"], fps),
                "insert": False,
                "sourceIn": frames_to_ticks(seg["source_frame"], fps),
                "duration": frames_to_ticks(seg["frames"], fps),
                "audio": has_audio,
            }
            if has_audio:
                params["audioTrack"] = "A1"
            clips = client.execute("timeline.place", params).get("clips") or []
            if clips:
                video_clips.append(clips[0])
        log("%d segments places sur la timeline" % len(video_clips))

        if profile == "9:16" and video_clips and width < height and \
                int(info.get("width") or 0) > int(info.get("height") or 0):
            client.execute("clip.fillFrame", {"clips": video_clips})
            log("Recadrage 9:16 (remplissage du cadre)")

        captions = 0
        if srt_path and os.path.isfile(srt_path):
            result = client.execute("captions.import", {
                "path": os.path.abspath(srt_path), "name": "Sous-titres Rexo Studio"})
            captions = int(result.get("captions") or 0)
            log("Piste de sous-titres : %d lignes" % captions)

        for seg in plan:
            client.execute("markers.add", {
                "target": "program",
                "time": frames_to_ticks(seg["timeline_frame"], fps),
                "name": (seg.get("reason") or seg.get("id") or "Segment")[:120],
                "comment": "%s - source %.2f s -> %.2f s" % (
                    seg.get("id") or "segment", seg["start"], seg["end"]),
                "author": AUTHOR,
            })
        if notes:
            client.execute("project.setNotes", {"text": notes})

        tools.ensure_parent(out_path)
        saved = client.execute("file.saveAs", {"path": os.path.abspath(out_path)})
        return {"path": saved.get("path") or out_path, "sequence": sequence,
                "clips": len(video_clips), "captions": captions}


def build_selection(client: Client, clips: list, out_path: str, fps: Fraction,
                    size: tuple, title: str = "Sélection Rexo Studio", notes: str = "",
                    log=None) -> dict:
    """Derushage : les rushes retenus, bout a bout dans l'ordre donne, chacun
    en entier, avec un marqueur (nom, heure de tournage). clips :
    [{"path", "duration", "name", "has_audio", "note"}]."""
    log = log or (lambda _m: None)
    if not clips:
        raise FilmCraftError("Aucun rush retenu : rien à envoyer à FilmCraft.")
    with _LOCK:
        try:
            backup = client.execute("file.autoSaveNow").get("path", "")
            if backup:
                log("Copie de secours du projet precedent : %s" % backup)
        except FilmCraftError as exc:
            log("Copie de secours impossible (%s)" % exc)
        client.execute("file.newProject", {"name": title})
        sequence = client.execute("file.newSequence", {
            "name": title, "width": size[0], "height": size[1], "fps": float(fps),
        }).get("sequence")
        position = placed = 0
        for clip in clips:
            frames = int(round(float(clip.get("duration") or 0) * fps))
            if frames <= 0:
                continue
            imported = client.execute("file.import", {"paths": [os.path.abspath(clip["path"])]})
            if imported.get("errors") or not imported.get("items"):
                log("Import refuse par FilmCraft : %s" % clip.get("name"))
                continue
            params = {"item": imported["items"][0], "track": "V1",
                      "time": frames_to_ticks(position, fps), "insert": False,
                      "sourceIn": 0, "duration": frames_to_ticks(frames, fps),
                      "audio": bool(clip.get("has_audio"))}
            if clip.get("has_audio"):
                params["audioTrack"] = "A1"
            if client.execute("timeline.place", params).get("clips"):
                client.execute("markers.add", {
                    "target": "program", "time": frames_to_ticks(position, fps),
                    "name": (clip.get("name") or "Rush")[:120],
                    "comment": clip.get("note", ""), "author": AUTHOR})
                position += frames
                placed += 1
        log("%d rushes places sur la timeline (%.1f s)" % (placed, float(position / fps)))
        if notes:
            client.execute("project.setNotes", {"text": notes})
        tools.ensure_parent(out_path)
        saved = client.execute("file.saveAs", {"path": os.path.abspath(out_path)})
        return {"path": saved.get("path") or out_path, "sequence": sequence,
                "clips": placed, "duration": round(float(position / fps), 3)}


def read_project(path: str) -> dict:
    """Relit un .fcproj enregistre et resume ses sequences (verification)."""
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if data.get("format") != "filmcraft.project":
        raise FilmCraftError("Ce fichier n'est pas un projet FilmCraft.")
    items = (data.get("project") or {}).get("items") or {}
    if isinstance(items, dict):
        items = list(items.values())
    sequences = []
    for it in items:
        seq = ((it or {}).get("kind") or {}).get("Sequence") if isinstance(it, dict) else None
        if not seq:
            continue
        clips = [c for track in seq.get("video_tracks") or [] for c in track.get("items") or []]
        sequences.append({
            "name": it.get("name", ""),
            "clips": len(clips),
            "duration": round(sum(c.get("duration", 0) for c in clips) / TICKS_PER_SECOND, 3),
            "captions": sum(len(t.get("captions") or []) for t in seq.get("caption_tracks") or []),
            "markers": len(seq.get("markers") or []),
        })
    return {"schema_version": data.get("schema_version"),
            "generator": data.get("generator", ""), "sequences": sequences}


def open_in_app() -> None:
    """Met FilmCraft au premier plan."""
    subprocess.Popen(["open", "-a", config.FILMCRAFT_APP])


def open_project(path: str, log=None) -> None:
    """Ouvre un .fcproj dans le FilmCraft pilote (le lance si besoin)."""
    client = connect(log=log)
    with _LOCK:
        try:
            client.execute("file.autoSaveNow")      # secours du projet en cours
        except FilmCraftError:
            pass
        client.execute("file.open", {"path": os.path.abspath(path)})
    open_in_app()


# --------------------------------------------------------------------------
# Chaine de production : un clip fini rejoint le projet de l'evenement
# --------------------------------------------------------------------------

MONTAGE_DIR = "05_Montage"


def event_project(event_dir: str) -> str:
    """Projet FilmCraft de l'evenement : le plus recent de 05_Montage, ou "" s'il n'y en a pas."""
    folder = os.path.join(event_dir, MONTAGE_DIR)
    if not os.path.isdir(folder):
        return ""
    found = [os.path.join(folder, n) for n in os.listdir(folder)
             if n.endswith(".fcproj") and not n.startswith(".")]
    return max(found, key=os.path.getmtime) if found else ""


def _find_bin(node: dict, name: str):
    for child in (node or {}).get("children") or []:
        if "children" in child and child.get("name") == name:
            return child.get("id")
        found = _find_bin(child, name)
        if found is not None:
            return found
    return None


def add_to_event_project(event_dir: str, clips: list, bin_name: str = "Génériques", log=None) -> dict:
    """Importe les clips dans le chutier bin_name du projet FilmCraft de l'evenement (cree
    s'il manque : 05_Montage/Montage.fcproj) et l'enregistre ; le montage continue dans
    FilmCraft."""
    log = log or (lambda _m: None)
    client = connect(log=log)
    path = event_project(event_dir)
    with _LOCK:
        try:
            client.execute("file.autoSaveNow")          # secours du projet en cours
        except FilmCraftError:
            pass
        if path:
            client.execute("file.open", {"path": os.path.abspath(path)})
        else:
            path = os.path.join(event_dir, MONTAGE_DIR, "Montage.fcproj")
            client.execute("file.newProject", {"name": "Montage " + os.path.basename(event_dir)})
        root = (client.execute("project.inspect") or {}).get("root") or {}
        bin_id = _find_bin(root, bin_name)
        if bin_id is None:
            bin_id = (client.execute("file.newBin", {"name": bin_name}) or {}).get("bin")
        imported = client.execute("file.import", {"paths": [os.path.abspath(c) for c in clips],
                                                  "bin": bin_id}) or {}
        if imported.get("errors"):
            raise FilmCraftError("Import refusé par FilmCraft : %s" % imported["errors"])
        tools.ensure_parent(path)
        saved = client.execute("file.saveAs", {"path": os.path.abspath(path)}) or {}
    log("FilmCraft : %d clip(s) dans le chutier « %s » de %s" % (
        len(imported.get("items") or []), bin_name, os.path.basename(path)))
    return {"project": saved.get("path") or path, "items": imported.get("items") or []}
