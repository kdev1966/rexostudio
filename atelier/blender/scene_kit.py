"""Outils communs aux scripts qui construisent les modeles de scenes Rexo Studio
(Blender 3.6 LTS). Ils respectent le contrat de docs/MODELES.md : camera DRONE qui vise
VISE, emplacements PHOTO_DEBOUT_* et PHOTO_CADRE_*, collection PREMIER_PLAN.
"""
import math
import os

import bpy

# Textures PBR faites par TextureCraft ou MaterialCraft (scripts/prepare_textures.py)
TEXTURES = os.environ.get("REXO_TEXTURES_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "textures")


def reset_scene():
    """Scene vide (sans recharger les reglages d'usine : Blender 4.5 plantait ainsi sur l'iMac)."""
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    return bpy.context.scene


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


def emissive(name, color, strength):
    """Lumiere peinte (ampoule, flamme, verre de lanterne) : visible et halo de bloom."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    nodes.clear()
    em = nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (*color, 1)
    em.inputs["Strength"].default_value = strength
    out = nodes.new("ShaderNodeOutputMaterial")
    mat.node_tree.links.new(em.outputs["Emission"], out.inputs["Surface"])
    return mat


def textured(name, texture, color, repeat=1.0, roughness=0.5, metallic=0.0, metal_scale=1.0, tint=None):
    """Materiau aux textures (couleur, metal, rugosite, normale), repetees `repeat` fois ;
    tint multiplie la couleur (un carrelage blanc devient terre cuite ou celadon) ;
    metal_scale attenue la carte de metal (de nuit, un metal pur ne reflete que le ciel
    noir) ; couleur unie si la texture manque."""
    folder = os.path.join(TEXTURES, texture)
    if not os.path.isfile(os.path.join(folder, texture + "_BaseColor.png")):
        return material(name, tint or color, roughness, metallic=metallic)
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
        node.image = bpy.data.images.load(path, check_existing=True)
        if data:
            node.image.colorspace_settings.name = "Non-Color"
        links.new(mapping.outputs["Vector"], node.inputs["Vector"])
        return node

    base = image("BaseColor", False).outputs["Color"]
    if tint:
        mix = nodes.new("ShaderNodeMixRGB")
        mix.blend_type, mix.inputs["Fac"].default_value = "MULTIPLY", 1.0
        mix.inputs["Color2"].default_value = (*tint, 1)
        links.new(base, mix.inputs["Color1"])
        base = mix.outputs["Color"]
    links.new(base, p.inputs["Base Color"])
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


def box(name, size, location, mat, rotation=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location, rotation=rotation)
    obj = bpy.context.active_object
    obj.scale = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return add(obj, mat, name)


def cut(target, cutters):
    """Retire les volumes `cutters` de `target` (booleen applique), puis les supprime."""
    if not cutters:
        return target
    bpy.ops.object.select_all(action="DESELECT")
    for c in cutters:
        c.select_set(True)
    bpy.context.view_layer.objects.active = cutters[0]
    if len(cutters) > 1:
        bpy.ops.object.join()
    tool = bpy.context.active_object
    mod = target.modifiers.new("arches", "BOOLEAN")
    # Les volumes reunis se recoupent (cercle + rectangle d'un arc) : sans « use_self »,
    # le calcul exact rend un objet vide
    mod.operation, mod.object, mod.solver = "DIFFERENCE", tool, "EXACT"
    mod.use_self, mod.use_hole_tolerant = True, True
    bpy.context.view_layer.objects.active = target
    bpy.ops.object.modifier_apply(modifier=mod.name)
    bpy.data.objects.remove(tool, do_unlink=True)
    return target


def standing_placeholder(name, width=1.2, height=1.85, location=(0, 0, 0), material_color=(0.9, 0.9, 0.9)):
    """PHOTO_DEBOUT_<NOM> : ovale debout (plan XZ, face -Y), origine aux pieds ; sa forme
    donne l'ombre au sol de la silhouette."""
    bpy.ops.mesh.primitive_circle_add(vertices=48, radius=0.5, fill_type="NGON", location=location)
    obj = bpy.context.active_object
    obj.name = "PHOTO_DEBOUT_" + name
    for v in obj.data.vertices:                 # cercle du plan XY -> ovale debout (XZ)
        v.co = (v.co.x * width, 0.0, (v.co.y + 0.5) * height)
    obj.data.materials.append(material("emplacement_" + name.lower(), material_color))
    return obj


def framed_placeholder(name, width, height, location, yaw_deg=0.0):
    """PHOTO_CADRE_<NOM> : plan debout (XZ, face -Y), origine au centre, tourne autour de Z."""
    bpy.ops.mesh.primitive_plane_add(size=1, location=location)
    obj = bpy.context.active_object
    obj.name = "PHOTO_CADRE_" + name
    for v in obj.data.vertices:
        v.co = (v.co.x * width, 0.0, v.co.y * height)
    obj.rotation_euler = (0, 0, math.radians(yaw_deg))
    obj.data.materials.append(material("emplacement_cadre_" + name.lower(), (0.1, 0.1, 0.1)))
    return obj


def camera_rig(scene, aim=(0, 0, 1.25), lens=35, face=()):
    """VISE (point vise), camera DRONE (TRACK_TO vers VISE) ; les emplacements debout
    donnes dans `face` restent tournes vers la camera (LOCKED_TRACK)."""
    target = bpy.data.objects.new("VISE", None)
    scene.collection.objects.link(target)
    target.location = aim
    data = bpy.data.cameras.new("DRONE")
    data.lens = lens
    data.dof.use_dof, data.dof.focus_object, data.dof.aperture_fstop = True, target, 2.0
    cam = bpy.data.objects.new("DRONE", data)
    scene.collection.objects.link(cam)
    cam.location = (0, -4.4, 1.7)
    scene.camera = cam
    track = cam.constraints.new("TRACK_TO")
    track.target, track.track_axis, track.up_axis = target, "TRACK_NEGATIVE_Z", "UP_Y"
    for obj in face:
        lock = obj.constraints.new("LOCKED_TRACK")
        lock.target, lock.track_axis, lock.lock_axis = cam, "TRACK_NEGATIVE_Y", "LOCK_Z"
    return cam


def front_collection(scene):
    """Collection PREMIER_PLAN (ce qui passe devant les photos), vide au depart."""
    front = bpy.data.collections.new("PREMIER_PLAN")
    scene.collection.children.link(front)
    return front


def finish(scene, out_blend, bloom=0.05):
    scene.view_settings.view_transform = "Standard"
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.use_bloom, scene.eevee.bloom_threshold, scene.eevee.bloom_intensity = True, 1.0, bloom
    bpy.ops.file.pack_all()                      # textures dans le .blend : modele autonome
    bpy.ops.wm.save_as_mainfile(filepath=out_blend)
    print("MODELE enregistre : %s" % out_blend)
