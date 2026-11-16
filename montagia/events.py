"""Evenements du studio : un evenement = un dossier de projet (ADR 0001).

    <racine>/AAAA-MM-JJ_Type_Noms/
        01_Rushes/ 02_Photos/ 03_Audio/ 04_Proxies/ 05_Montage/
        06_Rendus/{Film_complet,Teaser,Photos_animees}/ 07_Livraison/
        .rexo/evenement.json      fiche (type, date, noms, lieu, notes)

Le dossier est la verite : la liste est relue sur le disque a chaque demande,
un evenement copie ou archive a la main reapparait tel quel. Rien n'est
jamais efface : supprimer = mettre a la Corbeille du Mac (voir trash.py).
"""
from __future__ import annotations

import datetime
import json
import os
import re
import time
import unicodedata

FICHE_DIR = ".rexo"
FICHE_NAME = "evenement.json"

# (cle utilisee dans le nom du dossier, libelle affiche)
TYPES = (
    ("Mariage", "Mariage"),
    ("Fiancailles", "Fiançailles"),
    ("Henne", "Henné"),
    ("Anniversaire", "Anniversaire"),
    ("Circoncision", "Circoncision"),
    ("Diplome", "Diplôme"),
    ("Fete", "Fête"),
)
TYPE_LABELS = dict(TYPES)

# Sous-dossiers visibles, dans l'ordre du flux de travail.
FOLDERS = (
    ("01_Rushes", "Rushes"),
    ("02_Photos", "Photos"),
    ("03_Audio", "Audio"),
    ("04_Proxies", "Proxies"),
    ("05_Montage", "Montage"),
    ("06_Rendus", "Rendus"),
    ("07_Livraison", "Livraison"),
)
FOLDER_NAMES = tuple(name for name, _ in FOLDERS)
RENDER_SUBDIRS = ("Film_complet", "Teaser", "Photos_animees")

NAMES_MAX = 60
# Interdits sur macOS ou Windows (le portage Windows reste possible).
_FORBIDDEN = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')


class EventError(ValueError):
    """Demande invalide (message affichable tel quel)."""


def clean_names(text: str) -> str:
    """'Sarra & Ahmed' -> 'Sarra-et-Ahmed'. Accents et lettres arabes gardes."""
    text = unicodedata.normalize("NFC", text or "")
    text = text.replace("&", " et ")
    text = _FORBIDDEN.sub(" ", text)
    text = re.sub(r"\s+", "-", text.strip())
    text = re.sub(r"-{2,}", "-", text).strip("-.")
    return text[:NAMES_MAX].rstrip("-.")


def folder_name(type_key: str, date: str, names: str) -> str:
    return "%s_%s_%s" % (date, type_key, clean_names(names))


def _check_date(date: str) -> str:
    try:
        return datetime.datetime.strptime((date or "").strip(), "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        raise EventError("Date invalide : utilisez le format AAAA-MM-JJ") from None


def create(root: str, type_key: str, date: str, names: str,
           place: str = "", notes: str = "") -> dict:
    """Cree le dossier, ses sous-dossiers et la fiche ; retourne le resume."""
    if type_key not in TYPE_LABELS:
        raise EventError("Type d'événement inconnu : %s" % type_key)
    date = _check_date(date)
    names = (names or "").strip()
    if not clean_names(names):
        raise EventError("Indiquez les noms (ex : Sarra et Ahmed)")
    os.makedirs(root, exist_ok=True)
    base = folder_name(type_key, date, names)
    name, n = base, 1
    while os.path.exists(os.path.join(root, name)):
        n += 1
        name = "%s_%d" % (base, n)
    path = os.path.join(root, name)
    os.makedirs(path)
    for sub in FOLDER_NAMES:
        os.makedirs(os.path.join(path, sub))
    for sub in RENDER_SUBDIRS:
        os.makedirs(os.path.join(path, "06_Rendus", sub))
    os.makedirs(os.path.join(path, FICHE_DIR))
    fiche = {
        "version": 1, "type": type_key, "date": date, "names": names,
        "place": (place or "").strip(), "notes": (notes or "").strip(),
        "created_at": time.time(),
    }
    _write_fiche(path, fiche)
    return summary(root, name)


def _write_fiche(path: str, fiche: dict) -> None:
    target = os.path.join(path, FICHE_DIR, FICHE_NAME)
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(fiche, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, target)


def _read_fiche(path: str):
    try:
        with open(os.path.join(path, FICHE_DIR, FICHE_NAME), "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _usage(path: str) -> tuple:
    """(nombre de fichiers, octets) sous path, fichiers caches exclus."""
    count = size = 0
    for current, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            if name.startswith("."):
                continue
            try:
                size += os.path.getsize(os.path.join(current, name))
            except OSError:
                continue
            count += 1
    return count, size


def summary(root: str, event_id: str) -> dict:
    path = event_path(root, event_id)
    fiche = _read_fiche(path) or {}
    folders, total = [], 0
    for sub, label in FOLDERS:
        count, size = _usage(os.path.join(path, sub))
        total += size
        folders.append({"name": sub, "label": label, "files": count, "size": size})
    type_key = fiche.get("type", "")
    return {
        "id": event_id, "path": path,
        "type": type_key, "type_label": TYPE_LABELS.get(type_key, type_key),
        "date": fiche.get("date", ""), "names": fiche.get("names", ""),
        "place": fiche.get("place", ""), "notes": fiche.get("notes", ""),
        "folders": folders, "size": total,
    }


def list_events(root: str) -> list:
    """Evenements de la racine, le plus recent d'abord. Un dossier sans fiche
    (ou a la fiche abimee) n'est pas un evenement Rexo : il est ignore."""
    if not os.path.isdir(root):
        return []
    items = []
    for entry in os.scandir(root):
        if entry.name.startswith(".") or not entry.is_dir():
            continue
        if _read_fiche(entry.path) is None:
            continue
        items.append(summary(root, entry.name))
    items.sort(key=lambda e: (e["date"], e["id"]), reverse=True)
    return items


def event_path(root: str, event_id: str, sub: str = "") -> str:
    """Chemin d'un evenement (ou d'un de ses sous-dossiers), verifie : pas de
    separateur ni de '..', uniquement les sous-dossiers connus."""
    if (not event_id or event_id.startswith(".") or "/" in event_id
            or "\\" in event_id or event_id != os.path.basename(event_id)):
        raise EventError("Événement invalide")
    path = os.path.join(root, event_id)
    if _read_fiche(path) is None:
        raise EventError("Événement introuvable : %s" % event_id)
    if sub:
        if sub not in FOLDER_NAMES:
            raise EventError("Dossier inconnu : %s" % sub)
        path = os.path.join(path, sub)
    return path


# --------------------------------------------------------------------------
# Suppression = mise a la Corbeille
# --------------------------------------------------------------------------

def item_path(root: str, event_id: str, rel: str) -> str:
    """Chemin d'un element de l'evenement designe par un chemin relatif,
    verifie : dans un des dossiers visibles (jamais .rexo/ ni la racine)."""
    base = event_path(root, event_id)
    rel = os.path.normpath(rel or "")
    parts = rel.split(os.sep)
    if os.path.isabs(rel) or ".." in parts or parts[0] not in FOLDER_NAMES:
        raise EventError("Élément invalide : %s" % rel)
    path = os.path.join(base, rel)
    if not os.path.lexists(path) or not os.path.realpath(path).startswith(
            os.path.realpath(base) + os.sep):
        raise EventError("Élément introuvable : %s" % rel)
    return path


def trash_event(root: str, event_id: str, to_trash) -> str:
    """Met tout le dossier de l'evenement a la Corbeille."""
    path = event_path(root, event_id)
    to_trash(path)
    return path


def trash_item(root: str, event_id: str, rel: str, to_trash) -> list:
    """Met un fichier ou un dossier a la Corbeille. Un dossier principal
    (01_Rushes...) est vide, pas retire : la structure reste en place."""
    path = item_path(root, event_id, rel)
    rel = os.path.normpath(rel)
    if rel in FOLDER_NAMES:
        targets = [os.path.join(path, n) for n in sorted(os.listdir(path)) if not n.startswith(".")]
    else:
        targets = [path]
    for target in targets:
        to_trash(target)
    if rel == "06_Rendus":
        for sub in RENDER_SUBDIRS:
            os.makedirs(os.path.join(path, sub), exist_ok=True)
    return targets
