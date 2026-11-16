"""Photo animee en 3D (parallaxe) : les maries avancent devant le decor.

S'execute dans l'environnement d'effets (.effets/venv, Python 3.11) :

    parallax.py <photo> <masque.png> <sortie.mp4> --ffmpeg <bin/ffmpeg>
                [--motion avance|glisse] [--duration 6] [--fps 30] [--size 1920]

Deux calques :
  - les personnes : la photo, avec le masque (gris, blanc = personne ; le
    detourage affine de Rexo Studio) comme transparence ;
  - le decor : la photo dont la place des personnes, elargie, est reconstituee
    par MI-GAN. Pendant le mouvement, seule une bande etroite le long des
    silhouettes se decouvre : la ou MI-GAN prolonge le vrai decor (constat de
    rawi, ADR 0007), ses inventions au centre de la zone restent cachees.
Profondeur : Depth Anything V2 Small estime la distance de chaque point du decor,
relative a celle des maries ; chaque point bouge en proportion de sa proximite (le
lointain presque pas, le sol au premier plan plus que les maries). Carte lissee pour
que le decor ne se dechire pas. Sans le modele (ou --flat) : decor d'un bloc.
Mouvement de camera (debut et fin adoucis) :
  - avance : la camera s'approche ; les maries grandissent, le lointain presque pas ;
  - glisse : deplacement lateral ; le proche glisse, le lointain glisse un peu a l'oppose.
Les images sont envoyees a ffmpeg (H.264, yuv420p, lisible partout).

Sortie standard : une ligne JSON {"ok":true,"width","height","frames","ms"}, ou
{"ok":false,"error":...} avec le code de sortie 1.
"""
import argparse
import json
import os
import subprocess
import sys
import time


def fail(message):
    print(json.dumps({"ok": False, "error": message}, ensure_ascii=False))
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("mask")
    ap.add_argument("out")
    ap.add_argument("--ffmpeg", required=True)
    ap.add_argument("--motion", default="avance", choices=["avance", "glisse"])
    ap.add_argument("--duration", type=float, default=6.0)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--size", type=int, default=1920, help="grand cote de la video")
    ap.add_argument("--flat", action="store_true", help="decor d'un bloc, sans profondeur")
    ap.add_argument("--depth-png", default="", help="diagnostic : carte de profondeur relative")
    a = ap.parse_args()
    os.environ.setdefault("EMBEDKIT_OFFLINE", "1")

    import cv2
    import numpy as np
    from embedkit.tasks.inpaint import Inpainter

    start = time.time()
    image = cv2.imread(a.src, cv2.IMREAD_COLOR)            # orientation EXIF appliquee
    mask = cv2.imread(a.mask, cv2.IMREAD_GRAYSCALE)
    if image is None or mask is None:
        fail("photo ou masque illisible")
    if mask.shape != image.shape[:2]:
        mask = cv2.resize(mask, (image.shape[1], image.shape[0]), interpolation=cv2.INTER_LINEAR)
    # Taille de travail : grand cote a --size, dimensions paires (H.264)
    h0, w0 = image.shape[:2]
    scale = min(1.0, a.size / float(max(w0, h0)))
    w, h = int(w0 * scale) // 2 * 2, int(h0 * scale) // 2 * 2
    image = cv2.resize(image, (w, h), interpolation=cv2.INTER_AREA)
    alpha = cv2.resize(mask, (w, h), interpolation=cv2.INTER_LINEAR).astype(np.float32) / 255.0
    if (alpha > 0.5).mean() < 0.01:
        fail("personne trouvée sur la photo : l'effet 3D a besoin d'un premier plan")

    # Decor : la place des personnes (elargie de 1,5 % du grand cote, pour couvrir les
    # bords doux et ce que le mouvement decouvre) reconstituee par MI-GAN
    grow = max(6, int(round(max(w, h) * 0.015)))
    hole = (alpha > 0.06).astype(np.uint8)
    dist = cv2.distanceTransform((hole == 0).astype(np.uint8), cv2.DIST_L2, 5)
    hole = (dist <= grow).astype(np.uint8)
    with Inpainter.load(model="migan-512") as inp:
        if inp.tier == 0:
            fail("modèle MI-GAN absent : ./scripts/install_effects_env.sh")
        background = inp(image, hole)

    # Centre du mouvement : le centre des personnes (visages plutot que pieds)
    ys, xs = np.nonzero(alpha > 0.5)
    cx = float(xs.mean())
    cy = float(ys.min() + 0.4 * (ys.max() - ys.min()))

    # Profondeur du decor relative aux maries (Depth Anything V2 Small, 1 = proche) :
    # rel = 1 a la distance des maries, ~0 au loin, > 1 plus pres (le sol au premier plan).
    # Le decor reconstitue donne une profondeur continue derriere les maries ; la
    # photo d'origine donne la distance des maries. Les deux cartes, normalisees chacune
    # a sa facon, sont accordees sur la zone ou les deux images sont identiques.
    rel = None
    depth_info = "plat"
    if not a.flat:
        try:
            from embedkit.tasks.depth import DepthEstimator
            with DepthEstimator.load(model="depth-anything-v2-small") as est:
                if est.tier > 0:
                    d_img = cv2.resize(est(image), (w, h)).astype(np.float32)
                    d_bg = cv2.resize(est(background), (w, h)).astype(np.float32)
                    same = (hole == 0)
                    a_fit, b_fit = np.polyfit(d_bg[same][::37], d_img[same][::37], 1)
                    d_bg = a_fit * d_bg + b_fit
                    d_fg = float(np.median(d_img[alpha > 0.5]))
                    rel = np.clip(d_bg / max(d_fg, 1e-3), 0.0, 1.3).astype(np.float32)
                    # Lissage : pas de dechirure du decor aux changements brusques de distance
                    rel = cv2.GaussianBlur(rel, (0, 0), max(w, h) * 0.01)
                    depth_info = "profondeur (lointain %.2f, sol %.2f)" % (
                        float(np.percentile(rel, 5)), float(np.percentile(rel, 95)))
        except Exception as exc:                       # noqa: BLE001 - repli : decor plat
            depth_info = "plat (profondeur indisponible : %s)" % exc
    if rel is None:
        rel = np.full((h, w), 0.4, np.float32)         # decor d'un bloc, comme sans profondeur
    if a.depth_png:
        cv2.imwrite(a.depth_png, np.clip(rel / 1.3 * 255, 0, 255).astype(np.uint8))
    gx, gy = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    ox, oy = gx - cx, gy - cy

    # Calculs en entiers et dans OpenCV (C) : ~3 fois plus rapide que numpy en flottants
    fg = image
    bg = background
    alpha8 = (alpha * 255).astype(np.uint8)
    frames = max(2, int(round(a.duration * a.fps)))
    cmd = [a.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", "%dx%d" % (w, h), "-r", str(a.fps), "-i", "-",
           "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
           "-movflags", "+faststart", a.out]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    def warp(img, s, dx, dy, border):
        m = np.float32([[s, 0, (1 - s) * cx + dx], [0, s, (1 - s) * cy + dy]])
        return cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_LINEAR, borderMode=border)

    amplitude = 0.045 * w                                 # glissement : 4,5 % de la largeur
    try:
        for i in range(frames):
            t = i / float(frames - 1)
            e = t * t * (3 - 2 * t)                          # debut et fin adoucis
            # Chaque point du decor bouge selon sa profondeur (rel) ; les maries (rel = 1)
            # bougent comme leur calque. Lecture inverse : pour chaque point de l'image,
            # ou prendre la couleur dans le decor (cv2.remap).
            if a.motion == "avance":
                s0, sf = 1.04 + 0.01 * e, 1.04 + 0.11 * e     # lointain presque fixe, maries s'approchent
                s = s0 + (sf - s0) * rel
                mx, my = cx + ox / s, cy + oy / s
                dxf = 0.0
            else:
                sf = 1.06                                     # marge : jamais de bord vide
                shift = amplitude * (e - 0.5) * (rel - 0.3)   # le loin glisse un peu a l'oppose
                mx, my = cx + ox / sf - shift, cy + oy / sf
                dxf = amplitude * (e - 0.5) * 0.7
            b = cv2.remap(bg, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
            f = warp(fg, sf, dxf, 0.0, cv2.BORDER_REFLECT)
            wf = warp(alpha8, sf, dxf, 0.0, cv2.BORDER_CONSTANT).astype(np.float32) * (1 / 255.0)
            frame = cv2.blendLinear(f, b, wf, 1.0 - wf)
            proc.stdin.write(frame.tobytes())
        proc.stdin.close()
        err = proc.stderr.read().decode("utf-8", "replace")
        if proc.wait() != 0:
            fail("ffmpeg : %s" % err.strip()[-300:])
    except BrokenPipeError:
        fail("ffmpeg s'est arrêté : %s" % proc.stderr.read().decode("utf-8", "replace")[-300:])
    print(json.dumps({"ok": True, "width": w, "height": h, "frames": frames, "depth": depth_info,
                      "ms": int((time.time() - start) * 1000)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
