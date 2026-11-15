"""Plan de coupe : propositions, regles sures, classification par l'IA.

Donnees de reference : les vrais mots horodates de la video de test "cafe
filtre" (faux depart, intro redite, hesitations, digression), tels que
whisper.cpp les a produits sur l'iMac.
"""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from montagia import cutting, pipeline, transcribe  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def load_cafe():
    with open(os.path.join(HERE, "fixtures", "cafe_words.json"), encoding="utf-8") as fh:
        data = json.load(fh)
    return transcribe.clean_words(data["words"]), data["duration"]


def w(text, start, end):
    return {"start": start, "end": end, "text": text}


class Job(object):
    def set_progress(self, *a):
        pass

    def add_log(self, *a):
        pass


class WordsTest(unittest.TestCase):
    def test_clean_words_drops_noise_and_glues_punctuation(self):
        words = transcribe.clean_words([
            w(" [Musique]", 0, 1), w(" Bonjour", 1, 1.5), w(",", 1.5, 1.6),
            w("", 1.6, 1.6), w(" toi", 1.4, 2.0)])
        self.assertEqual([x["text"] for x in words], ["Bonjour,", "toi"])
        self.assertGreaterEqual(words[1]["start"], words[0]["end"])

    def test_subtitle_lines_end_at_sentences(self):
        words, _ = load_cafe()
        lines = transcribe.build_lines(words)
        self.assertEqual(lines[0]["text"], "Bonjour à tous et bienvenue sur la chaîne.")
        self.assertEqual(lines[1]["text"], "Attendez, je recommence.")
        self.assertTrue(all(len(line["text"]) <= 84 for line in lines))
        self.assertTrue(all(line["end"] - line["start"] <= 6.5 for line in lines))


class SubtitleRemapTest(unittest.TestCase):
    def test_cut_words_never_appear_in_subtitles(self):
        words, _ = load_cafe()
        plan = [{"start": 5.99, "end": 15.37}, {"start": 16.73, "end": 22.79},
                {"start": 30.3, "end": 47.35}]            # plan reel de l'iMac
        lines = transcribe.remap_words(words, plan)
        text = " ".join(line["text"] for line in lines)
        for cut in ("bref", "Heu", "marché", "recommence"):
            self.assertNotIn(cut, text)
        self.assertTrue(lines[0]["text"].startswith("Bonjour"))
        self.assertTrue(any(line["text"].startswith("deuxième étape") for line in lines))
        total = sum(p["end"] - p["start"] for p in plan)
        self.assertLessEqual(lines[-1]["end"], total + 1e-6)
        for a, b in zip(lines, lines[1:]):
            self.assertLessEqual(a["end"], b["start"] + 1e-6)


class RulesTest(unittest.TestCase):
    def test_cafe_rules(self):
        words, _ = load_cafe()
        cands = cutting.speech_candidates(words)
        ruled = {c["text"]: c["rule"] for c in cands}
        texts = [c["text"] for c in cands]
        # Premiere intro + "je recommence" : faux depart ; la 2e intro est gardee.
        self.assertEqual(cands[0]["rule"], "faux_depart")
        self.assertEqual(ruled["Attendez, je recommence."], "faux_depart")
        self.assertIsNone(cands[2]["rule"])
        self.assertEqual(cands[2]["text"], cands[0]["text"])
        for filler in ("Heu,", "alors,", "heu,", "bref,"):
            self.assertEqual(ruled[filler], "hesitation")
        # La digression est isolee dans UNE proposition, pas melangee a la recette.
        digression = [t for t in texts if t.startswith("Au fait")]
        self.assertEqual(len(digression), 1)
        self.assertNotIn("étape", digression[0])
        self.assertTrue(any(t.startswith("deuxième étape") for t in texts))

    def test_continuous_story_is_not_cut_by_rules(self):
        # Recit sans defaut (bande-annonce) : les regles ne touchent qu'au
        # connecteur isole "Alors," ; tout le reste est laisse a l'IA.
        with open(os.path.join(HERE, "fixtures", "recit_words.json"), encoding="utf-8") as fh:
            words = json.load(fh)["words"]
        cands = cutting.speech_candidates(words)
        ruled = [c["text"] for c in cands if c["rule"]]
        self.assertEqual(ruled, ["Alors,"])
        self.assertTrue(any(c["text"].startswith("Un homme fut jeté") for c in cands))

    def test_retake_keeps_last_take(self):
        words = [w("On", 0, .2), w("commence", .2, .6), w("par", .6, .8), w("le", .8, .9),
                 w("café.", .9, 1.4), w("On", 2.5, 2.7), w("commence", 2.7, 3.1),
                 w("par", 3.1, 3.3), w("le", 3.3, 3.4), w("café", 3.4, 3.8),
                 w("moulu.", 3.8, 4.4)]
        cands = cutting.speech_candidates(words)
        self.assertEqual([c["rule"] for c in cands], ["repetition", None])

    def test_short_fragment_joins_next_clause(self):
        words = [w("Première", 0, .4), w("étape,", .4, .8), w("choisissez", .9, 1.4),
                 w("un", 1.4, 1.5), w("bon", 1.5, 1.7), w("café.", 1.7, 2.2)]
        cands = cutting.speech_candidates(words)
        self.assertEqual([c["text"] for c in cands],
                         ["Première étape, choisissez un bon café."])

    def test_long_unpunctuated_speech_is_split(self):
        # Parole continue sans ponctuation (cas reel : podcast en arabe, 7 min
        # en 3 passages) : aucun passage ne depasse MAX_CLAUSE_SECONDS.
        words, t = [], 0.0
        for i in range(150):                       # ~60 s, une pause de 0,35 s tous les 9 mots
            gap = 0.35 if i % 9 == 8 else 0.05
            words.append(w("كلمة%d" % i, t, t + 0.35))
            t += 0.35 + gap
        cands = cutting.speech_candidates(words)
        self.assertGreaterEqual(len(cands), 5)
        for c in cands:
            self.assertLessEqual(c["end"] - c["start"],
                                 cutting.MAX_CLAUSE_SECONDS + 2 * cutting.PAD + 1e-6)
        self.assertEqual(" ".join(c["text"] for c in cands),
                         " ".join(x["text"] for x in words))

    def test_arabic_punctuation_splits_clauses(self):
        words = [w("مرحبا", 0, .5), w("بكم،", .5, 1.0), w("اليوم", 1.0, 1.4),
                 w("نتحدث", 1.4, 1.9), w("عن", 1.9, 2.0), w("التطبيقات؟", 2.0, 2.8),
                 w("أولا", 2.9, 3.3), w("نبدأ", 3.3, 3.7), w("بالتصميم.", 3.7, 4.4)]
        clauses = cutting.merge_short(cutting.split_clauses(words))
        self.assertEqual(clauses[-1][0]["text"], "أولا")

    def test_padding_never_overlaps_neighbours(self):
        words, _ = load_cafe()
        cands = cutting.speech_candidates(words)
        for a, b in zip(cands, cands[1:]):
            self.assertLessEqual(a["end"], b["start"] + 1e-6)

    def test_merge_kept_joins_contiguous_passages(self):
        cands = [{"id": "S1", "start": 0, "end": 2, "_index": 0, "text": "a b c"},
                 {"id": "S2", "start": 2.1, "end": 4, "_index": 1, "text": "d"},
                 {"id": "S3", "start": 4.1, "end": 6, "_index": 2, "text": "e"},
                 {"id": "S4", "start": 6.1, "end": 8, "_index": 3, "text": "f"}]
        segs = cutting.merge_kept(cands, {"S1": True, "S2": True, "S3": False, "S4": True})
        self.assertEqual([(s["start"], s["end"], s["id"]) for s in segs],
                         [(0, 4, "S1-S2"), (6.1, 8, "S4")])


def loop_words():
    """Boucle reelle de whisper small sur film002.mp4 (358-378 s), entre
    deux phrases normales."""
    words, t = [], 0.0
    text = ("مرحبا بيكم في الحلقة هذي. نحكيو اليوم على تعلم اللغات. "
            + "لا يجب أن تتعلم بشكل مهمة و " * 3
            + "يجب أن تتعلم معك. ان شاء الله الحلقة الجاية نشوفو كيفاش نخدمو.")
    for token in text.split():
        words.append(w(token, t, t + 0.4))
        t += 0.5
    return words


class LoopTest(unittest.TestCase):
    def test_transcription_loop_is_flagged_not_cut(self):
        cands = cutting.speech_candidates(loop_words())
        rules = [c["rule"] for c in cands]
        self.assertIn(cutting.DOUBT_RULE, rules)
        self.assertNotIn("repetition", rules)
        flagged = " ".join(c["text"] for c in cands if c["rule"] == cutting.DOUBT_RULE)
        self.assertIn("يجب أن تتعلم", flagged)
        self.assertNotIn("مرحبا", flagged)
        self.assertNotIn("الجاية", flagged)

    def test_loop_text_is_not_in_subtitles(self):
        words = loop_words()
        subs = " ".join(s["text"] for s in transcribe.remap_words(
            words, [{"start": 0.0, "end": words[-1]["end"]}]))
        self.assertNotIn("تتعلم بشكل", subs)
        self.assertIn("مرحبا", subs)
        self.assertIn("الجاية", subs)
        lines = transcribe.build_lines(transcribe.drop_loops(words))
        self.assertNotIn("تتعلم بشكل", " ".join(s["text"] for s in lines))

    def test_real_speech_has_no_loop(self):
        words, _ = load_cafe()
        self.assertEqual(cutting.find_loops(words), [])
        with open(os.path.join(HERE, "fixtures", "recit_words.json"), encoding="utf-8") as fh:
            recit = transcribe.clean_words(json.load(fh)["words"])
        self.assertEqual(cutting.find_loops(recit), [])

    def test_laughter_and_one_retake_are_not_loops(self):
        text = "ha ha ha ha ha ha ha ha ha alors on commence alors on commence par le debut"
        words = [w(t, i * 0.5, i * 0.5 + 0.4) for i, t in enumerate(text.split())]
        self.assertEqual(cutting.find_loops(words), [])

    def test_loop_is_kept_and_not_sent_to_ai(self):
        words = loop_words()
        cands = pipeline.build_candidates(transcribe.build_lines(words),
                                          duration=40.0, words=words)
        sent = []

        def fake_chat(system, user, schema, **kwargs):
            sent.append(user)
            return {"decisions": [{"id": c["id"], "type": "digression"} for c in cands]}

        with mock.patch.object(pipeline.ai, "chat_json", side_effect=fake_chat), \
                mock.patch.object(pipeline, "cached_ai", lambda _t, _p, compute: compute()):
            result = pipeline.ai_cut_plan(Job(), cands, 40.0, suggest_only=True)
        doubts = [r for r in result["decisions"] if r.get("doubt")]
        self.assertTrue(doubts)
        self.assertTrue(all(r["keep"] and not r["suggested"] for r in doubts))
        todo_line = [ln for ln in sent[0].splitlines() if ln.startswith("Classe CHAQUE")][0]
        ruled_line = [ln for ln in sent[0].splitlines() if ln.startswith("Deja coupes")][0]
        for r in doubts:
            self.assertNotIn(r["id"] + ",", todo_line + ",")
            self.assertNotIn(r["id"] + " ", ruled_line)
        self.assertIn("transcription douteuse (boucle)", result["rationale"])


class CutPlanTest(unittest.TestCase):
    def plan(self, answer, instruction=""):
        words, duration = load_cafe()
        cands = pipeline.build_candidates(transcribe.build_lines(words),
                                          duration=duration, words=words)
        sent = []

        def fake_chat(system, user, schema, **kwargs):
            sent.append(user)
            return answer(cands)

        with mock.patch.object(pipeline.ai, "chat_json", side_effect=fake_chat), \
                mock.patch.object(pipeline, "cached_ai", lambda _task, _payload, compute: compute()):
            result = pipeline.ai_cut_plan(Job(), cands, duration, "", instruction)
        return cands, result, sent

    def test_rules_are_not_sent_and_ai_cuts_digression(self):
        def answer(cands):
            return {"decisions": [
                {"id": c["id"], "type": "digression" if c["text"].startswith("Au fait") else "contenu"}
                for c in cands if not c["rule"]]}

        cands, result, sent = self.plan(answer)
        ruled_ids = [c["id"] for c in cands if c["rule"]]
        todo_line = [ln for ln in sent[0].splitlines() if ln.startswith("Classe CHAQUE")][0]
        for cid in ruled_ids:
            self.assertNotIn(cid + ",", todo_line + ",")
        kept = " ".join(c["text"] for c in cands
                        if any(s["start"] <= c["start"] and c["end"] <= s["end"]
                               for s in result["segments"]))
        self.assertNotIn("marché", kept)
        self.assertNotIn("Heu", kept)
        self.assertIn("deuxième étape", kept)
        self.assertIn("1 digression par l'IA", result["rationale"])
        self.assertLess(result["kept_duration"], 35)

    def test_unclassified_passages_are_kept(self):
        cands, result, _ = self.plan(lambda _cands: {"decisions": []})
        undecided = [d for d in result["decisions"] if d["by"] == "defaut"]
        self.assertTrue(undecided)
        self.assertTrue(all(d["keep"] for d in undecided))

    def test_visual_categories_do_not_cut_speech(self):
        cands, result, _ = self.plan(lambda cands: {"decisions": [
            {"id": c["id"], "type": "remplissage"} for c in cands if not c["rule"]]})
        by_ia = [d for d in result["decisions"] if d["by"] == "ia"]
        self.assertTrue(by_ia)
        self.assertTrue(all(d["keep"] and d["type"] == "contenu" for d in by_ia))

    def test_ai_cannot_cut_visual_shots_as_digression(self):
        cands = pipeline.build_candidates([], duration=12.0, scenes=[4.0, 8.0])
        answer = {"decisions": [{"id": "S1", "type": "digression"},
                                {"id": "S2", "type": "remplissage"},
                                {"id": "S3", "type": "hors_sujet"}]}
        with mock.patch.object(pipeline.ai, "chat_json", return_value=answer), \
                mock.patch.object(pipeline, "cached_ai", lambda _t, _p, compute: compute()):
            result = pipeline.ai_cut_plan(Job(), cands, 12.0)
        keep = {d["id"]: d["keep"] for d in result["decisions"]}
        self.assertEqual(keep, {"S1": True, "S2": False, "S3": True})

    def test_ai_cannot_use_rule_categories(self):
        # "repetition" / "hesitation" sont reserves aux regles : l'IA les
        # employait a tort (question d'un recit classee "repetition").
        cands, result, _ = self.plan(lambda cands: {"decisions": [
            {"id": c["id"], "type": "repetition"} for c in cands if not c["rule"]]})
        by_ia = [d for d in result["decisions"] if d["by"] != "regle"]
        self.assertTrue(all(d["keep"] for d in by_ia))

    def test_suggest_only_proposes_ai_cuts_but_applies_rules(self):
        words, duration = load_cafe()
        cands = pipeline.build_candidates(transcribe.build_lines(words),
                                          duration=duration, words=words)
        answer = {"decisions": [
            {"id": c["id"], "type": "digression" if c["text"].startswith("Au fait") else "contenu"}
            for c in cands if not c["rule"]]}
        with mock.patch.object(pipeline.ai, "chat_json", return_value=answer), \
                mock.patch.object(pipeline, "cached_ai", lambda _t, _p, compute: compute()):
            result = pipeline.ai_cut_plan(Job(), cands, duration, suggest_only=True)
        rows = {r["id"]: r for r in result["decisions"]}
        digression = next(c["id"] for c in cands if c["text"].startswith("Au fait"))
        self.assertTrue(rows[digression]["keep"])           # proposee, pas appliquee
        self.assertTrue(rows[digression]["suggested"])
        ruled = [c["id"] for c in cands if c["rule"]]
        self.assertTrue(all(not rows[cid]["keep"] for cid in ruled))
        self.assertIn("1 coupe proposée par l'IA, à valider", result["rationale"])

        # La personne valide la suggestion : le plan est recalcule sans la digression.
        rows[digression]["keep"] = False
        rows[digression]["by_user"] = True
        again = pipeline.plan_from_decisions(cands, list(rows.values()), duration)
        self.assertLess(again["kept_duration"], result["kept_duration"])
        self.assertIn("1 choix manuel", again["rationale"])

    def test_truncated_reply_is_salvaged(self):
        # Reponse coupee au plafond de tokens (cas reel sur film001.mp4).
        raw = ('{\n  "decisions" : [\n    {\n      "id" : "S3",\n      "type" : "contenu"\n'
               '    },\n    {\n      "id" : "S10",\n      "type" : "digression"\n    },\n'
               '    {\n      "id" : "S12",\n      "type"')
        words, duration = load_cafe()
        cands = pipeline.build_candidates(transcribe.build_lines(words),
                                          duration=duration, words=words)
        with mock.patch.object(pipeline.ai, "chat_json",
                               side_effect=pipeline.ai.OllamaError("tronque", raw=raw)), \
                mock.patch.object(pipeline, "cached_ai", lambda _t, _p, compute: compute()):
            result = pipeline.ai_cut_plan(Job(), cands, duration)
        by_id = {d["id"]: d for d in result["decisions"]}
        self.assertEqual((by_id["S10"]["type"], by_id["S10"]["keep"]), ("digression", False))
        self.assertEqual(by_id["S12"]["by"], "defaut")      # incomplet : garde
        self.assertTrue(by_id["S12"]["keep"])

    def test_everything_cut_is_an_error(self):
        with self.assertRaises(RuntimeError):
            self.plan(lambda cands: {"decisions": [
                {"id": c["id"], "type": "hors_sujet"} for c in cands if not c["rule"]]})


if __name__ == "__main__":
    unittest.main()
