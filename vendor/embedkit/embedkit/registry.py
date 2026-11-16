"""Model manifests (one YAML file per model) and the registry that loads them."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import EmbedkitError

TASKS = {"detect", "ocr", "inpaint", "segment", "depth", "vlm", "asr", "classify"}
RUNTIMES = {"onnx", "opencv_dnn", "llamacpp", "whispercpp"}
BUILTIN_DIR = Path(__file__).parent / "models"
ENV_PATH = "EMBEDKIT_MODELS_PATH"  # extra manifest folders, os.pathsep-separated

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_REV_RE = re.compile(r"^[0-9a-f]{40}$")


class ManifestError(EmbedkitError):
    pass


@dataclass(frozen=True)
class Source:
    """Where a model file comes from: a Hugging Face repo at a pinned commit, or a fixed URL.

    With ``url`` (e.g. a GitHub release asset), ``revision`` is a free label naming the
    release; the sha256 in the manifest is what guarantees the content.
    """

    repo: str  # Hugging Face "org/name" ("" when url is used)
    file: str  # path inside the repository, or the file name for a URL
    revision: (
        str  # pinned commit sha (40 hex) for Hugging Face; a release label for a URL
    )
    url: str = ""


@dataclass(frozen=True)
class Extra:
    """A companion file of a model (e.g. the character dictionary of an OCR model)."""

    name: str  # role, e.g. "dict"
    file: str  # path in the same Hugging Face repo, or file name for a URL
    sha256: str
    url: str = ""


@dataclass(frozen=True)
class License:
    code: str
    weights: str
    commercial: bool | None  # None = unknown


@dataclass(frozen=True)
class Manifest:
    id: str
    task: str
    tier: int
    runtime: str
    source: Source
    sha256: str
    size_mb: float
    license: License
    io: dict = field(default_factory=dict)
    notes: str = ""
    extras: tuple[Extra, ...] = ()
    path: Path | None = None  # file the manifest was read from

    @property
    def filename(self) -> str:
        return Path(self.source.file).name


def _require(data: dict, key: str, where: str):
    if key not in data or data[key] in (None, ""):
        raise ManifestError(f"{where} : champ obligatoire « {key} » manquant")
    return data[key]


def _parse_commercial(value, where: str) -> bool | None:
    if value is True or value is False:
        return value
    if value in (None, "unknown"):
        return None
    raise ManifestError(
        f"{where} : license.commercial doit valoir true, false ou unknown"
    )


def parse_manifest(data: dict, where: str = "manifeste") -> Manifest:
    """Validate a manifest dict and build a Manifest."""
    if not isinstance(data, dict):
        raise ManifestError(f"{where} : le contenu doit être un dictionnaire YAML")
    model_id = str(_require(data, "id", where))
    where = f"{where} ({model_id})"
    if not _ID_RE.match(model_id):
        raise ManifestError(
            f"{where} : identifiant invalide (minuscules, chiffres, . _ -)"
        )
    task = _require(data, "task", where)
    if task not in TASKS:
        raise ManifestError(
            f"{where} : tâche inconnue « {task} » ({', '.join(sorted(TASKS))})"
        )
    runtime = _require(data, "runtime", where)
    if runtime not in RUNTIMES:
        raise ManifestError(
            f"{where} : runtime inconnu « {runtime} » ({', '.join(sorted(RUNTIMES))})"
        )
    tier = _require(data, "tier", where)
    if tier not in (0, 1, 2):
        raise ManifestError(f"{where} : tier doit valoir 0, 1 ou 2")
    src = _require(data, "source", where)
    if src.get("url"):
        url = str(src["url"])
        if not url.startswith("https://"):
            raise ManifestError(f"{where} : source.url doit commencer par https://")
        source = Source(
            repo="",
            file=str(src.get("file") or url.rsplit("/", 1)[-1]),
            revision=str(_require(src, "revision", where)),
            url=url,
        )
    else:
        source = Source(
            repo=str(_require(src, "repo", where)),
            file=str(_require(src, "file", where)),
            revision=str(_require(src, "revision", where)),
        )
        if not _REV_RE.match(source.revision):
            raise ManifestError(
                f"{where} : source.revision doit être un commit épinglé (40 caractères hexadécimaux)"
            )
    extras = []
    for item in data.get("extras") or []:
        extra = Extra(
            name=str(_require(item, "name", where)),
            file=str(item.get("file") or str(item.get("url", "")).rsplit("/", 1)[-1]),
            sha256=str(_require(item, "sha256", where)).lower(),
            url=str(item.get("url", "")),
        )
        if not _SHA_RE.match(extra.sha256):
            raise ManifestError(
                f"{where} : sha256 invalide pour le fichier annexe « {extra.name} »"
            )
        if not extra.file or (not extra.url and source.url):
            raise ManifestError(
                f"{where} : fichier annexe « {extra.name} » sans adresse"
            )
        extras.append(extra)
    sha256 = str(_require(data, "sha256", where)).lower()
    if not _SHA_RE.match(sha256):
        raise ManifestError(f"{where} : sha256 invalide (64 caractères hexadécimaux)")
    lic = _require(data, "license", where)
    license_ = License(
        code=str(lic.get("code", "")),
        weights=str(lic.get("weights", "")),
        commercial=_parse_commercial(lic.get("commercial"), where),
    )
    return Manifest(
        id=model_id,
        task=task,
        tier=tier,
        runtime=runtime,
        source=source,
        sha256=sha256,
        size_mb=float(data.get("size_mb", 0)),
        license=license_,
        io=dict(data.get("io") or {}),
        notes=str(data.get("notes", "")),
        extras=tuple(extras),
    )


def load_manifest(path: str | os.PathLike) -> Manifest:
    path = Path(path)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ManifestError(f"{path.name} : YAML illisible ({exc})") from None
    m = parse_manifest(data, path.name)
    return Manifest(**{**m.__dict__, "path": path})


class Registry:
    """All known manifests: embedkit's own, then EMBEDKIT_MODELS_PATH, then the caller's folders.

    A later folder may override a model id from an earlier one (an application can pin
    another revision of a built-in model).
    """

    def __init__(
        self,
        extra_dirs: list[str | os.PathLike] | None = None,
        include_builtin: bool = True,
    ):
        dirs: list[Path] = [BUILTIN_DIR] if include_builtin else []
        dirs += [Path(p) for p in os.environ.get(ENV_PATH, "").split(os.pathsep) if p]
        dirs += [Path(p) for p in extra_dirs or []]
        self.dirs = dirs
        self._models: dict[str, Manifest] = {}
        for d in dirs:
            for f in sorted(d.glob("*.yaml")) if d.is_dir() else []:
                m = load_manifest(f)
                self._models[m.id] = m

    def __len__(self) -> int:
        return len(self._models)

    def __iter__(self):
        return iter(sorted(self._models.values(), key=lambda m: (m.task, m.tier, m.id)))

    def get(self, model_id: str) -> Manifest:
        try:
            return self._models[model_id]
        except KeyError:
            raise EmbedkitError(
                f"Modèle inconnu : « {model_id} ». Voir « embedkit models list »."
            ) from None

    def for_task(self, task: str, max_tier: int = 2) -> list[Manifest]:
        """Models for a task, best first (highest allowed tier, then smallest)."""
        found = [m for m in self if m.task == task and m.tier <= max_tier]
        return sorted(found, key=lambda m: (-m.tier, m.size_mb))
