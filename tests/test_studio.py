"""Chaine de production : Blender (scene 3D), EffectCraft (titres), recette clip drone."""
import json
import os
import shutil
import socketserver
import stat
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from montagia import blender, config, effectcraft, studio  # noqa: E402
from montagia.jobs import Job  # noqa: E402

# Faux Blender : ecrit la video demandee, annonce chaque image comme le vrai
FAKE_BLENDER = """#!/bin/bash
out="${@: -4:1}"
for i in 1 2 3 4; do echo "IMAGE $i"; done
echo "MESURE 3.6.23 sequence brouillon : 4 image(s) en 2.0 s (0.50 s par image)"
echo video > "$out"
"""

BROKEN_BLENDER = """#!/bin/bash
echo "Error: Python script failed"
exit 1
"""


def _write(path, data="x"):
    with open(path, "wb" if isinstance(data, bytes) else "w") as fh:
        fh.write(data)
    return path


def _script(folder, name, body):
    path = os.path.join(folder, name)
    with open(path, "w") as fh:
        fh.write(body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    return path


class BlenderCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rexo-blender-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.couple = os.path.join(self.tmp, "maries.png")
        _write(self.couple, b"png")
        self.scene = os.path.join(self.tmp, "jardin.blend")
        _write(self.scene, b"blend")

    def _with_bin(self, body):
        return mock.patch.object(config, "BLENDER_BIN", _script(self.tmp, "Blender", body))

    def test_render_reports_progress_and_measure(self):
        seen = []
        out = os.path.join(self.tmp, "sortie", "scene.mp4")
        with self._with_bin(FAKE_BLENDER):
            result = blender.render(self.couple, self.scene, out, "orbite", 4 / 30.0, "brouillon",
                                    progress=seen.append)
        self.assertTrue(os.path.isfile(out))
        self.assertEqual(result["frames"], 4)
        self.assertEqual(result["seconds"], 2.0)
        self.assertEqual(seen[-1], 1.0)

    def test_render_failure_shows_blender_message(self):
        with self._with_bin(BROKEN_BLENDER), \
                self.assertRaisesRegex(blender.BlenderError, "Python script failed"):
            blender.render(self.couple, self.scene, os.path.join(self.tmp, "x.mp4"))

    def test_render_rejects_unknown_motion_and_quality(self):
        with self._with_bin(FAKE_BLENDER):
            with self.assertRaises(blender.BlenderError):
                blender.render(self.couple, self.scene, os.path.join(self.tmp, "x.mp4"), motion="looping")
            with self.assertRaises(blender.BlenderError):
                blender.render(self.couple, self.scene, os.path.join(self.tmp, "x.mp4"), quality="ultra")

    def test_scenes_lists_blend_files(self):
        folder = os.path.join(self.tmp, "scenes")
        os.makedirs(folder)
        for name in ("jardin_nuit.blend", "salle_des_fetes.blend", "notes.txt", ".cache.blend"):
            open(os.path.join(folder, name), "w").close()
        with mock.patch.object(config, "SCENES_3D_DIR", folder):
            self.assertEqual([s["id"] for s in blender.scenes()], ["jardin_nuit", "salle_des_fetes"])
            self.assertTrue(blender.scene_path("jardin_nuit").endswith("jardin_nuit.blend"))
            with self.assertRaises(blender.BlenderError):
                blender.scene_path("plage")


class FakeEffectCraft(object):
    """Serveur de controle factice : une requete JSON par ligne, une reponse."""

    def __init__(self, tmp):
        self.calls = []
        self.tmp = tmp
        self.jobs_polls = 0
        fake = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                request = json.loads(self.rfile.readline().decode("utf-8"))
                reply = fake.answer(request)
                reply["id"] = request.get("id")
                self.wfile.write((json.dumps(reply) + "\n").encode("utf-8"))

        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def commands(self):
        return [c["command"] for c in self.calls]

    def answer(self, request):
        if request.get("method") != "engine.execute":
            return {"ok": False, "error": "unknown method"}
        command = request["params"]["command"]
        params = request["params"].get("params", {})
        self.calls.append({"command": command, "params": params})
        if command == "command.list":
            return {"ok": True, "result": [{"id": c} for c in effectcraft.REQUIRED]}
        if command == "file.import":
            return {"ok": True, "result": {"items": [1], "errors": [], "comps": []}}
        if command == "script.run":
            code = params["code"]
            result = "2,9,1920,1080" if "numItems" in code and "source.id" in code else "6.5,2.5"
            return {"ok": True, "result": {"ok": True, "result": result, "error": None}}
        if command == "essential.importTemplate":
            return {"ok": True, "result": {"comp": 27, "layer": 141}}
        if command == "essential.instance":
            return {"ok": True, "result": {"controls": [
                {"control": 113, "name": "Title", "type": "text"},
                {"control": 114, "name": "Subtitle", "type": "text"}]}}
        if command == "renderQueue.add":
            return {"ok": True, "result": {"id": 1}}
        if command == "renderQueue.render":
            _write(params.get("output") or self.calls[-2]["params"]["output"], "mp4")
            return {"ok": True, "result": {}}
        if command == "jobs.list":
            self.jobs_polls += 1
            running = [{"fraction": 0.5}] if self.jobs_polls == 1 else []
            return {"ok": True, "result": {"running": running, "finished": []}}
        if command == "renderQueue.list":
            return {"ok": True, "result": {"items": [{"id": 1, "status": "Done"}]}}
        if command == "file.saveAs":
            _write(params["path"], "projet")
            return {"ok": True, "result": {"path": params["path"]}}
        if command == "essential.set":
            return {"ok": True, "result": params["value"]}
        return {"ok": True, "result": None}


class EffectCraftCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rexo-ec-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.fake = FakeEffectCraft(self.tmp)
        self.addCleanup(self.fake.stop)
        self.client = effectcraft.Client(self.fake.port, timeout=5)

    def test_error_reply_raises(self):
        with self.assertRaises(effectcraft.EffectCraftError):
            self.client.call("doc.inspect")

    def test_connect_checks_required_commands(self):
        with mock.patch.object(config, "EFFECTCRAFT_PORT", self.fake.port):
            client = effectcraft.connect()
        self.assertEqual(client.port, self.fake.port)
        self.assertIn("command.list", self.fake.commands())

    def test_title_over_video_fills_fields_and_renders_whole_comp(self):
        out = os.path.join(self.tmp, "Clips_3D", "clip.mp4")
        with mock.patch("time.sleep"):
            result = effectcraft.title_over_video(self.client, "/v/scene.mp4", "/t/titre.ectemplate",
                                                  "Zied & Namsia", "16 novembre 2026", out)
        self.assertTrue(os.path.isfile(out))
        self.assertEqual(result["title_at"], 6.5)
        sets = {c["params"]["control"]: c["params"]["value"] for c in self.fake.calls
                if c["command"] == "essential.set"}
        self.assertEqual(sets, {113: "Zied & Namsia", 114: "16 novembre 2026"})
        add = next(c for c in self.fake.calls if c["command"] == "renderQueue.add")
        self.assertEqual(add["params"]["comp"], 2)
        self.assertEqual(add["params"]["timeSpan"], "comp")
        render = next(c for c in self.fake.calls if c["command"] == "renderQueue.render")
        self.assertFalse(render["params"]["wait"])           # suivi par jobs.list
        self.assertGreaterEqual(self.fake.jobs_polls, 2)

    def test_close_saves_before_quitting_and_cleans_up(self):
        with mock.patch.object(effectcraft, "_running", return_value=False):
            effectcraft.close(self.client, self.tmp)
        self.assertEqual(self.fake.commands()[-2:], ["file.saveAs", "app.quit"])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, ".rexo-effectcraft.ecproj")))


class ClipDroneCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rexo-studio-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.event = os.path.join(self.tmp, "2026-11-16_Mariage_Test")
        self.photo = os.path.join(self.event, "02_Photos", "IMG_0001.jpg")
        os.makedirs(os.path.dirname(self.photo))
        _write(self.photo, b"jpg")
        self.scenes = os.path.join(self.tmp, "scenes")
        os.makedirs(self.scenes)
        open(os.path.join(self.scenes, "jardin_nuit.blend"), "w").close()
        patches = [mock.patch.object(config, "SCENES_3D_DIR", self.scenes),
                   mock.patch.object(blender, "installed", return_value=True),
                   mock.patch.object(studio, "couple_cutout", side_effect=self._cutout)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _cutout(self, _src, out_png, *_a, **_k):
        _write(out_png, b"png")
        return out_png

    @staticmethod
    def _render(_couple, _scene, out, *_a, progress=None, **_k):
        _write(out, "scene")
        progress(1.0)
        return {"path": out, "frames": 270, "seconds": 450.0, "per_frame": 1.67}

    def test_untitled_clip_lands_in_rendus_and_temp_files_go(self):
        job = Job("studio")
        with mock.patch.object(blender, "render", side_effect=self._render):
            result = studio.clip_drone(job, self.event, self.photo, title="")
        self.assertEqual(result["path"], os.path.join("06_Rendus", "Clips_3D", "IMG_0001_clip_drone_sequence.mp4"))
        self.assertTrue(os.path.isfile(os.path.join(self.event, result["path"])))
        self.assertFalse(result["titled"])
        self.assertEqual(os.listdir(os.path.join(self.event, studio.WORK_DIR)), [])

    def test_titled_clip_goes_through_effectcraft_and_closes_it(self):
        job = Job("studio")
        client = mock.Mock()
        title = mock.Mock(side_effect=lambda *a, **_k: _write(a[5]))
        with mock.patch.object(blender, "render", side_effect=self._render), \
                mock.patch.object(effectcraft, "installed", return_value=True), \
                mock.patch.object(effectcraft, "connect", return_value=client), \
                mock.patch.object(effectcraft, "ensure_default_title", return_value="/t/simple.ectemplate"), \
                mock.patch.object(effectcraft, "title_over_video", title), \
                mock.patch.object(effectcraft, "close") as close:
            result = studio.clip_drone(job, self.event, self.photo, motion="orbite",
                                       title="Zied & Namsia", subtitle="16 novembre 2026")
        self.assertTrue(result["titled"])
        self.assertEqual(title.call_args[0][3:5], ("Zied & Namsia", "16 novembre 2026"))
        close.assert_called_once()
        self.assertEqual(os.listdir(os.path.join(self.event, studio.WORK_DIR)), [])

    def test_blender_failure_becomes_studio_error(self):
        job = Job("studio")
        with mock.patch.object(blender, "render", side_effect=blender.BlenderError("GPU perdu")), \
                self.assertRaisesRegex(studio.StudioError, "GPU perdu"):
            studio.clip_drone(job, self.event, self.photo)
        self.assertFalse(os.listdir(os.path.join(self.event, studio.CLIPS_DIR)))

    def test_unexpected_failure_leaves_no_empty_file(self):
        job = Job("studio")
        with mock.patch.object(blender, "render", side_effect=KeyError("id")), \
                self.assertRaises(KeyError):
            studio.clip_drone(job, self.event, self.photo)
        self.assertFalse(os.listdir(os.path.join(self.event, studio.CLIPS_DIR)))

    def test_french_date(self):
        self.assertEqual(studio.french_date("2026-11-16"), "16 novembre 2026")
        self.assertEqual(studio.french_date("2026-08-01"), "1 août 2026")
        self.assertEqual(studio.french_date(""), "")


if __name__ == "__main__":
    unittest.main()
