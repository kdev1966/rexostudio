"""TextureCraft : authentification par jeton, export des textures d'un materiau."""
import json
import os
import shutil
import socketserver
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from montagia import config, texturecraft  # noqa: E402

TOKEN = "a" * 64


class FakeTextureCraft(object):
    """Serveur factice : la premiere requete de chaque connexion doit etre « auth »."""

    def __init__(self):
        self.commands = []
        fake = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                authed = False
                for line in self.rfile:
                    req = json.loads(line.decode("utf-8"))
                    if req["method"] == "auth":
                        authed = req["params"].get("token") == TOKEN
                        reply = {"ok": authed} if authed else {"ok": False, "error": "bad token"}
                    elif not authed:
                        reply = {"ok": False, "error": "authenticate first"}
                    else:
                        reply = fake.answer(req)
                    reply["id"] = req["id"]
                    self.wfile.write((json.dumps(reply) + "\n").encode("utf-8"))
                    self.wfile.flush()

        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def answer(self, req):
        if req["method"] == "command.list":
            return {"ok": True, "result": []}
        cmd, params = req["params"]["id"], req["params"].get("params", {})
        self.commands.append((cmd, params))
        if cmd == "material.list":
            return {"ok": True, "result": [{"id": "marble"}, {"id": "gold_polished"}]}
        if cmd == "file.exportTextures":
            files = []
            for kind in ("BaseColor", "Roughness", "Normal"):
                path = os.path.join(params["dir"], "plane_Plane_%s.png" % kind)
                with open(path, "w") as fh:
                    fh.write("png")
                files.append(path)
            return {"ok": True, "result": {"files": files}}
        return {"ok": True, "result": None}


class TextureCraftCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rexo-tc-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.fake = FakeTextureCraft()
        self.addCleanup(self.fake.server.shutdown)
        p = mock.patch.object(config, "TEXTURES_DIR", self.tmp)
        p.start()
        self.addCleanup(p.stop)

    def test_wrong_token_is_refused(self):
        with self.assertRaises(texturecraft.TextureCraftError):
            texturecraft.Client(self.fake.port, "b" * 64, timeout=5).run("material.list")

    def test_export_material_names_maps_and_fills_library(self):
        client = texturecraft.Client(self.fake.port, TOKEN, timeout=5)
        self.assertEqual(texturecraft.materials(client), ["marble", "gold_polished"])
        files = texturecraft.export_material(client, "marble")
        self.assertEqual(files, ["marble_BaseColor.png", "marble_Normal.png", "marble_Roughness.png"])
        self.assertTrue(texturecraft.has_textures("marble"))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "marble.partiel")))
        applied = dict(self.fake.commands)
        self.assertEqual(applied["material.apply"], {"material": "marble"})
        self.assertEqual(applied["file.exportTextures"]["preset"], "Blender (Principled BSDF)")


if __name__ == "__main__":
    unittest.main()
