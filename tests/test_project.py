"""Projets persistants : enregistrement JSON et reprise apres redemarrage."""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from montagia import project  # noqa: E402


class PersistenceTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.media = os.path.join(self.dir, "rush.mp4")
        with open(self.media, "wb") as fh:
            fh.write(b"x")

    def test_project_survives_a_restart(self):
        store = project.ProjectStore()
        store.enable_persistence(self.dir)
        proj = store.create(self.media, "rush.mp4")
        proj.transcript = "Bonjour"
        proj.plan = [{"start": 1.0, "end": 2.5, "id": "S1", "reason": "accroche"}]
        proj.results["plan_rationale"] = "phrase forte"
        proj.add_export("/out/rush.fcproj")
        store.save(proj)

        restarted = project.ProjectStore()
        self.assertEqual(restarted.enable_persistence(self.dir), 1)
        again = restarted.get(proj.id)
        self.assertIsNotNone(again)
        self.assertEqual(again.to_dict(), proj.to_dict())

    def test_without_persistence_nothing_is_written(self):
        store = project.ProjectStore()
        store.create(self.media)
        self.assertEqual([f for f in os.listdir(self.dir) if f.endswith(".json")], [])

    def test_damaged_file_is_ignored(self):
        with open(os.path.join(self.dir, "project_abime.json"), "w") as fh:
            fh.write("{ pas du json")
        with open(os.path.join(self.dir, "project_liste.json"), "w") as fh:
            json.dump(["pas", "un", "objet"], fh)
        store = project.ProjectStore()
        self.assertEqual(store.enable_persistence(self.dir), 0)

    def test_no_temporary_file_left(self):
        store = project.ProjectStore()
        store.enable_persistence(self.dir)
        store.save(store.create(self.media))
        self.assertFalse([f for f in os.listdir(self.dir) if f.endswith(".tmp")])

    def test_recent_list_is_most_recently_updated_first(self):
        store = project.ProjectStore()
        store.enable_persistence(self.dir)
        old = store.create(self.media, "ancien")
        new = store.create(self.media, "nouveau")
        time.sleep(0.01)
        store.save(old)                     # l'ancien vient d'etre modifie
        self.assertEqual([p["name"] for p in store.list()], ["ancien", "nouveau"])
        self.assertEqual(store.list()[0]["id"], old.id)
        self.assertIn(new.id, [p["id"] for p in store.list()])

    def test_missing_media_is_flagged(self):
        store = project.ProjectStore()
        proj = store.create(os.path.join(self.dir, "disparu.mp4"))
        self.assertTrue(proj.summary()["media_missing"])
        self.assertTrue(proj.to_dict()["media_missing"])

    def test_limit_keeps_most_recent_on_load(self):
        store = project.ProjectStore(max_projects=50)
        store.enable_persistence(self.dir)
        for i in range(5):
            store.create(self.media, "p%d" % i)
            time.sleep(0.005)
        small = project.ProjectStore(max_projects=2)
        self.assertEqual(small.enable_persistence(self.dir), 2)
        self.assertEqual({p["name"] for p in small.list()}, {"p3", "p4"})


if __name__ == "__main__":
    unittest.main()
