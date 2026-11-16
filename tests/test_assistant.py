"""Assistant a consigne : regles fixes appliquees au plan de l'IA (sans modele).
L'evaluation avec le vrai modele : scripts/eval_consignes.py."""
import os
import shutil
import stat
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from montagia import ai, assistant, config, effects  # noqa: E402


def plan(*steps, every=False, feasible=True, message="ok"):
    return {"faisable": feasible, "etapes": list(steps), "toutes_les_photos": every, "message": message}


def tools(result):
    return [s["outil"] for s in result["etapes"]]


class NormalizeTest(unittest.TestCase):
    def test_unknown_tools_dropped_and_defaults(self):
        r = assistant.normalize(plan({"outil": "generer_ciel"}, {"outil": "fond_uni"},
                                     {"outil": "recadrer", "format": "3:2"}))
        self.assertEqual(tools(r), ["fond_uni", "recadrer"])
        self.assertEqual(r["etapes"][0]["couleur"], "blanc")
        self.assertEqual(r["etapes"][1]["format"], "4:5")

    def test_erase_targets_split_one_box_each(self):
        r = assistant.normalize(plan({"outil": "effacer_objet",
                                      "cible": "le fil électrique et le panneau dans le ciel"}))
        self.assertEqual([s["cible"] for s in r["etapes"]], ["le fil électrique", "le panneau dans le ciel"])
        self.assertTrue(all(s["cadre"] for s in r["etapes"]))
        r = assistant.normalize(plan({"outil": "effacer_objet", "cible": "el karhba w el poubelle"}))
        self.assertEqual([s["cible"] for s in r["etapes"]], ["el karhba", "el poubelle"])
        r = assistant.normalize(plan({"outil": "effacer_objet", "cible": "الكرهبة و الكرسي"}))
        self.assertEqual(len(r["etapes"]), 2)
        r = assistant.normalize(plan({"outil": "effacer_objet", "cible": "les invités derrière les mariés"}))
        self.assertEqual(len(r["etapes"]), 1)

    def test_single_style_most_precise(self):
        r = assistant.normalize(plan({"outil": "style", "style": "chaud"},
                                     {"outil": "style", "style": "vintage-chaud"}, every=True))
        self.assertEqual(tools(r), ["style"])
        self.assertEqual(r["etapes"][0]["style"], "vintage-chaud")
        self.assertTrue(r["toutes_les_photos"])

    def test_dress_words_add_couple_box_first(self):
        r = assistant.normalize(plan({"outil": "fond_flou"}), "Floute le fond, la robe doit rester nette")
        self.assertEqual(tools(r), ["cadre_maries", "fond_flou"])
        r = assistant.normalize(plan({"outil": "fond_uni"}, {"outil": "cadre_maries"}), "قص العروسة بالفستان")
        self.assertEqual(tools(r), ["cadre_maries", "fond_uni"])

    def test_couple_box_dropped_without_person_effect(self):
        r = assistant.normalize(plan({"outil": "cadre_maries"}, {"outil": "style", "style": "chaud"}))
        self.assertEqual(tools(r), ["style"])

    def test_crop_moved_last(self):
        r = assistant.normalize(plan({"outil": "recadrer", "format": "9:16"},
                                     {"outil": "effacer_objet", "cible": "la chaise"},
                                     {"outil": "recadrer", "format": "1:1"}))
        self.assertEqual(tools(r), ["effacer_objet", "recadrer"])
        self.assertEqual(r["etapes"][-1]["format"], "9:16")

    def test_refusal_clears_steps(self):
        r = assistant.normalize(plan({"outil": "fond_flou"}, feasible=False, message="Impossible."))
        self.assertFalse(r["faisable"])
        self.assertEqual(r["etapes"], [])
        r = assistant.normalize(plan(feasible=True, message=""))
        self.assertFalse(r["faisable"])
        self.assertTrue(r["message"])

    def test_boxes_forbid_whole_series(self):
        r = assistant.normalize(plan({"outil": "effacer_objet", "cible": "la voiture"}, every=True))
        self.assertFalse(r["toutes_les_photos"])
        self.assertIn("photo par photo", r["message"])


class PlanTest(unittest.TestCase):
    def test_empty_and_too_long(self):
        with self.assertRaises(assistant.AssistantError):
            assistant.plan("  ")
        with self.assertRaises(assistant.AssistantError):
            assistant.plan("x" * 501)

    def test_llm_error_reported(self):
        with mock.patch.object(ai, "chat_json", side_effect=ai.LLMError("arrêté")), \
                self.assertRaises(assistant.AssistantError):
            assistant.plan("floute le fond")

    def test_schema_and_prompt_sent(self):
        seen = {}

        def fake(system, user, schema, **kw):
            seen.update(system=system, user=user, schema=schema)
            return plan({"outil": "fond_flou"}, message="Je floute.")

        with mock.patch.object(ai, "chat_json", side_effect=fake):
            r = assistant.plan("a3mel el fond mdhabeb")
        self.assertEqual(tools(r), ["fond_flou"])
        self.assertEqual(seen["user"], "Consigne : a3mel el fond mdhabeb")
        self.assertEqual(seen["schema"]["properties"]["etapes"]["items"]["properties"]["outil"]["enum"],
                         list(assistant.TOOLS))
        for name in assistant.TOOLS:
            self.assertIn(name, seen["system"])


# Faux rexo-segment : note ses arguments, copie l'entree vers la sortie
FAKE_SEGMENT = """#!/bin/bash
echo "$@" >> "%(log)s"
cp "$2" "$3"
echo '{"ok":true,"width":4000,"height":3000,"coverage":0.3,"ms":10}'
"""


class RunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rexo-asst-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.event = os.path.join(self.tmp, "2026-11-16_Mariage_Test")
        self.cards = os.path.join(self.event, "02_Photos", "Carte_1")
        os.makedirs(self.cards)
        self.photo = self._photo("IMG_0001.jpg")
        self.log = os.path.join(self.tmp, "segment.log")
        tool = os.path.join(self.tmp, "rexo-segment")
        with open(tool, "w") as fh:
            fh.write(FAKE_SEGMENT % {"log": self.log})
        os.chmod(tool, os.stat(tool).st_mode | stat.S_IEXEC)
        patcher = mock.patch.object(config, "SEGMENT_BIN", tool)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _photo(self, name):
        path = os.path.join(self.cards, name)
        with open(path, "wb") as fh:
            fh.write(b"photo " + name.encode())
        return path

    def _calls(self):
        with open(self.log) as fh:
            return [line.split() for line in fh.read().splitlines()]

    def test_check_plan_requires_boxes(self):
        steps = [{"outil": "effacer_objet", "cible": "la voiture"}, {"outil": "fond_flou"}]
        with self.assertRaises(assistant.AssistantError) as ctx:
            assistant.check_plan(steps, {})
        self.assertIn("étape 1", str(ctx.exception))
        clean = assistant.check_plan(steps, {"0": [0.1, 0.1, 0.2, 0.2]})
        self.assertEqual(clean[0]["box"], [0.1, 0.1, 0.2, 0.2])
        with self.assertRaises(assistant.AssistantError):
            assistant.check_plan([{"outil": "inventer"}], {})

    def test_chain_of_steps_on_one_photo(self):
        steps = assistant.check_plan([{"outil": "recadrer", "format": "9:16"},
                                      {"outil": "fond_uni", "couleur": "beige"},
                                      {"outil": "style", "style": "chaud"}], {})
        r = assistant.run_photo(self.event, self.photo, steps)
        calls = self._calls()
        self.assertEqual([c[0] for c in calls], ["uni", "style", "crop"])     # recadrage en dernier
        self.assertEqual(calls[0][1], self.photo)
        self.assertEqual(calls[0][3:], ["--color", "225,210,185"])
        self.assertEqual(calls[1][1], calls[0][2])                           # chaque etape part de la precedente
        self.assertEqual(calls[1][3:], ["--name", "chaud"])
        self.assertEqual(calls[2][3:], ["--ratio", "9:16"])
        self.assertTrue(os.path.isfile(r["path"]))
        self.assertTrue(r["path"].endswith("_assistant.jpg"))
        work = os.path.join(self.event, effects.CACHE_DIR, "travail")
        self.assertEqual(os.listdir(work), [])                               # intermediaires effaces
        rel = assistant.save(self.event, self.photo)
        self.assertEqual(rel, os.path.join("06_Rendus", "Photos_effets", "IMG_0001_assistant.jpg"))

    def test_cutout_keeps_png_through_style(self):
        steps = assistant.check_plan([{"outil": "detourer"}, {"outil": "style", "style": "doux"}], {})
        r = assistant.run_photo(self.event, self.photo, steps)
        self.assertTrue(r["path"].endswith(".png"))
        self.assertTrue(self._calls()[1][2].endswith(".png"))

    def test_couple_box_adds_mask_to_person_effects(self):
        def fake_mask(src, box, out_png):
            shutil.copyfile(src, out_png)
            return [1, 2, 3, 4]

        steps = assistant.check_plan([{"outil": "cadre_maries"}, {"outil": "fond_flou"},
                                      {"outil": "style", "style": "chaud"}],
                                     {"0": [0.1, 0.0, 0.8, 1.0]})
        with mock.patch.object(effects, "couple_mask", side_effect=fake_mask) as cm:
            assistant.run_photo(self.event, self.photo, steps)
        self.assertEqual(cm.call_args[0][1], [0.1, 0.0, 0.8, 1.0])
        blur, style = self._calls()
        self.assertEqual(blur[0], "blur")
        self.assertEqual(blur[3], "--add-mask")
        self.assertNotIn("--add-mask", style)                                # le style ne detoure pas

    def test_erase_step_uses_its_box(self):
        def fake_erase(src, out, box, folder, key):
            shutil.copyfile(src, out)
            seen.append(box)
            return {"ok": True}

        seen = []
        steps = assistant.check_plan([{"outil": "effacer_objet", "cible": "le fil et le panneau"}],
                                     {"0": [0.1, 0.1, 0.1, 0.1], "1": [0.5, 0.5, 0.1, 0.1]})
        with mock.patch.object(effects, "erase", side_effect=fake_erase):
            r = assistant.run_photo(self.event, self.photo, steps)
        self.assertEqual(seen, [[0.1, 0.1, 0.1, 0.1], [0.5, 0.5, 0.1, 0.1]])
        self.assertTrue(os.path.isfile(r["path"]))

    def test_whole_series(self):
        second = self._photo("IMG_0002.jpg")
        steps = assistant.check_plan([{"outil": "style", "style": "vintage-chaud"}], {})
        r = assistant.run_all(self.event, [self.photo, second], steps)
        self.assertEqual(r["done"], 2)
        self.assertEqual(r["failed"], [])
        folder = os.path.join(self.event, r["folder"])
        self.assertTrue(r["folder"].startswith(os.path.join("06_Rendus", "Photos_effets", "Assistant_")))
        self.assertEqual(sorted(os.listdir(folder)), ["IMG_0001.jpg", "IMG_0002.jpg"])
        self.assertTrue(os.path.isfile(self.photo))                         # originaux intacts

    def test_whole_series_refuses_boxes(self):
        steps = assistant.check_plan([{"outil": "effacer_objet", "cible": "x"}], {"0": [0, 0, 1, 1]})
        with self.assertRaises(assistant.AssistantError):
            assistant.run_all(self.event, [self.photo], steps)

    def test_one_computation_at_a_time(self):
        steps = assistant.check_plan([{"outil": "fond_flou"}], {})
        self.assertTrue(effects._LOCK.acquire(blocking=False))
        try:
            with self.assertRaises(assistant.AssistantError):
                assistant.run_photo(self.event, self.photo, steps)
        finally:
            effects._LOCK.release()


if __name__ == "__main__":
    unittest.main()
