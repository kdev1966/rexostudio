"""Bibliotheque d'animations livrees par l'atelier : lecture, chemins, installation."""
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from montagia import animations, config  # noqa: E402

INFO = {"format": "rexo-animation", "version": 1, "id": "patio_nuit__sequence__6s",
        "titre": "Patio de nuit", "duree": 6.0, "mouvement": "sequence", "scene": "patio_nuit",
        "pixels_par_metre": 100, "premier_plan": False,
        "emplacements": [{"name": "PHOTO_DEBOUT_MARIES", "kind": "debout", "width_m": 1.2, "height_m": 1.85}]}


def make_package(folder, info=None, skip=()):
    os.makedirs(folder, exist_ok=True)
    data = dict(INFO, **(info or {}))
    files = {"animation.json": json.dumps(data), "decor.mp4": "video", "vignette.jpg": "jpg",
             "composition.jsx": 'new File("{{DOSSIER}}/decor.mp4");'}
    for name, text in files.items():
        if name not in skip:
            with open(os.path.join(folder, name), "w") as fh:
                fh.write(text)
    return folder


class AnimationsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rexo-anim-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.lib = os.path.join(self.tmp, "bibliotheque", "animations")
        p = mock.patch.object(config, "ANIMATIONS_DIR", self.lib)
        p.start()
        self.addCleanup(p.stop)

    def test_catalog_lists_only_complete_packages(self):
        make_package(os.path.join(self.lib, "patio_nuit__sequence__6s"))
        make_package(os.path.join(self.lib, "sans_video"), skip=("decor.mp4",))
        make_package(os.path.join(self.lib, "autre_format"), info={"format": "autre"})
        self.assertEqual([a["id"] for a in animations.catalog()], ["patio_nuit__sequence__6s"])

    def test_composition_points_at_the_installed_folder(self):
        folder = make_package(os.path.join(self.lib, "patio_nuit__sequence__6s"))
        self.assertEqual(animations.composition(folder), 'new File("%s/decor.mp4");' % folder)

    def test_get_refuses_paths_and_unknown_ids(self):
        for bad in ("../secret", "", ".cache", "inconnu"):
            with self.assertRaises(animations.AnimationError):
                animations.get(bad)

    def test_install_zip_replaces_and_skips_broken_packages(self):
        src = os.path.join(self.tmp, "src")
        make_package(os.path.join(src, "patio_nuit__sequence__6s"), info={"titre": "Nouveau patio"})
        make_package(os.path.join(src, "casse"), skip=("composition.jsx",))
        make_package(os.path.join(self.lib, "patio_nuit__sequence__6s"))         # ancienne version
        zpath = os.path.join(self.tmp, "livraison.zip")
        with zipfile.ZipFile(zpath, "w") as z:
            for root, _dirs, files in os.walk(src):
                for name in files:
                    full = os.path.join(root, name)
                    z.write(full, os.path.relpath(full, src))
        self.assertEqual(animations.install(zpath), ["patio_nuit__sequence__6s"])
        self.assertEqual(animations.catalog()[0]["titre"], "Nouveau patio")
        self.assertEqual(sorted(os.listdir(self.lib)), ["patio_nuit__sequence__6s"])   # rien d'autre

    def test_install_refuses_paths_leaving_the_library(self):
        zpath = os.path.join(self.tmp, "piege.zip")
        with zipfile.ZipFile(zpath, "w") as z:
            z.writestr("../../evil.txt", "x")
        with self.assertRaisesRegex(animations.AnimationError, "Chemin refusé"):
            animations.install(zpath)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "evil.txt")))


if __name__ == "__main__":
    unittest.main()
