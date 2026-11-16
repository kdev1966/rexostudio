"""Monocular depth: image in, relative depth map out (1 = closest, 0 = farthest)."""

from __future__ import annotations

import cv2
import numpy as np

from .. import store
from ..registry import Manifest, Registry
from ..runtimes.onnx import OnnxModel


def _normalise(d: np.ndarray) -> np.ndarray:
    lo, hi = float(d.min()), float(d.max())
    return (
        np.zeros_like(d, np.float32)
        if hi - lo < 1e-12
        else ((d - lo) / (hi - lo)).astype(np.float32)
    )


def classic_depth(image: np.ndarray) -> np.ndarray:
    """Tier 0: vertical gradient, bottom of the frame closest (ground-plane cue)."""
    h, w = image.shape[:2]
    return np.repeat(np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None], w, axis=1)


class DepthEstimator:
    """``DepthEstimator.load()`` then ``est(image) -> HxW float32 in [0, 1]``, 1 = closest."""

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
    ) -> DepthEstimator:
        """Choose and fetch the model (downloads it unless offline); tier 0 needs no model."""
        from . import resolve_model

        m = resolve_model("depth", model, tier, registry, allow_noncommercial)
        if m is not None:
            store.pull(m)
        return cls(m, engine, threads)

    @property
    def tier(self) -> int:
        return self.manifest.tier if self.manifest else 0

    def _preprocess(self, image: np.ndarray, manifest: Manifest) -> np.ndarray:
        spec = manifest.io.get("input", {})
        size = int(spec.get("size", 518))
        rgb = cv2.cvtColor(
            cv2.resize(image, (size, size), interpolation=cv2.INTER_AREA),
            cv2.COLOR_BGR2RGB,
        )
        x: np.ndarray = rgb.astype(np.float32) / 255.0
        x = (x - np.array(spec.get("mean", [0.0] * 3), np.float32)) / np.array(
            spec.get("std", [1.0] * 3), np.float32
        )
        return np.ascontiguousarray(x.transpose(2, 0, 1)[None])

    def __call__(self, image: np.ndarray) -> np.ndarray:
        if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
            raise ValueError("image must be HxWx3 uint8 (BGR)")
        if self.model is None or self.manifest is None:
            return classic_depth(image)
        x = self._preprocess(image, self.manifest)
        out = np.squeeze(self.model.run(x)[0]).astype(np.float32)
        if self.manifest.io.get("output", {}).get("kind", "disparity") == "depth":
            out = -out  # metric/relative depth: larger = farther
        h, w = image.shape[:2]
        return _normalise(cv2.resize(out, (w, h), interpolation=cv2.INTER_CUBIC))

    def close(self) -> None:
        if self.model:
            self.model.close()

    def __enter__(self) -> DepthEstimator:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
