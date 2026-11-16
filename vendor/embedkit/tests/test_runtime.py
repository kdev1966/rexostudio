"""Tests for the ONNX runtime, the depth task and the bench (tiny generated models, no network)."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import numpy as np
import onnx
import pytest
import yaml
from embedkit import EmbedkitError, licenses, store
from embedkit.bench import measure, run_isolated
from embedkit.cli import main
from embedkit.registry import Registry
from embedkit.runtimes.onnx import OnnxModel, RuntimeLoadError
from embedkit.tasks import DepthEstimator, resolve_model
from onnx import TensorProto, helper

REAL_CACHE = Path.home() / ".cache" / "embedkit"


def toy_depth_model(path: Path) -> Path:
    """[1,3,H,W] -> mean over channels -> [1,H,W]: brighter = 'closer' (disparity)."""
    x = helper.make_tensor_value_info(
        "pixel_values", TensorProto.FLOAT, [1, 3, "h", "w"]
    )
    y = helper.make_tensor_value_info(
        "predicted_depth", TensorProto.FLOAT, [1, "h", "w"]
    )
    node = helper.make_node(
        "ReduceMean", ["pixel_values"], ["predicted_depth"], axes=[1], keepdims=0
    )
    graph = helper.make_graph([node], "toy_depth", [x], [y])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 8
    onnx.save(model, path)
    return path


def install_toy(
    folder: Path, model_id: str = "toy-depth", commercial=True, tier: int = 1
) -> str:
    """Write a manifest for the toy model and place the file in the (isolated) cache."""
    src = toy_depth_model(folder / f"{model_id}.onnx")
    data = {
        "id": model_id,
        "task": "depth",
        "tier": tier,
        "runtime": "onnx",
        "source": {"repo": "org/toy", "file": "model.onnx", "revision": "b" * 40},
        "sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
        "size_mb": 0.001,
        "license": {"code": "MIT", "weights": "MIT", "commercial": commercial},
        "io": {
            "input": {
                "name": "pixel_values",
                "size": 28,
                "mean": [0, 0, 0],
                "std": [1, 1, 1],
            }
        },
    }
    (folder / f"{model_id}.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    m = Registry([folder], include_builtin=False).get(model_id)
    dest = store.model_path(m)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(src.read_bytes())
    return model_id


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv(store.ENV_CACHE, str(tmp_path / "cache"))
    monkeypatch.setenv(
        store.ENV_OFFLINE, "1"
    )  # nothing in these tests may touch the network
    for var in ("EMBEDKIT_MODELS_PATH", licenses.ENV_ALLOW):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def models(tmp_path) -> Path:
    folder = tmp_path / "models"
    folder.mkdir()
    return folder


def image_with_bright_bottom(h: int = 60, w: int = 40) -> np.ndarray:
    img = np.full((h, w, 3), 30, np.uint8)
    img[h // 2 :] = 220
    return img


# --- runtime ------------------------------------------------------------------------


@pytest.mark.parametrize("engine", ["onnxruntime", "opencv", "auto"])
def test_engines_agree(tmp_path, engine):
    path = toy_depth_model(tmp_path / "m.onnx")
    x = np.random.default_rng(1).standard_normal((1, 3, 8, 6)).astype(np.float32)
    with OnnxModel(path, engine) as model:
        out = model.run(x)[0]
        assert model.engine == ("onnxruntime" if engine == "auto" else engine)
    assert np.allclose(np.squeeze(out), x.mean(axis=1)[0], atol=1e-5)
    assert model.engine is None  # closed


def test_fallback_to_opencv_when_onnxruntime_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "onnxruntime", None)  # import fails
    model = OnnxModel(toy_depth_model(tmp_path / "m.onnx")).load()
    assert model.engine == "opencv"
    assert "repli sur OpenCV DNN" in capsys.readouterr().err


def test_unloadable_model(tmp_path):
    bad = tmp_path / "bad.onnx"
    bad.write_bytes(b"not onnx")
    with pytest.raises(RuntimeLoadError, match="Impossible de charger"):
        OnnxModel(bad).load()
    with pytest.raises(RuntimeLoadError, match="introuvable"):
        OnnxModel(tmp_path / "missing.onnx").load()


def test_lazy_loading(tmp_path):
    model = OnnxModel(toy_depth_model(tmp_path / "m.onnx"))
    assert model.engine is None
    model.run(np.zeros((1, 3, 4, 4), np.float32))
    assert model.engine == "onnxruntime"


# --- model choice -------------------------------------------------------------------


def test_resolve_model(models):
    install_toy(models)
    install_toy(models, "nc-depth", commercial=False, tier=2)
    reg = Registry([models], include_builtin=False)
    assert resolve_model("depth", tier=2, registry=reg).id == "toy-depth"  # nc skipped
    assert (
        resolve_model("depth", tier=2, registry=reg, allow_noncommercial=True).id
        == "nc-depth"
    )
    assert resolve_model("depth", tier=0, registry=reg) is None
    with pytest.raises(licenses.LicenseError):
        resolve_model("depth", model="nc-depth", registry=reg)
    with pytest.raises(EmbedkitError, match="sert à la tâche"):
        resolve_model("ocr", model="toy-depth", registry=reg)


def test_offline_skips_models_not_installed(models):
    install_toy(models)
    reg = Registry([models], include_builtin=False)
    store.model_path(reg.get("toy-depth")).unlink()
    assert resolve_model("depth", tier=1, registry=reg) is None


# --- depth task ---------------------------------------------------------------------


def test_depth_with_model(models):
    install_toy(models)
    img = image_with_bright_bottom()
    with DepthEstimator.load(
        tier=1, registry=Registry([models], include_builtin=False)
    ) as est:
        assert est.tier == 1
        d = est(img)
    assert d.shape == img.shape[:2] and d.dtype == np.float32
    assert 0.0 <= d.min() and d.max() <= 1.0
    assert d[-5:].mean() > 0.9 and d[:5].mean() < 0.1  # bright bottom = closest


def test_depth_classic_tier0():
    est = DepthEstimator.load(tier=0, registry=Registry(include_builtin=False))
    d = est(np.zeros((10, 4, 3), np.uint8))
    assert est.tier == 0 and d[0, 0] == 0.0 and d[-1, 0] == 1.0


def test_depth_rejects_bad_image(models):
    install_toy(models)
    est = DepthEstimator.load(
        tier=1, registry=Registry([models], include_builtin=False)
    )
    with pytest.raises(ValueError):
        est(np.zeros((10, 10), np.uint8))


# --- bench --------------------------------------------------------------------------


def test_bench_in_process_and_isolated(models):
    install_toy(models)
    m = Registry([models], include_builtin=False).get("toy-depth")
    r = measure(m, runs=3)
    assert (
        r["engine"] == "onnxruntime"
        and r["infer_ms"] >= 0
        and r["input"] == [1, 3, 28, 28]
    )
    r = run_isolated(m, runs=2, models_path=[str(models)])
    assert "error" not in r and r["peak_ram_mb"] > 0


def test_cli_bench(models, capsys):
    install_toy(models)
    assert main(["--models-path", str(models), "models", "bench", "--runs", "2"]) == 0
    out = capsys.readouterr().out
    assert "toy-depth" in out and "onnxruntime" in out


# --- real model (local only) --------------------------------------------------------


def _real_depth_installed() -> bool:
    try:
        m = Registry().get("depth-anything-v2-small")
    except EmbedkitError:
        return False
    return (REAL_CACHE / m.id / m.source.revision[:12] / m.filename).is_file()


@pytest.mark.skipif(
    not _real_depth_installed(),
    reason="Depth Anything V2 Small non installé (embedkit models pull)",
)
def test_real_depth_anything(monkeypatch):
    monkeypatch.setenv(store.ENV_CACHE, str(REAL_CACHE))
    img = image_with_bright_bottom(200, 150)
    img[: img.shape[0] // 2] = 30
    with DepthEstimator.load(model="depth-anything-v2-small") as est:
        d = est(img)
    assert d.shape == (200, 150) and np.isfinite(d).all()


# --- OCR task -----------------------------------------------------------------------


def test_reverse_arabic_runs_keeps_latin_forward():
    from embedkit.tasks.ocr import reverse_arabic_runs

    # model output is in visual order: Arabic letters come reversed, Latin runs do not
    assert reverse_arabic_runs("ريمب") == "بمير"
    assert reverse_arabic_runs("ابCash") == "Cashبا"
    assert reverse_arabic_runs("Hello") == "Hello"
    assert (
        reverse_arabic_runs("Are you profitable?") == "Are you profitable?"
    )  # LTR line untouched


def test_ctc_decode_merges_repeats_and_drops_blanks():
    from embedkit.tasks.ocr import ctc_decode

    charset = ["<blank>", "a", "b", " "]
    path = [1, 1, 0, 1, 2, 2, 0, 0, 3]  # a a _ a b b _ _ space -> "aab "
    probs = np.full((len(path), 4), 0.01, np.float32)
    for t, i in enumerate(path):
        probs[t, i] = 0.97
    text, conf = ctc_decode(probs, charset)
    assert text == "aab " and conf > 0.9


def test_text_recognizer_tier0_returns_nothing():
    from embedkit.tasks import TextRecognizer

    rec = TextRecognizer.load(tier=0, registry=Registry(include_builtin=False))
    assert rec.tier == 0 and rec(np.full((20, 60), 255, np.uint8)) == ("", 0.0)


# --- inpainting task ----------------------------------------------------------------


def _picture_with_hole():
    img = np.zeros((120, 160, 3), np.uint8)
    img[:, :80] = (200, 50, 50)
    img[:, 80:] = (50, 50, 200)
    mask = np.zeros((120, 160), np.uint8)
    mask[40:80, 60:100] = 1
    img[40:80, 60:100] = (0, 255, 0)  # what must disappear
    return img, mask


def test_inpainter_tier0_fills_only_the_hole():
    from embedkit.tasks import Inpainter

    img, mask = _picture_with_hole()
    inp = Inpainter.load(tier=0, registry=Registry(include_builtin=False))
    out = inp(img, mask)
    assert inp.tier == 0 and out.shape == img.shape
    assert out[60, 70, 1] < 200  # the green patch is gone
    assert np.array_equal(out[mask == 0], img[mask == 0])  # untouched elsewhere
    assert np.array_equal(inp(img, np.zeros_like(mask)), img)


def test_inpainter_rejects_bad_input():
    from embedkit.tasks import Inpainter

    inp = Inpainter.load(tier=0, registry=Registry(include_builtin=False))
    with pytest.raises(ValueError):
        inp(np.zeros((10, 10), np.uint8), np.zeros((10, 10), np.uint8))
    with pytest.raises(ValueError):
        inp(np.zeros((10, 10, 3), np.uint8), np.zeros((5, 5), np.uint8))


def _real_migan_installed() -> bool:
    try:
        m = Registry().get("migan-512")
    except EmbedkitError:
        return False
    return (REAL_CACHE / m.id / m.source.revision[:12] / m.filename).is_file()


@pytest.mark.skipif(
    not _real_migan_installed(),
    reason="MI-GAN non installé (embedkit models pull migan-512)",
)
def test_real_migan_fills_the_hole(monkeypatch):
    from embedkit.tasks import Inpainter

    monkeypatch.setenv(store.ENV_CACHE, str(REAL_CACHE))
    img, mask = _picture_with_hole()
    with Inpainter.load(model="migan-512") as inp:
        out = inp(img, mask)
    assert out[60, 70, 1] < 150  # no more bright green
    assert np.array_equal(out[mask == 0], img[mask == 0])


# --- segmentation -----------------------------------------------------------------------


def _picture_with_disc() -> np.ndarray:
    img = np.full((160, 200, 3), (200, 180, 160), np.uint8)
    img[::8] = (190, 170, 150)  # faint texture in the background
    import cv2

    cv2.circle(img, (100, 80), 40, (30, 40, 220), -1)
    return img


def test_segmenter_tier0_cuts_the_clicked_object():
    from embedkit.tasks import Segmenter

    seg = Segmenter.load(tier=0, registry=Registry(include_builtin=False))
    img = _picture_with_disc()
    emb = seg.embed(img)
    masks, scores = seg.segment(emb, points=[(100, 80, 1)], box=(50, 30, 150, 130))
    assert seg.tier == 0 and masks.shape == (1, 160, 200) and scores.shape == (1,)
    assert masks[0, 80, 100] == 1 and masks[0, 5, 5] == 0
    assert masks[0].sum() < 2 * 3.1416 * 40 * 40  # roughly the disc, not the box
    masks, _ = seg.segment(emb, points=[(100, 80, 1)])  # a click alone works too
    assert masks[0, 80, 100] == 1


def test_segmenter_rejects_empty_prompts():
    from embedkit.tasks import Segmenter

    seg = Segmenter.load(tier=0, registry=Registry(include_builtin=False))
    with pytest.raises(ValueError):
        seg.segment(seg.embed(_picture_with_disc()))
    with pytest.raises(ValueError):
        seg.embed(np.zeros((10, 10), np.uint8))


def _real_mobilesam_installed() -> bool:
    try:
        m = Registry().get("mobilesam")
    except EmbedkitError:
        return False
    folder = REAL_CACHE / m.id / m.source.revision[:12]
    return (folder / m.filename).is_file() and all(
        (folder / Path(e.file).name).is_file() for e in m.extras
    )


@pytest.mark.skipif(
    not _real_mobilesam_installed(),
    reason="MobileSAM non installé (embedkit models pull mobilesam)",
)
def test_real_mobilesam_cuts_the_clicked_object(monkeypatch):
    from embedkit.tasks import Segmenter

    monkeypatch.setenv(store.ENV_CACHE, str(REAL_CACHE))
    with Segmenter.load(model="mobilesam") as seg:
        img = _picture_with_disc()
        masks, scores = seg.segment(seg.embed(img), points=[(100, 80, 1)])
    assert masks.shape[1:] == (160, 200) and len(scores) == len(masks)
    best = masks[int(scores.argmax())]
    assert best[80, 100] == 1 and best[5, 5] == 0
