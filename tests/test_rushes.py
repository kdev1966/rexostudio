"""Derushage (M1) : import verifie, tri par la qualite, selection FilmCraft."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from fractions import Fraction
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from montagia import config, events, filmcraft, rushes  # noqa: E402
from test_filmcraft import TOKEN, FakeFilmCraft  # noqa: E402

FFMPEG = config.ffmpeg_bin()


def make_clip(path, seconds=3, vf="null", when="2026-11-14T16:00:00Z"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=size=640x360:rate=25:duration=%d" % seconds,
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=%d" % seconds,
                    "-vf", vf, "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", "-metadata", "creation_time=" + when, path],
                   check=True)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rexo-rushes-")
        self.root = os.path.join(self.tmp, "Evenements")
        self.event = events.create(self.root, "Mariage", "2026-11-14", "A et B")["path"]
        self.card = os.path.join(self.tmp, "CARTE", "DCIM", "100MEDIA")
        os.makedirs(self.card)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, name, data):
        path = os.path.join(self.card, name)
        with open(path, "wb") as fh:
            fh.write(data)
        return path


class ImportTest(Base):
    def test_copies_videos_and_photos_verified_and_keeps_source(self):
        self.write("C0001.MP4", b"v" * 1000)
        self.write("DSC_0001.JPG", b"p" * 10)
        self.write(".hidden.MP4", b"x")
        before = sorted(os.listdir(self.card))
        result = rushes.import_card(self.event, os.path.dirname(os.path.dirname(self.card)))
        self.assertEqual((result["card"], result["copied"]), ("Carte_1", 2))
        video = os.path.join(self.event, "01_Rushes", "Carte_1", "DCIM", "100MEDIA", "C0001.MP4")
        photo = os.path.join(self.event, "02_Photos", "Carte_1", "DCIM", "100MEDIA", "DSC_0001.JPG")
        with open(video, "rb") as fh:
            self.assertEqual(fh.read(), b"v" * 1000)
        self.assertTrue(os.path.isfile(photo))
        self.assertEqual(sorted(os.listdir(self.card)), before)        # source intacte
        self.assertEqual(os.path.getmtime(video),
                         os.path.getmtime(os.path.join(self.card, "C0001.MP4")))
        state = rushes.load_state(self.event)
        self.assertEqual(len(state["clips"]), 1)
        self.assertEqual(len(state["imports"]), 1)

    def test_reimport_copies_nothing_and_leaves_no_empty_card(self):
        self.write("C0001.MP4", b"v" * 100)
        source = os.path.dirname(self.card)
        rushes.import_card(self.event, source)
        again = rushes.import_card(self.event, source)
        self.assertEqual((again["copied"], again["card"]), (0, ""))
        self.assertEqual(os.listdir(os.path.join(self.event, "01_Rushes")), ["Carte_1"])
        self.assertEqual(len(rushes.load_state(self.event)["imports"]), 1)

    def test_same_file_on_another_card_is_a_duplicate(self):
        self.write("C0001.MP4", b"same")
        rushes.import_card(self.event, os.path.dirname(self.card))
        other = os.path.join(self.tmp, "AUTRE")
        os.makedirs(other)
        with open(os.path.join(other, "copie.MP4"), "wb") as fh:
            fh.write(b"same")
        result = rushes.import_card(self.event, other)
        self.assertEqual(result["copied"], 0)
        self.assertFalse(os.path.exists(os.path.join(self.event, "01_Rushes", "Carte_2")))

    def test_corrupted_copy_is_refused_and_removed(self):
        self.write("C0001.MP4", b"v" * 100)
        with mock.patch.object(rushes, "_sha256", return_value="0" * 64), \
                self.assertRaises(rushes.RushError):
            rushes.import_card(self.event, os.path.dirname(self.card))
        dest = os.path.join(self.event, "01_Rushes", "Carte_1", "100MEDIA")
        self.assertFalse(os.path.exists(os.path.join(dest, "C0001.MP4")))
        self.assertFalse(os.path.exists(os.path.join(dest, "C0001.MP4.part")))
        self.assertTrue(os.path.isfile(os.path.join(self.card, "C0001.MP4")))

    def test_refuses_event_folder_as_source_and_empty_source(self):
        with self.assertRaises(rushes.RushError):
            rushes.import_card(self.event, self.event)
        with self.assertRaises(rushes.RushError):
            rushes.import_card(self.event, self.card)                   # vide

    def test_refuses_when_disk_is_full(self):
        self.write("C0001.MP4", b"v" * 100)
        usage = shutil.disk_usage(self.tmp)._replace(free=10)
        with mock.patch.object(rushes.shutil, "disk_usage", return_value=usage), \
                self.assertRaisesRegex(rushes.RushError, "Place insuffisante"):
            rushes.import_card(self.event, os.path.dirname(self.card))


class MetricsTest(unittest.TestCase):
    def test_parse_motion_uses_median_of_local_vectors(self):
        trf = ("VID.STAB 1\n# x\nFrame 1 (List 0 [])\n"
               "Frame 2 (List 3 [(LM 4 -2 1 1 32 0.5 0.1),(LM 6 -2 1 1 32 0.5 0.1),"
               "(LM 50 9 1 1 32 0.5 0.1)])\n")
        self.assertEqual(rushes.parse_motion(trf), [(0.0, 0.0), (6, -2)])

    def test_shake_index_pan_vs_shake(self):
        pan = [(5, 0)] * 30
        shake = [(8 if i % 2 else -8, 6 if i % 3 else -6) for i in range(30)]
        self.assertEqual(rushes.shake_index(pan, 480), 0.0)
        self.assertGreater(rushes.shake_index(shake, 480), rushes.SHAKE_LIMIT)

    def test_parse_frames_skips_nan(self):
        text = "frame:0 pts:0\nlavfi.signalstats.YAVG=20.5\nlavfi.blur.blur=nan\n"
        self.assertEqual(rushes.parse_frames(text), [{"YAVG": 20.5}])

    def test_classify(self):
        self.assertEqual(rushes.classify({"luma": 120, "blur": 4, "shake": 0.2}, 10), [])
        self.assertEqual(rushes.classify({"luma": 18, "blur": 20, "shake": 5}, 10), ["noir"])
        self.assertEqual(rushes.classify({"luma": 40}, 10), ["sombre"])
        self.assertEqual(rushes.classify({"luma": 210}, 10), ["surexpose"])
        self.assertEqual(rushes.classify({"luma": 120, "blur": 12, "shake": 3}, 1.0),
                         ["flou", "tremble", "court"])

    def test_old_state_with_nan_loads_as_valid_json(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        os.makedirs(os.path.join(tmp, ".rexo"))
        with open(os.path.join(tmp, ".rexo", "rushes.json"), "w") as fh:
            fh.write('{"clips": {"a": {"metrics": {"blur": NaN, "luma": 18.0}}}}')
        state = rushes.load_state(tmp)
        json.dumps(state, allow_nan=False)
        self.assertIsNone(state["clips"]["a"]["metrics"]["blur"])

    def test_kept_follows_choice_then_proposal(self):
        self.assertTrue(rushes.is_kept({"issues": [], "keep": None}))
        self.assertFalse(rushes.is_kept({"issues": ["flou"], "keep": None}))
        self.assertTrue(rushes.is_kept({"issues": ["flou"], "keep": True}))


@unittest.skipUnless(FFMPEG, "ffmpeg absent")
class AnalyzeTest(Base):
    def test_analyze_detects_defects_and_orders_by_shot_time(self):
        rushdir = os.path.join(self.event, "01_Rushes", "Carte_1")
        make_clip(os.path.join(rushdir, "B_bon.MP4"), when="2026-11-14T18:00:00Z")
        make_clip(os.path.join(rushdir, "A_noir.MP4"), vf="lutrgb=r=val*0.02:g=val*0.02:b=val*0.02",
                  when="2026-11-14T17:00:00Z")
        make_clip(os.path.join(rushdir, "C_flou.MP4"), vf="gblur=sigma=14", when="2026-11-14T19:00:00Z")
        result = rushes.analyze(self.event)
        self.assertEqual(result["analyzed"], 3)
        clips = rushes.clip_list(self.event)
        self.assertEqual([c["name"] for c in clips], ["A_noir.MP4", "B_bon.MP4", "C_flou.MP4"])
        self.assertEqual([c["issues"] for c in clips], [["noir"], [], ["flou"]])
        self.assertEqual(clips[1]["shot_at"], "2026-11-14 18:00:00")
        self.assertTrue(all(os.path.isfile(c["thumb"]) for c in clips))
        self.assertEqual([c["kept"] for c in clips], [False, True, False])
        # deuxieme passage : rien a refaire
        self.assertEqual(rushes.analyze(self.event)["analyzed"], 0)
        rushes.set_keep(self.event, clips[2]["rel"], True)
        self.assertTrue(rushes.clip_list(self.event)[2]["kept"])

    def test_proxies(self):
        make_clip(os.path.join(self.event, "01_Rushes", "Carte_1", "C0001.MP4"))
        self.assertEqual(rushes.make_proxies(self.event)["made"], 1)
        clip = rushes.clip_list(self.event)[0]
        self.assertTrue(clip["proxy"].endswith(os.path.join("04_Proxies", "Carte_1", "C0001_proxy.mp4")))
        self.assertEqual(rushes.make_proxies(self.event)["made"], 0)


class SelectionTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeFilmCraft()
        self.addCleanup(self.fake.close)
        self.out = os.path.join(tempfile.mkdtemp(), "Selection.fcproj")

    def test_build_selection_places_clips_end_to_end(self):
        client = filmcraft.Client(self.fake.port, TOKEN)
        clips = [{"path": "/x/a.mp4", "duration": 2.0, "name": "a", "has_audio": True, "note": "n"},
                 {"path": "/x/b.mp4", "duration": 1.0, "name": "b", "has_audio": False, "note": "n"}]
        result = filmcraft.build_selection(client, clips, self.out, Fraction(25), (1920, 1080))
        self.assertEqual((result["clips"], result["duration"]), (2, 3.0))
        T = filmcraft.TICKS_PER_SECOND
        self.assertEqual([c["time"] for c in self.fake.clips], [0, 2 * T])
        self.assertEqual([c["sourceIn"] for c in self.fake.clips], [0, 0])
        self.assertEqual(self.fake.markers, 2)
        self.assertEqual(filmcraft.read_project(self.out)["sequences"][0]["clips"], 2)

    def test_empty_selection_refused(self):
        client = filmcraft.Client(self.fake.port, TOKEN)
        with self.assertRaises(filmcraft.FilmCraftError):
            filmcraft.build_selection(client, [], self.out, Fraction(25), (1920, 1080))


class SourcesTest(unittest.TestCase):
    def test_lists_only_volumes_with_media(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        os.makedirs(os.path.join(tmp, "CARTE", "DCIM"))
        open(os.path.join(tmp, "CARTE", "DCIM", "a.MP4"), "wb").close()
        os.makedirs(os.path.join(tmp, "VIDE"))
        real_stat = os.stat

        def fake_stat(path, *a, **k):
            st = real_stat(path, *a, **k)
            if path == "/":
                return os.stat_result((0,) * 2 + (-1,) + tuple(st)[3:])   # autre disque
            return st
        with mock.patch.object(rushes.os, "stat", side_effect=fake_stat):
            names = [s["name"] for s in rushes.list_sources(tmp)]
        self.assertEqual(names, ["CARTE"])


class PhotoChoiceTest(Base):
    def setUp(self):
        super().setUp()
        self.rel = os.path.join("02_Photos", "Carte_1", "IMG_1.jpg")
        os.makedirs(os.path.dirname(os.path.join(self.event, self.rel)))
        with open(os.path.join(self.event, self.rel), "wb") as fh:
            fh.write(b"jpg")

    def photo(self):
        return next(p for p in rushes.photo_list(self.event) if p["rel"] == self.rel)

    def test_choice_for_montage_and_couple_frame_are_kept(self):
        self.assertEqual((self.photo()["montage"], self.photo()["box"]), (False, None))
        rushes.set_photo(self.event, self.rel, montage=True)
        rushes.set_photo(self.event, self.rel, box=[0.1, 0.2, 0.5, 0.7])
        self.assertEqual((self.photo()["montage"], self.photo()["box"]), (True, [0.1, 0.2, 0.5, 0.7]))
        self.assertEqual(rushes.photo_box(self.event, self.rel), [0.1, 0.2, 0.5, 0.7])
        rushes.set_photo(self.event, self.rel, montage=False, box=None)
        self.assertEqual(rushes.load_state(self.event)["photos"], {})          # rien de garde pour rien

    def test_refuses_unknown_photo_and_bad_frame(self):
        with self.assertRaises(rushes.RushError):
            rushes.set_photo(self.event, "02_Photos/absente.jpg", montage=True)
        with self.assertRaises(rushes.RushError):
            rushes.set_photo(self.event, "../../etc/passwd", montage=True)
        for bad in ([0.1, 0.2, 0.5], [0.1, 0.2, 0, 0.5], [0.1, 0.2, 1.5, 0.5], "abcd"):
            with self.assertRaises(rushes.RushError):
                rushes.set_photo(self.event, self.rel, box=bad)

    def test_trashed_photo_is_forgotten(self):
        rushes.set_photo(self.event, self.rel, montage=True)
        os.remove(os.path.join(self.event, self.rel))
        rushes.forget_missing(self.event)
        self.assertEqual(rushes.load_state(self.event)["photos"], {})


if __name__ == "__main__":
    unittest.main()
