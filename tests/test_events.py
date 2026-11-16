"""Evenements : un evenement = un dossier de projet (docs/adr/0001)."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from montagia import events  # noqa: E402


class CleanNamesTest(unittest.TestCase):
    def test_spaces_and_ampersand(self):
        self.assertEqual(events.clean_names("  Sarra & Ahmed "), "Sarra-et-Ahmed")

    def test_forbidden_characters_removed(self):
        self.assertEqual(events.clean_names('Ali/Rim: "2026"?'), "Ali-Rim-2026")

    def test_accents_and_arabic_kept(self):
        self.assertEqual(events.clean_names("Hélène et سارة"), "Hélène-et-سارة")

    def test_length_limited(self):
        self.assertLessEqual(len(events.clean_names("x" * 200)), events.NAMES_MAX)


class EventsTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="rexo-events-")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_create_builds_folder_tree_and_fiche(self):
        ev = events.create(self.root, "Mariage", "2026-11-22", "Sarra et Ahmed", "Sousse")
        self.assertEqual(ev["id"], "2026-11-22_Mariage_Sarra-et-Ahmed")
        path = os.path.join(self.root, ev["id"])
        for sub in events.FOLDER_NAMES:
            self.assertTrue(os.path.isdir(os.path.join(path, sub)), sub)
        for sub in events.RENDER_SUBDIRS:
            self.assertTrue(os.path.isdir(os.path.join(path, "06_Rendus", sub)), sub)
        with open(os.path.join(path, ".rexo", "evenement.json"), encoding="utf-8") as fh:
            fiche = json.load(fh)
        self.assertEqual((fiche["type"], fiche["names"], fiche["place"]),
                         ("Mariage", "Sarra et Ahmed", "Sousse"))
        self.assertEqual(ev["type_label"], "Mariage")
        self.assertNotIn(os.path.join(self.root, "x"), fiche.values())   # pas de chemin absolu

    def test_same_name_gets_suffix(self):
        a = events.create(self.root, "Henne", "2026-11-20", "Rim")
        b = events.create(self.root, "Henne", "2026-11-20", "Rim")
        self.assertEqual(b["id"], a["id"] + "_2")

    def test_invalid_requests(self):
        with self.assertRaises(events.EventError):
            events.create(self.root, "Bapteme", "2026-11-22", "X")
        with self.assertRaises(events.EventError):
            events.create(self.root, "Mariage", "22/11/2026", "X")
        with self.assertRaises(events.EventError):
            events.create(self.root, "Mariage", "2026-11-22", "  /  ")

    def test_list_newest_first_and_ignores_foreign_folders(self):
        events.create(self.root, "Anniversaire", "2026-03-01", "Yasmine")
        events.create(self.root, "Mariage", "2026-11-22", "Sarra et Ahmed")
        os.makedirs(os.path.join(self.root, "Dossier perso"))
        ids = [e["id"] for e in events.list_events(self.root)]
        self.assertEqual(ids, ["2026-11-22_Mariage_Sarra-et-Ahmed", "2026-03-01_Anniversaire_Yasmine"])

    def test_list_missing_root(self):
        self.assertEqual(events.list_events(os.path.join(self.root, "absent")), [])

    def test_counts_files_without_hidden(self):
        ev = events.create(self.root, "Fete", "2026-12-31", "Reveillon")
        rushes = os.path.join(self.root, ev["id"], "01_Rushes", "Carte_1")
        os.makedirs(rushes)
        for name, data in (("C0001.MP4", b"x" * 10), ("C0002.MP4", b"y" * 5), (".DS_Store", b"z")):
            with open(os.path.join(rushes, name), "wb") as fh:
                fh.write(data)
        summary = events.summary(self.root, ev["id"])
        folder = next(f for f in summary["folders"] if f["name"] == "01_Rushes")
        self.assertEqual((folder["files"], folder["size"]), (2, 15))
        self.assertEqual(summary["size"], 15)

    def test_event_path_rejects_traversal(self):
        ev = events.create(self.root, "Mariage", "2026-11-22", "A et B")
        self.assertTrue(events.event_path(self.root, ev["id"], "02_Photos").endswith("02_Photos"))
        for bad in ("..", "../x", ".rexo", "", "a/b", "inconnu"):
            with self.assertRaises(events.EventError, msg=bad):
                events.event_path(self.root, bad)
        for bad_sub in (".rexo", "../..", "01_Rushes/Carte_1"):
            with self.assertRaises(events.EventError, msg=bad_sub):
                events.event_path(self.root, ev["id"], bad_sub)


if __name__ == "__main__":
    unittest.main()
