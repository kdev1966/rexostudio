"""TextureCraft (textures PBR, meme editeur que PhotoCraft et EffectCraft), pilote en
direct pour preparer les textures des modeles de scenes Blender.

TextureCraft ne fait qu'une chose dans la chaine : appliquer un de ses materiaux
(93 integres : marbre, or poli, chene, velours...) et exporter ses textures au format
Blender (Principled BSDF : couleur, metal, rugosite, normale, relief). Les textures
vont dans la bibliotheque config.TEXTURES_DIR/<materiau>/ ; les modeles .blend les
utilisent. Rien ne passe par TextureCraft au moment du travail d'un couple.

Serveur de controle local lance par `TextureCraft --control <port>`, jeton dans
TEXTURECRAFT_CONTROL_TOKEN ; une requete JSON par ligne, la premiere de chaque
connexion est {"method": "auth", "params": {"token"}} ; les commandes passent par
{"method": "command.run", "params": {"id", "params"}}.
"""
from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import time

from . import config, tools

PRESET = "Blender (Principled BSDF)"
MAPS = ("BaseColor", "Metallic", "Roughness", "Normal", "Height")


class TextureCraftError(RuntimeError):
    pass


class Client(object):
    """Protocole commun a TextureCraft et MaterialCraft (jeton, puis command.run)."""

    def __init__(self, port: int, token: str, timeout: float = 120.0, app: str = "TextureCraft"):
        self.port, self.token, self.timeout, self.app = int(port), token, timeout, app

    def call(self, method: str, params: dict = None):
        try:
            sock = socket.create_connection(("127.0.0.1", self.port), timeout=self.timeout)
        except OSError as exc:
            raise TextureCraftError("%s injoignable sur le port %d (%s)" % (self.app, self.port, exc)) from exc
        try:
            stream = sock.makefile("rwb")
            replies = []
            for i, (m, p) in enumerate((("auth", {"token": self.token}), (method, params or {}))):
                stream.write((json.dumps({"id": i, "method": m, "params": p}, ensure_ascii=False) + "\n").encode("utf-8"))
                stream.flush()
                line = stream.readline()
                if not line:
                    raise TextureCraftError("%s a fermé la connexion" % self.app)
                replies.append(json.loads(line.decode("utf-8")))
        except (OSError, ValueError) as exc:
            raise TextureCraftError("Échange avec %s interrompu (%s)" % (self.app, exc)) from exc
        finally:
            sock.close()
        for reply in replies:
            if not reply.get("ok"):
                raise TextureCraftError("%s (%s) : %s" % (
                    self.app, (params or {}).get("id", method), reply.get("error", "erreur inconnue")))
        return replies[-1].get("result")

    def run(self, command: str, params: dict = None):
        return self.call("command.run", {"id": command, "params": params or {}})

    def ping(self) -> bool:
        try:
            self.call("command.list")
            return True
        except TextureCraftError:
            return False


def installed() -> bool:
    return os.path.isfile(config.TEXTURECRAFT_BIN) and os.access(config.TEXTURECRAFT_BIN, os.X_OK)


def _running() -> bool:
    try:
        out = subprocess.run(["pgrep", "-x", "TextureCraft"], capture_output=True, text=True, timeout=5)
        return bool(out.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return False


def connect(log=None, wait: float = 60.0) -> Client:
    """Lance TextureCraft avec un jeton neuf (jamais ecrit sur disque ni dans les logs)."""
    log = log or (lambda _m: None)
    if not installed():
        raise TextureCraftError("TextureCraft introuvable (%s)." % config.TEXTURECRAFT_APP)
    if _running():
        raise TextureCraftError("TextureCraft est déjà ouvert : enregistrez votre travail et quittez-le, "
                                "Rexo Studio le relancera.")
    token = secrets.token_hex(32)
    log_path = os.path.join(config.CACHE_DIR, "texturecraft.log")
    tools.ensure_parent(log_path)
    log("Lancement de TextureCraft (pilotage sur le port %d)" % config.TEXTURECRAFT_PORT)
    with open(log_path, "ab") as out:
        subprocess.Popen([config.TEXTURECRAFT_BIN, "--control", str(config.TEXTURECRAFT_PORT)],
                         env=dict(os.environ, **config.CRAFT_GPU_ENV, TEXTURECRAFT_CONTROL_TOKEN=token),
                         stdin=subprocess.DEVNULL, stdout=out, stderr=out, start_new_session=True, close_fds=True)
    client = Client(config.TEXTURECRAFT_PORT, token)
    deadline = time.time() + wait
    while not client.ping():
        if time.time() > deadline:
            raise TextureCraftError("TextureCraft ne répond pas après %d s (voir %s)." % (wait, log_path))
        time.sleep(0.5)
    return client


def close(client: Client, wait: float = 20.0) -> None:
    try:
        client.run("file.close")
    except TextureCraftError:
        pass
    subprocess.run(["osascript", "-e", 'tell application "TextureCraft" to quit'],
                   capture_output=True, timeout=30)
    deadline = time.time() + wait
    while _running() and time.time() < deadline:
        time.sleep(0.5)


def materials(client: Client) -> list:
    return [m["id"] for m in client.run("material.list") or []]


def texture_dir(material: str) -> str:
    return os.path.join(config.TEXTURES_DIR, material)


def has_textures(material: str) -> bool:
    folder = texture_dir(material)
    return os.path.isdir(folder) and any(n.endswith("_BaseColor.png") for n in os.listdir(folder))


def export_material(client: Client, material: str, resolution: int = 1024, log=None) -> list:
    """Textures du materiau (plan carre, a repeter dans Blender) dans la bibliotheque."""
    folder = texture_dir(material)
    work = folder + ".partiel"
    os.makedirs(work, exist_ok=True)
    client.run("project.new", {"mesh": "plane", "resolution": int(resolution), "name": material})
    client.run("material.apply", {"material": material})
    result = client.run("file.exportTextures", {"dir": os.path.abspath(work), "preset": PRESET, "format": "png"}) or {}
    files = result.get("files") or []
    if not any(f.endswith("_BaseColor.png") for f in files):
        raise TextureCraftError("Export des textures « %s » incomplet" % material)
    # Noms stables : <materiau>_<carte>.png
    for path in files:
        kind = os.path.splitext(path)[0].rsplit("_", 1)[-1]
        os.replace(path, os.path.join(work, "%s_%s.png" % (material, kind)))
    if os.path.isdir(folder):
        for name in os.listdir(folder):
            os.remove(os.path.join(folder, name))
        os.rmdir(folder)
    os.rename(work, folder)
    if log:
        log("TextureCraft : textures « %s » (%d cartes)" % (material, len(files)))
    return sorted(os.listdir(folder))
