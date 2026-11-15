"""Serveur web : fin des flux SSE et refus des requetes d'un autre site.

Lance un vrai serveur sur un port libre (aucun appel a Ollama ni ffmpeg).
"""
import http.client
import json
import os
import socket
import sys
import threading
import time
import unittest
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

    def test_foreign_upload_is_rejected(self):
        status, _ = self.request(
            "POST", "/api/upload?name=a.mp4", headers={
                "Origin": "https://evil.example", "Content-Type": "video/mp4"})
        self.assertEqual(status, 403)


if __name__ == "__main__":
    unittest.main()
