"""Efface un objet d'une photo : MobileSAM le detoure dans un cadre, MI-GAN
reconstitue le decor a sa place.

S'execute dans l'environnement d'effets (.effets/venv, Python 3.11, voir
scripts/install_effects_env.sh), jamais dans le coeur de Rexo Studio :

    erase.py <entree> <sortie.jpg> --box x,y,l,h [--mask masque.png]

--box : cadre autour de l'objet, en proportions de l'image telle qu'on la voit
(orientation EXIF appliquee, comme dans le navigateur et pour Vision).
Sortie standard : une ligne JSON {"ok":true,"width","height","coverage","score","ms"}
(coverage = part de l'image effacee, score = confiance de MobileSAM), ou
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
    ap.add_argument("out")
    ap.add_argument("--box", required=True)
    ap.add_argument("--mask", default="")
    a = ap.parse_args()
    os.environ.setdefault("EMBEDKIT_OFFLINE", "1")   # jamais de reseau pendant un effet

    import cv2
    import numpy as np
    from embedkit.tasks.inpaint import Inpainter
    from embedkit.tasks.segment import Segmenter

    start = time.time()
    image = cv2.imread(a.src, cv2.IMREAD_COLOR)        # applique l'orientation EXIF
    if image is None:
        fail("image illisible : %s" % os.path.basename(a.src))
    h, w = image.shape[:2]
    try:
        fx, fy, fw, fh = (float(v) for v in a.box.split(","))
    except ValueError:
        fail("cadre invalide")
    x0, y0 = max(0.0, fx) * w, max(0.0, fy) * h
    x1, y1 = min(1.0, fx + fw) * w, min(1.0, fy + fh) * h
    if x1 - x0 < 8 or y1 - y0 < 8:
        fail("cadre trop petit")

    with Segmenter.load(model="mobilesam") as seg:
        if seg.tier == 0:
            fail("modèle MobileSAM absent : ./scripts/install_effects_env.sh")
        masks, scores = seg.segment(seg.embed(image), box=(x0, y0, x1, y1))
    best = int(np.argmax(scores))
    mask = masks[best].astype(np.uint8)
    # Ce qui deborde du cadre n'est pas l'objet designe
    inside = np.zeros_like(mask)
    inside[int(y0):int(np.ceil(y1)), int(x0):int(np.ceil(x1))] = 1
    mask &= inside
    if not mask.any():
        fail("aucun objet trouvé dans le cadre")
    # Bord de l'objet (ombre douce, pixels melanges) efface avec lui : tout pixel a
    # moins de « grow » px de l'objet. Transformee de distance sur la seule zone de
    # l'objet : son cout ne depend pas de grow. (cv2.dilate avec un disque de 65 px
    # sur une photo de 19 Mpx prenait 155 s sur l'iMac.)
    grow = max(7, int(round(max(w, h) * 0.006)))
    ys, xs = np.nonzero(mask)
    zx0, zy0 = max(0, xs.min() - grow - 1), max(0, ys.min() - grow - 1)
    zx1, zy1 = min(w, xs.max() + grow + 2), min(h, ys.max() + grow + 2)
    outside = (mask[zy0:zy1, zx0:zx1] == 0).astype(np.uint8)
    dist = cv2.distanceTransform(outside, cv2.DIST_L2, 5)
    hole = np.zeros_like(mask)
    hole[zy0:zy1, zx0:zx1] = (dist <= grow).astype(np.uint8)

    with Inpainter.load(model="migan-512") as inp:
        if inp.tier == 0:
            fail("modèle MI-GAN absent : ./scripts/install_effects_env.sh")
        result = inp(image, hole)       # hors du trou, la photo est recopiee telle quelle

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    if not cv2.imwrite(a.out, result, [cv2.IMWRITE_JPEG_QUALITY, 92]):
        fail("écriture impossible")
    if a.mask:
        cv2.imwrite(a.mask, hole * 255)
    print(json.dumps({"ok": True, "width": w, "height": h,
                      "coverage": round(float(hole.mean()), 4),
                      "score": round(float(scores[best]), 3),
                      "ms": int((time.time() - start) * 1000)}))


if __name__ == "__main__":
    main()
