"""Animation generique d'un modele de scene, sans les maries : Blender rend le decor
filme par la camera drone et l'exporte en composition After Effects (script .jsx),
que EffectCraft ouvre pour y placer la photo detouree et les titres.

    blender -b modele.blend --python export_generic.py -- dossier_sortie \
            [sequence|approche|orbite|envol|spirale] [secondes] [brouillon|normal|fin]

Le dossier recoit :
  decor.mp4         le decor seul (l'emplacement MARIES est cache)
  composition.jsx   la composition : video du decor, camera animee (position et point
                    vise, image par image), et un nul « MARIES » (pieds des maries,
                    tourne vers la camera) auquel EffectCraft accroche la photo
  scene.json        dimensions, cadence, echelle (pixels par metre)

Correspondance des axes : Blender (x droite, y profondeur, z haut, metres) ->
After Effects (x droite, y bas, z profondeur, pixels) : X = W/2 + x*S, Y = H/2 - z*S,
Z = y*S ; zoom de la camera = W * focale / largeur du capteur.
"""
import json
import math
import os
import sys
import time

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from drone_paths import animate_camera, apply_quality  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:]
out_dir = os.path.abspath(argv[0])
motion = argv[1] if len(argv) > 1 else "sequence"
seconds = float(argv[2]) if len(argv) > 2 else 9.0
quality = argv[3] if len(argv) > 3 else "normal"
FPS, W, H, S = 30, 1920, 1080, 100.0          # S : pixels After Effects par metre
os.makedirs(out_dir, exist_ok=True)

scene = bpy.context.scene
frames = animate_camera(scene, motion, seconds, FPS)
apply_quality(scene, quality)
scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = W, H, 100
scene.render.fps = FPS

# Decor seul : l'emplacement des maries est cache au rendu (sa photo viendra d'EffectCraft)
couple = bpy.data.objects["MARIES"]
couple.hide_render = True

# --- Composition After Effects ---------------------------------------------------
cam = scene.camera
target = bpy.data.objects["VISE"]


def ae(v):
    return [round(W / 2 + v[0] * S, 3), round(H / 2 - v[2] * S, 3), round(v[1] * S, 3)]


times, positions, yaws = [], [], []
for f in range(1, frames + 1):
    scene.frame_set(f)
    p = cam.matrix_world.translation
    times.append(round((f - 1) / FPS, 6))
    positions.append(ae(p))
    # Rotation Y du nul : la photo reste face a la camera, sans se pencher
    # (sens d'After Effects : rotation Y positive vers la gauche vue de dessus)
    yaws.append(round(-math.degrees(math.atan2(p.x, -p.y)), 4))
zoom = W * cam.data.lens / cam.data.sensor_width
poi = ae(target.matrix_world.translation)
feet = ae(couple.matrix_world.translation)
video = os.path.join(out_dir, "decor.mp4")
duration = frames / float(FPS)

jsx = """// Rexo Studio : animation generique « %(name)s » (%(motion)s), sans les maries
(function () {
  var W = %(W)d, H = %(H)d, FPS = %(FPS)d, DUR = %(DUR)r;
  var comp = app.project.items.addComp(%(cname)s, W, H, 1, DUR, FPS);
  var footage = app.project.importFile(new ImportOptions(new File(%(video)s)));
  var decor = comp.layers.add(footage);
  decor.name = "DECOR";
  var times = %(times)s;
  var cam = comp.layers.addCamera("DRONE", [W / 2, H / 2]);
  cam.property("Camera Options").property("Zoom").setValue(%(zoom)r);
  cam.property("Transform").property("Point of Interest").setValue(%(poi)s);
  cam.property("Transform").property("Position").setValuesAtTimes(times, %(positions)s);
  var maries = comp.layers.addNull(DUR);
  maries.name = "MARIES";
  maries.threeDLayer = true;
  // Origine du nul en son centre : une photo accrochee a (0, 0, 0) tombe sur les pieds
  maries.property("Transform").property("Anchor Point").setValue([0, 0, 0]);
  maries.property("Transform").property("Position").setValue(%(feet)s);
  maries.property("Transform").property("Y Rotation").setValuesAtTimes(times, %(yaws)s);
  return comp.id;
})()
""" % {"name": os.path.splitext(os.path.basename(bpy.data.filepath))[0], "motion": motion,
       "W": W, "H": H, "FPS": FPS, "DUR": duration,
       "cname": json.dumps("Scène drone - %s" % motion), "video": json.dumps(video),
       "times": json.dumps(times), "zoom": round(zoom, 3), "poi": json.dumps(poi),
       "positions": json.dumps(positions), "feet": json.dumps(feet), "yaws": json.dumps(yaws)}
with open(os.path.join(out_dir, "composition.jsx"), "w", encoding="utf-8") as fh:
    fh.write(jsx)
with open(os.path.join(out_dir, "scene.json"), "w", encoding="utf-8") as fh:
    json.dump({"width": W, "height": H, "fps": FPS, "frames": frames, "duration": duration,
               "pixels_per_meter": S, "motion": motion, "quality": quality,
               "couple_height_m": max(v.co.z for v in couple.data.vertices),
               "feet": feet, "zoom": zoom}, fh, indent=2)


def _image_written(scn, *_args):
    print("IMAGE %d" % (scn.frame_current - scn.frame_start + 1), flush=True)


bpy.app.handlers.render_write.append(_image_written)
scene.frame_set(1)
scene.render.image_settings.file_format = "FFMPEG"
scene.render.ffmpeg.format, scene.render.ffmpeg.codec = "MPEG4", "H264"
scene.render.ffmpeg.constant_rate_factor = "HIGH"
scene.render.filepath = video
t = time.time()
bpy.ops.render.render(animation=True)
total = time.time() - t
print("MESURE %s %s %s : %d image(s) en %.1f s (%.2f s par image)" % (
    bpy.app.version_string, motion, quality, frames, total, total / frames))
