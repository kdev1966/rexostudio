"""Moteur llama.cpp : demarrage a la demande, requetes, arret apres
inactivite, echec au demarrage. Un faux llama-server (script Python) joue
le role du vrai binaire : aucun modele n'est charge."""
import json
import os
import stat
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from montagia import ai, config, llm_server  # noqa: E402

FAKE_SERVER = textwrap.dedent('''\
    #!%(python)s
    """Faux llama-server : /health, /v1/chat/completions (normal et flux)."""
    import json, sys
    from http.server import BaseHTTPRequestHandler, HTTPServer
    args = sys.argv[1:]
    if "--crash" in open(args[args.index("-m") + 1]).read():
        print("error: failed to load model"); sys.exit(1)
    port = int(args[args.index("--port") + 1])

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass
        def do_GET(self):
            self.send_response(200 if self.path == "/health" else 404)
            self.end_headers()
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if body.get("stream"):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for piece in ("Bon", "jour"):
                    chunk = {"choices": [{"delta": {"content": piece}}]}
                    self.wfile.write(("data: %%s\\n\\n" %% json.dumps(chunk)).encode())
                self.wfile.write(b"data: [DONE]\\n\\n")
                return
            content = json.dumps({"echo": body.get("response_format") is not None,
                                  "thinking": body["chat_template_kwargs"]["enable_thinking"]})
            data = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    HTTPServer(("127.0.0.1", port), H).serve_forever()
''') % {"python": sys.executable}


class LlamaServerTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.binary = os.path.join(self.dir, "llama-server")
        with open(self.binary, "w") as fh:
            fh.write(FAKE_SERVER)
        os.chmod(self.binary, os.stat(self.binary).st_mode | stat.S_IXUSR)
        self.model = os.path.join(self.dir, "modele.gguf")
        with open(self.model, "w") as fh:
            fh.write("GGUF")
        self.server = llm_server.LlamaServer(self.binary, self.model,
                                             os.path.join(self.dir, "log.txt"), idle_seconds=60)
        self.addCleanup(self.server.stop)

    def test_starts_on_demand_and_answers(self):
        self.assertFalse(self.server.running())
        data = self.server.post("/v1/chat/completions", ai._llama_body(
            ai._messages("s", "u"), 0.1, 10, schema={"type": "object"}))
        self.assertTrue(self.server.running())
        content = json.loads(data["choices"][0]["message"]["content"])
        self.assertEqual(content, {"echo": True, "thinking": False})

    def test_idle_server_is_stopped_but_not_during_a_request(self):
        self.server.idle_seconds = 0
        with self.server.session():
            self.assertFalse(self.server.stop_if_idle())    # requete en cours
        self.assertTrue(self.server.stop_if_idle())
        self.assertFalse(self.server.running())
        self.server.post("/v1/chat/completions", ai._llama_body(ai._messages("s", "u"), 0.1, 10))
        self.assertTrue(self.server.running())              # redemarre a la demande

    def test_crash_at_start_reports_the_log(self):
        with open(self.model, "w") as fh:
            fh.write("--crash")
        with self.assertRaises(llm_server.LlamaServerError) as ctx:
            self.server.ensure()
        self.assertIn("failed to load model", str(ctx.exception))
        self.assertFalse(self.server.running())

    def test_missing_install_is_explained(self):
        server = llm_server.LlamaServer(os.path.join(self.dir, "absent"), self.model)
        with self.assertRaises(llm_server.LlamaServerError) as ctx:
            server.ensure()
        self.assertIn("install_models.sh", str(ctx.exception))

    def test_ai_module_uses_llama_backend(self):
        with mock.patch.object(config, "LLM_BACKEND", "llama"), \
                mock.patch.object(llm_server, "SERVER", self.server):
            self.assertEqual(ai.chat_json("s", "u", {"type": "object"}),
                             {"echo": True, "thinking": False})
            self.assertEqual("".join(ai.chat_stream("s", "u")), "Bonjour")
            self.assertTrue(ai.stats()["running"])
            ai.unload()
            self.assertFalse(self.server.running())


class BackendChoiceTest(unittest.TestCase):
    def test_auto_prefers_llama_when_installed(self):
        with mock.patch.dict(os.environ, {"MONTAGIA_LLM_BACKEND": "auto"}), \
                mock.patch.object(config.os, "access", return_value=True), \
                mock.patch.object(config.os.path, "isfile", return_value=True):
            self.assertEqual(config._llm_backend(), "llama")
        with mock.patch.dict(os.environ, {"MONTAGIA_LLM_BACKEND": "auto"}), \
                mock.patch.object(config.os, "access", return_value=False):
            self.assertEqual(config._llm_backend(), "ollama")
        with mock.patch.dict(os.environ, {"MONTAGIA_LLM_BACKEND": "ollama"}):
            self.assertEqual(config._llm_backend(), "ollama")

    def test_cache_key_depends_on_model(self):
        from montagia import pipeline
        with mock.patch.object(config, "LLM_MODEL", "a"):
            first = pipeline._cache_key("t", {"x": 1})
        with mock.patch.object(config, "LLM_MODEL", "b"):
            second = pipeline._cache_key("t", {"x": 1})
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
