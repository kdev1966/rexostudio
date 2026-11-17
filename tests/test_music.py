"""Musique du generique et du teaser : bibliotheque, depart sur l'energie, mixage."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from montagia import config, music, studio  # noqa: E402
from montagia.jobs import Job  # noqa: E402


def series(levels):
    return [(round(i * music.STEP, 1), m) for i, m in enumerate(levels)]


class StartOffsetCase(unittest.TestCase):
    def test_quiet_intro_is_skipped(self):
        levels = [-45] * 80 + [-18] * 220                     # 8 s calmes, puis le morceau
        self.assertEqual(music.start_offset(series(levels), 6), 8.0)

    def test_offset_leaves_enough_music_for_the_video(self):
        levels = [-45] * 80 + [-18] * 220                     # 30 s en tout
        self.assertEqual(music.start_offset(series(levels), 25), 5.0)
        self.assertEqual(music.start_offset(series(levels), 40), 0.0)

    def test_even_track_starts_at_the_beginning(self):
        self.assertEqual(music.start_offset(series([-16] * 300), 10), 0.0)
        self.assertEqual(music.start_offset([], 10), 0.0)


class LibraryCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rexo-musique-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.lib = os.path.join(self.tmp, "musiques")
        self.event = os.path.join(self.tmp, "evt")
        for path in (os.path.join(self.lib, "Andalou", "nouba.mp3"), os.path.join(self.lib, "notes.txt"),
                     os.path.join(self.event, "03_Audio", "entree.m4a")):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as fh:
                fh.write("x")
        p = mock.patch.object(config, "MUSIC_DIR", self.lib)
        p.start()
        self.addCleanup(p.stop)

    def test_library_lists_studio_then_event_tracks(self):
        items = music.library(self.event)
        self.assertEqual([(m["id"], m["source"]) for m in items],
                         [("bib:Andalou/nouba.mp3", "bibliothèque"), ("evt:entree.m4a", "événement")])
        self.assertEqual(music.resolve(self.event, "evt:entree.m4a"),
                         os.path.realpath(os.path.join(self.event, "03_Audio", "entree.m4a")))

    def test_resolve_refuses_paths_outside_and_non_music(self):
        for bad in ("bib:../evt/03_Audio/entree.m4a", "bib:notes.txt", "xyz:nouba.mp3", "bib:", "",
                    "bib:/etc/passwd"):
            with self.assertRaises(music.MusicError):
                music.resolve(self.event, bad)


class MixCase(unittest.TestCase):
    @unittest.skipUnless(config.ffmpeg_bin(), "ffmpeg absent")
    def test_music_is_laid_at_video_length(self):
        tmp = tempfile.mkdtemp(prefix="rexo-mix-")
        self.addCleanup(shutil.rmtree, tmp, True)
        video, track = os.path.join(tmp, "v.mp4"), os.path.join(tmp, "m.m4a")
        subprocess.run([config.ffmpeg_bin(), "-v", "error", "-y", "-f", "lavfi", "-i",
                        "color=c=black:s=320x568:r=25:d=3", "-c:v", "libx264", "-preset", "ultrafast", video],
                       check=True)
        subprocess.run([config.ffmpeg_bin(), "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=330:d=10",
                        "-c:a", "aac", track], check=True)
        result = music.soundtrack(video, track)
        self.assertEqual(result["duration"], 3.0)
        streams = subprocess.run([config.ffprobe_bin(), "-v", "error", "-show_entries", "stream=codec_type",
                                  "-of", "csv=p=0", video], capture_output=True, text=True).stdout.split()
        self.assertEqual(sorted(streams), ["audio", "video"])

    def test_failed_music_keeps_the_silent_video(self):
        job, result = Job("studio"), {}
        with mock.patch.object(music, "soundtrack", side_effect=music.MusicError("illisible")):
            studio._add_music(job, "/x.mp4", "/m.mp3", [], False, "Musique", result)
        self.assertFalse(result["music"])
        self.assertTrue(any("sans son" in line for line in job.log))


if __name__ == "__main__":
    unittest.main()
