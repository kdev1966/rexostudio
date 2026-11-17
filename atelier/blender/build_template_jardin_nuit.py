"""Construit le modele de scene « jardin de ceremonie de nuit » (Blender 3.6 LTS) et
l'enregistre en .blend : decor, camera et emplacements des photos.

    blender -b --factory-startup --python build_template_jardin.py -- jardin_nuit.blend

Premier modele, volontairement simple (materiaux unis, formes de base) ; de vrais
decors, textures et modeles 3D viendront ensuite, construits a la main dans Blender.

Contrat d'un modele de scene Rexo Studio (blender/export_generic.py s'appuie dessus) :
  - camera « DRONE » (scene.camera), contrainte TRACK_TO vers l'objet vide « VISE »
    (point vise : le buste des maries) ; le mouvement est ajoute a l'export ;
  - emplacements des photos, reconnus par leur nom, plans dans le plan XZ local, face
    vers -Y local :
      PHOTO_DEBOUT_<nom>  personne detouree debout (ex. PHOTO_DEBOUT_MARIES) : origine
                          aux pieds, taille = hauteur et largeur reservees ; toujours
                          tournee vers la camera (LOCKED_TRACK) ; sa forme sert
                          d'ombre au sol (elle est invisible au rendu)
      PHOTO_CADRE_<nom>   photo a plat et fixe (tableau, chevalet, ecran) : origine au
                          centre, debout, orientation libre autour de la verticale
  - collection « PREMIER_PLAN » (facultative) : ce qui passe devant les photos, rendu
    a part avec transparence et pose par-dessus dans EffectCraft.
"""
import math
import os
import random
import sys

import bpy

out_blend = sys.argv[sys.argv.index("--") + 1]
random.seed(7)
for obj in list(bpy.data.objects):          # scene vide (sans recharger les reglages d'usine)
    bpy.data.objects.remove(obj, do_unlink=True)
scene = bpy.context.scene


def material(name, color, roughness=0.5, emission=None, strength=0.0, metallic=0.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    p = mat.node_tree.nodes.get("Principled BSDF")
    p.inputs["Base Color"].default_value = (*color, 1)
    p.inputs["Roughness"].default_value = roughness
    p.inputs["Metallic"].default_value = metallic
    if emission:
        p.inputs["Emission"].default_value = (*emission, 1)
        p.inputs["Emission Strength"].default_value = strength
    return mat


# Textures PBR faites par TextureCraft (scripts/prepare_textures.py) ; sans elles, le
# modele garde ses couleurs unies
TEXTURES = os.environ.get("REXO_TEXTURES_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "textures")


def textured(name, texture, color, repeat=1.0, roughness=0.5, metallic=0.0, metal_scale=1.0):
    """Materiau aux textures TextureCraft (couleur, metal, rugosite, normale), repetees
    `repeat` fois ; couleur unie si la texture manque. metal_scale attenue la carte de
    metal : dans une scene de nuit, un metal pur ne reflete que le ciel noir."""
    folder = os.path.join(TEXTURES, texture)
    base = os.path.join(folder, texture + "_BaseColor.png")
    if not os.path.isfile(base):
        return material(name, color, roughness, metallic=metallic)
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    p = nodes.get("Principled BSDF")
    coord, mapping = nodes.new("ShaderNodeTexCoord"), nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (repeat, repeat, repeat)
    links.new(coord.outputs["UV"], mapping.inputs["Vector"])

    def image(kind, data):
        path = os.path.join(folder, "%s_%s.png" % (texture, kind))
        if not os.path.isfile(path):
            return None
        node = nodes.new("ShaderNodeTexImage")
        node.image = bpy.data.images.load(path)
        if data:
            node.image.colorspace_settings.name = "Non-Color"
        links.new(mapping.outputs["Vector"], node.inputs["Vector"])
        return node

    links.new(image("BaseColor", False).outputs["Color"], p.inputs["Base Color"])
    node = image("Metallic", True)
    if node:
        scale = nodes.new("ShaderNodeMath")
        scale.operation, scale.inputs[1].default_value = "MULTIPLY", metal_scale
        links.new(node.outputs["Color"], scale.inputs[0])
        links.new(scale.outputs["Value"], p.inputs["Metallic"])
    node = image("Roughness", True)
    if node:
        links.new(node.outputs["Color"], p.inputs["Roughness"])
    node = image("Normal", True)
    if node:
        normal = nodes.new("ShaderNodeNormalMap")
        links.new(node.outputs["Color"], normal.inputs["Color"])
        links.new(normal.outputs["Normal"], p.inputs["Normal"])
    return mat


def add(obj, mat, name=None):
    obj.data.materials.append(mat)
    if name:
        obj.name = name
    return obj


# Sol, colonnes (derriere), arche fleurie, petites lumieres au loin (halos avec la mise au point)
bpy.ops.mesh.primitive_plane_add(size=80)
add(bpy.context.active_object, textured("sol", "marble", (0.80, 0.78, 0.75), repeat=30, roughness=0.12), "Sol")
white = textured("colonnes", "plaster", (0.92, 0.90, 0.86), repeat=2, roughness=0.35)
# Colonnes en demi-cercle derriere les maries : la camera vole devant (+-40 degres)
# et ne passe jamais entre une colonne et les maries
for i in range(7):
    ang = math.radians(-90 + 30 * i)
    bpy.ops.mesh.primitive_cylinder_add(radius=0.28, depth=4.5, vertices=24,
                                        location=(7.5 * math.sin(ang), 7.5 * math.cos(ang), 2.25))
    add(bpy.context.active_object, white, "Colonne")
bpy.ops.mesh.primitive_torus_add(major_radius=2.1, minor_radius=0.09, location=(0, 1.3, 0),
                                 rotation=(math.radians(90), 0, 0))
add(bpy.context.active_object, textured("arche", "gold_polished", (0.85, 0.75, 0.55), repeat=4, roughness=0.3,
                                        metallic=0.8, metal_scale=0.3), "Arche")
flowers = [material("rose_blanche", (0.95, 0.93, 0.92), 0.6), material("rose_rose", (0.90, 0.45, 0.55), 0.6),
           material("rose_rouge", (0.65, 0.04, 0.08), 0.6), material("feuillage", (0.10, 0.30, 0.12), 0.7)]
for _ in range(70):
    t = math.radians(8 + 164 * random.random())
    r = 2.1 + random.uniform(-0.12, 0.12)
    bpy.ops.mesh.primitive_ico_sphere_add(radius=random.uniform(0.09, 0.2), subdivisions=2,
                                          location=(r * math.cos(t), 1.3 + random.uniform(-0.15, 0.15),
                                                    r * math.sin(t)))
    add(bpy.context.active_object, random.choice(flowers), "Fleur")
warm = material("ampoule", (1, 0.8, 0.5), emission=(1.0, 0.72, 0.4), strength=25)
for _ in range(140):
    bpy.ops.mesh.primitive_ico_sphere_add(radius=0.035, subdivisions=1,
                                          location=(random.uniform(-14, 14), random.uniform(5, 22),
                                                    random.uniform(0.8, 6.5)))
    add(bpy.context.active_object, warm, "Lumiere")

world = bpy.data.worlds.new("nuit")
scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.004, 0.007, 0.02, 1)
bpy.ops.object.light_add(type="AREA", location=(0, -4, 5), rotation=(math.radians(40), 0, 0))
key = bpy.context.active_object
key.data.energy, key.data.size, key.data.color = 900, 5, (1.0, 0.9, 0.8)
bpy.ops.object.light_add(type="SUN", rotation=(math.radians(50), 0, math.radians(-20)))
sun = bpy.context.active_object
sun.data.energy, sun.data.color, sun.data.angle = 1.2, (0.75, 0.82, 1.0), math.radians(8)

# Emplacement des maries : ovale vertical 1,2 x 1,85 m, pieds a l'origine (sa forme
# donne l'ombre au sol d'une silhouette de couple)
bpy.ops.mesh.primitive_circle_add(vertices=48, radius=0.5, fill_type="NGON")
couple = bpy.context.active_object
couple.name = "PHOTO_DEBOUT_MARIES"
for v in couple.data.vertices:                 # cercle du plan XY -> ovale debout (XZ)
    v.co = (v.co.x * 1.2, 0.0, (v.co.y + 0.5) * 1.85)
couple.data.materials.append(material("emplacement_maries", (0.9, 0.9, 0.9)))

# Un chevalet a cote de l'arche avec un cadre : emplacement d'une photo a plat
wood = textured("bois", "wood_oak", (0.35, 0.22, 0.12), roughness=0.6)
easel_at, easel_yaw = (2.9, 0.4, 0.0), math.radians(-25)
for dx, tilt in ((-0.35, 8), (0.35, -8)):
    bpy.ops.mesh.primitive_cube_add(size=1, location=(easel_at[0] + dx * math.cos(easel_yaw),
                                                      easel_at[1] + dx * math.sin(easel_yaw), 0.9))
    leg = bpy.context.active_object
    leg.scale = (0.05, 0.05, 1.8)
    leg.rotation_euler = (0, math.radians(tilt), easel_yaw)
    add(leg, wood, "Chevalet")
bpy.ops.mesh.primitive_cube_add(size=1, location=(easel_at[0], easel_at[1] + 0.03, 1.35))
border = bpy.context.active_object
border.scale = (0.82, 0.04, 1.02)
border.rotation_euler = (0, 0, easel_yaw)
add(border, textured("cadre_dore", "gold_polished", (0.8, 0.62, 0.3), roughness=0.3, metallic=0.9,
                     metal_scale=0.3), "Cadre")
bpy.ops.mesh.primitive_plane_add(size=1, location=(easel_at[0], easel_at[1], 1.35))
frame = bpy.context.active_object
frame.name = "PHOTO_CADRE_PHOTO"
for v in frame.data.vertices:                  # plan XY -> plan debout (XZ), 0,7 x 0,9 m
    v.co = (v.co.x * 0.7, 0.0, v.co.y * 0.9)
frame.rotation_euler = (0, 0, easel_yaw)
frame.data.materials.append(material("emplacement_cadre", (0.1, 0.1, 0.1)))

# Collection du premier plan (vide dans ce modele simple)
front = bpy.data.collections.new("PREMIER_PLAN")
scene.collection.children.link(front)

target = bpy.data.objects.new("VISE", None)
scene.collection.objects.link(target)
target.location = (0, 0, 1.25)
cam_data = bpy.data.cameras.new("DRONE")
cam_data.lens = 35
cam_data.dof.use_dof, cam_data.dof.focus_object, cam_data.dof.aperture_fstop = True, target, 2.0
cam = bpy.data.objects.new("DRONE", cam_data)
scene.collection.objects.link(cam)
cam.location = (0, -4.4, 1.7)
scene.camera = cam
track = cam.constraints.new("TRACK_TO")
track.target, track.track_axis, track.up_axis = target, "TRACK_NEGATIVE_Z", "UP_Y"
face = couple.constraints.new("LOCKED_TRACK")      # l'ombre suit la photo
face.target, face.track_axis, face.lock_axis = cam, "TRACK_NEGATIVE_Y", "LOCK_Z"

scene.view_settings.view_transform = "Standard"
scene.render.engine = "BLENDER_EEVEE"
scene.eevee.use_bloom, scene.eevee.bloom_threshold, scene.eevee.bloom_intensity = True, 1.0, 0.05
bpy.ops.file.pack_all()                     # textures dans le .blend : modele autonome
bpy.ops.wm.save_as_mainfile(filepath=out_blend)
print("MODELE enregistre : %s" % out_blend)
