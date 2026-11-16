"""Serveur web : fin des flux SSE et refus des requetes d'un autre site.

Lance un vrai serveur sur un port libre (aucun appel a Ollama ni ffmpeg).
"""
import http.client
import json
import os
import shutil
import socket
import tempfile
import sys
import threading
import time
import unittest
import urllib.parse
from http.server import ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from montagia import project  # noqa: E402
from montagia.jobs import MANAGER  # noqa: E402
from server import app  # noqa: E402

TIMEOUT = 5.0


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), app.StudioHandler)
        cls.httpd.daemon_threads = True
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def request(self, method, path, body=None, headers=None):
        """Renvoie (statut, corps complet). Echoue si la reponse ne se termine pas."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=TIMEOUT)
        hdrs = {"Content-Type": "application/json"} if body is not None else {}
        hdrs.update(headers or {})
        data = json.dumps(body).encode("utf-8") if body is not None else None
        try:
            conn.request(method, path, body=data, headers=hdrs)
            resp = conn.getresponse()
            return resp.status, resp.read().decode("utf-8")
        except socket.timeout:
            self.fail("%s %s : la reponse ne se termine jamais" % (method, path))
        finally:
            conn.close()

    # -- B2 : flux SSE ---------------------------------------------------
    def test_chat_stream_ends(self):
        proj = project.STORE.create("/tmp/inexistant.mp4", "x.mp4")
        with mock.patch.object(app.pipeline, "ai_chat",
                               lambda *_a: iter(["Bon", "jour"])):
            status, body = self.request("POST", "/api/chat",
                                        {"project_id": proj.id, "question": "q"})
        self.assertEqual(status, 200)
        self.assertIn('"token": "Bon"', body)
        self.assertTrue(body.rstrip().endswith('{"done": true}'))

    def test_events_of_finished_job_end_with_final_state(self):
        job = MANAGER.create("test")
        MANAGER.run_async(job, lambda _j: {"ok": 1})
        for _ in range(50):
            if job.status == "done":
                break
            time.sleep(0.02)
        status, body = self.request("GET", "/api/jobs/%s/events" % job.id)
        self.assertEqual(status, 200)
        events = [json.loads(line[6:]) for line in body.splitlines()
                  if line.startswith("data: ")]
        self.assertEqual(events[0]["type"], "snapshot")
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(events[-1]["result"], {"ok": 1})

    def test_events_of_failed_job(self):
        job = MANAGER.create("test")

        def boom(_j):
            raise RuntimeError("echec voulu")

        with mock.patch("traceback.print_exc"):
            MANAGER.run_async(job, boom)
            for _ in range(50):
                if job.status == "error":
                    break
                time.sleep(0.02)
        _status, body = self.request("GET", "/api/jobs/%s/events" % job.id)
        self.assertIn('"type": "error"', body)
        self.assertIn("echec voulu", body)

    # -- B3 : requetes d'un autre site ----------------------------------
    def test_same_origin_is_accepted(self):
        status, _ = self.request(
            "POST", "/api/analyze", {"project_id": "absent"},
            headers={"Origin": "http://127.0.0.1:%d" % self.port})
        self.assertEqual(status, 500)       # projet introuvable, mais pas refuse

    def test_foreign_origin_is_rejected(self):
        with mock.patch.object(app.subprocess, "Popen") as popen:
            status, _ = self.request(
                "POST", "/api/open", {"path": "/Applications/Calculator.app"},
                headers={"Origin": "https://evil.example"})
        self.assertEqual(status, 403)
        popen.assert_not_called()

    def test_text_plain_post_is_rejected(self):
        with mock.patch.object(app.subprocess, "Popen") as popen:
            status, _ = self.request(
                "POST", "/api/open", {"path": "/Applications/Calculator.app"},
                headers={"Content-Type": "text/plain"})
        self.assertEqual(status, 403)
        popen.assert_not_called()

    def test_foreign_host_is_rejected(self):
        # DNS rebinding : la page d'un autre domaine resolu vers 127.0.0.1.
        status, _ = self.request("GET", "/api/status",
                                 headers={"Host": "evil.example:%d" % self.port})
        self.assertEqual(status, 403)

    def test_open_rejects_path_outside_allowed_dirs(self):
        with mock.patch.object(app.subprocess, "Popen") as popen:
            status, _ = self.request("POST", "/api/open",
                                     {"path": "/ApplicationsEvil/x.app"})
        self.assertEqual(status, 403)
        popen.assert_not_called()

    def test_filmcraft_route_runs_pipeline_job(self):
        proj = project.STORE.create("/tmp/inexistant.mp4", "clip.mp4")
        proj.plan = [{"start": 0, "end": 2}]
        calls = []

        def fake_job(job, source, segments, out_path, **kwargs):
            calls.append((source, segments, out_path, kwargs.get("profile")))
            return {"path": out_path, "valid": True}

        with mock.patch.object(app.pipeline, "build_filmcraft_job", side_effect=fake_job):
            status, body = self.request("POST", "/api/filmcraft",
                                        {"project_id": proj.id, "profile": "9:16"})
            job_id = json.loads(body)["job_id"]
            for _ in range(50):
                if MANAGER.get(job_id).status == "done":
                    break
                time.sleep(0.02)
        self.assertEqual(status, 200)
        self.assertEqual(MANAGER.get(job_id).status, "done")
        source, segments, out_path, profile = calls[0]
        self.assertEqual((source, segments, profile), ("/tmp/inexistant.mp4", proj.plan, "9:16"))
        self.assertTrue(out_path.endswith("clip.fcproj"))
        self.assertIn(out_path, proj.exports)

    def test_plan_keep_toggle_recomputes_plan(self):
        proj = project.STORE.create("/tmp/inexistant.mp4", "bascule.mp4")
        proj.info = {"duration": 10.0}
        proj.candidates = [{"id": "S1", "start": 0.0, "end": 3.0, "text": "a", "kind": "parole"},
                           {"id": "S2", "start": 4.0, "end": 6.0, "text": "b", "kind": "parole"}]
        proj.results["plan_decisions"] = [
            {"id": "S1", "keep": True, "type": "contenu", "by": "ia"},
            {"id": "S2", "keep": True, "type": "digression", "by": "ia", "suggested": True}]
        status, body = self.request("POST", "/api/plan/keep",
                                    {"project_id": proj.id, "id": "S2", "keep": False})
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual([(s["start"], s["end"]) for s in data["plan"]], [(0.0, 3.0)])
        self.assertEqual(proj.plan, data["plan"])
        # Tout couper est refuse (plan vide) et la decision est retablie.
        status, _ = self.request("POST", "/api/plan/keep",
                                 {"project_id": proj.id, "id": "S1", "keep": False})
        self.assertEqual(status, 400)
        self.assertTrue(proj.results["plan_decisions"][0]["keep"])
        status, _ = self.request("POST", "/api/plan/keep",
                                 {"project_id": proj.id, "id": "S9", "keep": False})
        self.assertEqual(status, 404)

    def test_filmcraft_route_requires_a_plan(self):
        proj = project.STORE.create("/tmp/inexistant.mp4", "vide.mp4")
        status, _ = self.request("POST", "/api/filmcraft", {"project_id": proj.id})
        self.assertEqual(status, 400)

    def test_open_filmcraft_only_fcproj_in_workspace(self):
        with mock.patch.object(app.filmcraft, "open_project") as opener:
            status, _ = self.request("POST", "/api/open",
                                     {"target": "filmcraft", "path": "/etc/hosts"})
        self.assertEqual(status, 403)
        opener.assert_not_called()

    def test_same_name_uploads_do_not_overwrite(self):
        media_dir = tempfile.mkdtemp()
        info = {"duration": 1.0, "width": 16, "height": 16}
        paths = []
        with mock.patch.object(app.config, "MEDIA_DIR", media_dir), \
                mock.patch.object(app.media, "probe", return_value=info):
            for payload in (b"premier", b"second"):
                conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=TIMEOUT)
                conn.request("POST", "/api/upload?name=rush.mp4", body=payload,
                             headers={"Content-Type": "video/mp4"})
                resp = conn.getresponse()
                paths.append(json.loads(resp.read())["project"]["path"])
                conn.close()
        self.assertNotEqual(paths[0], paths[1])
        with open(paths[0], "rb") as fh:
            self.assertEqual(fh.read(), b"premier")
        with open(paths[1], "rb") as fh:
            self.assertEqual(fh.read(), b"second")
        self.assertFalse([f for f in os.listdir(os.path.dirname(paths[0]))
                          if f.endswith(".part")])

    def _range(self, path, header):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=TIMEOUT)
        conn.request("GET", "/api/file?path=" + urllib.parse.quote(path),
                     headers={"Range": header} if header else {})
        resp = conn.getresponse()
        out = resp.status, dict(resp.getheaders()), resp.read()
        conn.close()
        return out

    def test_file_range_requests(self):
        workspace = tempfile.mkdtemp()
        path = os.path.join(workspace, "clip \"final\".mp4")
        with open(path, "wb") as fh:
            fh.write(bytes(range(100)))
        with mock.patch.object(app.config, "WORKSPACE", workspace):
            status, headers, body = self._range(path, None)
            self.assertEqual((status, len(body)), (200, 100))
            self.assertEqual(headers["Accept-Ranges"], "bytes")
            self.assertNotIn('"final"', headers["Content-Disposition"])

            status, headers, body = self._range(path, "bytes=10-19")
            self.assertEqual((status, body), (206, bytes(range(10, 20))))
            self.assertEqual(headers["Content-Range"], "bytes 10-19/100")

            status, _h, body = self._range(path, "bytes=90-")
            self.assertEqual((status, body), (206, bytes(range(90, 100))))

            status, _h, body = self._range(path, "bytes=-5")
            self.assertEqual((status, body), (206, bytes(range(95, 100))))

            status, headers, _b = self._range(path, "bytes=200-300")
            self.assertEqual(status, 416)
            self.assertEqual(headers["Content-Range"], "bytes */100")

    def test_foreign_upload_is_rejected(self):
        status, _ = self.request(
            "POST", "/api/upload?name=a.mp4", headers={
                "Origin": "https://evil.example", "Content-Type": "video/mp4"})
        self.assertEqual(status, 403)

    # -- preparer en un clic, supprimer, quitter ------------------------
    def wait_job(self, job_id):
        for _ in range(100):
            if MANAGER.get(job_id).status in ("done", "error"):
                break
            time.sleep(0.02)
        return MANAGER.get(job_id)

    def test_prepare_chains_analyze_transcribe_plan(self):
        proj = project.STORE.create("/tmp/inexistant.mp4", "prep.mp4")
        proj.language = "ar"
        calls, progress = [], []

        def analyze(j, path, *_a):
            calls.append("analyse")
            j.set_progress(1.0, "a")
            return {"info": {"duration": 6.0}, "silences": [], "speech_segments": [],
                    "scenes": []}

        def transcribe_media(j, path, model, language):
            calls.append(("transcription", language))
            return {"segments": [{"start": 0, "end": 6, "text": "salut"}],
                    "words": [], "language": "ar", "model": "small"}

        def cut_plan(j, cands, duration, transcript, instruction, style, suggest_only):
            calls.append(("plan", duration, suggest_only))
            j.set_progress(1.0, "fin")
            return {"segments": [{"start": 0, "end": 6}], "rationale": "r", "decisions": []}

        with mock.patch.object(app.pipeline, "analyze_media", side_effect=analyze), \
                mock.patch.object(app.pipeline, "transcribe_media", side_effect=transcribe_media), \
                mock.patch.object(app.pipeline, "ai_cut_plan", side_effect=cut_plan), \
                mock.patch.object(app.transcribe, "write_srt"):
            status, body = self.request("POST", "/api/prepare",
                                        {"project_id": proj.id, "language": "auto"})
            job = self.wait_job(json.loads(body)["job_id"])
            progress = job.progress
        self.assertEqual(status, 200)
        self.assertEqual(job.status, "done", job.error)
        self.assertEqual(calls, ["analyse", ("transcription", "auto"), ("plan", 6.0, True)])
        self.assertEqual(progress, 1.0)
        self.assertEqual(proj.plan, [{"start": 0, "end": 6}])

    def test_delete_project_removes_uploaded_media_only(self):
        media_dir = tempfile.mkdtemp()
        inside = os.path.join(media_dir, "rush.mp4")
        outside = os.path.join(tempfile.mkdtemp(), "autre.mp4")
        for path in (inside, outside):
            with open(path, "wb") as fh:
                fh.write(b"x")
        a = project.STORE.create(inside, "rush.mp4")
        b = project.STORE.create(outside, "autre.mp4")
        with mock.patch.object(app.config, "MEDIA_DIR", media_dir):
            self.assertEqual(self.request("POST", "/api/project/delete",
                                          {"project_id": a.id})[0], 200)
            self.assertEqual(self.request("POST", "/api/project/delete",
                                          {"project_id": b.id})[0], 200)
            self.assertEqual(self.request("POST", "/api/project/delete",
                                          {"project_id": b.id})[0], 404)
        self.assertFalse(os.path.exists(inside))
        self.assertTrue(os.path.exists(outside))       # hors du dossier des videos
        self.assertIsNone(project.STORE.get(a.id))
        os.remove(outside)

    def test_events_create_list_open(self):
        root = tempfile.mkdtemp(prefix="rexo-events-")
        self.addCleanup(shutil.rmtree, root, True)
        with mock.patch.object(app.config, "EVENTS_DIR", root), \
                mock.patch.object(app.subprocess, "Popen") as popen:
            status, body = self.request("POST", "/api/events/create", {
                "type": "Mariage", "date": "2026-11-22", "names": "Sarra et Ahmed"})
            self.assertEqual(status, 200, body)
            event_id = json.loads(body)["id"]
            status, body = self.request("GET", "/api/events")
            data = json.loads(body)
            self.assertEqual([e["id"] for e in data["events"]], [event_id])
            self.assertIn("Fiançailles", [t["label"] for t in data["types"]])
            status, _ = self.request("POST", "/api/events/open",
                                     {"id": event_id, "sub": "01_Rushes"})
            self.assertEqual(status, 200)
            popen.assert_called_once_with(["open", os.path.join(root, event_id, "01_Rushes")])
            status, _ = self.request("POST", "/api/events/open", {"id": "../..", "sub": ""})
            self.assertEqual(status, 404)
            status, body = self.request("POST", "/api/events/create", {
                "type": "Mariage", "date": "demain", "names": "X"})
            self.assertEqual(status, 400)
            self.assertIn("Date invalide", body)
            self.assertEqual(popen.call_count, 1)

    def test_quit_unloads_model_then_stops(self):
        stopped = threading.Event()
        with mock.patch.object(app.ai, "unload") as unload, \
                mock.patch.object(self.httpd, "shutdown", side_effect=stopped.set):
            status, _ = self.request("POST", "/api/quit", {})
            self.assertTrue(stopped.wait(2))
        self.assertEqual(status, 200)
        unload.assert_called_once()

    def test_quit_refused_while_a_job_runs(self):
        release = threading.Event()
        job = MANAGER.create("test")
        MANAGER.run_async(job, lambda _j: release.wait(5))
        try:
            with mock.patch.object(self.httpd, "shutdown") as shutdown:
                status, body = self.request("POST", "/api/quit", {})
            self.assertEqual(status, 409)
            self.assertIn("en cours", body)
            shutdown.assert_not_called()
        finally:
            release.set()
            self.wait_job(job.id)


if __name__ == "__main__":
    unittest.main()


class QuietServerTest(unittest.TestCase):
    def test_connection_reset_is_not_logged(self):
        server = object.__new__(app.StudioServer)     # sans ouvrir de port
        with mock.patch.object(ThreadingHTTPServer, "handle_error") as parent:
            try:
                raise ConnectionResetError(54, "Connection reset by peer")
            except ConnectionResetError:
                server.handle_error(None, ("127.0.0.1", 1))
            parent.assert_not_called()
            try:
                raise ValueError("vraie erreur")
            except ValueError:
                server.handle_error(None, ("127.0.0.1", 1))
            parent.assert_called_once()
