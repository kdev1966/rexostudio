"""Plan de coupe : resolution des identifiants, normalisation, recalage des
sous-titres. Lancer :  python3 -m unittest discover -s tests
"""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from montagia import edit, pipeline, transcribe  # noqa: E402

CANDIDATES = [
    {"id": "S1", "start": 0.0, "end": 5.0, "text": "a"},
    {"id": "S2", "start": 5.0, "end": 10.0, "text": "b"},
    {"id": "S3", "start": 10.0, "end": 15.0, "text": "c"},
]
SUBS = [
    {"start": 0.0, "end": 5.0, "text": "a"},
    {"start": 10.0, "end": 15.0, "text": "c"},
]


def _spans(segments):
    return [(s["start"], s["end"]) for s in segments]


class ResolveSelectionTest(unittest.TestCase):
    def test_duplicate_ids_are_kept_once(self):
        plan = pipeline.resolve_selection(
            [{"id": "S1"}, {"id": "s1"}, {"id": "S3"}], CANDIDATES)
        self.assertEqual(_spans(plan), [(0.0, 5.0), (10.0, 15.0)])

    def test_unknown_ids_and_garbage_are_ignored(self):
        plan = pipeline.resolve_selection(
            [{"id": "S9"}, "S2", None, {"id": "S2"}], CANDIDATES)
        self.assertEqual(_spans(plan), [(5.0, 10.0)])

    def test_trims_never_invert_a_segment(self):
        plan = pipeline.resolve_selection(
            [{"id": "S1", "trim_start": 10, "trim_end": 10}], CANDIDATES)
        self.assertGreater(plan[0]["end"], plan[0]["start"])


class NormalizeSegmentsTest(unittest.TestCase):
    def test_keeps_metadata_and_merges_overlaps(self):
        plan = edit.normalize_segments([
            {"start": 4, "end": 9, "id": "S2", "reason": "suite"},
            {"start": 0, "end": 5, "id": "S1", "reason": "intro"},
            {"start": 0, "end": 5, "id": "S1", "reason": "intro"},
        ], duration=20)
        self.assertEqual(_spans(plan), [(0.0, 9.0)])
        self.assertEqual(plan[0]["reason"], "intro")

    def test_clamps_to_duration_and_drops_tiny_segments(self):
        plan = edit.normalize_segments([
            {"start": -1, "end": 2},
            {"start": 3, "end": 3.1},
            {"start": 8, "end": 30},
        ], duration=10)
        self.assertEqual(_spans(plan), [(0.0, 2.0), (8.0, 10.0)])

    def test_is_idempotent(self):
        once = edit.normalize_segments(
            [{"start": 5, "end": 9}, {"start": 0, "end": 6}], duration=10)
        self.assertEqual(edit.normalize_segments(once, duration=10), once)


class RenderSubtitleSyncTest(unittest.TestCase):
    """Les sous-titres incrustes doivent suivre la timeline reellement rendue."""

    def test_overlapping_plan_keeps_subtitles_in_sync(self):
        captured = {}

        def fake_export(source, segments, out_path, **kwargs):
            captured["rendered"] = edit.normalize_segments(segments, 15.0)
            return {"path": out_path}

        def fake_write_srt(segments, path):
            captured["subs"] = segments
            return path

        job = mock.Mock()
        # os.makedirs est neutralise plus bas : le dossier des SRT temporaires
        # doit deja exister (une copie neuve du depot n'a pas de workspace/).
        cache = tempfile.mkdtemp(prefix="rexo-cache-")
        self.addCleanup(shutil.rmtree, cache, True)
        os.makedirs(os.path.join(cache, "subs"))
        patcher = mock.patch.object(pipeline.config, "CACHE_DIR", cache)
        patcher.start()
        self.addCleanup(patcher.stop)
        overlapping = [{"start": 0, "end": 5}, {"start": 0, "end": 5},
                       {"start": 10, "end": 15}]
        with mock.patch.object(pipeline.media, "probe",
                               return_value={"duration": 15.0}), \
                mock.patch.object(pipeline.edit, "export", side_effect=fake_export), \
                mock.patch.object(pipeline.transcribe, "write_srt",
                                  side_effect=fake_write_srt), \
                mock.patch.object(pipeline.os, "makedirs"):
            pipeline.render_video(job, "/x.mp4", overlapping, "/out.mp4",
                                  burn_subtitles=True, subtitle_segments=SUBS)

        rendered_length = sum(e - s for s, e in _spans(captured["rendered"]))
        self.assertEqual(rendered_length, 10.0)
        self.assertEqual([(s["start"], s["end"], s["text"]) for s in captured["subs"]],
                         [(0.0, 5.0, "a"), (5.0, 10.0, "c")])
        self.assertLessEqual(captured["subs"][-1]["end"], rendered_length)

    def test_remap_drops_unreadable_fragments(self):
        subs = [{"start": 3.0, "end": 7.0, "text": "phrase coupee"},
                {"start": 0.0, "end": 0.3, "text": "Oui"}]
        # 0,2 s restants d'une phrase de 4 s : supprime ; mot court entier : garde.
        out = transcribe.remap_segments(subs, [{"start": 0.0, "end": 3.2}])
        self.assertEqual([s["text"] for s in out], ["Oui"])

    def test_remap_follows_plan(self):
        out = transcribe.remap_segments(SUBS, [{"start": 10, "end": 15}])
        self.assertEqual([(s["start"], s["end"], s["text"]) for s in out],
                         [(0.0, 5.0, "c")])


class ParseSrtTest(unittest.TestCase):
    def test_roundtrip(self):
        text = "1\n00:00:01,500 --> 00:00:03,000\nBonjour\n\n2\n00:00:04,000 --> 00:00:05,250\nle monde\n"
        segs = transcribe.parse_srt(text)
        self.assertEqual([(s["start"], s["end"], s["text"]) for s in segs],
                         [(1.5, 3.0, "Bonjour"), (4.0, 5.25, "le monde")])


if __name__ == "__main__":
    unittest.main()


class ChatPromptTest(unittest.TestCase):
    def test_chat_asks_for_plain_text_not_json(self):
        # Gemma suivait la consigne JSON du persona d'analyse et repondait en JSON.
        seen = {}

        def fake_stream(system, user, **_k):
            seen["system"] = system
            yield "ok"

        with mock.patch.object(pipeline.ai, "chat_stream", side_effect=fake_stream), \
                mock.patch.object(pipeline, "cached_ai", lambda *_a: None):
            self.assertEqual("".join(pipeline.ai_chat(None, "q ?", "transcription", 10.0)), "ok")
        self.assertNotIn("schema", seen["system"])
        self.assertIn("ni JSON", seen["system"])


class TrailerDurationTest(unittest.TestCase):
    def seg(self, cid, start, end):
        return {"id": cid, "start": start, "end": end, "reason": ""}

    def test_best_scored_moments_fill_the_target(self):
        segs = [self.seg("S1", 0, 10), self.seg("S2", 20, 32), self.seg("S3", 40, 50),
                self.seg("S4", 60, 75)]
        scores = {"S1": 5, "S2": 9, "S3": 8, "S4": 7}
        kept = pipeline.fit_to_duration(segs, scores, 30)
        # S2 + S3 = 22 s ; S4 (15 s) depasserait 34,5 s, S1 (10 s) tient encore.
        self.assertEqual([s["id"] for s in kept], ["S1", "S2", "S3"])
        self.assertLessEqual(sum(s["end"] - s["start"] for s in kept), 30 * 1.15)

    def test_single_long_moment_is_shortened(self):
        kept = pipeline.fit_to_duration([self.seg("S1", 5, 65)], {"S1": 9}, 30)
        self.assertEqual((kept[0]["start"], kept[0]["end"]), (5, 35))
