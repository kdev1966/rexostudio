"""Projet de montage : tout l'etat d'une video en cours de traitement."""
from __future__ import annotations

import os
import time
import uuid


class Project(object):
    def __init__(self, media_path: str, name: str = ""):
        self.id = uuid.uuid4().hex[:10]
        self.name = name or os.path.basename(media_path)
        self.path = media_path
        self.created_at = time.time()
        self.info = {}
        self.silences = []
        self.speech_segments = []
        self.transcript_segments = []     # segments whisper
        self.candidates = []              # segments numerotes S1, S2...
        self.transcript = ""              # texte continu
        self.plan = []                    # plan de coupe retenu (timecodes reels)
        self.srt_path = ""
        self.language = ""
        self.model = ""
        self.results = {}                 # pack / summary / trailer / subtitles
        self.exports = []                 # fichiers produits

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "info": self.info,
            "silences": self.silences,
            "speech_segments": self.speech_segments,
            "transcript_segments": self.transcript_segments,
            "candidates": self.candidates,
            "transcript": self.transcript,
            "plan": self.plan,
            "srt_path": self.srt_path,
            "language": self.language,
            "model": self.model,
            "results": self.results,
            "exports": self.exports,
        }

    def add_export(self, path: str) -> None:
        if path and path not in self.exports:
            self.exports.append(path)


class ProjectStore(object):
    def __init__(self, max_projects: int = 30):
        self._items = {}
        self._order = []
        self._max = max_projects

    def create(self, media_path: str, name: str = "") -> Project:
        project = Project(media_path, name)
        self._items[project.id] = project
        self._order.append(project.id)
        while len(self._order) > self._max:
            old = self._order.pop(0)
            self._items.pop(old, None)
        return project

    def get(self, project_id: str):
        return self._items.get(project_id)

    def list(self) -> list:
        return [self._items[i].to_dict() for i in reversed(self._order)
                if i in self._items]


STORE = ProjectStore()
