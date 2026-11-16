"""Promptable segmentation: cut out the object under a click or inside a box.

Tier 1 runs a SAM-style pair of ONNX models (MobileSAM): the encoder turns the image into
embeddings once, then the decoder answers each prompt in a few tens of milliseconds.
Tier 0 is OpenCV's GrabCut seeded by the same prompts: slower per prompt, rougher edges.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .. import store
from ..registry import Manifest, Registry
from ..runtimes.onnx import OnnxModel

GRABCUT_ITERATIONS = 5
GRABCUT_SEED = 6  # px, radius of the area a click marks as sure


@dataclass
class Embedding:
    """An image prepared for prompts: ``Segmenter.embed(image)``."""

    shape: tuple[int, int]  # (h, w) of the original image
    scale: float  # original -> encoder frame
    features: np.ndarray | None  # tier 1: [1, 256, 64, 64]
    image: np.ndarray | None  # tier 0: the BGR image itself


class Segmenter:
    """``Segmenter.load()``, ``embed(image)``, then ``segment(embedding, points, box)``.

    ``points``: [(x, y, label)], label 1 = on the object, 0 = not on it; ``box``:
    (x0, y0, x1, y1). Coordinates are pixels of the original image. Returns candidate
    masks (N x H x W uint8, 0/1) and their quality scores (N floats), best guesses first
    for tier 1 as the model ranks them.
    """

    def __init__(
        self,
        manifest: Manifest | None,
        engine: str = "auto",
        threads: int | None = None,
    ):
        self.manifest = manifest
        self.encoder = self.decoder = None
        if manifest:
            self.encoder = OnnxModel(store.model_path(manifest), engine, threads)
            self.decoder = OnnxModel(
                store.extra_path(manifest, "decoder"), engine, threads
            )
        self.size = (
            int(manifest.io.get("input", {}).get("size", 1024)) if manifest else 0
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
    ) -> Segmenter:
        """Choose and fetch the model (downloads it unless offline); tier 0 needs no model."""
        from . import resolve_model

        m = resolve_model("segment", model, tier, registry, allow_noncommercial)
        if m is not None:
            store.pull(m)
        return cls(m, engine, threads)

    @property
    def tier(self) -> int:
        return self.manifest.tier if self.manifest else 0

    def embed(self, image: np.ndarray) -> Embedding:
        if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
            raise ValueError("image must be HxWx3 uint8 (BGR)")
        h, w = image.shape[:2]
        if self.encoder is None:
            return Embedding((h, w), 1.0, None, image.copy())
        scale = self.size / max(h, w)
        size = (max(1, round(w * scale)), max(1, round(h * scale)))
        rgb = cv2.cvtColor(
            cv2.resize(image, size, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB
        )
        features = self.encoder.run({"input_image": rgb.astype(np.float32)})[0]
        return Embedding((h, w), scale, features, None)

    def segment(
        self,
        embedding: Embedding,
        points: list[tuple[float, float, int]] | None = None,
        box: tuple[float, float, float, float] | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        points = list(points or [])
        if not points and box is None:
            raise ValueError("a prompt needs at least one point or a box")
        if embedding.features is None or self.decoder is None:
            return self._grabcut(embedding, points, box)
        coords = [[x, y] for x, y, _ in points]
        labels = [1.0 if label else 0.0 for _, _, label in points]
        if box is not None:
            coords += [[box[0], box[1]], [box[2], box[3]]]
            labels += [2.0, 3.0]
        else:  # SAM's convention: a padding point when there is no box
            coords.append([0.0, 0.0])
            labels.append(-1.0)
        masks, scores, _ = self.decoder.run(
            {
                "image_embeddings": embedding.features,
                "point_coords": np.array([coords], np.float32) * embedding.scale,
                "point_labels": np.array([labels], np.float32),
                "mask_input": np.zeros((1, 1, 256, 256), np.float32),
                "has_mask_input": np.zeros(1, np.float32),
                "orig_im_size": np.array(embedding.shape, np.float32),
            }
        )
        return (masks[0] > 0).astype(np.uint8), scores[0].astype(np.float32)

    def _grabcut(self, embedding, points, box) -> tuple[np.ndarray, np.ndarray]:
        image = embedding.image
        h, w = embedding.shape
        if box is None:  # a box around the clicks, with a margin
            xs = [x for x, _, label in points if label]
            ys = [y for _, y, label in points if label]
            if not xs:
                return np.zeros((1, h, w), np.uint8), np.zeros(1, np.float32)
            m = 0.25 * max(h, w)
            box = (min(xs) - m, min(ys) - m, max(xs) + m, max(ys) + m)
        x0, y0 = int(max(0, box[0])), int(max(0, box[1]))
        x1, y1 = int(min(w, box[2])), int(min(h, box[3]))
        if x1 - x0 < 2 or y1 - y0 < 2:
            return np.zeros((1, h, w), np.uint8), np.zeros(1, np.float32)
        mask = np.full((h, w), cv2.GC_BGD, np.uint8)
        mask[y0:y1, x0:x1] = cv2.GC_PR_FGD
        for x, y, label in points:
            sure = int(cv2.GC_FGD if label else cv2.GC_BGD)
            cv2.circle(mask, (int(x), int(y)), GRABCUT_SEED, (sure,), thickness=-1)
        bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
        cv2.grabCut(
            image,
            mask,
            (0, 0, 0, 0),
            bgd,
            fgd,
            GRABCUT_ITERATIONS,
            cv2.GC_INIT_WITH_MASK,
        )
        out = ((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD)).astype(np.uint8)
        return out[None], np.array([0.5], np.float32)

    def close(self) -> None:
        for model in (self.encoder, self.decoder):
            if model:
                model.close()

    def __enter__(self) -> Segmenter:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
