"""Affine le masque des personnes de Vision avec MobileSAM.

S'execute dans l'environnement d'effets (.effets/venv, Python 3.11) :

    refine.py <photo> <masque_vision.png> <sortie.png> [--boxes x,y,l,h;x,y,l,h...]

Le masque de Vision est doux (bon sur les cheveux et le voile) mais garde, avec une
confiance faible, des morceaux de fond (trainees grises autour des maries) ; une
main peut n'etre vue qu'a 17 %. MobileSAM detoure chaque personne comme un objet
entier, aux contours nets. Combinaison prudente :
  - ce que Vision voit avec certitude (>= 50 %) est toujours garde ;
  - l'incertain n'est garde que pres d'une personne trouvee par MobileSAM
    (les trainees de fond disparaissent) ;
  - au coeur d'une personne trouvee par MobileSAM, tout est opaque (les mains
    ne peuvent plus disparaitre) ;
  - sur la bordure, le bord doux de Vision reste.
Invites de MobileSAM : le cadre de chaque personne (--boxes, proportions de l'image,
venant de Vision) et, pour chaque zone certaine de Vision que ces cadres ont
manquee, son propre cadre (une mariee non detectee comme personne).

Sortie standard : une ligne JSON {"ok":true,"persons","extra","removed","filled","ms"}
(removed = part du masque de Vision retiree, filled = pixels rendus opaques), ou
{"ok":false,"error":...} avec le code de sortie 1.
"""
import argparse
import json
import os
import sys
import time


def fail(message):
    print(json.dumps({"ok": False, "error": message}, ensure_ascii=False))
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("vision")
    ap.add_argument("out")
    ap.add_argument("--boxes", default="")
    a = ap.parse_args()
    os.environ.setdefault("EMBEDKIT_OFFLINE", "1")

    import cv2
    import numpy as np
    from embedkit.tasks.segment import Segmenter

    start = time.time()
    image = cv2.imread(a.src, cv2.IMREAD_COLOR)            # orientation EXIF appliquee
    vision = cv2.imread(a.vision, cv2.IMREAD_GRAYSCALE)
    if image is None or vision is None:
        fail("image ou masque illisible")
    h, w = image.shape[:2]
    if vision.shape != (h, w):
        fail("masque de taille différente de la photo")
    v = vision.astype(np.float32) / 255.0
    boxes = []
    for part in filter(None, a.boxes.split(";")):
        try:
            x, y, bw, bh = (float(t) for t in part.split(","))
        except ValueError:
            fail("cadre invalide : %s" % part)
        boxes.append((max(0.0, x) * w, max(0.0, y) * h, min(1.0, x + bw) * w, min(1.0, y + bh) * h))

    sam = np.zeros((h, w), np.uint8)
    strong = (v >= 0.5).astype(np.uint8)
    extra = 0
    with Segmenter.load(model="mobilesam") as seg:
        if seg.tier == 0:
            fail("modèle MobileSAM absent : ./scripts/install_effects_env.sh")
        embedding = seg.embed(image)
        for box in boxes:
            masks, scores = seg.segment(embedding, box=box)
            sam |= masks[int(np.argmax(scores))].astype(np.uint8)
        n, labels, stats, _ = cv2.connectedComponentsWithStats(strong)
        for i in range(1, n):
            x, y, bw, bh, area = stats[i]
            if area < 0.005 * h * w or (sam[labels == i] > 0).mean() > 0.5:
                continue
            masks, scores = seg.segment(embedding, box=(x, y, x + bw, y + bh))
            sam |= masks[int(np.argmax(scores))].astype(np.uint8)
            extra += 1

    # Pres d'une personne / au coeur d'une personne : distance au masque MobileSAM,
    # calculee sur une version reduite (cout independant de la taille de la photo)
    r = max(4, int(round(max(w, h) * 0.006)))
    scale = min(1.0, 1536.0 / max(w, h))
    small = cv2.resize(sam, (max(1, round(w * scale)), max(1, round(h * scale))),
                       interpolation=cv2.INTER_NEAREST)
    rs = r * scale
    outside = cv2.distanceTransform((small == 0).astype(np.uint8), cv2.DIST_L2, 5)
    inside = cv2.distanceTransform(small, cv2.DIST_L2, 5)
    near = cv2.resize((outside <= rs).astype(np.uint8), (w, h), interpolation=cv2.INTER_LINEAR) > 0
    core = cv2.resize((inside > rs).astype(np.uint8), (w, h), interpolation=cv2.INTER_LINEAR) > 0

    final = np.where(near | (v >= 0.5), v, 0.0)
    final = np.where(core, 1.0, final)
    if not cv2.imwrite(a.out, (final * 255).astype(np.uint8)):
        fail("écriture impossible")
    total = max(1, int((v > 0.1).sum()))
    print(json.dumps({"ok": True, "persons": len(boxes), "extra": extra,
                      "removed": round(float(((v > 0.1) & ~(near | (v >= 0.5))).sum()) / total, 4),
                      "filled": int(((v < 0.5) & core).sum()),
                      "ms": int((time.time() - start) * 1000)}))


if __name__ == "__main__":
    main()
