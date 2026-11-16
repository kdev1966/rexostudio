"""Licence policy (EK-3): by default only models cleared for commercial use may load."""

from __future__ import annotations

import os
import sys

from . import EmbedkitError
from .registry import Manifest

ENV_ALLOW = "EMBEDKIT_ALLOW_NONCOMMERCIAL"


class LicenseError(EmbedkitError):
    pass


def status(m: Manifest) -> str:
    return {True: "commerciale", False: "non commerciale", None: "inconnue"}[
        m.license.commercial
    ]


def noncommercial_allowed() -> bool:
    return os.environ.get(ENV_ALLOW, "") in ("1", "true", "yes")


def check(m: Manifest, allow_noncommercial: bool | None = None) -> None:
    """Raise LicenseError unless the model is cleared for commercial use or explicitly allowed."""
    if m.license.commercial is True:
        return
    allowed = (
        noncommercial_allowed() if allow_noncommercial is None else allow_noncommercial
    )
    detail = f"poids : {m.license.weights or '?'}, usage commercial : {status(m)}"
    if not allowed:
        raise LicenseError(
            f"Le modèle « {m.id} » n'est pas autorisé pour un usage commercial ({detail}). "
            f"Pour l'utiliser quand même, passez --allow-noncommercial ou {ENV_ALLOW}=1."
        )
    print(
        f"Attention : « {m.id} » est chargé sans licence commerciale claire ({detail}).",
        file=sys.stderr,
    )


def audit(models) -> list[tuple[str, str, str, str]]:
    """(id, code licence, weights licence, commercial status) for each model."""
    return [(m.id, m.license.code, m.license.weights, status(m)) for m in models]
