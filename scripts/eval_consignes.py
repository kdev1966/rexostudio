"""Evaluation de l'assistant a consigne avec le VRAI modele local, sur les
consignes du studio (tests/fixtures/consignes_studio.json). A relancer apres
toute modification du prompt, du schema ou du modele.

    python3 scripts/eval_consignes.py
    python3 scripts/eval_consignes.py --repeat 3     # stabilite des reponses

Pour chaque consigne : le plan obtenu, compare au plan attendu
- exact    : memes outils, dans le meme ordre (« lot » = toutes les photos,
             « refuser » = consigne refusee)
- essentiel: idem en ignorant « cadre_maries » (le studio peut toujours tracer
             le cadre lui-meme si la robe est coupee)
Code de sortie 1 si le score essentiel est sous 8/10.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from montagia import assistant, llm_server  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "consignes_studio.json")


def tools_of(result: dict) -> list:
    if not result["faisable"]:
        return ["refuser"]
    tools = [s["outil"] for s in result["etapes"]]
    if result["toutes_les_photos"]:
        tools.append("lot")
    return tools


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=1)
    a = ap.parse_args()
    with open(FIXTURE, encoding="utf-8") as fh:
        cases = json.load(fh)["consignes"]
    exact = essential = total = 0
    times = []
    for _ in range(a.repeat):
        for case in cases:
            t = time.time()
            try:
                result = assistant.plan(case["texte"])
            except assistant.AssistantError as exc:
                print("✗ %2d ERREUR %s" % (case["id"], exc))
                total += 1
                continue
            times.append(time.time() - t)
            got = tools_of(result)
            want = case["attendu"]
            ok_exact = got == want
            ok_core = [x for x in got if x != "cadre_maries"] == [x for x in want if x != "cadre_maries"]
            exact += ok_exact
            essential += ok_core
            total += 1
            mark = "✓" if ok_exact else ("≈" if ok_core else "✗")
            print("%s %2d %-28s %4.1f s  %s" % (mark, case["id"], case["langue"][:28], times[-1], case["texte"]))
            print("        obtenu  : %s" % " → ".join(got))
            if not ok_exact:
                print("        attendu : %s" % " → ".join(want))
            details = [s.get("cible") or s.get("couleur") or s.get("style") or s.get("format")
                       for s in result["etapes"]]
            details = [d for d in details if d]
            if details:
                print("        paramètres : %s" % ", ".join(details))
            print("        message : %s" % result["message"])
    print()
    print("Exact : %d/%d   Essentiel : %d/%d   Temps moyen : %.1f s (max %.1f s)" % (
        exact, total, essential, total, sum(times) / max(1, len(times)), max(times or [0])))
    llm_server.stop() if hasattr(llm_server, "stop") else None
    return 0 if essential * 10 >= 8 * total else 1


if __name__ == "__main__":
    sys.exit(main())
