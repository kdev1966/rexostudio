"""Rend une video « camera drone » a partir d'un modele de scene et des maries detoures
(Blender 3.6 LTS, EEVEE). Contrat du modele : voir build_template_jardin.py.

    blender -b modele.blend --python render_template.py -- maries.png sortie.mp4 \
            [sequence|approche|orbite|envol|spirale] [secondes] [brouillon|normal|fin] [image]

Dernier argument facultatif « image » : rend une seule image (au milieu du mouvement)
en JPEG, pour mesurer ou previsualiser rapidement.
"""
import math
import os
import sys
import time

import bpy
import numpy as np

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

# Mouvements de drone : points de passage (angle depuis l'avant en degres, distance m,
# hauteur m) ; rotation limitee a +-40 degres (la photo reste credible)
PATHS = {
    "approche": [(-8, 14, 7), (0, 4.2, 1.6)],
    "orbite": [(-38, 4.6, 1.7), (38, 4.6, 1.7)],
    "envol": [(0, 3.6, 1.4), (12, 10, 6)],
    "spirale": [(-40, 11, 6), (0, 7, 3.5), (35, 4.2, 1.6)],
    "sequence": [(-10, 15, 8), (0, 4.4, 1.7), (35, 4.4, 1.6), (15, 10, 6)],
}
cam = scene.camera
points = PATHS.get(motion, PATHS["sequence"])
scene.frame_start, scene.frame_end = 1, frames
for i, (ang, dist, z) in enumerate(points):
    f = 1 + round(i * (frames - 1) / (len(points) - 1))
    a = math.radians(ang)
    cam.location = (dist * math.sin(a), -dist * math.cos(a), z)
    cam.keyframe_insert("location", frame=f)
for fc in cam.animation_data.action.fcurves:
    for kp in fc.keyframe_points:
        kp.interpolation = "BEZIER"
        kp.handle_left_type = kp.handle_right_type = "AUTO_CLAMPED"

# Qualite : ce qui coute le plus cher sur l'Iris Pro de l'iMac
ev = scene.eevee
# Le flou de mise au point d'EEVEE domine sur l'iMac (3 s/image avec, 1,1 s sans en
# brouillon, mesure du 16/11/2026) et ne se voyait pas sur ce decor : il est reserve
# a la qualite « fin ». Un flou d'arriere-plan moins cher viendra avec les vrais decors.
QUALITY = {
    "brouillon": {"samples": 8, "ssr": False, "soft": False, "gtao": False, "dof": False},
    "normal": {"samples": 16, "ssr": False, "soft": True, "gtao": True, "dof": False},
    "fin": {"samples": 32, "ssr": True, "soft": True, "gtao": True, "dof": True},
}
q = QUALITY.get(quality, QUALITY["normal"])
ev.taa_render_samples = q["samples"]
ev.use_ssr, ev.use_soft_shadows, ev.use_gtao = q["ssr"], q["soft"], q["gtao"]
scene.camera.data.dof.use_dof = q["dof"]
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
