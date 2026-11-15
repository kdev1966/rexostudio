"""File d'attente des jobs : un seul job lourd a la fois."""
import os
import sys
import threading
import time
import unittest
import unittest.mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from montagia.jobs import JobManager  # noqa: E402


def wait_for(cond, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.01)
    return False


class QueueTest(unittest.TestCase):
    def test_heavy_jobs_never_overlap(self):
        manager = JobManager()
        running, peak, lock = [0], [0], threading.Lock()

        def work(_job):
            with lock:
                running[0] += 1
                peak[0] = max(peak[0], running[0])
            time.sleep(0.15)
            with lock:
                running[0] -= 1
            return {"ok": True}

        jobs = [manager.create("render") for _ in range(3)]
        for job in jobs:
            manager.run_async(job, work)
        self.assertTrue(wait_for(lambda: manager.waiting() == 2))
        queued = [j for j in jobs if j.status == "queued"]
        self.assertEqual(len(queued), 2)
        self.assertTrue(all("attente" in j.step for j in queued))
        self.assertTrue(wait_for(lambda: all(j.status == "done" for j in jobs)))
        self.assertEqual(peak[0], 1)
        self.assertEqual(manager.waiting(), 0)

    def test_light_job_does_not_wait(self):
        manager = JobManager()
        release = threading.Event()
        heavy = manager.create("render")
        manager.run_async(heavy, lambda _j: release.wait(5) and {"ok": 1})
        self.assertTrue(wait_for(lambda: heavy.status == "running"))
        light = manager.create("filmcraft")
        manager.run_async(light, lambda _j: {"ok": 2}, heavy=False)
        self.assertTrue(wait_for(lambda: light.status == "done"))
        self.assertEqual(heavy.status, "running")
        release.set()
        self.assertTrue(wait_for(lambda: heavy.status == "done"))

    def test_failed_heavy_job_releases_its_slot(self):
        manager = JobManager()

        def boom(_job):
            raise RuntimeError("echec")

        first = manager.create("render")
        with unittest.mock.patch("traceback.print_exc"):
            manager.run_async(first, boom)
            self.assertTrue(wait_for(lambda: first.status == "error"))
        second = manager.create("render")
        manager.run_async(second, lambda _j: {"ok": 1})
        self.assertTrue(wait_for(lambda: second.status == "done"))


if __name__ == "__main__":
    unittest.main()
