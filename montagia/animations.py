"""Bibliotheque d'animations 3D livrees par l'atelier (dossier atelier/ du depot, a part).

Rexo Studio ne fabrique jamais d'animation 3D : les techniciens les fabriquent dans
l'atelier (decors Blender, textures) et les livrent en paquets « rexo-animation »
(format : commun/paquet_animation.py). Rexo Studio les installe dans
config.ANIMATIONS_DIR et les utilise telles quelles : EffectCraft ouvre la
composition, y place les photos et le titre.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile

from commun import paquet_animation
from commun.paquet_animation import FILES, FORMAT, TOKEN, VERSIONS  # noqa: F401  (contrat public)

from . import config

MAX_INSTALL_BYTES = 8 * 1024 ** 3


class AnimationError(RuntimeError):
    pass


def read(folder: str):
    """animation.json d'un paquet complet et dans un format connu, sinon None."""
    return paquet_animation.read(folder)


def catalog() -> list:
    """Animations installees, pour l'interface."""
    root = config.ANIMATIONS_DIR
    items = []
    for name in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        folder = os.path.join(root, name)
        info = read(folder)
        if info:
            items.append({"id": name, "titre": info.get("titre") or name, "duree": info.get("duree"),
                          "mouvement": info.get("mouvement"), "scene": info.get("scene"),
                          "vignette": os.path.join(folder, "vignette.jpg"),
                          "emplacements": [e["name"] for e in info["emplacements"]]})
    return items


def get(animation_id: str) -> tuple:
    """(dossier, animation.json) d'une animation installee."""
    if not animation_id or os.sep in animation_id or animation_id.startswith("."):
        raise AnimationError("Animation invalide : %s" % animation_id)
    folder = os.path.join(config.ANIMATIONS_DIR, animation_id)
    info = read(folder)
    if not info:
        raise AnimationError("Animation introuvable ou incomplète : %s" % animation_id)
    return folder, info


def composition(folder: str) -> str:
    """Texte de composition.jsx, les videos designees dans le dossier reel du paquet."""
    with open(os.path.join(folder, "composition.jsx"), "r", encoding="utf-8") as fh:
        text = fh.read()
    # Chaine JavaScript : le chemin est echappe comme le ferait JSON
    return text.replace(TOKEN, json.dumps(os.path.abspath(folder))[1:-1])


def install(path: str, log=None) -> list:
    """Installe une livraison de l'atelier (zip, ou dossier d'un paquet) ; retourne les
    animations installees. Une animation deja presente est remplacee."""
    log = log or (lambda _m: None)
    os.makedirs(config.ANIMATIONS_DIR, exist_ok=True)
    work = tempfile.mkdtemp(prefix=".installation-", dir=config.ANIMATIONS_DIR)
    try:
        if os.path.isdir(path):
            shutil.copytree(path, os.path.join(work, os.path.basename(os.path.normpath(path))))
        else:
            _extract(path, work)
        installed = []
        for name in sorted(os.listdir(work)):
            src = os.path.join(work, name)
            info = read(src)
            if not info:
                log("Ignoré (paquet incomplet ou format inconnu) : %s" % name)
                continue
            dest = os.path.join(config.ANIMATIONS_DIR, name)
            if os.path.isdir(dest):
                shutil.rmtree(dest)
            os.rename(src, dest)
            installed.append(name)
            log("Animation installée : %s — %s" % (name, info.get("titre", "")))
        if not installed:
            raise AnimationError("Aucune animation valide dans %s" % os.path.basename(path))
        return installed
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _extract(zip_path: str, dest: str) -> None:
    """Extraction prudente : aucun chemin ne sort de dest, taille totale bornee."""
    try:
        archive = zipfile.ZipFile(zip_path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise AnimationError("Livraison illisible : %s" % exc) from exc
    with archive:
        total = 0
        root = os.path.realpath(dest)
        for member in archive.infolist():
            target = os.path.realpath(os.path.join(dest, member.filename))
            if not target.startswith(root + os.sep):
                raise AnimationError("Chemin refusé dans la livraison : %s" % member.filename)
            if (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise AnimationError("Lien symbolique refusé dans la livraison : %s" % member.filename)
            total += member.file_size
            if total > MAX_INSTALL_BYTES:
                raise AnimationError("Livraison trop grosse")
        archive.extractall(dest)
