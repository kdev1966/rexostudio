"""Text recognition of one text line (CTC models such as PaddleOCR recognisers).

Finding the lines is the caller's job (a balloon, a caption…): this task reads one line.
Tier 0 has no model: it returns no text, and the user types it (PRD: manual entry).
"""

from __future__ import annotations

import re

import cv2
import numpy as np

from .. import store
from ..registry import Manifest, Registry
from ..runtimes.onnx import OnnxModel

_LATIN_RUN = re.compile(r"[a-zA-Z0-9 :*./%+,'’\-]")
_ARABIC = re.compile("[\u0600-\u06ff\u0750-\u077f\ufb50-\ufdff\ufe70-\ufeff]")


def reverse_arabic_runs(text: str) -> str:
    """PaddleOCR's rule for Arabic models: reverse the runs, keep Latin and digit runs forward.

    A line without any Arabic letter is left as it is (it is left-to-right text).
    """
    if not _ARABIC.search(text):
        return text
    runs: list[str] = []
    latin = ""
    for ch in text:
        if _LATIN_RUN.match(ch):
            latin += ch
            continue
        if latin:
            runs.append(latin)
            latin = ""
        runs.append(ch)
    if latin:
        runs.append(latin)
    return "".join(reversed(runs))


def ctc_decode(probs: np.ndarray, charset: list[str]) -> tuple[str, float]:
    """Greedy CTC decoding: (text, mean probability of the emitted characters)."""
    best = probs.argmax(axis=1)
    out, conf, prev = [], [], -1
    for t, i in enumerate(best):
        if i != prev and i != 0 and i < len(charset):
            out.append(charset[i])
            conf.append(float(probs[t, i]))
        prev = int(i)
    return "".join(out), (float(np.mean(conf)) if conf else 0.0)


class TextRecognizer:
    """``TextRecognizer.load()`` then ``rec(line_image) -> (text, confidence)``.

    ``line_image``: one text line, grey or BGR uint8, dark text on a light background.
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
        self.charset: list[str] = []
        if manifest:
            words = (
                store.extra_path(manifest, "dict")
                .read_text(encoding="utf-8")
                .splitlines()
            )
            self.charset = ["<blank>", *words, " "]

    @classmethod
    def load(
        cls,
        model: str | None = None,
        tier: int | str = "auto",
        registry: Registry | None = None,
        allow_noncommercial: bool | None = None,
        engine: str = "auto",
        threads: int | None = None,
    ) -> TextRecognizer:
        """Choose and fetch the model (downloads it unless offline); tier 0 needs no model."""
        from . import resolve_model

        m = resolve_model("ocr", model, tier, registry, allow_noncommercial)
        if m is not None:
            store.pull(m)
        return cls(m, engine, threads)

    @property
    def tier(self) -> int:
        return self.manifest.tier if self.manifest else 0

    def _preprocess(self, line: np.ndarray, manifest: Manifest) -> np.ndarray:
        spec = manifest.io.get("input", {})
        height = int(spec.get("height", 48))
        rgb = (
            cv2.cvtColor(line, cv2.COLOR_GRAY2RGB)
            if line.ndim == 2
            else cv2.cvtColor(line, cv2.COLOR_BGR2RGB)
        )
        h, w = rgb.shape[:2]
        width = max(16, round(w * height / max(h, 1)))
        x: np.ndarray = (
            cv2.resize(rgb, (width, height), interpolation=cv2.INTER_CUBIC).astype(
                np.float32
            )
            / 255.0
        )
        x = (x - np.array(spec.get("mean", [0.5] * 3), np.float32)) / np.array(
            spec.get("std", [0.5] * 3), np.float32
        )
        return np.ascontiguousarray(x.transpose(2, 0, 1)[None])

    def __call__(self, line: np.ndarray) -> tuple[str, float]:
        if (
            line.dtype != np.uint8
            or line.ndim not in (2, 3)
            or min(line.shape[:2]) == 0
        ):
            raise ValueError("line must be a non-empty uint8 grey or BGR image")
        if self.model is None or self.manifest is None:
            return "", 0.0
        probs = self.model.run(self._preprocess(line, self.manifest))[0][0]
        text, conf = ctc_decode(probs, self.charset)
        if self.manifest.io.get("output", {}).get("order") == "arabic_runs_reversed":
            text = reverse_arabic_runs(text)
        return text.strip(), conf

    def close(self) -> None:
        if self.model:
            self.model.close()

    def __enter__(self) -> TextRecognizer:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
