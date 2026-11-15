"""Gestion des taches longues (jobs) avec progression et evenements.

Chaque job tourne dans un thread. L'interface web s'abonne au flux
d'evenements (SSE) et affiche la progression en direct.
"""
from __future__ import annotations

import queue
import threading
import time
import traceback
import uuid


class Job(object):
    def __init__(self, job_type: str, title: str = ""):
        self.id = uuid.uuid4().hex[:12]
        self.type = job_type
        self.title = title or job_type
        self.status = "queued"          # queued | running | done | error | cancelled
        self.progress = 0.0
        self.step = ""
        self.log = []
        self.result = {}
        self.error = ""
        self.created_at = time.time()
        self.started_at = 0.0
        self.finished_at = 0.0
        self._listeners = []
        self._lock = threading.Lock()

    # -- evenements --------------------------------------------------------
    def subscribe(self) -> "queue.Queue":
        q = queue.Queue()
        with self._lock:
            self._listeners.append(q)
        return q

    def unsubscribe(self, q) -> None:
        with self._lock:
            if q in self._listeners:
                self._listeners.remove(q)

    def _broadcast(self, event: dict) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for q in listeners:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass

    # -- etats -------------------------------------------------------------
    def add_log(self, message: str) -> None:
        message = str(message).rstrip()
        if not message:
            return
        self.log.append(message)
        if len(self.log) > 500:
            del self.log[:-500]
        self._broadcast({"type": "log", "message": message})

    def set_progress(self, value: float, step: str = "") -> None:
        try:
            value = max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            value = self.progress
        self.progress = value
        if step:
            self.step = step
        self._broadcast({"type": "progress", "progress": self.progress,
                         "step": self.step})

    def start(self) -> None:
        self.status = "running"
        self.started_at = time.time()
        self._broadcast({"type": "status", "status": self.status})

    def finish(self, result=None) -> None:
        self.status = "done"
        self.progress = 1.0
        self.finished_at = time.time()
        if result:
            self.result = result
        self._broadcast({"type": "done", "result": self.result,
                         "status": self.status})

    def fail(self, error) -> None:
        self.status = "error"
        self.error = str(error)
        self.finished_at = time.time()
        self.add_log("ERREUR : %s" % self.error)
        self._broadcast({"type": "error", "error": self.error,
                         "status": self.status})

    def cancel(self) -> None:
        self.status = "cancelled"
        self.finished_at = time.time()
        self._broadcast({"type": "status", "status": self.status})

    # -- serialisation -----------------------------------------------------
    def summary(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "title": self.title,
            "status": self.status,
            "progress": round(self.progress, 4),
            "step": self.step,
            "error": self.error,
            "result": self.result,
            "log": self.log[-40:],
            "created_at": self.created_at,
            "duration": round((self.finished_at or time.time()) - self.created_at, 1),
        }


class JobManager(object):
    """Jobs en arriere-plan, avec une file d'attente pour les jobs lourds.

    Sur l'iMac (4 coeurs), whisper, ffmpeg et le LLM se disputent le
    processeur : lances ensemble, chacun ralentit fortement les autres. Les
    jobs lourds passent donc un par un (heavy_slots), dans l'ordre d'arrivee.
    """

    def __init__(self, max_jobs: int = 100, heavy_slots: int = 1):
        self._jobs = {}
        self._order = []
        self._lock = threading.Lock()
        self._max = max_jobs
        self._heavy = threading.Semaphore(heavy_slots)
        self._waiting = 0

    def create(self, job_type: str, title: str = "") -> Job:
        job = Job(job_type, title)
        with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
            while len(self._order) > self._max:
                old = self._order.pop(0)
                self._jobs.pop(old, None)
        return job

    def get(self, job_id: str):
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list:
        with self._lock:
            ids = list(self._order)
        return [self._jobs[i].summary() for i in ids if i in self._jobs][::-1]

    def busy(self) -> bool:
        """Un traitement est en cours ou en attente."""
        with self._lock:
            jobs = [self._jobs[i] for i in self._order if i in self._jobs]
        return any(j.status in ("queued", "running") for j in jobs)

    def waiting(self) -> int:
        """Nombre de jobs lourds en attente d'un creneau."""
        with self._lock:
            return self._waiting

    def run_async(self, job: Job, func, *args, heavy: bool = True, **kwargs) -> Job:
        """Lance func(job, *args) dans un thread de fond.

        heavy=True : attend son tour (un seul job lourd a la fois) ; le job
        reste "queued" et l'interface affiche qu'il est en attente.
        """
        def _target():
            if heavy and not self._heavy.acquire(blocking=False):
                with self._lock:
                    self._waiting += 1
                job.set_progress(0.0, "En attente : une autre tache est en cours")
                self._heavy.acquire()
                with self._lock:
                    self._waiting -= 1
            try:
                job.start()
                try:
                    result = func(job, *args, **kwargs)
                    if result is not None:
                        job.finish(result)
                    elif job.status == "running":
                        job.finish()
                except Exception as exc:        # noqa: BLE001
                    traceback.print_exc()
                    job.fail(exc)
            finally:
                if heavy:
                    self._heavy.release()
        thread = threading.Thread(target=_target, daemon=True)
        thread.start()
        return job

    def run_sync(self, job: Job, func, *args, **kwargs):
        """Execute func dans le thread courant (utilise par les appels API courts)."""
        job.start()
        try:
            result = func(job, *args, **kwargs)
            job.finish(result)
            return result
        except Exception as exc:                # noqa: BLE001
            job.fail(exc)
            raise


MANAGER = JobManager()
