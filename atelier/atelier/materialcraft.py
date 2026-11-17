"""MaterialCraft (materiaux proceduraux par graphes de noeuds, meme editeur que
TextureCraft), pilote pour preparer les textures des modeles de scenes Blender.

MaterialCraft ne fait qu'une chose dans la chaine : ouvrir un materiau concu a part
(paquet .mcraft, ou .sbs de Substance Designer), en regler les entrees exposees
(couleurs du theme du mariage, motif, graine) et en exporter les cartes. Elles vont
dans la meme bibliotheque que celles de TextureCraft, config.TEXTURES_DIR/<nom>/, aux
noms qu'attendent les modeles .blend (<nom>_BaseColor.png...).

Meme protocole que TextureCraft : `MaterialCraft --control <port>`, jeton dans
MATERIALCRAFT_CONTROL_TOKEN, « auth » puis « command.run » {id, params}.
"""
from __future__ import annotations

import os
import secrets
import subprocess
import time

from . import config, texturecraft, tools
from .texturecraft import TextureCraftError as MaterialCraftError

# Sorties d'un graphe MaterialCraft -> cartes des modeles Blender
MAPS = {"basecolor": "BaseColor", "normal": "Normal", "roughness": "Roughness",
        "metallic": "Metallic", "height": "Height", "ambientocclusion": "AO"}


def installed() -> bool:
    return os.path.isfile(config.MATERIALCRAFT_BIN) and os.access(config.MATERIALCRAFT_BIN, os.X_OK)


def _running() -> bool:
    try:
        out = subprocess.run(["pgrep", "-x", "MaterialCraft"], capture_output=True, text=True, timeout=5)
        return bool(out.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return False


def connect(log=None, wait: float = 60.0) -> texturecraft.Client:
    """Lance MaterialCraft avec un jeton neuf (jamais ecrit sur disque ni dans les logs)."""
    log = log or (lambda _m: None)
    if not installed():
        raise MaterialCraftError("MaterialCraft introuvable (%s)." % config.MATERIALCRAFT_APP)
    if _running():
        raise MaterialCraftError("MaterialCraft est déjà ouvert : enregistrez votre travail et quittez-le, "
                                 "Rexo Studio le relancera.")
    token = secrets.token_hex(32)
    log_path = os.path.join(config.CACHE_DIR, "materialcraft.log")
    tools.ensure_parent(log_path)
    log("Lancement de MaterialCraft (pilotage sur le port %d)" % config.MATERIALCRAFT_PORT)
    with open(log_path, "ab") as out:
        subprocess.Popen([config.MATERIALCRAFT_BIN, "--control", str(config.MATERIALCRAFT_PORT)],
                         env=dict(os.environ, **config.CRAFT_GPU_ENV, MATERIALCRAFT_CONTROL_TOKEN=token),
                         stdin=subprocess.DEVNULL, stdout=out, stderr=out, start_new_session=True, close_fds=True)
    client = texturecraft.Client(config.MATERIALCRAFT_PORT, token, app="MaterialCraft")
    deadline = time.time() + wait
    while not client.ping():
        if time.time() > deadline:
            raise MaterialCraftError("MaterialCraft ne répond pas après %d s (voir %s)." % (wait, log_path))
        time.sleep(0.5)
    return client


def close(client, wait: float = 20.0) -> None:
    """Ferme sans enregistrer : Rexo Studio ne modifie jamais le paquet source."""
    try:
        client.run("package.closeAll", {"discard": True})
    except MaterialCraftError:
        pass
    subprocess.run(["osascript", "-e", 'tell application "MaterialCraft" to quit'], capture_output=True, timeout=30)
    deadline = time.time() + wait
    while _running() and time.time() < deadline:
        time.sleep(0.5)


def export_material(client, package: str, name: str, values: dict = None, graph: str = None,
                    size: int = 1024, log=None) -> list:
    """Ouvre le paquet, regle ses entrees exposees (values), exporte les cartes du
    graphe dans la bibliotheque sous le nom `name` ; retourne les fichiers."""
    folder = texturecraft.texture_dir(name)
    work = folder + ".partiel"
    os.makedirs(work, exist_ok=True)
    opened = client.run("file.open", {"path": os.path.abspath(package)}) or {}
    if opened.get("warnings") and log:
        log("MaterialCraft : %s" % "; ".join(str(w) for w in opened["warnings"]))
    # MaterialCraft ajoute un graphe vide a l'ouverture : on ouvre le graphe nomme,
    # sinon le premier qui a des noeuds
    if graph:
        client.run("graph.open", {"graph": graph})
    else:
        for index in range(int(opened.get("graphs") or 1)):
            client.run("graph.open", {"graph": index})
            if ((client.run("session.inspect") or {}).get("graph") or {}).get("nodes"):
                break
        else:
            raise MaterialCraftError("Le paquet n'a aucun graphe avec des noeuds")
    for key, value in (values or {}).items():
        client.run("graph.exposed.set", {"id": key, "value": value})
    result = client.run("file.export", {"dir": os.path.abspath(work), "format": "png", "size": int(size),
                                        "pattern": "$(identifier)"}) or {}
    kept = []
    for path in result.get("files") or []:
        kind = MAPS.get(os.path.splitext(os.path.basename(path))[0].rsplit("_", 1)[-1].lower())
        if kind:
            os.replace(path, os.path.join(work, "%s_%s.png" % (name, kind)))
            kept.append(kind)
        else:
            os.remove(path)
    if "BaseColor" not in kept:
        raise MaterialCraftError("Le graphe n'a pas de sortie « basecolor » : rien à exporter")
    if os.path.isdir(folder):
        for f in os.listdir(folder):
            os.remove(os.path.join(folder, f))
        os.rmdir(folder)
    os.rename(work, folder)
    if log:
        log("MaterialCraft : textures « %s » (%s)" % (name, ", ".join(sorted(kept))))
    return sorted(os.listdir(folder))
