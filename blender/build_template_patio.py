"""Construit le modele de scene « patio arabo-andalou de nuit » (Blender 3.6 LTS) :
cour a arcades en arcs outrepasses sur trois cotes (le quatrieme, ouvert, laisse voler
la camera drone), galeries eclairees de lanternes, sol de tomettes, soubassements de
zellige, fontaine derriere les maries, cypres en pots, guirlandes d'ampoules.

    blender -b --factory-startup --python build_template_patio.py -- patio_nuit.blend

Contrat Rexo Studio : voir docs/MODELES.md (DRONE, VISE, PHOTO_DEBOUT_MARIES,
PHOTO_CADRE_PHOTO, PREMIER_PLAN). Textures : scripts/prepare_textures.py
tiles_ceramic marble plaster clay brass gold_polished wood_oak.
"""
import math
import os
import random
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scene_kit as kit  # noqa: E402

out_blend = sys.argv[sys.argv.index("--") + 1]
random.seed(11)
scene = kit.reset_scene()

# --- Materiaux -----------------------------------------------------------------------
tomettes = kit.textured("tomettes", "tiles_ceramic", (0.62, 0.32, 0.2), repeat=22, roughness=0.6,
                        tint=(0.72, 0.38, 0.24))
zellige = kit.textured("zellige", "tiles_ceramic", (0.25, 0.55, 0.5), repeat=6, roughness=0.15,
                       tint=(0.30, 0.62, 0.55))
marbre = kit.textured("marbre", "marble", (0.9, 0.88, 0.84), repeat=3, roughness=0.15)
marbre_allee = kit.textured("marbre_allee", "marble", (0.9, 0.88, 0.84), repeat=6, roughness=0.12)
platre = kit.textured("platre", "plaster", (0.93, 0.88, 0.80), repeat=3, roughness=0.8,
                      tint=(1.0, 0.93, 0.82))
terre = kit.textured("terre_cuite", "clay", (0.6, 0.32, 0.2), repeat=2, roughness=0.8)
laiton = kit.textured("laiton", "brass", (0.8, 0.6, 0.3), repeat=1, roughness=0.3, metallic=0.9,
                      metal_scale=0.35)
or_cadre = kit.textured("or", "gold_polished", (0.8, 0.62, 0.3), roughness=0.3, metallic=0.9, metal_scale=0.3)
bois = kit.textured("bois", "wood_oak", (0.35, 0.22, 0.12), roughness=0.6)
eau = kit.material("eau", (0.02, 0.12, 0.14), roughness=0.03)
cypres = kit.material("cypres", (0.04, 0.16, 0.07), roughness=0.9)
flamme = kit.emissive("flamme", (1.0, 0.62, 0.28), 22)
ampoule = kit.emissive("ampoule", (1.0, 0.72, 0.4), 30)

# --- Sol et allee de marbre ---------------------------------------------------------
bpy.ops.mesh.primitive_plane_add(size=60)
kit.add(bpy.context.active_object, tomettes, "Sol")
kit.box("Allee", (2.4, 17, 0.02), (0, -5.5, 0.01), marbre_allee)

# --- Arcades : murs perces d'arcs outrepasses (cercle plus large que le passage) ------
WALL_H, WALL_T = 5.5, 0.5
ARC_R, ARC_Z, PASS_W = 1.15, 3.0, 1.8          # rayon et centre de l'arc, largeur du passage


def arcade(name, center, length, along_x, openings):
    """Mur d'arcades ; openings : positions des arcs le long du mur (m)."""
    size = (length, WALL_T, WALL_H) if along_x else (WALL_T, length, WALL_H)
    wall = kit.box(name, size, (center[0], center[1], WALL_H / 2), platre)
    cutters = []
    for pos in openings:
        loc = (pos, center[1]) if along_x else (center[0], pos)
        rot = (math.radians(90), 0, 0) if along_x else (0, math.radians(90), 0)
        bpy.ops.mesh.primitive_cylinder_add(radius=ARC_R, depth=WALL_T * 3, vertices=48,
                                            location=(loc[0], loc[1], ARC_Z), rotation=rot)
        cutters.append(bpy.context.active_object)
        rect = (PASS_W, WALL_T * 3, ARC_Z) if along_x else (WALL_T * 3, PASS_W, ARC_Z)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(loc[0], loc[1], ARC_Z / 2))
        r = bpy.context.active_object
        r.scale = rect
        cutters.append(r)
    kit.cut(wall, cutters)
    # Corniche et colonnettes de marbre de part et d'autre de chaque passage
    proud = 0.12
    if along_x:
        side = -1 if center[1] > 0 else 1                       # face cote cour
        kit.box(name + "_corniche", (length, WALL_T + 2 * proud, 0.25), (center[0], center[1], WALL_H), marbre)
        face = center[1] + side * (WALL_T / 2 + 0.05)
        cols = [(pos + dx, face) for pos in openings for dx in (-PASS_W / 2 - 0.08, PASS_W / 2 + 0.08)]
    else:
        side = -1 if center[0] > 0 else 1
        kit.box(name + "_corniche", (WALL_T + 2 * proud, length, 0.25), (center[0], center[1], WALL_H), marbre)
        face = center[0] + side * (WALL_T / 2 + 0.05)
        cols = [(face, pos + dx) for pos in openings for dx in (-PASS_W / 2 - 0.08, PASS_W / 2 + 0.08)]
    for x, y in cols:
        bpy.ops.mesh.primitive_cylinder_add(radius=0.1, depth=ARC_Z, vertices=16, location=(x, y, ARC_Z / 2))
        kit.add(bpy.context.active_object, marbre, "Colonnette")
        kit.box("Chapiteau", (0.3, 0.3, 0.16), (x, y, ARC_Z + 0.02), marbre)
    return wall


def gallery(name, wall_center, along_x, length, depth, openings):
    """Galerie derriere les arcades : mur du fond (soubassement de zellige), plafond,
    lanternes suspendues dans chaque arc, lumiere chaude."""
    if along_x:
        back = (wall_center[0], wall_center[1] + math.copysign(depth, wall_center[1]))
        kit.box(name + "_fond", (length, 0.4, WALL_H), (back[0], back[1], WALL_H / 2), platre)
        kit.box(name + "_zellige", (length, 0.05, 1.2), (back[0], back[1] - math.copysign(0.22, back[1]), 0.6), zellige)
        kit.box(name + "_plafond", (length, depth, 0.3),
                (wall_center[0], (wall_center[1] + back[1]) / 2, WALL_H), platre)
        light_at = (wall_center[0], (wall_center[1] + back[1]) / 2, 4.2)
        lanterns = [(pos, wall_center[1]) for pos in openings]
    else:
        back = (wall_center[0] + math.copysign(depth, wall_center[0]), wall_center[1])
        kit.box(name + "_fond", (0.4, length, WALL_H), (back[0], back[1], WALL_H / 2), platre)
        kit.box(name + "_zellige", (0.05, length, 1.2), (back[0] - math.copysign(0.22, back[0]), back[1], 0.6), zellige)
        kit.box(name + "_plafond", (depth, length, 0.3),
                ((wall_center[0] + back[0]) / 2, wall_center[1], WALL_H), platre)
        light_at = ((wall_center[0] + back[0]) / 2, wall_center[1], 4.2)
        lanterns = [(wall_center[0], pos) for pos in openings]
    bpy.ops.object.light_add(type="POINT", location=light_at)
    lamp = bpy.context.active_object
    lamp.data.energy, lamp.data.color, lamp.data.shadow_soft_size = 220, (1.0, 0.7, 0.4), 0.8
    for x, y in lanterns:
        z = 3.35
        bpy.ops.mesh.primitive_cylinder_add(radius=0.012, depth=ARC_Z + ARC_R - z - 0.2, vertices=6,
                                            location=(x, y, (z + ARC_Z + ARC_R - 0.2) / 2 + 0.2))
        kit.add(bpy.context.active_object, laiton, "Chainette")
        bpy.ops.mesh.primitive_cylinder_add(radius=0.15, depth=0.36, vertices=8, location=(x, y, z))
        kit.add(bpy.context.active_object, laiton, "Lanterne")
        bpy.ops.mesh.primitive_cylinder_add(radius=0.12, depth=0.26, vertices=8, location=(x, y, z))
        kit.add(bpy.context.active_object, flamme, "Lanterne_verre")


back_openings = [-6.8, -3.4, 0.0, 3.4, 6.8]
side_openings = [0.25, 3.75, 7.25]
arcade("Arcade_fond", (0, 9), 18.5, True, back_openings)
gallery("Galerie_fond", (0, 9), True, 18.5, 2.6, back_openings)
for sx in (-9, 9):
    arcade("Arcade_cote", (sx, 3.75), 10.5, False, side_openings)
    gallery("Galerie_cote", (sx, 3.75), False, 10.5, 2.6, side_openings)

# --- Fontaine octogonale derriere les maries ------------------------------------------
fx, fy = 0.0, 4.6
bpy.ops.mesh.primitive_cylinder_add(radius=1.75, depth=0.55, vertices=8, location=(fx, fy, 0.275))
basin = kit.add(bpy.context.active_object, marbre, "Fontaine")
bpy.ops.mesh.primitive_cylinder_add(radius=1.55, depth=0.6, vertices=8, location=(fx, fy, 0.5))
kit.cut(basin, [bpy.context.active_object])
bpy.ops.mesh.primitive_cylinder_add(radius=1.56, depth=0.02, vertices=8, location=(fx, fy, 0.42))
kit.add(bpy.context.active_object, eau, "Eau")
bpy.ops.mesh.primitive_cylinder_add(radius=0.16, depth=0.95, vertices=12, location=(fx, fy, 0.5))
kit.add(bpy.context.active_object, marbre, "Fontaine_pied")
bpy.ops.mesh.primitive_cylinder_add(radius=0.6, depth=0.14, vertices=12, location=(fx, fy, 1.0))
kit.add(bpy.context.active_object, marbre, "Fontaine_vasque")
bpy.ops.object.light_add(type="POINT", location=(fx, fy, 0.7))
glow = bpy.context.active_object
glow.data.energy, glow.data.color = 120, (0.6, 0.85, 1.0)

# --- Cypres en pots de terre cuite -----------------------------------------------------
for x, y in ((-6.6, 7.4), (6.6, 7.4), (-7.4, 1.6), (7.4, 1.6), (-2.9, 5.2), (2.9, 5.2)):
    bpy.ops.mesh.primitive_cone_add(radius1=0.38, radius2=0.48, depth=0.75, vertices=16, location=(x, y, 0.375))
    kit.add(bpy.context.active_object, terre, "Pot")
    height = random.uniform(2.6, 3.4)
    bpy.ops.mesh.primitive_cone_add(radius1=0.42, radius2=0.05, depth=height, vertices=12,
                                    location=(x, y, 0.7 + height / 2))
    kit.add(bpy.context.active_object, cypres, "Cypres")

# --- Guirlandes d'ampoules en chainettes au-dessus de la cour -------------------------
for gy in (1.4, 4.6, 7.6):
    for i in range(29):
        t = i / 28.0
        x = -8.7 + 17.4 * t
        z = 5.3 - 1.1 * 4 * t * (1 - t)                  # chainette : creux de 1,1 m au milieu
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.055, segments=8, ring_count=6, location=(x, gy, z))
        kit.add(bpy.context.active_object, ampoule, "Ampoule")

# --- Chevalet et cadre dore (emplacement d'une photo a plat) --------------------------
easel_at, yaw = (2.7, 0.6, 0.0), -25
for dx, tilt in ((-0.35, 8), (0.35, -8)):
    a = math.radians(yaw)
    kit.box("Chevalet", (0.05, 0.05, 1.8),
            (easel_at[0] + dx * math.cos(a), easel_at[1] + dx * math.sin(a), 0.9), bois,
            rotation=(0, math.radians(tilt), a))
kit.box("Cadre", (0.82, 0.04, 1.02), (easel_at[0] - 0.03 * math.sin(math.radians(yaw)),
                                      easel_at[1] + 0.03 * math.cos(math.radians(yaw)), 1.35),
        or_cadre, rotation=(0, 0, math.radians(yaw)))
kit.framed_placeholder("PHOTO", 0.7, 0.9, (easel_at[0], easel_at[1], 1.35), yaw)

# --- Maries, camera, lumiere, ciel ---------------------------------------------------
couple = kit.standing_placeholder("MARIES", 1.2, 1.85)
kit.camera_rig(scene, aim=(0, 0, 1.25), lens=35, face=[couple])
kit.front_collection(scene)

bpy.ops.object.light_add(type="AREA", location=(0, -4, 5), rotation=(math.radians(40), 0, 0))
key = bpy.context.active_object
key.data.energy, key.data.size, key.data.color = 700, 4, (1.0, 0.86, 0.68)
bpy.ops.object.light_add(type="SUN", rotation=(math.radians(55), 0, math.radians(-25)))
moon = bpy.context.active_object
moon.data.energy, moon.data.color, moon.data.angle = 0.6, (0.6, 0.72, 1.0), math.radians(6)
world = bpy.data.worlds.new("nuit")
scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.01, 0.015, 0.035, 1)

kit.finish(scene, out_blend, bloom=0.06)
