"""Suppression = Corbeille : evenement, carte, dossier, rush, photo."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from montagia import events, rushes, trash  # noqa: E402


class FakeTrash(object):
    """Corbeille de test : deplace dans un dossier temporaire."""

    def __init__(self, folder):
        self.folder = folder
        self.items = []

    def __call__(self, path):
        dest = os.path.join(self.folder, "%d_%s" % (len(self.items), os.path.basename(path)))
        shutil.move(path, dest)
        self.items.append(path)


class TrashTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rexo-trash-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = os.path.join(self.tmp, "Evenements")
        self.ev = events.create(self.root, "Mariage", "2026-11-14", "A et B")
        self.dir = self.ev["path"]
        os.makedirs(os.path.join(self.tmp, "corbeille"))
        self.trash = FakeTrash(os.path.join(self.tmp, "corbeille"))
        for rel in ("01_Rushes/Carte_1/C0001.MP4", "01_Rushes/Carte_2/C0002.MP4",
                    "02_Photos/Carte_1/DSC_0001.JPG", "04_Proxies/Carte_1/C0001_proxy.mp4",
                    "06_Rendus/Teaser/teaser.mp4"):
            path = os.path.join(self.dir, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(b"x")

    def test_item_path_refuses_outside_and_internal(self):
        for bad in ("", ".", "..", "../x", ".rexo", ".rexo/evenement.json",
                    "/etc/passwd", "Inconnu/x", "01_Rushes/../../x", "01_Rushes/absent.MP4"):
            with self.assertRaises(events.EventError, msg=bad):
                events.item_path(self.root, self.ev["id"], bad)

    def test_trash_one_rush_with_its_proxy_and_forget_it(self):
        rel = os.path.join("01_Rushes", "Carte_1", "C0001.MP4")
        self.assertEqual(rushes.related_paths(self.dir, rel),
                         [os.path.join(self.dir, "04_Proxies", "Carte_1", "C0001_proxy.mp4")])
        events.trash_item(self.root, self.ev["id"], rel, self.trash)
        self.assertFalse(os.path.exists(os.path.join(self.dir, rel)))
        rushes.forget_missing(self.dir)
        self.assertNotIn(rel, rushes.load_state(self.dir)["clips"])

    def test_main_folder_is_emptied_not_removed(self):
        events.trash_item(self.root, self.ev["id"], "06_Rendus", self.trash)
        for sub in events.RENDER_SUBDIRS:
            self.assertTrue(os.path.isdir(os.path.join(self.dir, "06_Rendus", sub)))
        self.assertFalse(os.path.exists(os.path.join(self.dir, "06_Rendus", "Teaser", "teaser.mp4")))
        self.assertEqual(events.list_events(self.root)[0]["id"], self.ev["id"])   # fiche intacte

    def test_card_paths_and_list(self):
        self.assertEqual([c["name"] for c in rushes.card_list(self.dir)], ["Carte_1", "Carte_2"])
        self.assertEqual(rushes.card_list(self.dir)[0], {"name": "Carte_1", "videos": 1, "photos": 1})
        paths = rushes.card_paths(self.dir, "Carte_1")
        self.assertEqual(len(paths), 3)                          # rushes, photos, proxies
        for bad in ("../Carte_1", "Carte_x", "Carte_9", ""):
            with self.assertRaises(rushes.RushError, msg=bad):
                rushes.card_paths(self.dir, bad)

    def test_trash_whole_event(self):
        events.trash_event(self.root, self.ev["id"], self.trash)
        self.assertEqual(events.list_events(self.root), [])
        self.assertEqual(len(self.trash.items), 1)

    def test_real_trash_refuses_missing_path(self):
        with self.assertRaises(trash.TrashError):
            trash.to_trash(os.path.join(self.tmp, "absent"))

    @unittest.skipUnless(sys.platform == "darwin" and shutil.which("sips"), "macOS")
    def test_photo_thumbnails_and_list(self):
        photo = os.path.join(self.dir, "02_Photos", "Carte_1", "DSC_0001.JPG")
        ffmpeg = rushes.config.ffmpeg_bin()
        if not ffmpeg:
            self.skipTest("ffmpeg absent")
        os.remove(photo)
        rushes.tools.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=800x600",
                          "-frames:v", "1", photo])
        self.assertEqual(rushes.photo_thumbnails(self.dir), 1)
        self.assertEqual(rushes.photo_thumbnails(self.dir), 0)
        photos = rushes.photo_list(self.dir)
        self.assertEqual(len(photos), 1)
        self.assertTrue(os.path.isfile(photos[0]["thumb"]))
        self.assertTrue(photos[0]["viewable"])
        events.trash_item(self.root, self.ev["id"], photos[0]["rel"], self.trash)
        rushes.forget_missing(self.dir)
        self.assertFalse(os.path.exists(photos[0]["thumb"]))     # vignette orpheline effacee


if __name__ == "__main__":
    unittest.main()
