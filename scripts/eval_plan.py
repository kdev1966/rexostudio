"""Evaluation du plan de coupe avec le VRAI modele (Ollama), sur les videos
de reference de tests/fixtures/. A lancer apres toute modification des
prompts ou des regles de coupe.

    python3 scripts/eval_plan.py
    OLLAMA_URL=http://127.0.0.1:11499 python3 scripts/eval_plan.py   # via tunnel

Chaque reference precise ce qui DOIT etre coupe et ce qui doit etre garde ;
le script affiche les decisions et termine en erreur si une attente echoue.
Le cache IA est ignore (calcul reel a chaque lancement).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from montagia import config, pipeline, transcribe  # noqa: E402

FIXTURES = os.path.join(ROOT, "tests", "fixtures")

# (fichier, mots bruts whisper ?, textes qui doivent etre coupes, textes qui doivent rester)
REFERENCES = [
    ("cafe_words.json", True,
     ["Attendez, je recommence", "Heu,", "Au fait, hier"],
     ["première étape", "deuxième étape", "Et voilà, votre café est prêt"]),
    ("recit_words.json", False,
     [],
     ["Je vais vous raconter une histoire", "Un homme fut jeté", "au lieu de",
      "Et qu'a-t-il trouvé en enfer", "Il m'a trouvé moi"]),
]


class _Job(object):
    def set_progress(self, *_a):
        pass

    def add_log(self, message):
        print("   log :", message)


def evaluate(name, raw, must_cut, must_keep) -> bool:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        data = json.load(fh)
    words = transcribe.clean_words(data["words"]) if raw else data["words"]
    cands = pipeline.build_candidates(transcribe.build_lines(words),
                                      duration=data["duration"], words=words)
    t0 = time.time()
    result = pipeline.ai_cut_plan(_Job(), cands, data["duration"])
    print("== %s : %.1f s de calcul, %.1f s gardees sur %.1f s"
          % (name, time.time() - t0, result["kept_duration"], data["duration"]))
    keep = {d["id"]: d for d in result["decisions"]}
    for cand in cands:
        d = keep[cand["id"]]
        print("   %-5s %-12s %-6s %s" % ("garde" if d["keep"] else "COUPE", d["type"],
                                         d["by"], cand["text"][:70]))
    ok = True
    for text in must_cut:
        if any(c["text"].startswith(text) and keep[c["id"]]["keep"] for c in cands):
            print("   ECHEC : devait etre coupe -> %s" % text)
            ok = False
    for text in must_keep:
        if any(c["text"].startswith(text) and not keep[c["id"]]["keep"] for c in cands):
            print("   ECHEC : devait etre garde -> %s" % text)
            ok = False
    print("   %s\n" % ("OK" if ok else "ECHEC"))
    return ok


def main() -> int:
    print("Modele : %s sur %s\n" % (config.LLM_MODEL, config.OLLAMA_URL))
    cache = tempfile.mkdtemp(prefix="montagia-eval-")
    pipeline.AI_CACHE_DIR = cache           # jamais le cache du projet
    try:
        results = [evaluate(*ref) for ref in REFERENCES]
    finally:
        shutil.rmtree(cache, ignore_errors=True)
    print("%d/%d references conformes" % (sum(results), len(results)))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
