"""Utilitaires systeme : execution de processus, chemins, logs."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
import unicodedata

# --------------------------------------------------------------------------
# Noms de fichiers
# --------------------------------------------------------------------------

_SLUG_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def slugify(text: str, maxlen: int = 60) -> str:
    """Transforme un titre en nom de fichier sure (accents -> ascii)."""
    text = unicodedata.normalize("NFKD", text or "")
    text = text.encode("ascii", "ignore").decode("ascii")
    text = _SLUG_RE.sub("-", text).strip("-._")
    return (text or "sans-titre")[:maxlen]


def safe_component(text: str, fallback: str = "media") -> str:
    """Nom de fichier court et sure, sans extension."""
    base = slugify(text, 48)
    if not base:
        base = fallback
    return base


def human_size(num: float) -> str:
    for unit in ("o", "Ko", "Mo", "Go"):
        if abs(num) < 1024:
            return "%.1f %s" % (num, unit)
        num /= 1024.0
    return "%.1f To" % num


def human_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return "%dh%02d:%02d" % (h, m, s)
    return "%02d:%02d" % (m, s)


# --------------------------------------------------------------------------
# Execution de commandes
# --------------------------------------------------------------------------

class CommandError(RuntimeError):
    def __init__(self, cmd, code, stderr, stdout=""):
        self.cmd = cmd
        self.code = code
        self.stderr = stderr or ""
        self.stdout = stdout or ""
        super().__init__("Commande echouee (%s): %s" % (code, (stderr or "")[-600:]))


def run(cmd, timeout=1800, cwd=None, env=None):
    """Execute une commande, leve CommandError en cas d'echec."""
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout,
        cwd=cwd, env=env, errors="replace")
    if proc.returncode != 0:
        raise CommandError(cmd, proc.returncode, proc.stderr, proc.stdout)
    return proc.stdout


def run_streaming(cmd, on_line, timeout=3600, cwd=None, env=None):
    """Execute une commande en flux, on_line est appele a chaque ligne."""
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, cwd=cwd, env=env, errors="replace")
    lines = []
    try:
        for raw in proc.stdout:
            line = raw.rstrip("\n")
            lines.append(line)
            if on_line:
                on_line(line)
        proc.wait(timeout=max(1, timeout - 60))
    finally:
        if proc.poll() is None:
            proc.kill()
    out = "\n".join(lines)
    if proc.returncode not in (0, None):
        raise CommandError(cmd, proc.returncode, out)
    return out


def which(name: str) -> str:
    return shutil.which(name) or ""


def ensure_parent(path: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def is_within(base: str, target: str) -> bool:
    """Verifie que target est dans base (protection path traversal)."""
    base_r = os.path.realpath(base)
    target_r = os.path.realpath(target)
    return target_r == base_r or target_r.startswith(base_r + os.sep)


def tail_file(path: str, max_lines: int = 40) -> list:
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read().splitlines()[-max_lines:]
    except OSError:
        return []


def now() -> str:
    return time.strftime("%H:%M:%S")
