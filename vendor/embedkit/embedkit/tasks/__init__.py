"""High-level tasks with a model-independent interface (EK-5): NumPy HxWx3 uint8 BGR in, NumPy out."""

from __future__ import annotations

import sys

from .. import EmbedkitError, hardware, licenses, store
from ..registry import Manifest, Registry
from .depth import DepthEstimator
from .inpaint import Inpainter
from .ocr import TextRecognizer
from .segment import Segmenter

__all__ = [
    "DepthEstimator",
    "Inpainter",
    "Segmenter",
    "TextRecognizer",
    "resolve_model",
]


def resolve_model(
    task: str,
    model: str | None = None,
    tier: int | str = "auto",
    registry: Registry | None = None,
    allow_noncommercial: bool | None = None,
) -> Manifest | None:
    """Pick the model for a task, or None for the tier-0 (classical) method.

    - ``model``: an explicit model id (its licence is still checked);
    - ``tier``: 0, 1, 2 or "auto" (from hardware.probe()). The best allowed, licence-cleared
      model of that tier or below is chosen; models refused by the licence policy are skipped.
    """
    registry = registry or Registry()
    if model:
        m = registry.get(model)
        if m.task != task:
            raise EmbedkitError(
                f"Le modèle « {model} » sert à la tâche « {m.task} », pas « {task} »."
            )
        licenses.check(m, allow_noncommercial)
        return m
    max_tier = hardware.probe().recommended_tier if tier == "auto" else int(tier)
    if max_tier == 0:
        return None
    for m in registry.for_task(task, max_tier=max_tier):
        try:
            licenses.check(m, allow_noncommercial)
        except licenses.LicenseError:
            continue
        if store.offline() and not store.is_installed(m):
            continue
        return m
    print(
        f"Aucun modèle utilisable pour « {task} » : méthode classique (niveau 0).",
        file=sys.stderr,
    )
    return None
