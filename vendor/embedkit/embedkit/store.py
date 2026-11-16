"""Model files: local cache, download with resume, sha256 check, strict offline mode (EK-1, EK-2)."""

from __future__ import annotations

import hashlib
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import EmbedkitError
from .registry import Manifest

ENV_CACHE = "EMBEDKIT_CACHE"
ENV_OFFLINE = "EMBEDKIT_OFFLINE"
ENV_ENDPOINT = "EMBEDKIT_HF_ENDPOINT"  # mirror or test server
DEFAULT_ENDPOINT = "https://huggingface.co"
CHUNK = 1 << 20


class StoreError(EmbedkitError):
    pass


def cache_dir() -> Path:
    return Path(os.environ.get(ENV_CACHE) or Path.home() / ".cache" / "embedkit")


def offline() -> bool:
    return os.environ.get(ENV_OFFLINE, "") in ("1", "true", "yes")


def model_dir(m: Manifest) -> Path:
    """One folder per model id and release: the pinned commit, or the release label."""
    label = m.source.revision[:12] if not m.source.url else m.source.revision
    safe = (
        "".join(c if c.isalnum() or c in "._-" else "_" for c in label) or m.sha256[:12]
    )
    return cache_dir() / m.id / safe


def model_path(m: Manifest) -> Path:
    """Where the model file lives once installed."""
    return model_dir(m) / m.filename


def extra_path(m: Manifest, name: str) -> Path:
    """Where a companion file (e.g. ``dict``) lives once installed."""
    for e in m.extras:
        if e.name == name:
            return model_dir(m) / Path(e.file).name
    raise StoreError(f"Le modèle « {m.id} » n'a pas de fichier annexe « {name} ».")


def is_installed(m: Manifest) -> bool:
    return model_path(m).is_file() and all(
        (model_dir(m) / Path(e.file).name).is_file() for e in m.extras
    )


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _hf_url(repo: str, revision: str, file: str) -> str:
    endpoint = os.environ.get(ENV_ENDPOINT, DEFAULT_ENDPOINT).rstrip("/")
    return f"{endpoint}/{repo}/resolve/{revision}/{file}"


def url_of(m: Manifest) -> str:
    return m.source.url or _hf_url(m.source.repo, m.source.revision, m.source.file)


def _files(m: Manifest) -> list[tuple[str, Path, str, str]]:
    """(label, local path, url, sha256) of the model file and its companions."""
    out = [(m.id, model_path(m), url_of(m), m.sha256)]
    for e in m.extras:
        url = e.url or _hf_url(m.source.repo, m.source.revision, e.file)
        out.append(
            (f"{m.id}/{e.name}", model_dir(m) / Path(e.file).name, url, e.sha256)
        )
    return out


def verify(m: Manifest) -> bool:
    """True if the model file and its companions match their sha256."""
    return all(
        path.is_file() and sha256_of(path) == sha for _, path, _, sha in _files(m)
    )


def _progress(done: int, total: int | None, started: float) -> None:
    rate = done / max(time.monotonic() - started, 1e-6) / 2**20
    if total:
        print(
            f"\r  {done / 2**20:7.1f} / {total / 2**20:.1f} Mo  ({rate:.1f} Mo/s)",
            end="",
            file=sys.stderr,
        )
    else:
        print(f"\r  {done / 2**20:7.1f} Mo  ({rate:.1f} Mo/s)", end="", file=sys.stderr)


def _download(label: str, url: str, path: Path, sha256: str, timeout: float) -> None:
    """Download one file to ``path`` with resume (.part + HTTP Range) and sha256 check."""
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    request = urllib.request.Request(url, headers={"User-Agent": "embedkit"})
    if have:
        request.add_header("Range", f"bytes={have}-")
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        if exc.code == 416 and have:  # .part already complete
            response = None
        else:
            raise StoreError(
                f"Téléchargement de « {label} » impossible : HTTP {exc.code} ({url})"
            ) from None
    except (urllib.error.URLError, OSError) as exc:
        raise StoreError(
            f"Téléchargement de « {label} » impossible : {exc}. Vérifiez la connexion."
        ) from None

    if response is not None:
        with response:
            if have and response.status != 206:  # server ignored Range: start over
                have = 0
            length = response.headers.get("Content-Length")
            total = have + int(length) if length else None
            started, done = time.monotonic(), have
            print(f"→ {label}", file=sys.stderr)
            with open(part, "ab" if have else "wb") as out:
                while chunk := response.read(CHUNK):
                    out.write(chunk)
                    done += len(chunk)
                    _progress(done, total, started)
            print(file=sys.stderr)

    digest = sha256_of(part)
    if digest != sha256:
        part.unlink()
        raise StoreError(
            f"Fichier corrompu pour « {label} » (sha256 {digest[:12]}… au lieu de {sha256[:12]}…). "
            "Le fichier partiel a été supprimé ; relancez le téléchargement."
        )
    os.replace(part, path)


def pull(m: Manifest, timeout: float = 60) -> Path:
    """Make sure the model file and its companions are in the cache and intact.

    Downloads what is missing; an interrupted download resumes from its .part file.
    """
    missing = [f for f in _files(m) if not f[1].is_file()]
    if missing and offline():
        raise StoreError(
            f"Mode hors ligne : le modèle « {m.id} » n'est pas installé. "
            f"Lancez « embedkit models pull {m.id} » avec une connexion."
        )
    for label, path, url, sha in missing:
        _download(label, url, path, sha, timeout)
    return model_path(m)
