"""Projet de montage : tout l'etat d'une video en cours de traitement.

Les projets sont enregistres en JSON dans workspace/projects/ (un fichier
par projet) et recharges au demarrage du serveur : un redemarrage ne fait
plus perdre transcription, plan de coupe, resultats IA ni exports.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid

_FIELDS = ("name", "path", "created_at", "updated_at", "info", "silences",
           "speech_segments", "scenes", "transcript_segments", "transcript_words",
           "candidates",
           "transcript", "plan", "srt_path", "language", "model", "results",
           "exports")


class Project(object):
    def __init__(self, media_path: str, name: str = ""):
        self.id = uuid.uuid4().hex[:10]
        self.name = name or os.path.basename(media_path)
        self.path = media_path
        self.created_at = time.time()
        self.updated_at = self.created_at
        self.info = {}
        self.silences = []
        self.speech_segments = []
        self.scenes = []                  # changements de plan (secondes)
        self.transcript_segments = []     # lignes de sous-titres
        self.transcript_words = []        # mots horodates (plan de coupe)
        self.candidates = []              # segments numerotes S1, S2...
        self.transcript = ""              # texte continu
        self.plan = []                    # plan de coupe retenu (timecodes reels)
        self.srt_path = ""
        self.language = ""
        self.model = ""
        self.results = {}                 # pack / summary / trailer / subtitles
        self.exports = []                 # fichiers produits

    def to_dict(self) -> dict:
        data = {"id": self.id}
        for field in _FIELDS:
            data[field] = getattr(self, field)
        data["media_missing"] = not os.path.isfile(self.path)
        return data

    def summary(self) -> dict:
        """Version legere pour la liste des projets."""
        return {
            "id": self.id, "name": self.name,
            "created_at": self.created_at, "updated_at": self.updated_at,
            "duration": (self.info or {}).get("duration", 0),
            "transcribed": bool(self.transcript_segments),
            "planned": bool(self.plan),
            "exports": len(self.exports),
            "media_missing": not os.path.isfile(self.path),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Project":
        proj = cls(data.get("path", ""), data.get("name", ""))
        proj.id = str(data.get("id") or proj.id)
        for field in _FIELDS:
            if field in data and data[field] is not None:
                setattr(proj, field, data[field])
        return proj

    def add_export(self, path: str) -> None:
        if path and path not in self.exports:
            self.exports.append(path)


class ProjectStore(object):
    """Projets en memoire, enregistres sur disque une fois la persistance
    activee (enable_persistence) : le serveur l'active, les tests non."""

    def __init__(self, max_projects: int = 50):
        self._items = {}
        self._order = []
        self._max = max_projects
        self._dir = ""
        self._lock = threading.Lock()

    # -- persistance -------------------------------------------------------
    def enable_persistence(self, directory: str) -> int:
        """Charge les projets enregistres ; retourne leur nombre."""
        os.makedirs(directory, exist_ok=True)
        self._dir = directory
        loaded = []
        for name in os.listdir(directory):
            if not (name.startswith("project_") and name.endswith(".json")):
                continue
            try:
                with open(os.path.join(directory, name), "r", encoding="utf-8") as fh:
                    loaded.append(Project.from_dict(json.load(fh)))
            except (OSError, ValueError, TypeError, AttributeError):
                continue                    # fichier abime : ignore, jamais bloquant
        loaded.sort(key=lambda p: p.updated_at or p.created_at)
        with self._lock:
            for proj in loaded[-self._max:]:
                if proj.id not in self._items:
                    self._items[proj.id] = proj
                    self._order.append(proj.id)
        return len(loaded[-self._max:])

    def _file(self, project_id: str) -> str:
        return os.path.join(self._dir, "project_%s.json" % project_id)

    def save(self, project: Project) -> None:
        """Ecriture atomique (fichier temporaire + rename) : un arret brutal
        ne laisse jamais un JSON a moitie ecrit."""
        project.updated_at = time.time()
        if not self._dir:
            return
        path = self._file(project.id)
        tmp = "%s.%d.tmp" % (path, threading.get_ident())
        data = project.to_dict()
        data.pop("media_missing", None)
        with self._lock:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False)
            os.replace(tmp, path)

    # -- acces -------------------------------------------------------------
    def create(self, media_path: str, name: str = "") -> Project:
        project = Project(media_path, name)
        with self._lock:
            self._items[project.id] = project
            self._order.append(project.id)
            while len(self._order) > self._max:
                old = self._order.pop(0)
                self._items.pop(old, None)  # le fichier JSON reste sur disque
        self.save(project)
        return project

    def get(self, project_id: str):
        return self._items.get(project_id)

    def list(self) -> list:
        """Projets, le plus recemment modifie en premier."""
        with self._lock:
            items = [self._items[i] for i in self._order if i in self._items]
        items.sort(key=lambda p: p.updated_at or p.created_at, reverse=True)
        return [p.summary() for p in items]


STORE = ProjectStore()
