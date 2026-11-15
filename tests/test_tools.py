"""Execution de processus (delai reel) et noms de fichiers uniques."""
import os
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from montagia import tools  # noqa: E402


class RunStreamingTest(unittest.TestCase):
    def test_silent_hung_process_is_killed_at_deadline(self):
        # "sleep" n'ecrit rien : l'ancienne version restait bloquee sur stdout.
        t0 = time.time()
        with self.assertRaises(tools.CommandTimeout):
            tools.run_streaming(["sleep", "30"], on_line=None, timeout=1)
        self.assertLess(time.time() - t0, 5)

    def test_output_and_errors(self):
        out = tools.run_streaming(["printf", "a\\nb\\n"], on_line=None, timeout=10)
        self.assertEqual(out, "a\nb")
        with self.assertRaises(tools.CommandError) as ctx:
            tools.run_streaming(["sh", "-c", "echo oups; exit 3"], on_line=None, timeout=10)
        self.assertNotIsInstance(ctx.exception, tools.CommandTimeout)
        self.assertEqual(ctx.exception.code, 3)

    def test_keep_lines_bounds_memory(self):
        out = tools.run_streaming(["seq", "1", "5000"], on_line=None, timeout=10,
                                  keep_lines=3)
        self.assertEqual(out, "4998\n4999\n5000")


class UniquePathTest(unittest.TestCase):
    def test_existing_name_gets_a_suffix(self):
        d = tempfile.mkdtemp()
        first = tools.unique_path(os.path.join(d, "video.mp4"))
        second = tools.unique_path(os.path.join(d, "video.mp4"))
        self.assertEqual(os.path.basename(first), "video.mp4")
        self.assertEqual(os.path.basename(second), "video-2.mp4")

    def test_concurrent_reservations_never_collide(self):
        d = tempfile.mkdtemp()
        results = []
        threads = [threading.Thread(target=lambda: results.append(
            tools.unique_path(os.path.join(d, "clip.mov")))) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(set(results)), 20)


if __name__ == "__main__":
    unittest.main()
