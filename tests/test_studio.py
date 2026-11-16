"""Chaine de production : bibliotheque d'animations, EffectCraft (photos, titres),
FilmCraft (projet de l'evenement), recettes clip drone, generique, detourage video."""
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

from montagia import animations, config, effectcraft, effects, filmcraft, moments, studio  # noqa: E402
from montagia.jobs import Job  # noqa: E402

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


class FakeEffectCraft(object):
    """Serveur de controle factice : une requete JSON par ligne, une reponse."""

    def __init__(self, tmp):
        self.calls = []
        self.tmp = tmp
        self.jobs_polls = 0
        self.scripts = []
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
            self.scripts.append(code)
            if "addComp" in code and "parts" in code:
                result = "5,11.6"                                  # assemblage : comp, duree
            elif "addComp" in code:
                result = "2"
            elif "frameRate" in code:
                result = "4,720,1280,30,20"                        # rush : comp, taille, cadence, duree
            else:
                result = "6.5,2.5"
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
            if self.jobs_polls == 2:
                return {"ok": False, "error": "timeout"}          # EffectCraft occupe : passager
            running = [{"fraction": 0.5}] if self.jobs_polls in (1, 3) else []
            return {"ok": True, "result": {"running": running, "finished": []}}
        if command == "renderQueue.list":
            return {"ok": True, "result": {"items": [{"id": 1, "status": "Done"}]}}
        if command == "file.saveAs":
            _write(params["path"], "projet")
            return {"ok": True, "result": {"path": params["path"]}}
        if command == "essential.set":
            return {"ok": True, "result": params["value"]}
        if command == "roto.models":
            return {"ok": True, "result": {"models": [{"id": "sam2.1-hiera-tiny", "installed": True}]}}
        if command == "objectMatte.apply":
            return {"ok": True, "result": {"effect": 28, "span": [90, 390]}}
        if command == "objectMatte.status":
            self.matte_polls = getattr(self, "matte_polls", 0) + 1
            running = self.matte_polls == 1
            return {"ok": True, "result": {"running": running, "pending": False, "computed": [90, 91]}}
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

    def test_compose_places_photos_titles_front_and_renders_whole_comp(self):
        generic = os.path.join(self.tmp, "animation")
        os.makedirs(generic)
        _write(os.path.join(generic, "composition.jsx"),
               "var comp = app.project.items.addComp('x'); new File(\"{{DOSSIER}}/decor.mp4\");")
        info = {"pixels_par_metre": 100, "premier_plan": True, "duree": 9, "emplacements": [
            {"name": "PHOTO_DEBOUT_MARIES", "kind": "debout", "width_m": 1.2, "height_m": 1.85},
            {"name": "PHOTO_CADRE_PHOTO", "kind": "cadre", "width_m": 0.7, "height_m": 0.9},
            {"name": "PHOTO_DEBOUT_INVITE", "kind": "debout", "width_m": 0.6, "height_m": 1.8}]}
        out = os.path.join(self.tmp, "Clips_3D", "clip.mp4")
        with mock.patch("time.sleep"):
            result = effectcraft.compose(self.client, generic, info,
                                         {"PHOTO_DEBOUT_MARIES": "/p/maries.png", "PHOTO_CADRE_PHOTO": "/p/photo.jpg"},
                                         out, "Zied & Namsia", "16 novembre 2026", "/t/titre.ectemplate")
        self.assertTrue(os.path.isfile(out))
        self.assertEqual(result["placed"], ["PHOTO_DEBOUT_MARIES", "PHOTO_CADRE_PHOTO"])   # l'invite est vide
        attach = [c for c in self.fake.scripts if "comp.layers.add(img)" in c]
        self.assertEqual(len(attach), 2)
        self.assertIn('comp.layer("PHOTO_DEBOUT_MARIES")', attach[0])
        self.assertIn("var standing = true", attach[0])
        self.assertIn("var standing = false", attach[1])
        self.assertTrue(any("moveToBeginning" in c for c in self.fake.scripts))       # premier plan dessus
        opened = next(c for c in self.fake.scripts if "addComp" in c)
        self.assertIn(generic + "/decor.mp4", opened)                               # {{DOSSIER}} remplace
        sets = {c["params"]["control"]: c["params"]["value"] for c in self.fake.calls
                if c["command"] == "essential.set"}
        self.assertEqual(sets, {113: "Zied & Namsia", 114: "16 novembre 2026"})
        add = next(c for c in self.fake.calls if c["command"] == "renderQueue.add")
        self.assertEqual((add["params"]["comp"], add["params"]["timeSpan"]), (2, "comp"))
        render = next(c for c in self.fake.calls if c["command"] == "renderQueue.render")
        self.assertFalse(render["params"]["wait"])           # suivi par jobs.list
        self.assertGreaterEqual(self.fake.jobs_polls, 2)

    def test_assemble_chains_parts_without_sound_and_titles(self):
        out = os.path.join(self.tmp, "Generiques", "moments.mp4")
        with mock.patch("time.sleep"):
            result = effectcraft.assemble(self.client, [("/r/a.mp4", 10, 13), ("/r/b.mp4", 40, 43.4),
                                                        ("/r/a.mp4", 20, 25.6)], out, size=(1080, 1920),
                                          title="Zied & Namsia", subtitle="", title_template="/t/t.ectemplate")
        self.assertTrue(os.path.isfile(out))
        self.assertEqual(result["duration"], 11.6)
        imports = [c for c in self.fake.calls if c["command"] == "file.import"]
        self.assertEqual(len(imports), 2)                         # un import par rush
        script = next(c for c in self.fake.scripts if "parts" in c)
        self.assertIn("var W = 1080, H = 1920", script)
        self.assertIn("audioEnabled = false", script)
        self.assertIn("[1, 10, 13]", script.replace(".0", ""))
        self.assertTrue(any(c["command"] == "essential.importTemplate" for c in self.fake.calls))

    def test_detour_video_tracks_then_renders_prores_with_alpha(self):
        out = os.path.join(self.tmp, "Videos_detourees", "rush.mov")
        with mock.patch("time.sleep"):
            result = effectcraft.detour_video(self.client, "/r/rush.mp4", (0.5, 0.25), 3.0, 10.0, out)
        apply = next(c for c in self.fake.calls if c["command"] == "objectMatte.apply")
        self.assertEqual(apply["params"]["point"], [360, 320])
        self.assertEqual((apply["params"]["frame"], apply["params"]["after"]), (90, 300))
        self.assertEqual(self.fake.commands().count("objectMatte.apply"), 1)    # jamais relance
        add = next(c for c in self.fake.calls if c["command"] == "renderQueue.add")
        self.assertEqual((add["params"]["format"], add["params"]["proresProfile"], add["params"]["channels"]),
                         ("prores", "4444", "rgba"))
        self.assertEqual((add["params"]["timeSpan"], add["params"]["start"], add["params"]["end"]),
                         ("custom", 3.0, 13.0))
        self.assertEqual(result["frames"], 300)

    def test_detour_video_box_becomes_pixels(self):
        out = os.path.join(self.tmp, "Videos_detourees", "cadre.mov")
        with mock.patch("time.sleep"):
            effectcraft.detour_video(self.client, "/r/rush.mp4", (0.2, 0.6), 3.0, 2.0, out, box=(0.0, 0.25, 0.5, 0.5))
        apply = next(c for c in self.fake.calls if c["command"] == "objectMatte.apply")
        self.assertEqual(apply["params"]["box"], [0, 320, 360, 960])

    def test_close_saves_before_quitting_and_cleans_up(self):
        with mock.patch.object(effectcraft, "_running", return_value=False):
            effectcraft.close(self.client, self.tmp)
        self.assertEqual(self.fake.commands()[-2:], ["file.saveAs", "app.quit"])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, ".rexo-effectcraft.ecproj")))


class ClipDroneCase(unittest.TestCase):
    ANIMATION = "patio_nuit__sequence__6s"
    INFO = {"titre": "Patio de nuit", "duree": 6, "emplacements": [
        {"name": "PHOTO_DEBOUT_MARIES", "kind": "debout", "width_m": 1.2, "height_m": 1.85},
        {"name": "PHOTO_CADRE_PHOTO", "kind": "cadre", "width_m": 0.7, "height_m": 0.9}]}

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rexo-studio-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.event = os.path.join(self.tmp, "2026-11-16_Mariage_Test")
        self.photo = os.path.join(self.event, "02_Photos", "IMG_0001.jpg")
        os.makedirs(os.path.dirname(self.photo))
        _write(self.photo, b"jpg")
        self.compose = mock.Mock(side_effect=lambda *a, **_k: _write(a[4]))
        self.close = mock.Mock()
        self.to_fc = mock.Mock(return_value={"project": os.path.join(self.event, "05_Montage", "Montage.fcproj")})
        patches = [
            mock.patch.object(studio, "couple_cutout", side_effect=lambda _s, out, *_a, **_k: _write(out, b"png")),
            mock.patch.object(effects, "trim", side_effect=self._trim),
            mock.patch.object(effects, "segment", side_effect=lambda args: _write(args[2], b"jpg")),
            mock.patch.object(animations, "get", side_effect=self._animation),
            mock.patch.object(effectcraft, "installed", return_value=True),
            mock.patch.object(effectcraft, "connect", return_value=mock.Mock()),
            mock.patch.object(effectcraft, "ensure_default_title", return_value="/t/simple.ectemplate"),
            mock.patch.object(effectcraft, "compose", self.compose),
            mock.patch.object(effectcraft, "close", self.close),
            mock.patch.object(filmcraft, "installed", return_value=True),
            mock.patch.object(filmcraft, "add_to_event_project", self.to_fc),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    cut_bottom = False

    def _trim(self, _src, out):
        _write(out, b"png")
        return {"ok": True, "cut_bottom": self.cut_bottom}

    def _animation(self, animation_id):
        if animation_id != self.ANIMATION:
            raise animations.AnimationError("Animation introuvable ou incomplète : %s" % animation_id)
        return "/bibliotheque/animations/" + animation_id, self.INFO

    def test_clip_goes_library_effectcraft_filmcraft_and_cleans_up(self):
        job = Job("studio")
        result = studio.clip_drone(job, self.event, self.photo, self.ANIMATION,
                                   title="Zied & Namsia", subtitle="16 novembre 2026")
        self.assertEqual(result["path"], os.path.join("06_Rendus", "Clips_3D",
                                                      "IMG_0001_patio_nuit__sequence__6s.mp4"))
        self.assertEqual(self.compose.call_args[0][1], "/bibliotheque/animations/" + self.ANIMATION)
        self.assertTrue(os.path.isfile(os.path.join(self.event, result["path"])))
        self.assertTrue(result["titled"])
        args = self.compose.call_args[0]
        self.assertEqual(sorted(args[3]), ["PHOTO_CADRE_PHOTO", "PHOTO_DEBOUT_MARIES"])
        self.assertTrue(args[3]["PHOTO_DEBOUT_MARIES"].endswith("_maries.png"))   # detoure, recadre
        self.assertTrue(args[3]["PHOTO_CADRE_PHOTO"].endswith("_photo.jpg"))      # photo amelioree
        self.assertEqual(args[5:8], ("Zied & Namsia", "16 novembre 2026", "/t/simple.ectemplate"))
        self.close.assert_called_once()
        self.to_fc.assert_called_once()
        self.assertEqual(result["filmcraft"], os.path.join("05_Montage", "Montage.fcproj"))
        self.assertEqual(os.listdir(os.path.join(self.event, studio.WORK_DIR)), [])

    def test_filmcraft_failure_keeps_the_clip(self):
        self.to_fc.side_effect = filmcraft.FilmCraftError("FilmCraft ne répond pas")
        job = Job("studio")
        result = studio.clip_drone(job, self.event, self.photo, self.ANIMATION, title="")
        self.assertTrue(os.path.isfile(os.path.join(self.event, result["path"])))
        self.assertEqual(result["filmcraft"], "")
        self.assertFalse(result["titled"])
        self.assertTrue(any("FilmCraft : envoi impossible" in m for m in job.log))

    def test_photo_not_full_length_is_flagged(self):
        self.cut_bottom = True
        job = Job("studio")
        studio.clip_drone(job, self.event, self.photo, self.ANIMATION)
        self.assertTrue(any("pas en pied" in m for m in job.log))

    def test_template_without_couple_placeholder_is_refused(self):
        self.INFO = {"emplacements": [{"name": "PHOTO_CADRE_PHOTO", "kind": "cadre", "width_m": 1, "height_m": 1}]}
        with self.assertRaisesRegex(studio.StudioError, "PHOTO_DEBOUT_MARIES"):
            studio.clip_drone(Job("studio"), self.event, self.photo, self.ANIMATION)
        self.assertFalse(os.path.isdir(os.path.join(self.event, studio.CLIPS_DIR)))

    def test_missing_animation_becomes_studio_error(self):
        with self.assertRaisesRegex(studio.StudioError, "introuvable"):
            studio.clip_drone(Job("studio"), self.event, self.photo, "plage__orbite__9s")

    def test_unexpected_failure_leaves_no_empty_file(self):
        with mock.patch.object(effectcraft, "compose", side_effect=KeyError("id")), \
                self.assertRaises(KeyError):
            studio.clip_drone(Job("studio"), self.event, self.photo, self.ANIMATION)
        self.assertFalse(os.listdir(os.path.join(self.event, studio.CLIPS_DIR)))

    def test_generique_goes_moments_effectcraft_filmcraft(self):
        found = {"moments": [
            {"rel": "01_Rushes/a.mp4", "name": "a.mp4", "start": 2, "end": 5, "score": 0.8, "people": 0.3,
             "width": 720, "height": 1280},
            {"rel": "01_Rushes/b.mp4", "name": "b.mp4", "start": 0, "end": 3, "score": 0.7, "people": 0.1,
             "width": 720, "height": 1280}]}
        assemble = mock.Mock(side_effect=lambda _c, _parts, out, **_k: {"duration": 5.6, "path": _write(out)})
        job = Job("studio")
        with mock.patch.object(moments, "find", return_value=found), \
                mock.patch.object(effectcraft, "assemble", assemble):
            result = studio.generique(job, self.event, count=4, title="Zied & Namsia")
        parts = assemble.call_args[0][1]
        self.assertEqual(parts[0], (os.path.join(self.event, "01_Rushes/a.mp4"), 2, 5))
        self.assertEqual(assemble.call_args[1]["size"], (1080, 1920))      # rushes verticaux
        self.assertTrue(result["path"].startswith(os.path.join("06_Rendus", "Generiques", "Moments_forts_")))
        self.assertEqual(self.to_fc.call_args[1]["bin_name"], "Génériques")
        self.close.assert_called_once()

    def test_detour_video_checks_point_and_sends_to_detourages_bin(self):
        rush = os.path.join(self.event, "01_Rushes", "1.mp4")
        os.makedirs(os.path.dirname(rush))
        _write(rush, b"mp4")
        with self.assertRaises(studio.StudioError):
            studio.detour_video(Job("studio"), self.event, "01_Rushes/1.mp4", [1.5, 0.2])
        detour = mock.Mock(side_effect=lambda _c, _v, _p, s, d, out, **_k: (
            _write(out), {"frames": 300, "start": s, "duration": d})[1])
        with mock.patch.object(effectcraft, "detour_video", detour):
            result = studio.detour_video(Job("studio"), self.event, "01_Rushes/1.mp4", [0.4, 0.3], 3, 10)
        self.assertEqual(result["path"], os.path.join("06_Rendus", "Videos_detourees", "1_detoure_3s.mov"))
        self.assertEqual(self.to_fc.call_args[1]["bin_name"], "Détourages")

    def test_detour_video_box_alone_uses_its_centre_and_rejects_bad_frames(self):
        rush = os.path.join(self.event, "01_Rushes", "1.mp4")
        os.makedirs(os.path.dirname(rush))
        _write(rush, b"mp4")
        detour = mock.Mock(side_effect=lambda _c, _v, _p, s, d, out, **_k: (
            _write(out), {"frames": 60, "start": s, "duration": d})[1])
        with mock.patch.object(effectcraft, "detour_video", detour):
            studio.detour_video(Job("studio"), self.event, "01_Rushes/1.mp4", None, 1, 2, box=[0.1, 0.2, 0.4, 0.6])
            with self.assertRaises(studio.StudioError):
                studio.detour_video(Job("studio"), self.event, "01_Rushes/1.mp4", None, 1, 2, box=[0.9, 0.2, 0.4, 0.6])
        x, y = detour.call_args[0][2]
        self.assertAlmostEqual(x, 0.3)
        self.assertAlmostEqual(y, 0.5)
        self.assertEqual(detour.call_args[1]["box"], (0.1, 0.2, 0.4, 0.6))

    def test_french_date(self):
        self.assertEqual(studio.french_date("2026-11-16"), "16 novembre 2026")
        self.assertEqual(studio.french_date("2026-08-01"), "1 août 2026")
        self.assertEqual(studio.french_date(""), "")


if __name__ == "__main__":
    unittest.main()
