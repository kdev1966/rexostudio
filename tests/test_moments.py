"""Moments forts : notes par fenetre, choix d'un moment par rush, orientation."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from montagia import moments  # noqa: E402


def _series(seconds, luma=120.0, blur=3.0, shaky_from=None):
    """Mesures factices : 4 i/s (luminance, nettete), 12 i/s (mouvement)."""
    motion = []
    for i in range(int(seconds * 12)):
        t = i / 12.0
        jitter = 25 if shaky_from is not None and t >= shaky_from and i % 2 else 0
        motion.append((float(jitter), 0.0))
    return {"luma": [luma] * int(seconds * 4), "blur": [blur] * int(seconds * 4), "motion": motion}


class WindowScoreCase(unittest.TestCase):
    def test_sharp_stable_window_beats_shaky_one(self):
        scores = moments.window_scores(_series(10, shaky_from=5), 10, window=3, step=1)
        self.assertEqual(scores[0]["start"], 0.0)
        best = max(scores, key=lambda w: w["score"])
        self.assertLess(best["end"], 6)                 # avant le tremblement
        worst = min(scores, key=lambda w: w["score"])
        self.assertGreater(worst["end"], 6)                  # surtout dans le tremblement

    def test_dark_and_blurry_windows_score_low(self):
        good = moments.window_scores(_series(4), 4, window=3)[0]["score"]
        dark = moments.window_scores(_series(4, luma=30), 4, window=3)[0]["score"]
        blurry = moments.window_scores(_series(4, blur=12), 4, window=3)[0]["score"]
        self.assertGreater(good, dark)
        self.assertGreater(good, blurry)

    def test_rush_shorter_than_window_has_no_moment(self):
        self.assertEqual(moments.window_scores(_series(2), 2, window=3), [])

    def test_orientation_follows_most_rushes(self):
        vertical = {"width": 720, "height": 1280}
        horizontal = {"width": 1920, "height": 1080}
        self.assertEqual(moments.orientation([vertical, vertical, horizontal]), (1080, 1920))
        self.assertEqual(moments.orientation([horizontal, vertical]), (1920, 1080))


class PeopleShareCase(unittest.TestCase):
    def test_silhouettes_count_when_the_mask_sees_nobody(self):
        work = tempfile.mkdtemp(prefix="rexo-gens-")
        self.addCleanup(shutil.rmtree, work, True)
        veiled = {"ok": True, "coverage": 0, "persons": [[0.23, 0.34, 0.32, 0.52]]}
        with mock.patch.object(moments.tools, "run"), \
                mock.patch.object(moments.effects, "segment", return_value=veiled):
            self.assertAlmostEqual(moments.people_share("/r/a.mp4", 3.0, work), 0.5 * 0.32 * 0.52, places=4)
        seen = {"ok": True, "coverage": 0.56, "persons": [[0.1, 0.1, 0.4, 0.8]]}
        with mock.patch.object(moments.tools, "run"), \
                mock.patch.object(moments.effects, "segment", return_value=seen):
            self.assertEqual(moments.people_share("/r/a.mp4", 3.0, work), 0.56)


class FindCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rexo-moments-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.clips = [
            {"rel": "01_Rushes/a.mp4", "name": "a.mp4", "path": "/r/a.mp4", "duration": 8, "analyzed": True,
             "kept": True, "shot_at": "2026-11-16 18:00:00", "width": 720, "height": 1280},
            {"rel": "01_Rushes/b.mp4", "name": "b.mp4", "path": "/r/b.mp4", "duration": 8, "analyzed": True,
             "kept": True, "shot_at": "2026-11-16 17:00:00", "width": 720, "height": 1280},
            {"rel": "01_Rushes/c.mp4", "name": "c.mp4", "path": "/r/c.mp4", "duration": 8, "analyzed": True,
             "kept": False, "shot_at": "2026-11-16 16:00:00", "width": 720, "height": 1280},
        ]

    def test_one_moment_per_kept_rush_in_shooting_order(self):
        series = {"/r/a.mp4": _series(8, shaky_from=4), "/r/b.mp4": _series(8, blur=6)}
        with mock.patch.object(moments.rushes, "clip_list", return_value=self.clips), \
                mock.patch.object(moments, "measure_series", side_effect=lambda p, _d: series[p]), \
                mock.patch.object(moments, "people_share", return_value=0.2):
            result = moments.find(self.tmp, count=6)
        self.assertEqual([m["name"] for m in result["moments"]], ["b.mp4", "a.mp4"])   # c n'est pas garde
        self.assertEqual(result["explored"], 2)
        with open(os.path.join(self.tmp, moments.STATE_FILE)) as fh:
            self.assertEqual(len(json.load(fh)["moments"]), 2)

    def test_people_break_ties_between_windows(self):
        clip = dict(self.clips[0], duration=6)
        shares = {1.5: 0.0, 2.0: 0.25}

        def share(_path, at, _work):
            return shares.get(at, 0.0)

        with mock.patch.object(moments.rushes, "clip_list", return_value=[clip]), \
                mock.patch.object(moments, "measure_series", return_value=_series(6)), \
                mock.patch.object(moments, "people_share", side_effect=share):
            result = moments.find(self.tmp, count=1)
        self.assertEqual(result["moments"][0]["start"], 0.5)          # la fenetre avec des personnes

    def test_no_kept_rush_is_an_error(self):
        with mock.patch.object(moments.rushes, "clip_list", return_value=[self.clips[2]]), \
                self.assertRaises(moments.MomentError):
            moments.find(self.tmp)

    def test_load_keeps_only_moments_of_rushes_still_kept(self):
        os.makedirs(os.path.join(self.tmp, "01_Rushes"))
        for name in ("a.mp4", "c.mp4"):
            with open(os.path.join(self.tmp, "01_Rushes", name), "w") as fh:
                fh.write("x")
        saved = {"moments": [{"rel": "01_Rushes/a.mp4", "start": 1}, {"rel": "01_Rushes/b.mp4", "start": 2},
                             {"rel": "01_Rushes/c.mp4", "start": 3}]}
        os.makedirs(os.path.join(self.tmp, ".rexo"), exist_ok=True)
        with open(os.path.join(self.tmp, moments.STATE_FILE), "w") as fh:
            json.dump(saved, fh)
        with mock.patch.object(moments.rushes, "clip_list", return_value=self.clips):
            loaded = moments.load(self.tmp)
        # b a disparu du disque, c n'est plus garde
        self.assertEqual([m["rel"] for m in loaded["moments"]], ["01_Rushes/a.mp4"])
        with mock.patch.object(moments.rushes, "clip_list", return_value=[]):
            self.assertIsNone(moments.load(self.tmp))

    def test_load_without_saved_moments(self):
        self.assertIsNone(moments.load(self.tmp))


if __name__ == "__main__":
    unittest.main()
