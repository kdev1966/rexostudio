"""Effets photo (M5) : apercu, cadre PhotoCraft, enregistrement dans 06_Rendus."""
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from montagia import config, effects, photocraft  # noqa: E402

# Faux rexo-segment : copie l'entree vers la sortie, note ses arguments,
# repond comme le vrai (orient : taille 4000 x 3000).
FAKE_SEGMENT = """#!/bin/bash
echo "$@" >> "%(log)s"
cp "$2" "$3"
if [ "$1" = "orient" ]; then
  echo '{"ok":true,"width":4000,"height":3000,"coverage":0,"ms":5}'
else
  echo '{"ok":true,"width":4000,"height":3000,"coverage":0.31,"ms":2100}'
fi
"""

FAILING_SEGMENT = """#!/bin/bash
echo '{"ok":false,"error":"image illisible"}'
exit 1
"""


class EffectsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rexo-fx-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.event = os.path.join(self.tmp, "2026-11-16_Mariage_Test")
        self.photo = os.path.join(self.event, "02_Photos", "Carte_1", "IMG_0001.jpg")
        os.makedirs(os.path.dirname(self.photo))
        with open(self.photo, "wb") as fh:
            fh.write(b"\xff\xd8photo")
        self.log = os.path.join(self.tmp, "segment.log")
        self._binary(FAKE_SEGMENT % {"log": self.log})

    def _binary(self, script):
        path = os.path.join(self.tmp, "rexo-segment")
        with open(path, "w") as fh:
            fh.write(script)
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
        patcher = mock.patch.object(config, "SEGMENT_BIN", path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _calls(self):
        with open(self.log) as fh:
            return [line.split() for line in fh.read().splitlines()]

    # -- cadre ----------------------------------------------------------
    def test_box_fractions_to_pixels(self):
        self.assertEqual(effects.check_box([0.1, 0.2, 0.5, 0.5], 4000, 3000),
                         [400.0, 600.0, 2000.0, 1500.0])

    def test_box_clamped_to_image(self):
        self.assertEqual(effects.check_box([-0.2, 0.5, 0.6, 0.9], 1000, 1000),
                         [0.0, 500.0, 400.0, 500.0])

    def test_box_too_small_or_invalid(self):
        with self.assertRaises(effects.EffectError):
            effects.check_box([0.5, 0.5, 0.001, 0.2], 4000, 3000)
        with self.assertRaises(effects.EffectError):
            effects.check_box(["a", 0, 1, 1], 4000, 3000)
        with self.assertRaises(effects.EffectError):
            effects.check_box([0, 0, 1], 4000, 3000)

    # -- apercu ---------------------------------------------------------
    def test_preview_vision_only(self):
        r = effects.preview(self.event, self.photo, "noir-et-blanc")
        self.assertTrue(os.path.isfile(r["path"]))
        self.assertTrue(r["path"].startswith(os.path.join(self.event, ".rexo", "effets")))
        self.assertTrue(r["path"].endswith("_noir-et-blanc.jpg"))
        self.assertFalse(r["framed"])
        self.assertEqual(r["coverage"], 0.31)
        self.assertEqual(self._calls(), [["bw", self.photo, r["path"]]])

    def test_preview_with_box_uses_photocraft_on_reduced_copy(self):
        seen = {}

        def fake_cutout(src, rect, out):
            seen["src"], seen["rect"] = src, rect
            shutil.copyfile(src, out)
            return [100, 200, 300, 400]

        with mock.patch.object(photocraft, "installed", return_value=True), \
                mock.patch.object(photocraft, "object_cutout", side_effect=fake_cutout):
            r = effects.preview(self.event, self.photo, "detourage", box=[0.25, 0.1, 0.5, 0.8])
        self.assertTrue(r["framed"])
        self.assertTrue(r["path"].endswith("_detourage_cadre.png"))
        # Copie reduite a 2048 px de grand cote : cadre mis a la meme echelle
        scale = 2048 / 4000.0
        self.assertEqual([round(v, 3) for v in seen["rect"]],
                         [round(v * scale, 3) for v in (1000, 300, 2000, 2400)])
        self.assertEqual(r["object_bounds"], [round(v / scale) for v in (100, 200, 300, 400)])
        calls = self._calls()
        self.assertEqual(calls[0][:2], ["orient", self.photo])
        self.assertEqual(calls[0][-2:], ["--max", "2048"])
        self.assertEqual(calls[1][:3], ["cutout", self.photo, r["path"]])
        self.assertEqual(calls[1][3], "--add-mask")
        # Fichiers intermediaires effaces : il ne reste que l'apercu
        self.assertEqual(os.listdir(os.path.dirname(r["path"])), [os.path.basename(r["path"])])

    def test_preview_box_without_photocraft(self):
        with mock.patch.object(photocraft, "installed", return_value=False), \
                self.assertRaises(effects.EffectError):
            effects.preview(self.event, self.photo, "detourage", box=[0, 0, 1, 1])

    def test_photocraft_failure_is_reported(self):
        with mock.patch.object(photocraft, "installed", return_value=True), \
                mock.patch.object(photocraft, "object_cutout",
                                  side_effect=photocraft.PhotoCraftError("Aucun objet trouvé dans le cadre.")), \
                self.assertRaises(effects.EffectError) as ctx:
            effects.preview(self.event, self.photo, "detourage", box=[0, 0, 1, 1])
        self.assertIn("Aucun objet", str(ctx.exception))
        self.assertEqual(os.listdir(os.path.join(self.event, ".rexo", "effets")), [])

    def test_only_current_photo_previews_kept(self):
        other = os.path.join(self.event, "02_Photos", "Carte_1", "IMG_0002.jpg")
        shutil.copyfile(self.photo, other)
        first = effects.preview(self.event, self.photo, "fond-flou")["path"]
        effects.preview(self.event, self.photo, "noir-et-blanc")
        self.assertTrue(os.path.isfile(first))
        effects.preview(self.event, other, "fond-flou")
        self.assertFalse(os.path.exists(first))

    def test_tool_error_message(self):
        self._binary(FAILING_SEGMENT)
        with self.assertRaises(effects.EffectError) as ctx:
            effects.preview(self.event, self.photo, "fond-flou")
        self.assertIn("image illisible", str(ctx.exception))

    def test_rejects_unknown_effect_and_non_photos(self):
        with self.assertRaises(effects.EffectError):
            effects.preview(self.event, self.photo, "pixelise")
        video = os.path.join(self.event, "01_Rushes", "C0001.MP4")
        os.makedirs(os.path.dirname(video))
        open(video, "wb").close()
        with self.assertRaises(effects.EffectError):
            effects.preview(self.event, video, "fond-flou")

    def test_one_effect_at_a_time(self):
        self.assertTrue(effects._LOCK.acquire(blocking=False))
        try:
            with self.assertRaises(effects.EffectError):
                effects.preview(self.event, self.photo, "fond-flou")
        finally:
            effects._LOCK.release()

    # -- enregistrement -------------------------------------------------
    def test_save_copies_into_renders_without_overwriting(self):
        effects.preview(self.event, self.photo, "noir-et-blanc")
        first = effects.save(self.event, self.photo, "noir-et-blanc", False)
        second = effects.save(self.event, self.photo, "noir-et-blanc", False)
        self.assertEqual(first, os.path.join("06_Rendus", "Photos_effets", "IMG_0001_noir-et-blanc.jpg"))
        self.assertEqual(second, os.path.join("06_Rendus", "Photos_effets", "IMG_0001_noir-et-blanc-2.jpg"))
        with open(os.path.join(self.event, first), "rb") as fh:
            self.assertEqual(fh.read(), b"\xff\xd8photo")
        # L'original n'a pas bouge
        self.assertTrue(os.path.isfile(self.photo))

    def test_save_without_preview(self):
        with self.assertRaises(effects.EffectError):
            effects.save(self.event, self.photo, "detourage", False)


class PhotoCraftTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rexo-pc-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.src = os.path.join(self.tmp, "in.jpg")
        open(self.src, "wb").close()
        self.args = os.path.join(self.tmp, "args.json")

    def _cli(self, selected=True):
        """Faux photocraft-cli : note ses arguments, ecrit --out, repond en JSON."""
        path = os.path.join(self.tmp, "photocraft-cli")
        result = {"bounds": [1, 2, 30, 40], "changed": True, "selected": selected}
        with open(path, "w") as fh:
            fh.write("#!/usr/bin/env python3\nimport json, sys\n"
                     "a = sys.argv[1:]\n"
                     "json.dump(a, open(%r, 'w'))\n"
                     "open(a[a.index('--out') + 1], 'w').close()\n"
                     "print(json.dumps({'command': 'select.object', 'result': %s}))\n"
                     "print(json.dumps({'command': 'layer.layerMask.revealSelection', 'result': None}))\n"
                     "print('warning: 1 layer(s) flattened', file=sys.stderr)\n"
                     % (self.args, json.dumps(result).replace("true", "True").replace("false", "False")))
        os.chmod(path, 0o755)
        patcher = mock.patch.object(config, "PHOTOCRAFT_CLI", path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_object_cutout_command_line(self):
        self._cli()
        out = os.path.join(self.tmp, "sub", "out.png")
        bounds = photocraft.object_cutout(self.src, [10.4, 20.6, 300, 400], out)
        self.assertEqual(bounds, [1, 2, 30, 40])
        with open(self.args) as fh:
            args = json.load(fh)
        self.assertEqual(args[:2], ["run", self.src])
        self.assertEqual(args[2:4], ["--cmd", "select.object"])
        self.assertEqual(json.loads(args[5]), {"rect": [10, 21, 300, 400], "mode": "replace"})
        self.assertEqual(args[6:8], ["--cmd", "layer.layerMask.revealSelection"])
        self.assertEqual(args[-2:], ["--out", out])

    def test_nothing_selected(self):
        self._cli(selected=False)
        with self.assertRaises(photocraft.PhotoCraftError):
            photocraft.object_cutout(self.src, [0, 0, 100, 100], os.path.join(self.tmp, "o.png"))

    def test_never_overwrites_source(self):
        self._cli()
        with self.assertRaises(photocraft.PhotoCraftError):
            photocraft.run(self.src, [], self.src)


if __name__ == "__main__":
    unittest.main()
