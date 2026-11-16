"""Rend une video « camera drone » a partir d'un modele de scene et des maries detoures
(Blender 3.6 LTS, EEVEE). Contrat du modele : voir build_template_jardin.py.

    blender -b modele.blend --python render_template.py -- maries.png sortie.mp4 \
            [sequence|approche|orbite|envol|spirale] [secondes] [brouillon|normal|fin] [image]

Dernier argument facultatif « image » : rend une seule image (au milieu du mouvement)
en JPEG, pour mesurer ou previsualiser rapidement.
"""
import os
import sys
import time

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from drone_paths import animate_camera, apply_quality  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:]
couple_png, out_path = argv[0], argv[1]
motion = argv[2] if len(argv) > 2 else "sequence"
seconds = float(argv[3]) if len(argv) > 3 else 9.0
quality = argv[4] if len(argv) > 4 else "normal"
still = len(argv) > 5 and argv[5] == "image"
fps = 30
frames = max(2, int(round(seconds * fps)))
scene = bpy.context.scene

# Maries : la photo detouree (pleine taille) dans l'emplacement du modele. Le plan ne
# montre que le cadre des personnes (pieds au sol), a ses proportions : la photo n'a
# pas besoin d'etre recadree avant.
couple = bpy.data.objects["MARIES"]
img = bpy.data.images.load(couple_png)
couple.active_material.node_tree.nodes["MARIES_IMAGE"].image = img
iw, ih = img.size
pixels = np.empty(iw * ih * 4, dtype=np.float32)
img.pixels.foreach_get(pixels)
alpha = pixels[3::4].reshape(ih, iw)            # ligne 0 = bas de l'image
rows = np.nonzero(alpha.max(axis=1) > 0.5)[0]
cols = np.nonzero(alpha.max(axis=0) > 0.5)[0]
del pixels, alpha
if not len(rows):
    raise SystemExit("ERREUR : le detourage est vide")
u0, u1 = cols[0] / iw, (cols[-1] + 1) / iw
v0, v1 = rows[0] / ih, (rows[-1] + 1) / ih
height = max(v.co.z for v in couple.data.vertices)
width = height * (u1 - u0) * iw / ((v1 - v0) * ih)
for v in couple.data.vertices:
    v.co.x = (1 if v.co.x > 0 else -1) * width / 2
uv = couple.data.uv_layers.active.data
for loop in couple.data.loops:
    co = couple.data.vertices[loop.vertex_index].co
    uv[loop.index].uv = (u1 if co.x > 0 else u0, v1 if co.z > height / 2 else v0)

# Mouvement de drone et qualite (communs avec export_generic.py)
animate_camera(scene, motion, seconds, fps)
ev = scene.eevee
apply_quality(scene, quality)
# Diagnostic des temps : REXO_BLENDER_SANS="flou,halo,ombres,ombre_maries" coupe ces postes
off = set(filter(None, os.environ.get("REXO_BLENDER_SANS", "").split(",")))
if "flou" in off:
    scene.camera.data.dof.use_dof = False
if "halo" in off:
    ev.use_bloom = False
if "ombres" in off:
    for light in bpy.data.lights:
        light.use_shadow = False
if "ombre_maries" in off:
    couple.active_material.shadow_method = "NONE"
scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 1920, 1080, 100
scene.render.fps = fps
# Progression : une ligne par image enregistree, envoyee tout de suite (la sortie de
# Blender lui-meme reste en memoire tampon quand Rexo Studio la lit)


def _image_written(scn, *_args):
    print("IMAGE %d" % (scn.frame_current - scn.frame_start + 1), flush=True)


bpy.app.handlers.render_write.append(_image_written)
t = time.time()
if still:
    scene.frame_set(frames // 2)
    scene.render.image_settings.file_format = "JPEG"
    scene.render.filepath = out_path
    bpy.ops.render.render(write_still=True)
    n = 1
else:
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.ffmpeg.format, scene.render.ffmpeg.codec = "MPEG4", "H264"
    scene.render.ffmpeg.constant_rate_factor = "HIGH"
    scene.render.filepath = out_path
    bpy.ops.render.render(animation=True)
    n = frames
total = time.time() - t
print("MESURE %s %s %s : %d image(s) en %.1f s (%.2f s par image)" % (
    bpy.app.version_string, motion, quality, n, total, total / n))
