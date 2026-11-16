"""Tests for embedkit's core: hardware, registry, licences, store and CLI (no network)."""

from __future__ import annotations

import hashlib
import http.server
import platform
import threading
from pathlib import Path

import pytest
import yaml
from embedkit import EmbedkitError, hardware, licenses, store
from embedkit.cli import main
from embedkit.registry import ManifestError, Registry, parse_manifest

PAYLOAD = bytes(range(256)) * 4096  # 1 MiB of model "weights"
SHA = hashlib.sha256(PAYLOAD).hexdigest()
REV = "a" * 40


def manifest_dict(**over) -> dict:
    data = {
        "id": "toy-depth",
        "task": "depth",
        "tier": 1,
        "runtime": "onnx",
        "source": {"repo": "org/toy", "file": "onnx/model.onnx", "revision": REV},
        "sha256": SHA,
        "size_mb": 1,
        "license": {"code": "Apache-2.0", "weights": "Apache-2.0", "commercial": True},
    }
    data.update(over)
    return data


def write_manifest(folder: Path, **over) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    data = manifest_dict(**over)
    path = folder / f"{data['id']}.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Own cache, no extra manifest path, online by default."""
    monkeypatch.setenv(store.ENV_CACHE, str(tmp_path / "cache"))
    for var in (
        "EMBEDKIT_MODELS_PATH",
        store.ENV_OFFLINE,
        licenses.ENV_ALLOW,
        store.ENV_ENDPOINT,
    ):
        monkeypatch.delenv(var, raising=False)


class RangeHandler(http.server.BaseHTTPRequestHandler):
    """Serves PAYLOAD at any path, honouring `Range: bytes=N-`; counts requests."""

    requests: list[str] = []
    body = PAYLOAD

    def do_GET(self):  # noqa: N802
        RangeHandler.requests.append(self.headers.get("Range", ""))
        data, status = self.body, 200
        rng = self.headers.get("Range")
        if rng:
            start = int(rng.removeprefix("bytes=").rstrip("-"))
            if start >= len(data):
                self.send_response(416)
                self.end_headers()
                return
            data, status = data[start:], 206
        self.send_response(status)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture
def server(monkeypatch):
    RangeHandler.requests = []
    RangeHandler.body = PAYLOAD
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), RangeHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv(
        store.ENV_ENDPOINT, f"http://127.0.0.1:{httpd.server_address[1]}"
    )
    yield RangeHandler
    httpd.shutdown()


# --- hardware -----------------------------------------------------------------------


def test_probe_describes_this_machine():
    p = hardware.probe()
    assert p.ram_gb > 0 and p.logical_cores >= p.physical_cores >= 1
    assert p.recommended_tier in (0, 1, 2)
    if platform.system() == "Darwin" and platform.machine() == "x86_64":
        assert p.cpu and p.avx2 in (True, False)


@pytest.mark.parametrize(
    ("ram", "accel", "tier"),
    [
        (4, [], 0),
        (16, [], 1),
        (16, ["CoreMLExecutionProvider"], 1),
        (16, ["CUDAExecutionProvider"], 2),
        (4, ["CUDAExecutionProvider"], 0),
    ],
)
def test_recommend_tier(ram, accel, tier):
    assert hardware.recommend_tier(ram, accel) == tier


# --- registry -----------------------------------------------------------------------


def test_parse_valid_manifest():
    m = parse_manifest(manifest_dict())
    assert m.filename == "model.onnx" and m.license.commercial is True


@pytest.mark.parametrize(
    "over",
    [
        {"task": "dance"},
        {"runtime": "ollama"},
        {"tier": 3},
        {"sha256": "abc"},
        {"id": "Bad Id"},
        {"source": {"repo": "org/toy", "file": "m.onnx", "revision": "main"}},
        {"license": {"code": "MIT", "commercial": "maybe"}},
    ],
)
def test_invalid_manifests(over):
    with pytest.raises(ManifestError):
        parse_manifest(manifest_dict(**over))


def test_missing_field():
    data = manifest_dict()
    del data["sha256"]
    with pytest.raises(ManifestError, match="sha256"):
        parse_manifest(data)


def test_registry_order_override_and_env(tmp_path, monkeypatch):
    base, app, env = tmp_path / "base", tmp_path / "app", tmp_path / "env"
    write_manifest(base, id="big", tier=1, size_mb=90)
    write_manifest(base, id="small", tier=1, size_mb=10)
    write_manifest(base, id="classic", tier=0, size_mb=1)
    write_manifest(app, id="small", tier=1, size_mb=12)  # app overrides
    write_manifest(env, id="ocr-x", task="ocr")
    monkeypatch.setenv("EMBEDKIT_MODELS_PATH", str(env))
    reg = Registry(extra_dirs=[base, app], include_builtin=False)
    assert len(reg) == 4
    assert reg.get("small").size_mb == 12
    assert [m.id for m in reg.for_task("depth")] == ["small", "big", "classic"]
    assert [m.id for m in reg.for_task("depth", max_tier=0)] == ["classic"]
    with pytest.raises(EmbedkitError, match="inconnu"):
        reg.get("nope")


def test_builtin_manifests_are_valid():
    Registry()  # raises on any invalid built-in manifest


# --- licences -----------------------------------------------------------------------


def test_licence_policy(monkeypatch, capsys):
    ok = parse_manifest(manifest_dict())
    unknown = parse_manifest(
        manifest_dict(license={"code": "MIT", "weights": "?", "commercial": "unknown"})
    )
    nc = parse_manifest(
        manifest_dict(
            license={"code": "MIT", "weights": "CC-BY-NC", "commercial": False}
        )
    )
    licenses.check(ok)
    for m in (unknown, nc):
        with pytest.raises(licenses.LicenseError):
            licenses.check(m)
    licenses.check(nc, allow_noncommercial=True)
    assert "Attention" in capsys.readouterr().err
    monkeypatch.setenv(licenses.ENV_ALLOW, "1")
    licenses.check(unknown)
    assert [r[3] for r in licenses.audit([ok, unknown, nc])] == [
        "commerciale",
        "inconnue",
        "non commerciale",
    ]


# --- store --------------------------------------------------------------------------


def test_pull_verify_and_cache(server):
    m = parse_manifest(manifest_dict())
    assert not store.is_installed(m)
    path = store.pull(m)
    assert path.read_bytes() == PAYLOAD and store.verify(m)
    assert path == store.model_path(m) and REV[:12] in str(path)
    store.pull(m)  # already installed: no new request
    assert len(server.requests) == 1


def test_resume_partial_download(server):
    m = parse_manifest(manifest_dict())
    part = store.model_path(m).with_name("model.onnx.part")
    part.parent.mkdir(parents=True)
    part.write_bytes(PAYLOAD[:300_000])
    store.pull(m)
    assert server.requests == ["bytes=300000-"]
    assert store.verify(m) and not part.exists()


def test_complete_part_file(server):
    m = parse_manifest(manifest_dict())
    part = store.model_path(m).with_name("model.onnx.part")
    part.parent.mkdir(parents=True)
    part.write_bytes(PAYLOAD)
    store.pull(m)  # server answers 416, file is complete
    assert store.verify(m)


def test_corrupt_download_is_rejected(server):
    server.body = b"x" * 1000
    m = parse_manifest(manifest_dict())
    with pytest.raises(store.StoreError, match="corrompu"):
        store.pull(m)
    assert not store.is_installed(m)
    assert not list(store.model_path(m).parent.glob("*.part"))


def test_http_error(server, monkeypatch):
    monkeypatch.setenv(store.ENV_ENDPOINT, "http://127.0.0.1:9")  # closed port
    with pytest.raises(store.StoreError, match="impossible"):
        store.pull(parse_manifest(manifest_dict()))


def test_offline_mode_never_downloads(server, monkeypatch):
    monkeypatch.setenv(store.ENV_OFFLINE, "1")
    m = parse_manifest(manifest_dict())
    with pytest.raises(store.StoreError, match="hors ligne"):
        store.pull(m)
    assert server.requests == []


# --- CLI ----------------------------------------------------------------------------


def test_cli_list_pull_verify_audit(server, tmp_path, monkeypatch, capsys):
    models = tmp_path / "models"
    write_manifest(models)
    write_manifest(
        models,
        id="nc-model",
        license={"code": "MIT", "weights": "CC-BY-NC", "commercial": False},
    )
    monkeypatch.setenv(store.ENV_OFFLINE, "1")
    assert main(["--models-path", str(models), "models", "list"]) == 0
    assert "toy-depth" in capsys.readouterr().out  # list works offline
    monkeypatch.delenv(store.ENV_OFFLINE)

    assert main(["--models-path", str(models), "models", "pull", "toy-depth"]) == 0
    assert (
        main(["--models-path", str(models), "models", "pull", "nc-model"]) == 2
    )  # licence refused
    assert "commercial" in capsys.readouterr().err
    assert main(["--models-path", str(models), "models", "verify"]) == 0

    store.model_path(parse_manifest(manifest_dict())).write_bytes(b"tampered")
    assert main(["--models-path", str(models), "models", "verify", "toy-depth"]) == 1
    assert (
        main(["--models-path", str(models), "licenses", "audit"]) == 1
    )  # nc-model present
    assert main(["hardware"]) == 0


# --- URL sources and companion files --------------------------------------------------


def test_url_source_and_extras(server):
    data = manifest_dict(
        source={
            "url": "https://example.org/models/v1/model.onnx",
            "revision": "release-1.0",
        },
        extras=[
            {
                "name": "dict",
                "url": "https://example.org/models/v1/dict.txt",
                "sha256": SHA,
            }
        ],
    )
    m = parse_manifest(data)
    assert m.filename == "model.onnx" and m.extras[0].name == "dict"
    assert store.model_dir(m).name == "release-1.0"
    assert store.extra_path(m, "dict").name == "dict.txt"
    with pytest.raises(EmbedkitError, match="annexe"):
        store.extra_path(m, "nope")


def test_url_must_be_https():
    with pytest.raises(ManifestError, match="https"):
        parse_manifest(
            manifest_dict(source={"url": "http://example.org/m.onnx", "revision": "x"})
        )


def test_pull_downloads_model_and_extras_from_hf(server):
    m = parse_manifest(
        manifest_dict(extras=[{"name": "dict", "file": "onnx/dict.txt", "sha256": SHA}])
    )
    assert not store.is_installed(m)
    store.pull(m)
    assert store.is_installed(m) and store.verify(m)
    assert store.extra_path(m, "dict").read_bytes() == PAYLOAD
    assert len(server.requests) == 2  # model + dictionary
    store.extra_path(m, "dict").write_bytes(b"broken")
    assert not store.verify(m)
