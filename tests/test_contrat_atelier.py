"""Contrat atelier -> Rexo Studio : un paquet fabrique et livre par l'atelier s'installe
et s'utilise dans Rexo Studio (format commun/paquet_animation.py)."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "atelier"))

from atelier import animation as atelier_animation  # noqa: E402
from atelier import config as atelier_config  # noqa: E402
from montagia import animations, config  # noqa: E402

# Ce qu'ecrit blender/export_generic.py dans scene.json
SCENE_INFO = {"duration": 6.0, "width": 1920, "height": 1080, "fps": 30, "frames": 180,
              "pixels_per_meter": 100, "premier_plan": True,
              "placeholders": [{"name": "PHOTO_DEBOUT_MARIES", "kind": "debout", "width_m": 1.2,
                                "height_m": 1.85}]}


class ContratCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rexo-contrat-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.livraison = os.path.join(self.tmp, "livraison")
        self.library = os.path.join(self.tmp, "bibliotheque", "animations")
        for p in (mock.patch.object(atelier_config, "LIVRAISON_DIR", self.livraison),
                  mock.patch.object(config, "ANIMATIONS_DIR", self.library)):
            p.start()
            self.addCleanup(p.stop)

    def fabricate(self):
        """Paquet tel que le laisse atelier.animation.render (sans Blender)."""
        info = atelier_animation.package_info("patio_nuit", "sequence", 6, "normal", "Patio de nuit",
                                              SCENE_INFO, 203.0)
        folder = os.path.join(self.livraison, info["id"])
        os.makedirs(folder)
        files = {"decor.mp4": "video", "premier_plan.mov": "alpha", "vignette.jpg": "jpg",
                 "composition.jsx": 'var d = new File("{{DOSSIER}}/decor.mp4");'}
        for name, text in files.items():
            with open(os.path.join(folder, name), "w") as fh:
                fh.write(text)
        with open(os.path.join(folder, "animation.json"), "w", encoding="utf-8") as fh:
            json.dump(info, fh)
        return info

    def test_delivered_package_is_installed_and_usable(self):
        info = self.fabricate()
        self.assertEqual([p["id"] for p in atelier_animation.packages()], [info["id"]])
        zip_path = atelier_animation.deliver(log=lambda _m: None)
        self.assertEqual(animations.install(zip_path), [info["id"]])
        folder, installed = animations.get(info["id"])
        self.assertEqual(installed["emplacements"][0]["name"], "PHOTO_DEBOUT_MARIES")
        self.assertIn(folder + "/decor.mp4", animations.composition(folder))
        self.assertEqual(animations.catalog()[0]["titre"], "Patio de nuit")

    def test_atelier_refuses_what_rexo_studio_would_refuse(self):
        info = self.fabricate()
        os.remove(os.path.join(self.livraison, info["id"], "premier_plan.mov"))   # annonce mais absent
        self.assertEqual(atelier_animation.packages(), [])


if __name__ == "__main__":
    unittest.main()
