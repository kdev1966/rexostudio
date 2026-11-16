"""Essai reel des modeles de l'environnement d'effets (lance par check_install.sh).

S'execute avec .effets/venv/bin/python et PYTHONPATH=vendor/embedkit. Sur une image
synthetique (aucune photo de client) : un disque rouge sur un fond en degrade.
  - MobileSAM detoure le disque a partir d'un cadre (recouvrement attendu > 0,8)
  - MI-GAN efface le disque (il ne doit plus rester de rouge)
  - Depth Anything donne une carte de profondeur de la taille de l'image
Imprime une ligne par modele avec ses temps ; code de sortie 1 au premier echec.
Option --photo <fichier> : produit en plus, sur une vraie photo, le detourage du
cadre central et son effacement, dans le dossier --out, pour un controle visuel.
"""
import argparse
import os
import sys
import time

import cv2
import numpy as np


def synthetic():
    h, w = 480, 640
    grad = np.linspace(40, 200, w, dtype=np.float32)[None, :].repeat(h, 0)
    img = np.dstack([grad, grad * 0.9, grad * 0.7]).astype(np.uint8)
    cv2.rectangle(img, (0, 360), (w, h), (90, 110, 120), -1)          # sol
    disk = np.zeros((h, w), np.uint8)
    cv2.circle(disk, (330, 250), 80, 1, -1)
    img[disk > 0] = (30, 30, 220)                                     # disque rouge (BGR)
    return img, disk


def check(name, cond, detail):
    print("%s %-26s %s" % ("✓" if cond else "✗", name, detail))
    if not cond:
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--photo")
    ap.add_argument("--out", default=".")
    a = ap.parse_args()
    os.environ.setdefault("EMBEDKIT_OFFLINE", "1")   # aucun telechargement pendant l'essai
    from embedkit.tasks.depth import DepthEstimator
    from embedkit.tasks.inpaint import Inpainter
    from embedkit.tasks.segment import Segmenter

    img, disk = synthetic()
    t = time.time()
    with Segmenter.load(model="mobilesam") as seg:
        t_load = time.time() - t
        t = time.time()
        emb = seg.embed(img)
        masks, scores = seg.segment(emb, box=(230, 150, 430, 350))
        t_run = time.time() - t
    mask = masks[int(np.argmax(scores))]
    iou = float((mask & disk).sum()) / float((mask | disk).sum())
    check("MobileSAM (detourage)", iou > 0.8,
          "recouvrement %.2f, chargement %.1f s, calcul %.1f s" % (iou, t_load, t_run))

    hole = cv2.dilate(disk, np.ones((9, 9), np.uint8))
    t = time.time()
    with Inpainter.load(model="migan-512") as inp:
        filled = inp(img, hole)
    t_fill = time.time() - t
    red = filled[disk > 0].astype(np.int32)
    redness = float(np.mean(red[:, 2] - (red[:, 0] + red[:, 1]) / 2))
    check("MI-GAN (effacement)", redness < 40,
          "rouge restant %.0f (disque : 190), %.1f s" % (redness, t_fill))

    t = time.time()
    with DepthEstimator.load(model="depth-anything-v2-small") as est:
        depth = est(img)
    check("Depth Anything (profondeur)", depth.shape == img.shape[:2],
          "carte %dx%d, %.1f s" % (depth.shape[1], depth.shape[0], time.time() - t))

    # L'ouvrier d'effacement de la galerie, sur une image de 19 Mpx : MI-GAN ne doit
    # traiter que la zone de l'objet (sur l'image entiere : 155 s sur l'iMac).
    import json
    import subprocess
    import tempfile
    big = cv2.resize(img, (5368, 3579), interpolation=cv2.INTER_NEAREST)
    worker = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "effects_worker", "erase.py")
    with tempfile.TemporaryDirectory() as tmp:
        src, out = os.path.join(tmp, "grande.jpg"), os.path.join(tmp, "effacee.jpg")
        cv2.imwrite(src, big, [cv2.IMWRITE_JPEG_QUALITY, 95])
        t = time.time()
        proc = subprocess.run([sys.executable, worker, src, out, "--box", "0.34,0.29,0.36,0.46"],
                              capture_output=True, text=True)
        elapsed = time.time() - t
        reply = json.loads(proc.stdout.strip().splitlines()[-1]) if proc.stdout.strip() else {}
        erased = cv2.imread(out) if reply.get("ok") else None
    if erased is None:
        check("Effacement (galerie)", False, reply.get("error") or proc.stderr.strip()[-300:])
    disk_big = cv2.resize(disk, (5368, 3579), interpolation=cv2.INTER_NEAREST)
    red = erased[disk_big > 0].astype(np.int32)
    redness = float(np.mean(red[:, 2] - (red[:, 0] + red[:, 1]) / 2))
    check("Effacement 19 Mpx (galerie)", redness < 40 and elapsed < 40,
          "rouge restant %.0f, %.1f s (limite 40 s)" % (redness, elapsed))

    if a.photo:
        photo = cv2.imread(a.photo)
        if photo is None:
            check("photo", False, "illisible : %s" % a.photo)
        h, w = photo.shape[:2]
        box = (w * 0.3, h * 0.3, w * 0.7, h * 0.7)
        t = time.time()
        with Segmenter.load(model="mobilesam") as seg:
            masks, scores = seg.segment(seg.embed(photo), box=box)
        m = masks[int(np.argmax(scores))]
        with Inpainter.load(model="migan-512") as inp:
            out = inp(photo, cv2.dilate(m, np.ones((15, 15), np.uint8)))
        os.makedirs(a.out, exist_ok=True)
        stem = os.path.splitext(os.path.basename(a.photo))[0]
        cv2.imwrite(os.path.join(a.out, stem + "_masque_mobilesam.png"), m * 255)
        cv2.imwrite(os.path.join(a.out, stem + "_efface_migan.jpg"), out)
        check("photo reelle", True, "objet du cadre central efface en %.1f s -> %s"
              % (time.time() - t, a.out))


if __name__ == "__main__":
    main()
