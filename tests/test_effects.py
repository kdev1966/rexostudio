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


class PhotoEventCase(unittest.TestCase):
    """Un evenement temporaire avec une photo, et un faux rexo-segment."""

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


class EffectsTest(PhotoEventCase):
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
        alpha = os.path.join(os.path.dirname(r["path"]),
                             effects.mask_name("02_Photos/Carte_1/IMG_0001.jpg", "noir-et-blanc", False))
        self.assertEqual(self._calls(), [["bw", self.photo, r["path"], "--save-alpha", alpha]])

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
        self.assertEqual(calls[1][3], "--save-alpha")
        self.assertTrue(calls[1][4].endswith("_detourage_cadre_masque.png"))
        self.assertEqual(calls[1][5], "--save-fg")
        self.assertTrue(calls[1][6].endswith("_detourage_cadre_couleurs.jpg"))
        self.assertEqual(calls[1][7], "--add-mask")
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

    # -- PSD a calques pour PhotoCraft ----------------------------------
    def _fake_alpha(self, r, effect, framed=False):
        alpha = os.path.join(os.path.dirname(r["path"]),
                             effects.mask_name("02_Photos/Carte_1/IMG_0001.jpg", effect, framed))
        open(alpha, "wb").close()
        return alpha

    def test_export_psd_layers(self):
        r = effects.preview(self.event, self.photo, "fond-flou")
        alpha = self._fake_alpha(r, "fond-flou")
        seen = {}

        def fake_psd(base, effect_image, alpha_png, mode, name, out, roots, base_name=""):
            seen.update(base=base, effect=effect_image, alpha=alpha_png, mode=mode, name=name,
                        out=out, roots=roots, base_exists=os.path.isfile(base), base_name=base_name)
            return {"path": out}

        with mock.patch.object(photocraft, "installed", return_value=True), \
                mock.patch.object(photocraft, "layered_psd", side_effect=fake_psd):
            out = effects.export_psd(self.event, self.photo, "fond-flou", False)
        self.assertEqual(out, os.path.join(self.event, "06_Rendus", "Photos_effets", "IMG_0001_fond-flou.psd"))
        self.assertEqual((seen["effect"], seen["alpha"], seen["mode"]), (r["path"], alpha, "outside"))
        self.assertIn("masque à affiner", seen["name"])
        self.assertTrue(seen["base_exists"])                       # photo redressee sans perte...
        self.assertFalse(os.path.exists(seen["base"]))              # ...effacee apres
        self.assertEqual(seen["roots"], [self.event])
        self.assertEqual(self._calls()[-1][:3], ["orient", self.photo, seen["base"]])
        self.assertEqual(seen["base_name"], "Photo originale")

    # -- amelioration avant l'effet -------------------------------------
    def test_enhance_before_effect(self):
        r = effects.preview(self.event, self.photo, "fond-flou", enhance=True)
        self.assertTrue(r["enhanced"])
        self.assertTrue(r["path"].endswith("_fond-flou_ameliore.jpg"))
        self.assertIn("--enhance", self._calls()[0])
        effects.save(self.event, self.photo, "fond-flou", False, True)
        with self.assertRaises(effects.EffectError):               # pas d'apercu sans amelioration
            effects.save(self.event, self.photo, "fond-flou", False, False)

    def test_enhance_only_effect(self):
        r = effects.preview(self.event, self.photo, "ameliorer", box=[0, 0, 1, 1], enhance=True)
        self.assertFalse(r["framed"])
        self.assertFalse(r["enhanced"])
        self.assertEqual(self._calls(), [["enhance", self.photo, r["path"]]])

    def test_enhanced_psd_uses_enhanced_base(self):
        r = effects.preview(self.event, self.photo, "noir-et-blanc", enhance=True)
        alpha = os.path.join(os.path.dirname(r["path"]),
                             effects.mask_name("02_Photos/Carte_1/IMG_0001.jpg", "noir-et-blanc", False, True))
        open(alpha, "wb").close()
        seen = {}
        with mock.patch.object(photocraft, "installed", return_value=True), \
                mock.patch.object(photocraft, "layered_psd",
                                  side_effect=lambda *a, **k: seen.update(a=a, k=k)):
            effects.export_psd(self.event, self.photo, "noir-et-blanc", False, enhanced=True)
        self.assertEqual(seen["a"][1], r["path"])
        self.assertEqual(seen["k"]["base_name"], "Photo améliorée")
        self.assertIn("--enhance", self._calls()[-1])               # fond du PSD ameliore aussi

    def test_export_psd_modes(self):
        modes = {}
        for effect, box in (("detourage", None), ("noir-et-blanc", None)):
            r = effects.preview(self.event, self.photo, effect, box)
            self._fake_alpha(r, effect)
            with mock.patch.object(photocraft, "installed", return_value=True), \
                    mock.patch.object(photocraft, "layered_psd",
                                      side_effect=lambda *a, **_k: modes.setdefault(a[3], a[4])):
                effects.export_psd(self.event, self.photo, effect, False)
        self.assertEqual(set(modes), {"keep", "outside"})

    def test_export_psd_cutout_uses_cleaned_colors(self):
        r = effects.preview(self.event, self.photo, "detourage")
        self._fake_alpha(r, "detourage")
        fg = os.path.join(os.path.dirname(r["path"]),
                          effects.fg_name("02_Photos/Carte_1/IMG_0001.jpg", False))
        open(fg, "wb").close()                       # le faux outil ne l'ecrit pas
        seen = {}
        with mock.patch.object(photocraft, "installed", return_value=True), \
                mock.patch.object(photocraft, "layered_psd",
                                  side_effect=lambda *a, **_k: seen.update(layer=a[1], mode=a[3])):
            effects.export_psd(self.event, self.photo, "detourage", False)
        self.assertEqual((seen["layer"], seen["mode"]), (fg, "keep"))

    def test_export_psd_needs_preview_and_mask(self):
        with mock.patch.object(photocraft, "installed", return_value=True):
            with self.assertRaises(effects.EffectError):
                effects.export_psd(self.event, self.photo, "fond-flou", False)
            effects.preview(self.event, self.photo, "fond-flou")          # pas de masque (faux outil)
            with self.assertRaises(effects.EffectError):
                effects.export_psd(self.event, self.photo, "fond-flou", False)

    def test_export_psd_failure_leaves_no_empty_file(self):
        r = effects.preview(self.event, self.photo, "fond-flou")
        self._fake_alpha(r, "fond-flou")
        with mock.patch.object(photocraft, "installed", return_value=True), \
                mock.patch.object(photocraft, "layered_psd",
                                  side_effect=photocraft.PhotoCraftError("arrêt")), \
                self.assertRaises(effects.EffectError):
            effects.export_psd(self.event, self.photo, "fond-flou", False)
        folder = os.path.join(self.event, "06_Rendus", "Photos_effets")
        self.assertEqual(os.listdir(folder), [])


# Faux python de l'environnement d'effets : note ses arguments et PYTHONPATH,
# copie l'entree vers la sortie, repond comme effects_worker/erase.py.
FAKE_EFFECTS_PYTHON = """#!/bin/bash
echo "$@" >> "%(log)s"
echo "PYTHONPATH=$PYTHONPATH OFFLINE=$EMBEDKIT_OFFLINE" >> "%(log)s"
cp "$2" "$3"
echo '{"ok":true,"width":4000,"height":3000,"coverage":0.012,"score":0.96,"ms":2200}'
"""


class EraseTest(PhotoEventCase):
    """Effacer un objet : l'environnement d'effets est un processus separe."""

    def setUp(self):
        super().setUp()
        self.erase_log = os.path.join(self.tmp, "erase.log")
        workers = os.path.join(self.tmp, "effects_worker")
        os.makedirs(workers)
        open(os.path.join(workers, "erase.py"), "w").close()
        python = os.path.join(self.tmp, "python")
        with open(python, "w") as fh:
            fh.write(FAKE_EFFECTS_PYTHON % {"log": self.erase_log})
        os.chmod(python, 0o755)
        for name, value in (("EFFECTS_PYTHON", python), ("EFFECTS_WORKER_DIR", workers)):
            patcher = mock.patch.object(config, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _erase_calls(self):
        with open(self.erase_log) as fh:
            return fh.read().splitlines()

    def test_erase_runs_worker_with_box(self):
        r = effects.preview(self.event, self.photo, "effacer", box=[0.1, 0.2, 0.3, 0.4])
        self.assertTrue(r["path"].endswith("_effacer_cadre.jpg"))
        self.assertTrue(os.path.isfile(r["path"]))
        self.assertEqual((r["coverage"], r["score"], r["ms"]), (0.012, 0.96, 2200))
        args, env = self._erase_calls()
        args = args.split()
        self.assertEqual(args[0], os.path.join(config.EFFECTS_WORKER_DIR, "erase.py"))
        self.assertEqual(args[1], self.photo)
        self.assertEqual(args[3:5], ["--box", "0.100000,0.200000,0.300000,0.400000"])
        self.assertEqual(args[5], "--mask")
        self.assertTrue(args[6].endswith("_effacer_cadre_masque.png"))
        self.assertIn("PYTHONPATH=" + config.EMBEDKIT_DIR, env)
        self.assertIn("OFFLINE=1", env)
        # Vision n'est pas appele pour une photo JPEG
        self.assertFalse(os.path.exists(self.log))

    def test_erase_needs_a_box(self):
        with self.assertRaises(effects.EffectError) as ctx:
            effects.preview(self.event, self.photo, "effacer")
        self.assertIn("cadre", str(ctx.exception))
        with self.assertRaises(effects.EffectError):
            effects.preview(self.event, self.photo, "effacer", box=[0.1, 0.1, 0.001, 0.5])

    def test_erase_enhanced_photo(self):
        r = effects.preview(self.event, self.photo, "effacer", box=[0.1, 0.1, 0.2, 0.2], enhance=True)
        self.assertTrue(r["path"].endswith("_effacer_cadre_ameliore.jpg"))
        enhance = self._calls()[0]
        self.assertEqual(enhance[:2], ["enhance", self.photo])
        args = self._erase_calls()[0].split()
        self.assertEqual(args[1], enhance[2])                  # efface sur la photo amelioree
        self.assertFalse(os.path.exists(enhance[2]))           # copie effacee ensuite

    def test_erase_heic_goes_through_vision_copy(self):
        heic = os.path.join(self.event, "02_Photos", "Carte_1", "IMG_0002.HEIC")
        shutil.copyfile(self.photo, heic)
        r = effects.preview(self.event, heic, "effacer", box=[0, 0, 1, 1])
        orient = self._calls()[0]
        self.assertEqual(orient[0], "orient")
        self.assertEqual(orient[1], heic)
        args = self._erase_calls()[0].split()
        self.assertEqual(args[1], orient[2])                  # la copie JPEG redressee
        self.assertFalse(os.path.exists(orient[2]))           # effacee ensuite
        self.assertTrue(os.path.isfile(r["path"]))

    def test_erase_unavailable_without_env(self):
        with mock.patch.object(config, "EFFECTS_PYTHON", os.path.join(self.tmp, "absent")):
            self.assertFalse(effects.available("effacer"))
            with self.assertRaises(effects.EffectError) as ctx:
                effects.preview(self.event, self.photo, "effacer", box=[0, 0, 1, 1])
        self.assertIn("install_effects_env", str(ctx.exception))

    def test_catalog_flags(self):
        cat = {e["key"]: e for e in effects.catalog()}
        self.assertTrue(cat["effacer"]["needs_box"])
        self.assertTrue(cat["effacer"]["available"])
        self.assertFalse(cat["fond-flou"]["needs_box"])

    def test_save_erased_photo(self):
        effects.preview(self.event, self.photo, "effacer", box=[0.1, 0.1, 0.2, 0.2])
        rel = effects.save(self.event, self.photo, "effacer", True)
        self.assertEqual(rel, os.path.join("06_Rendus", "Photos_effets", "IMG_0001_effacer.jpg"))


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
