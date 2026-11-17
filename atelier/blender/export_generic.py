"""Animation generique d'un modele de scene, sans aucune photo : Blender rend le decor
filme par la camera drone et l'exporte en composition After Effects (script .jsx), que
EffectCraft ouvre pour y placer les vraies photos et les titres.

    blender -b modele.blend --python export_generic.py -- dossier_sortie \
            [sequence|approche|orbite|envol|spirale] [secondes] [brouillon|normal|fin]

Le dossier recoit :
  decor.mp4          le decor, avec l'ombre au sol des emplacements PHOTO_DEBOUT_* (leur
                     forme, invisible a la camera) ; les emplacements eux-memes sont vides
  premier_plan.mov   la collection PREMIER_PLAN seule, avec transparence (si elle existe)
  composition.jsx    la composition : DECOR, camera DRONE animee image par image (position,
                     point vise, zoom), un nul 3D par emplacement (meme nom), PREMIER_PLAN ;
                     les videos y sont designees par {{DOSSIER}}/..., que Rexo Studio remplace
                     par le dossier ou le paquet est installe (paquet deplacable)
  scene.json         dimensions, cadence, echelle, emplacements (type, taille en metres)
  vignette.jpg       une image du decor a mi-parcours (catalogue de Rexo Studio)

Axes : Blender (x droite, y profondeur, z haut, metres) -> After Effects (x droite, y bas,
z profondeur, pixels) : X = W/2 + x*S, Y = H/2 - z*S, Z = y*S ; rotation Y d'After Effects
= - rotation Z de Blender ; zoom = W * focale / largeur du capteur.
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
cam = scene.camera
target = bpy.data.objects["VISE"]


def ae(v):
    return [round(W / 2 + v[0] * S, 3), round(H / 2 - v[2] * S, 3), round(v[1] * S, 3)]


# --- Emplacements ------------------------------------------------------------------
standing = [o for o in scene.objects if o.name.startswith("PHOTO_DEBOUT_") and o.type == "MESH"]
framed = [o for o in scene.objects if o.name.startswith("PHOTO_CADRE_") and o.type == "MESH"]
if not standing and not framed:
    raise SystemExit("ERREUR : aucun emplacement PHOTO_DEBOUT_* ni PHOTO_CADRE_* dans le modele")

# Emplacement debout : invisible a la camera, mais son ombre tombe au sol
invisible = bpy.data.materials.new("rexo_ombre_seule")
invisible.use_nodes = True
nodes = invisible.node_tree.nodes
nodes.clear()
nodes.new("ShaderNodeOutputMaterial")
invisible.node_tree.links.new(nodes.new("ShaderNodeBsdfTransparent").outputs["BSDF"],
                              nodes["Material Output"].inputs["Surface"])
invisible.blend_method, invisible.shadow_method = "BLEND", "OPAQUE"
for obj in standing:
    obj.data.materials.clear()
    obj.data.materials.append(invisible)
for obj in framed:
    obj.hide_render = True


def size_of(obj):
    xs = [v.co.x * obj.scale.x for v in obj.data.vertices]
    zs = [v.co.z * obj.scale.z for v in obj.data.vertices]
    return max(xs) - min(xs), max(zs) - min(zs)


places = []
for obj in standing + framed:
    width, height = size_of(obj)
    places.append({"name": obj.name, "kind": "debout" if obj in standing else "cadre",
                   "width_m": round(width, 4), "height_m": round(height, 4), "obj": obj})

times, cam_positions = [], []
yaws = {p["name"]: [] for p in places if p["kind"] == "debout"}
for f in range(1, frames + 1):
    scene.frame_set(f)
    c = cam.matrix_world.translation
    times.append(round((f - 1) / FPS, 6))
    cam_positions.append(ae(c))
    for p in places:
        if p["kind"] == "debout":
            o = p["obj"].matrix_world.translation
            # Face a la camera, sans se pencher (comme la contrainte LOCKED_TRACK)
            yaws[p["name"]].append(round(-math.degrees(math.atan2(c.x - o.x, -(c.y - o.y))), 4))
scene.frame_set(1)

# --- Composition After Effects ----------------------------------------------------
front = bpy.data.collections.get("PREMIER_PLAN")
has_front = bool(front and front.all_objects)
video = os.path.join(out_dir, "decor.mp4")
front_video = os.path.join(out_dir, "premier_plan.mov")
TOKEN = "{{DOSSIER}}"                             # remplace a l'installation dans Rexo Studio
duration = frames / float(FPS)
lines = [
    "// Rexo Studio : animation generique « %s » (%s), sans photo" % (
        os.path.splitext(os.path.basename(bpy.data.filepath))[0], motion),
    "(function () {",
    "  var W = %d, H = %d, FPS = %d, DUR = %r;" % (W, H, FPS, duration),
    "  var comp = app.project.items.addComp(%s, W, H, 1, DUR, FPS);" % json.dumps("Scène drone - " + motion),
    "  var decor = comp.layers.add(app.project.importFile(new ImportOptions(new File(%s))));"
    % json.dumps(TOKEN + "/decor.mp4"),
    "  decor.name = 'DECOR';",
    "  var times = %s;" % json.dumps(times),
    "  var cam = comp.layers.addCamera('DRONE', [W / 2, H / 2]);",
    "  cam.property('Camera Options').property('Zoom').setValue(%r);" % round(W * cam.data.lens / cam.data.sensor_width, 3),
    "  cam.property('Transform').property('Point of Interest').setValue(%s);" % json.dumps(ae(target.matrix_world.translation)),
    "  cam.property('Transform').property('Position').setValuesAtTimes(times, %s);" % json.dumps(cam_positions),
    "  var n;",
]
for p in places:
    obj = p["obj"]
    anchor = obj.matrix_world.translation               # pieds (debout) ou centre (cadre)
    lines += [
        "  n = comp.layers.addNull(DUR); n.name = %s; n.threeDLayer = true;" % json.dumps(p["name"]),
        "  n.property('Transform').property('Anchor Point').setValue([0, 0, 0]);",
        "  n.property('Transform').property('Position').setValue(%s);" % json.dumps(ae(anchor)),
    ]
    if p["kind"] == "debout":
        lines.append("  n.property('Transform').property('Y Rotation').setValuesAtTimes(times, %s);"
                     % json.dumps(yaws[p["name"]]))
    else:
        lines.append("  n.property('Transform').property('Y Rotation').setValue(%r);"
                     % round(-math.degrees(obj.matrix_world.to_euler().z), 4))
if has_front:
    lines += [
        "  var front = comp.layers.add(app.project.importFile(new ImportOptions(new File(%s))));"
        % json.dumps(TOKEN + "/premier_plan.mov"),
        "  front.name = 'PREMIER_PLAN';",
    ]
lines += ["  return comp.id;", "})()", ""]
with open(os.path.join(out_dir, "composition.jsx"), "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines))
with open(os.path.join(out_dir, "scene.json"), "w", encoding="utf-8") as fh:
    json.dump({"scene": os.path.splitext(os.path.basename(bpy.data.filepath))[0],
               "width": W, "height": H, "fps": FPS, "frames": frames, "duration": duration,
               "pixels_per_meter": S, "motion": motion, "quality": quality,
               "premier_plan": has_front,
               "placeholders": [{k: v for k, v in p.items() if k != "obj"} for p in places]},
              fh, indent=2, ensure_ascii=False)


# --- Rendus ------------------------------------------------------------------------
def _image_written(scn, *_args):
    print("IMAGE %d" % (scn.frame_current - scn.frame_start + 1), flush=True)


bpy.app.handlers.render_write.append(_image_written)
t = time.time()
scene.render.image_settings.file_format = "FFMPEG"
scene.render.ffmpeg.format, scene.render.ffmpeg.codec = "MPEG4", "H264"
scene.render.ffmpeg.constant_rate_factor = "HIGH"
scene.render.filepath = video
bpy.ops.render.render(animation=True)
print("MESURE %s %s %s : %d image(s) en %.1f s (%.2f s par image)" % (
    bpy.app.version_string, motion, quality, frames, time.time() - t, (time.time() - t) / frames))

if has_front:
    # Premier plan seul, sur fond transparent (QuickTime PNG, avec alpha)
    print("PASSE premier plan", flush=True)
    front_names = {o.name for o in front.all_objects}
    for obj in scene.objects:
        if obj.name not in front_names and obj.type not in ("CAMERA", "LIGHT"):
            obj.hide_render = True
    scene.render.film_transparent = True
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.ffmpeg.format, scene.render.ffmpeg.codec = "QUICKTIME", "PNG"
    scene.render.filepath = front_video
    bpy.ops.render.render(animation=True)


# Vignette : le decor a mi-parcours, sans les emplacements (catalogue de Rexo Studio)
for obj in scene.objects:
    obj.hide_render = obj.hide_render or obj.name.startswith("PHOTO_")
scene.render.film_transparent = False
if has_front:
    for obj in scene.objects:
        obj.hide_render = obj.name.startswith("PHOTO_")
scene.render.image_settings.file_format, scene.render.image_settings.color_mode = "JPEG", "RGB"
scene.render.resolution_percentage = 33
scene.frame_set(frames // 2)
scene.render.filepath = os.path.join(out_dir, "vignette.jpg")
bpy.ops.render.render(write_still=True)
