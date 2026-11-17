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
            "POST", "/api/events/keep", {"id": "absent", "rel": "x"},
            headers={"Origin": "http://127.0.0.1:%d" % self.port})
        self.assertEqual(status, 404)       # evenement introuvable, mais pas refuse

    def test_foreign_origin_is_rejected(self):
        with mock.patch.object(app.subprocess, "Popen") as popen:
            status, _ = self.request(
                "POST", "/api/events/open", {"id": "x", "sub": ""},
                headers={"Origin": "https://evil.example"})
        self.assertEqual(status, 403)
        popen.assert_not_called()

    def test_text_plain_post_is_rejected(self):
        with mock.patch.object(app.subprocess, "Popen") as popen:
            status, _ = self.request(
                "POST", "/api/events/open", {"id": "x", "sub": ""},
                headers={"Content-Type": "text/plain"})
        self.assertEqual(status, 403)
        popen.assert_not_called()

    def test_foreign_host_is_rejected(self):
        # DNS rebinding : la page d'un autre domaine resolu vers 127.0.0.1.
        status, _ = self.request("GET", "/api/status",
                                 headers={"Host": "evil.example:%d" % self.port})
        self.assertEqual(status, 403)

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

    # -- evenements, quitter --------------------------------------------
    def wait_job(self, job_id):
        for _ in range(100):
            if MANAGER.get(job_id).status in ("done", "error"):
                break
            time.sleep(0.02)
        return MANAGER.get(job_id)

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

    def test_event_import_detail_keep_and_files(self):
        root = tempfile.mkdtemp(prefix="rexo-events-")
        self.addCleanup(shutil.rmtree, root, True)
        card = os.path.join(root, "..", os.path.basename(root) + "-carte")
        os.makedirs(card)
        self.addCleanup(shutil.rmtree, card, True)
        with open(os.path.join(card, "C0001.MP4"), "wb") as fh:
            fh.write(b"pas une vraie video")
        with mock.patch.object(app.config, "EVENTS_DIR", root):
            event_id = app.events.create(root, "Henne", "2026-11-20", "Rim")["id"]
            status, body = self.request("POST", "/api/events/import",
                                        {"id": event_id, "source": card})
            self.assertEqual(status, 200, body)
            job = MANAGER.get(json.loads(body)["job_id"])
            for _ in range(200):
                if job.status in ("done", "error"):
                    break
                time.sleep(0.02)
            self.assertEqual(job.status, "done", job.error)
            self.assertEqual(job.result["copied"], 1)
            status, body = self.request("GET", "/api/events/detail?id=" + urllib.parse.quote(event_id))
            clips = json.loads(body)["clips"]
            self.assertEqual([c["name"] for c in clips], ["C0001.MP4"])
            status, body = self.request("POST", "/api/events/keep",
                                        {"id": event_id, "rel": clips[0]["rel"], "keep": False})
            self.assertEqual((status, json.loads(body)["kept"]), (200, False))
            status, body = self.request("GET", "/api/file?path=" + urllib.parse.quote(clips[0]["path"]))
            self.assertEqual((status, body), (200, "pas une vraie video"))
            status, _ = self.request("POST", "/api/events/keep",
                                     {"id": event_id, "rel": "../../etc/passwd", "keep": True})
            self.assertEqual(status, 404)
            status, _ = self.request("GET", "/api/events/detail?id=..")
            self.assertEqual(status, 404)

    def test_event_trash_routes_use_the_trash(self):
        root = tempfile.mkdtemp(prefix="rexo-events-")
        self.addCleanup(shutil.rmtree, root, True)
        trashed = []

        def fake_trash(path):
            trashed.append(path)
            shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)

        with mock.patch.object(app.config, "EVENTS_DIR", root), \
                mock.patch.object(app.trash, "to_trash", side_effect=fake_trash):
            ev = app.events.create(root, "Fete", "2026-12-31", "Reveillon")
            rush = os.path.join(ev["path"], "01_Rushes", "Carte_1", "C0001.MP4")
            os.makedirs(os.path.dirname(rush))
            open(rush, "wb").close()
            status, body = self.request("POST", "/api/events/trash",
                                        {"id": ev["id"], "rel": ".rexo/evenement.json"})
            self.assertEqual(status, 404, body)
            status, body = self.request("POST", "/api/events/trash",
                                        {"id": ev["id"], "card": "Carte_1"})
            self.assertEqual(status, 200, body)
            self.assertEqual(trashed, [os.path.join(ev["path"], "01_Rushes", "Carte_1")])
            with mock.patch.object(app.MANAGER, "busy", return_value=True):
                status, _ = self.request("POST", "/api/events/delete", {"id": ev["id"]})
            self.assertEqual(status, 409)
            status, body = self.request("POST", "/api/events/delete", {"id": ev["id"]})
            self.assertEqual(status, 200, body)
            self.assertEqual(trashed[-1], ev["path"])
            status, body = self.request("GET", "/api/events")
            self.assertEqual(json.loads(body)["events"], [])

    def test_pick_folder_returns_the_finder_choice(self):
        chosen = mock.Mock(returncode=0, stdout="/Volumes/CARTE/DCIM/\n", stderr="")
        with mock.patch.object(app.rushes, "list_sources", return_value=[]), \
                mock.patch.object(app.subprocess, "run", return_value=chosen) as run:
            status, body = self.request("POST", "/api/pick-folder", {})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["path"], "/Volumes/CARTE/DCIM")
        args = run.call_args[0][0]
        self.assertEqual(args[:2], ["osascript", "-"])          # prompt et depart en arguments
        self.assertEqual(args[3], "/Volumes")

    def test_pick_folder_cancelled_or_already_open(self):
        cancelled = mock.Mock(returncode=0, stdout="\n", stderr="")
        with mock.patch.object(app.rushes, "list_sources", return_value=[]), \
                mock.patch.object(app.subprocess, "run", return_value=cancelled):
            status, body = self.request("POST", "/api/pick-folder", {})
        self.assertEqual((status, json.loads(body)["path"]), (200, ""))
        with app._PICK_LOCK:
            status, _ = self.request("POST", "/api/pick-folder", {})
        self.assertEqual(status, 409)

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
