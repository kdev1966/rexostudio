"""Recadre une image detouree (PNG transparent) au plus pres des personnes, pour
qu'EffectCraft pose leurs pieds exactement sur l'emplacement de la scene 3D.

S'execute dans l'environnement d'effets (.effets/venv, Python 3.11) :

    trim.py <entree.png> <sortie.png>

Sortie standard : une ligne JSON {"ok":true,"width","height","box":[x,y,l,h],
"cut_bottom"} ; cut_bottom : les personnes touchent le bas de la photo (pas en pied).
"""
import json
import sys

import cv2
import numpy as np


def main():
    if len(sys.argv) != 3:
        print(json.dumps({"ok": False, "error": "usage : trim.py entree.png sortie.png"}))
        return 2
    image = cv2.imread(sys.argv[1], cv2.IMREAD_UNCHANGED)
    if image is None or image.ndim != 3 or image.shape[2] != 4:
        print(json.dumps({"ok": False, "error": "image transparente (PNG RGBA) attendue"}))
        return 1
    ys, xs = np.nonzero(image[:, :, 3] > 127)
    if not len(xs):
        print(json.dumps({"ok": False, "error": "détourage vide : aucune personne"}, ensure_ascii=False))
        return 1
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()) + 1, int(ys.min()), int(ys.max()) + 1
    if not cv2.imwrite(sys.argv[2], image[y0:y1, x0:x1]):
        print(json.dumps({"ok": False, "error": "écriture impossible"}, ensure_ascii=False))
        return 1
    cut_bottom = y1 >= image.shape[0] - max(2, image.shape[0] // 200)
    print(json.dumps({"ok": True, "width": x1 - x0, "height": y1 - y0, "box": [x0, y0, x1 - x0, y1 - y0],
                      "cut_bottom": bool(cut_bottom)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
