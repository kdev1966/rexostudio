"""Atelier : rendu d'un paquet d'animation (Blender factice) et livraison en zip."""
import os
import shutil
import stat
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from atelier import animation, config  # noqa: E402

# Faux Blender : ecrit dans le dossier de travail ce qu'ecrit export_generic.py
FAKE_BLENDER = """#!/bin/bash
work="${@: -4:1}"
echo "$@" >> "$(dirname "$0")/appels.txt"
echo video > "$work/decor.mp4"
echo jpg > "$work/vignette.jpg"
echo 'new File("{{DOSSIER}}/decor.mp4");' > "$work/composition.jsx"
echo '{"duration": 6.0, "width": 1920, "height": 1080, "fps": 30, "frames": 180, "pixels_per_meter": 100, "premier_plan": false, "placeholders": [{"name": "PHOTO_DEBOUT_MARIES", "kind": "debout", "width_m": 1.2, "height_m": 1.85}]}' > "$work/scene.json"
for i in 1 2 3; do echo "IMAGE $i"; done
echo "MESURE 3.6.23 sequence normal : 180 image(s) en 200.0 s (1.11 s par image)"
"""


class AnimationCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="atelier-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        blender = os.path.join(self.tmp, "Blender")
        with open(blender, "w") as fh:
            fh.write(FAKE_BLENDER)
        os.chmod(blender, os.stat(blender).st_mode | stat.S_IEXEC)
        scenes = os.path.join(self.tmp, "scenes")
        os.makedirs(scenes)
        open(os.path.join(scenes, "patio_nuit.blend"), "w").close()
        for name, value in (("BLENDER_BIN", blender), ("SCENES_DIR", scenes),
                            ("LIVRAISON_DIR", os.path.join(self.tmp, "livraison"))):
            p = mock.patch.object(config, name, value)
            p.start()
            self.addCleanup(p.stop)

    def test_render_makes_a_complete_package(self):
        folder = animation.render("patio_nuit", "sequence", 6, "normal", title="Patio de nuit", log=lambda _m: None)
        self.assertEqual(os.path.basename(folder), "patio_nuit__sequence__6s")
        info = animation.read_package(folder)
        self.assertEqual((info["format"], info["version"]), ("rexo-animation", 1))
        self.assertEqual(info["titre"], "Patio de nuit")
        self.assertEqual(info["emplacements"][0]["name"], "PHOTO_DEBOUT_MARIES")
        self.assertEqual(info["secondes_de_rendu"], 200.0)
        self.assertFalse(os.path.exists(os.path.join(folder, "scene.json")))
        self.assertFalse(os.path.exists(folder + ".partiel"))

    def test_render_refuses_unknown_motion_quality_and_scene(self):
        for args in (("patio_nuit", "looping"), ("patio_nuit", "sequence", 6, "ultra"), ("plage",)):
            with self.assertRaises(animation.AnimationError):
                animation.render(*args, log=lambda _m: None)

    def test_deliver_zips_packages_by_folder(self):
        animation.render("patio_nuit", "orbite", 9, log=lambda _m: None)
        out = animation.deliver(log=lambda _m: None)
        with zipfile.ZipFile(out) as z:
            names = sorted(z.namelist())
        self.assertIn("patio_nuit__orbite__9s/animation.json", names)
        self.assertIn("patio_nuit__orbite__9s/decor.mp4", names)
        with self.assertRaises(animation.AnimationError):
            animation.deliver(["inconnu"], log=lambda _m: None)


if __name__ == "__main__":
    unittest.main()
