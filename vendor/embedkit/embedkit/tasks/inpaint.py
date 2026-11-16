"""Inpainting: fill the masked part of an image from its surroundings.

Tier 1 runs an ONNX pipeline such as MI-GAN's (image + mask in, image out, any size).
Tier 0 is OpenCV's Telea inpainting: smooth, fine for thin areas, smeary for large ones.
"""

from __future__ import annotations

import cv2
import numpy as np

from .. import store
from ..registry import Manifest, Registry
from ..runtimes.onnx import OnnxModel

TELEA_RADIUS = 5


class Inpainter:
    """``Inpainter.load()`` then ``fill(image, mask) -> image``.

    ``image``: HxWx3 uint8 BGR. ``mask``: HxW, non-zero where the image must be filled.
    """

    def __init__(
        self,
        manifest: Manifest | None,
        engine: str = "auto",
        threads: int | None = None,
    ):
        self.manifest = manifest
        self.model = (
            OnnxModel(store.model_path(manifest), engine, threads) if manifest else None
        )

    @classmethod
    def load(
        cls,
        model: str | None = None,
        tier: int | str = "auto",
        registry: Registry | None = None,
        allow_noncommercial: bool | None = None,
        engine: str = "auto",
        threads: int | None = None,
    ) -> Inpainter:
        """Choose and fetch the model (downloads it unless offline); tier 0 needs no model."""
        from . import resolve_model

        m = resolve_model("inpaint", model, tier, registry, allow_noncommercial)
        if m is not None:
            store.pull(m)
        return cls(m, engine, threads)

    @property
    def tier(self) -> int:
        return self.manifest.tier if self.manifest else 0

    def __call__(self, image: np.ndarray, mask: np.ndarray) -> np.ndarray:
        if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
            raise ValueError("image must be HxWx3 uint8 (BGR)")
        if mask.shape[:2] != image.shape[:2]:
            raise ValueError("mask must have the image's height and width")
        hole = (mask > 0).astype(np.uint8)
        if not hole.any():
            return image.copy()
        if self.model is None:
            return cv2.inpaint(image, hole, TELEA_RADIUS, cv2.INPAINT_TELEA)
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB).transpose(2, 0, 1)[None]
        keep = ((1 - hole) * 255).astype(np.uint8)[None, None]
        out = self.model.run(
            {"image": np.ascontiguousarray(rgb), "mask": np.ascontiguousarray(keep)}
        )[0][0]
        result = cv2.cvtColor(
            np.ascontiguousarray(out.transpose(1, 2, 0)), cv2.COLOR_RGB2BGR
        )
        return np.where(
            hole[..., None] > 0, result, image
        )  # untouched outside the hole

    def close(self) -> None:
        if self.model:
            self.model.close()

    def __enter__(self) -> Inpainter:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
