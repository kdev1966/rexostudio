"""Integration FilmCraft, sans lancer l'application : un faux serveur de
controle parle le meme protocole (JSON par ligne, jeton obligatoire) et
enregistre les commandes recues.
"""
import json
import os
import socketserver
import sys
import tempfile
import threading
import unittest
from fractions import Fraction
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from montagia import filmcraft, pipeline, transcribe  # noqa: E402

T = filmcraft.TICKS_PER_SECOND
TOKEN = "ab" * 32


class FakeFilmCraft(object):
    """Faux FilmCraft : repond comme la version 0.20.1 et ecrit un .fcproj
    coherent avec les clips places, pour tester la verification."""

    def __init__(self):
        self.calls = []
        self.captions_text = ""
        self.clips = []
        self.captions = 0
        self.markers = 0
        handler = self._handler_class()
        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def commands(self):
        return [c for c, _p in self.calls]

    def _handler_class(self):
        fake = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                line = self.rfile.readline()
                req = json.loads(line)
                if req.get("token") != TOKEN:
                    reply = {"ok": False, "error": "invalid token"}
                else:
                    reply = fake.dispatch(req)
                self.wfile.write((json.dumps(reply) + "\n").encode("utf-8"))

        return Handler

    def dispatch(self, req):
        method = req.get("method")
        if method == "perf.stats":
            return {"ok": True, "result": {}}
        if method != "engine.execute":
            return {"ok": False, "error": "unknown method"}
        cmd = req["params"]["command"]
        p = req["params"].get("params") or {}
        self.calls.append((cmd, p))
        result = {}
        if cmd == "file.autoSaveNow":
            result = {"path": "/tmp/secours.fcproj"}
        elif cmd == "file.import":
            result = {"errors": [], "items": [1]}
        elif cmd == "file.newSequence":
            result = {"sequence": 8}
        elif cmd == "timeline.place":
            for name in ("time", "sourceIn", "duration"):
                if not isinstance(p.get(name), int):
                    return {"ok": False, "error": "%s doit etre en ticks" % name}
            self.clips.append(p)
            result = {"clips": [100 + 2 * len(self.clips), 101 + 2 * len(self.clips)]}
        elif cmd == "captions.import":
            with open(p["path"], encoding="utf-8") as fh:
                self.captions_text = fh.read()
            self.captions = len(transcribe.parse_srt(self.captions_text))
            result = {"captions": self.captions, "track": 15}
        elif cmd == "markers.add":
            self.markers += 1
            result = {"marker": 200 + self.markers}
        elif cmd == "file.saveAs":
            self._write_project(p["path"])
            result = {"path": p["path"], "bytes": 1}
        return {"ok": True, "result": result}

    def _write_project(self, path):
        clips = [{"id": i, "item": 1, "start": c["time"], "duration": c["duration"],
                  "source_in": c["sourceIn"]} for i, c in enumerate(self.clips)]
        doc = {"format": "filmcraft.project", "schema_version": 17,
               "generator": "FilmCraft 0.20.1",
               "project": {"items": {"8": {"name": "Montage", "kind": {"Sequence": {
                   "video_tracks": [{"items": clips}], "audio_tracks": [],
                   "caption_tracks": [{"captions": [{}] * self.captions}],
                   "markers": [{}] * self.markers}}}}}}
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)


class TimeTest(unittest.TestCase):
    def test_fps_fraction(self):
        self.assertEqual(filmcraft.fps_fraction(30), Fraction(30))
        self.assertEqual(filmcraft.fps_fraction(29.97), Fraction(30000, 1001))
        self.assertEqual(filmcraft.fps_fraction(23.976), Fraction(24000, 1001))
        self.assertEqual(filmcraft.fps_fraction(0), Fraction(30))

    def test_ticks_are_exact_integers(self):
        self.assertEqual(filmcraft.frames_to_ticks(30, Fraction(30)), T)
        self.assertEqual(filmcraft.frames_to_ticks(30000, Fraction(30000, 1001)), 1001 * T)

    def test_frame_plan_is_contiguous_and_frame_aligned(self):
        plan = filmcraft.frame_plan(
            [{"start": 0.01, "end": 2.99, "id": "S1"}, {"start": 7.0, "end": 11.5}],
            Fraction(30))
        self.assertEqual([(p["source_frame"], p["frames"], p["timeline_frame"]) for p in plan],
                         [(0, 90, 0), (210, 135, 90)])
        self.assertEqual((plan[0]["start"], plan[0]["end"]), (0.0, 3.0))

    def test_frame_plan_skips_segments_shorter_than_a_frame(self):
        self.assertEqual(filmcraft.frame_plan([{"start": 1.0, "end": 1.01}], Fraction(30)), [])


class ClientTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeFilmCraft()

    def tearDown(self):
        self.fake.close()

    def test_wrong_token_is_an_error(self):
        client = filmcraft.Client(self.fake.port, "00" * 32)
        self.assertFalse(client.ping())
        with self.assertRaises(filmcraft.FilmCraftError):
            client.execute("file.import", {"paths": ["/x.mp4"]})

    def test_unreachable_port_is_an_error(self):
        client = filmcraft.Client(1, TOKEN, timeout=1)
        with self.assertRaises(filmcraft.FilmCraftError):
            client.call("perf.stats")


class BuildProjectTest(unittest.TestCase):
    INFO = {"duration": 12.0, "fps": 30.0, "width": 1280, "height": 720, "has_audio": True}

    def setUp(self):
        self.fake = FakeFilmCraft()
        self.client = filmcraft.Client(self.fake.port, TOKEN)
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        self.fake.close()

    def test_commands_and_ticks(self):
        plan = filmcraft.frame_plan(
            [{"start": 0, "end": 3, "id": "S1", "reason": "accroche"},
             {"start": 7, "end": 11.5, "id": "S4", "reason": "conclusion"}], Fraction(30))
        out = os.path.join(self.tmp, "m.fcproj")
        result = filmcraft.build_project(self.client, "/src/v.mp4", plan, out,
                                         Fraction(30), self.INFO, title="Essai")
        cmds = self.fake.commands()
        # La copie de secours passe AVANT le nouveau projet (qui remplace l'ancien).
        self.assertEqual(cmds[:4], ["file.autoSaveNow", "file.newProject",
                                    "file.import", "file.newSequence"])
        self.assertEqual(cmds[-1], "file.saveAs")
        placed = [(c["time"], c["sourceIn"], c["duration"]) for c in self.fake.clips]
        self.assertEqual(placed, [(0, 0, 3 * T), (3 * T, 7 * T, int(4.5 * T))])
        self.assertEqual(self.fake.markers, 2)
        self.assertNotIn("clip.fillFrame", cmds)
        self.assertEqual(result["clips"], 2)
        self.assertTrue(os.path.isfile(out))

    def test_vertical_profile_fills_frame(self):
        plan = filmcraft.frame_plan([{"start": 0, "end": 2}], Fraction(30))
        filmcraft.build_project(self.client, "/src/v.mp4", plan,
                                os.path.join(self.tmp, "v.fcproj"), Fraction(30),
                                self.INFO, profile="9:16")
        seq = dict(self.fake.calls)["file.newSequence"]
        self.assertEqual((seq["width"], seq["height"]), (1080, 1920))
        self.assertIn("clip.fillFrame", self.fake.commands())

    def test_empty_plan_is_refused(self):
        with self.assertRaises(filmcraft.FilmCraftError):
            filmcraft.build_project(self.client, "/src/v.mp4", [], "/tmp/x.fcproj",
                                    Fraction(30), self.INFO)


class PipelineFilmCraftTest(unittest.TestCase):
    """Chaine complete : normalisation, calage sur les images, sous-titres
    recales, construction et verification du projet relu."""

    def test_subtitles_follow_frame_aligned_timeline(self):
        fake = FakeFilmCraft()
        tmp = tempfile.mkdtemp()
        info = {"duration": 15.0, "fps": 30.0, "width": 1280, "height": 720,
                "has_audio": True}
        subs = [{"start": 0.0, "end": 2.0, "text": "Bonjour"},
                {"start": 10.0, "end": 12.0, "text": "Au revoir"}]
        try:
            with mock.patch.object(pipeline.media, "probe", return_value=info), \
                    mock.patch.object(pipeline.config, "CACHE_DIR", tmp), \
                    mock.patch.object(pipeline.filmcraft, "connect",
                                      return_value=filmcraft.Client(fake.port, TOKEN)):
                result = pipeline.build_filmcraft_job(
                    mock.Mock(), "/src/v.mp4",
                    [{"start": 0, "end": 3}, {"start": 0, "end": 3},   # doublon
                     {"start": 9.99, "end": 12.01}],
                    os.path.join(tmp, "out.fcproj"), subtitle_segments=subs)
        finally:
            fake.close()
        self.assertTrue(result["valid"], result["message"])
        self.assertEqual(result["clips"], 2)
        lines = [(s["start"], s["end"], s["text"]) for s in transcribe.parse_srt(fake.captions_text)]
        self.assertEqual(lines, [(0.0, 2.0, "Bonjour"), (3.0, 5.0, "Au revoir")])
        # Le SRT temporaire est supprime apres l'envoi.
        self.assertEqual(os.listdir(os.path.join(tmp, "subs")), [])


class ReadProjectTest(unittest.TestCase):
    def test_rejects_foreign_files(self):
        path = os.path.join(tempfile.mkdtemp(), "x.fcproj")
        with open(path, "w") as fh:
            json.dump({"format": "autre"}, fh)
        with self.assertRaises(filmcraft.FilmCraftError):
            filmcraft.read_project(path)


if __name__ == "__main__":
    unittest.main()
