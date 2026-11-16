"""ONNX models: ONNX Runtime by default, OpenCV DNN as a partial fallback (ADR 0003).

Loading is lazy (first call) and memory is released by close() or a `with` block (EK-7).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import numpy as np

from .. import EmbedkitError

ENGINES = ("auto", "onnxruntime", "opencv")


class RuntimeLoadError(EmbedkitError):
    pass


def _default_threads() -> int:
    from ..hardware import probe

    return max(1, probe().physical_cores)


class OnnxModel:
    """One ONNX model behind a small, engine-independent interface.

    ``engine="auto"`` tries ONNX Runtime, then OpenCV DNN. OpenCV DNN cannot load every
    model (dynamic shapes, recent operators): a model that fails under both raises
    RuntimeLoadError, and the calling task falls back to its tier-0 method.
    """

    def __init__(
        self, path: str | os.PathLike, engine: str = "auto", threads: int | None = None
    ):
        if engine not in ENGINES:
            raise ValueError(f"engine must be one of {ENGINES}")
        self.path = Path(path)
        self.requested_engine = engine
        self.threads = threads
        self.engine: str | None = None  # set once loaded
        self._session: Any = None  # onnxruntime.InferenceSession
        self._net: Any = None  # cv2.dnn.Net
        self.input_names: list[str] = []
        self.output_names: list[str] = []

    # -- loading -----------------------------------------------------------------------

    def _load_onnxruntime(self) -> None:
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = self.threads or _default_threads()
        opts.log_severity_level = 3
        self._session = ort.InferenceSession(
            str(self.path), opts, providers=ort.get_available_providers()
        )
        self.input_names = [i.name for i in self._session.get_inputs()]
        self.output_names = [o.name for o in self._session.get_outputs()]

    def _load_opencv(self) -> None:
        import cv2

        try:
            net = cv2.dnn.readNetFromONNX(str(self.path))
        except cv2.error as exc:
            raise RuntimeLoadError(
                f"OpenCV DNN ne sait pas charger {self.path.name} : {str(exc).splitlines()[0]}"
            ) from None
        self._net = net
        self.output_names = list(net.getUnconnectedOutLayersNames())
        self.input_names = []  # OpenCV DNN does not expose ONNX input names reliably

    def load(self) -> OnnxModel:
        if self.engine:
            return self
        if not self.path.is_file():
            raise RuntimeLoadError(f"Fichier de modèle introuvable : {self.path}")
        errors: list[str] = []
        order = (
            ["onnxruntime", "opencv"]
            if self.requested_engine == "auto"
            else [self.requested_engine]
        )
        for engine in order:
            try:
                (
                    self._load_onnxruntime
                    if engine == "onnxruntime"
                    else self._load_opencv
                )()
                self.engine = engine
                if errors:
                    print(
                        f"Attention : {errors[-1]} ; repli sur OpenCV DNN.",
                        file=sys.stderr,
                    )
                return self
            except ImportError:
                errors.append(f"{engine} n'est pas installé")
            except RuntimeLoadError as exc:
                errors.append(str(exc))
            except (
                Exception
            ) as exc:  # engine-specific load failures (bad graph, unsupported op)
                errors.append(
                    f"{engine} : {type(exc).__name__}: {str(exc).splitlines()[0][:200]}"
                )
        raise RuntimeLoadError(
            f"Impossible de charger {self.path.name} ({' ; '.join(errors)})"
        )

    # -- inference -----------------------------------------------------------------------

    def run(self, inputs: np.ndarray | dict[str, np.ndarray]) -> list[np.ndarray]:
        """Run the model; a single array is fed to the first input. Returns all outputs."""
        self.load()
        if self._session is not None:
            feed = inputs if isinstance(inputs, dict) else {self.input_names[0]: inputs}
            return self._session.run(None, feed)
        net = self._net
        if isinstance(inputs, dict):
            for name, value in inputs.items():
                net.setInput(value, name)
        else:
            net.setInput(inputs)
        out = net.forward(self.output_names)
        return list(out)

    __call__ = run

    def input_shapes(self) -> list[list[int | str | None]]:
        """Declared input shapes (ONNX Runtime only; dynamic dims are names or None)."""
        self.load()
        if self._session is None:
            return []
        return [list(i.shape) for i in self._session.get_inputs()]

    def input_specs(self) -> list[tuple[str, list[int | str | None], str]]:
        """(name, shape, ONNX type such as "tensor(uint8)") of every input (ONNX Runtime only)."""
        self.load()
        if self._session is None:
            return []
        return [(i.name, list(i.shape), i.type) for i in self._session.get_inputs()]

    # -- lifetime ------------------------------------------------------------------------

    def close(self) -> None:
        self._session = None
        self._net = None
        self.engine = None

    def __enter__(self) -> OnnxModel:
        return self.load()

    def __exit__(self, *exc) -> None:
        self.close()
