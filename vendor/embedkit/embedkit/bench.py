"""Micro-benchmarks (EK-6): load time, median inference time and peak RAM per installed model.

Each model is measured in its own process so that peak RAM is not polluted by the others.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import numpy as np

from . import EmbedkitError, store
from .registry import Manifest, Registry


def _peak_rss_mb() -> float | None:
    try:
        import resource
    except ImportError:  # Windows
        return None
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(
        peak / 2**20 if sys.platform == "darwin" else peak / 1024, 1
    )  # bytes on macOS, KiB on Linux


def _dummy_tensor(shape: list, onnx_type: str, size: int) -> np.ndarray:
    dims = [
        d if isinstance(d, int) and d > 0 else (1 if i == 0 else 3 if i == 1 else size)
        for i, d in enumerate(shape)
    ]
    rng = np.random.default_rng(0)
    if "uint8" in onnx_type:
        return rng.integers(0, 256, dims, dtype=np.uint8)
    return rng.standard_normal(dims).astype(np.float32)


def _dummy_inputs(m: Manifest, specs: list) -> tuple[np.ndarray | dict, list[int]]:
    """Random input(s) for every model input, and the shape of the first one."""
    size = int(m.io.get("input", {}).get("size", 224) or 224)
    if not specs:  # OpenCV DNN: one float NCHW input
        x = _dummy_tensor([1, 3, size, size], "tensor(float)", size)
        return x, list(x.shape)
    if str(m.io.get("input", {}).get("layout", "")).startswith("hwc"):
        specs = [
            (name, [size, size, 3] if k == 0 else shape, typ)
            for k, (name, shape, typ) in enumerate(specs)
        ]
    feed = {name: _dummy_tensor(shape, typ, size) for name, shape, typ in specs}
    first = feed[specs[0][0]]
    return (feed if len(feed) > 1 else first), list(first.shape)


def measure(m: Manifest, runs: int = 5, engine: str = "auto") -> dict:
    """Measure one model in the current process (call through `run_isolated` for clean RAM)."""
    if m.runtime not in ("onnx", "opencv_dnn"):
        raise EmbedkitError(
            f"Bench non disponible pour le runtime « {m.runtime} » ({m.id})."
        )
    from .runtimes.onnx import OnnxModel

    started = time.perf_counter()
    model = OnnxModel(
        store.model_path(m), "opencv" if m.runtime == "opencv_dnn" else engine
    ).load()
    load_s = time.perf_counter() - started
    x, first_shape = _dummy_inputs(m, model.input_specs())
    model.run(x)  # warm-up
    times = []
    for _ in range(runs):
        t = time.perf_counter()
        model.run(x)
        times.append(time.perf_counter() - t)
    return {
        "id": m.id,
        "engine": model.engine,
        "input": first_shape,
        "load_s": round(load_s, 2),
        "infer_ms": round(1000 * float(np.median(times)), 1),
        "peak_ram_mb": _peak_rss_mb(),
        "runs": runs,
    }


def run_isolated(
    m: Manifest,
    runs: int = 5,
    engine: str = "auto",
    models_path: list[str] | None = None,
) -> dict:
    cmd = [
        sys.executable,
        "-m",
        "embedkit.bench",
        m.id,
        "--runs",
        str(runs),
        "--engine",
        engine,
    ]
    for p in models_path or []:
        cmd += ["--models-path", p]
    out = subprocess.run(cmd, capture_output=True, text=True, env=os.environ.copy())
    lines = [line for line in out.stdout.splitlines() if line.startswith("{")]
    if out.returncode != 0 or not lines:
        err = (out.stderr.strip().splitlines() or ["erreur inconnue"])[-1]
        return {"id": m.id, "error": err}
    return json.loads(lines[-1])


def _child(argv: list[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("id")
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--engine", default="auto")
    ap.add_argument("--models-path", action="append", default=[])
    a = ap.parse_args(argv)
    try:
        print(json.dumps(measure(Registry(a.models_path).get(a.id), a.runs, a.engine)))
    except EmbedkitError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(_child(sys.argv[1:]))
