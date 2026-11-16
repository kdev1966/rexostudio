"""PhotoCraft (editeur photo, meme editeur que FilmCraft), pilote sans interface.

L'application livre un moteur sans fenetre, photocraft-cli :
    run      ouvre une image, enchaine des commandes du moteur, enregistre
    batch    applique une liste d'actions a tout un dossier
    serve    session ouverte qui repond a des lignes JSON (stdio ou 127.0.0.1)
    commands le registre des commandes (select.subject, select.object,
             layer.removeBackground, paint.remove, filtres, reglages...)
Chaque commande lancee par `run` imprime une ligne JSON
{"command": id, "result": ...} ; on les relit pour verifier le resultat.

Rexo Studio s'en sert pour la Selection d'objet dans un cadre (detourage de
la robe et de la traine, que Vision ne voit pas) et pour ouvrir un resultat
dans PhotoCraft afin que le studio le retouche a la main.
"""
from __future__ import annotations

import json
import os
import subprocess

from . import config, tools


class PhotoCraftError(RuntimeError):
    pass


def installed() -> bool:
    return os.path.isfile(config.PHOTOCRAFT_CLI) and os.access(config.PHOTOCRAFT_CLI, os.X_OK)


def run(src: str, commands: list, out: str, timeout: float = 300) -> list:
    """Ouvre src, execute les commandes [(id, params), ...] dans l'ordre et
    enregistre le resultat dans out (jamais par-dessus src).
    Retourne le resultat de chaque commande, dans l'ordre."""
    if not installed():
        raise PhotoCraftError("PhotoCraft introuvable (%s)." % config.PHOTOCRAFT_APP)
    if os.path.abspath(out) == os.path.abspath(src):
        raise PhotoCraftError("PhotoCraft n'ecrit jamais par-dessus l'original.")
    cmd = [config.PHOTOCRAFT_CLI, "run", src]
    for command_id, params in commands:
        cmd += ["--cmd", command_id, "--params", json.dumps(params or {})]
    cmd += ["--out", out]
    tools.ensure_parent(out)
    try:
        stdout = tools.run(cmd, timeout=timeout)
    except tools.CommandError as exc:
        raise PhotoCraftError("PhotoCraft : %s" % (exc.stderr.strip()[-300:] or exc.code)) from exc
    except subprocess.TimeoutExpired as exc:
        raise PhotoCraftError("PhotoCraft ne repond pas apres %d s." % timeout) from exc
    results = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            results.append(json.loads(line).get("result"))
        except ValueError:
            continue
    if not os.path.isfile(out):
        raise PhotoCraftError("PhotoCraft n'a pas enregistre le resultat.")
    return results


def object_cutout(src: str, rect: list, out: str) -> list:
    """Selection d'objet dans le cadre rect = [x, y, largeur, hauteur] (pixels
    de src), detouree sur fond transparent dans out (PNG).
    Retourne le cadre de l'objet trouve [x, y, largeur, hauteur]."""
    x, y, w, h = (int(round(v)) for v in rect)
    if w < 8 or h < 8:
        raise PhotoCraftError("Cadre trop petit.")
    results = run(src, [
        ("select.object", {"rect": [x, y, w, h], "mode": "replace"}),
        ("layer.layerMask.revealSelection", {}),
    ], out)
    found = results[0] if results else None
    if not isinstance(found, dict) or not found.get("selected"):
        raise PhotoCraftError("Aucun objet trouvé dans le cadre.")
    return found.get("bounds") or []


def open_in_app(path: str) -> None:
    """Ouvre un fichier dans PhotoCraft (avec son interface), pour retoucher."""
    if not os.path.isdir(config.PHOTOCRAFT_APP):
        raise PhotoCraftError("PhotoCraft introuvable (%s)." % config.PHOTOCRAFT_APP)
    subprocess.Popen(["open", "-a", config.PHOTOCRAFT_APP, path],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
