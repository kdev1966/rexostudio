"""Videos sans parole : changements de plan et candidats visuels."""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from montagia import config, media, pipeline, prompts  # noqa: E402


def spans(cands):
    return [(c["start"], c["end"], c["kind"]) for c in cands]


class VisualCandidatesTest(unittest.TestCase):
    def test_talking_video_is_unchanged(self):
        # 9 s de parole sur 10 s : aucun candidat visuel (comportement d'avant).
        speech = [{"start": 0.0, "end": 4.0, "text": "Bonjour"},
                  {"start": 5.0, "end": 10.0, "text": "Suite"}]
        cands = pipeline.build_candidates(speech, duration=10.0, scenes=[4.5])
        self.assertEqual(spans(cands), [(0.0, 4.0, "parole"), (5.0, 10.0, "parole")])

    def test_silent_video_is_cut_at_scene_changes(self):
        cands = pipeline.build_candidates([], duration=12.0, scenes=[4.0, 9.0])
        self.assertEqual(spans(cands), [(0.0, 4.0, "visuel"), (4.0, 9.0, "visuel"),
                                        (9.0, 12.0, "visuel")])
        self.assertEqual([c["id"] for c in cands], ["S1", "S2", "S3"])

    def test_long_shot_is_split(self):
        cands = pipeline.build_candidates([], duration=20.0, scenes=[])
        self.assertEqual(len(cands), 3)
        self.assertTrue(all(c["duration"] <= pipeline.VISUAL_MAX_SECONDS for c in cands))
        self.assertAlmostEqual(sum(c["duration"] for c in cands), 20.0, places=2)

    def test_low_speech_video_mixes_both_kinds(self):
        speech = [{"start": 2.0, "end": 4.0, "text": "Une phrase"}]
        cands = pipeline.build_candidates(speech, duration=10.0, scenes=[7.0])
        self.assertEqual(spans(cands), [(0.0, 2.0, "visuel"), (2.0, 4.0, "parole"),
                                        (4.0, 7.0, "visuel"), (7.0, 10.0, "visuel")])

    def test_tiny_gaps_are_ignored(self):
        cands = pipeline.build_candidates([], duration=5.0, scenes=[0.4, 4.6])
        self.assertEqual(spans(cands), [(0.4, 4.6, "visuel")])

    def test_without_duration_nothing_is_invented(self):
        self.assertEqual(pipeline.build_candidates([], scenes=[1.0]), [])

    def test_prompt_labels_visual_candidates(self):
        cands = pipeline.build_candidates([], duration=6.0, scenes=[3.0])
        context = prompts.numbered_passages(cands)
        self.assertEqual(context.splitlines()[0], "S1 : [plan sans parole, 3 s]")


@unittest.skipUnless(config.ffmpeg_bin(), "ffmpeg absent")
class DetectScenesTest(unittest.TestCase):
    def test_detects_real_cuts(self):
        path = os.path.join(tempfile.mkdtemp(), "trois_plans.mp4")
        subprocess.run([
            config.ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=s=320x180:r=25:d=4",
            "-f", "lavfi", "-i", "mandelbrot=s=320x180:r=25",
            "-f", "lavfi", "-i", "smptebars=s=320x180:r=25:d=3",
            "-filter_complex",
            "[1]trim=duration=5,setpts=PTS-STARTPTS[m];[0][m][2]concat=n=3:v=1:a=0",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", path,
        ], check=True)
        self.assertEqual(media.detect_scenes(path), [4.0, 9.0])


if __name__ == "__main__":
    unittest.main()
