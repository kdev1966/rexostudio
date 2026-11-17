"""Mouvements de camera drone et reglages de qualite, communs aux scripts Blender
(render_template.py, export_generic.py)."""
import math

# Points de passage : (angle depuis l'avant en degres, distance m, hauteur m) ; rotation
# limitee a +-40 degres (la photo des maries reste credible)
PATHS = {
    "approche": [(-8, 14, 7), (0, 4.2, 1.6)],
    "orbite": [(-38, 4.6, 1.7), (38, 4.6, 1.7)],
    "envol": [(0, 3.6, 1.4), (12, 10, 6)],
    "spirale": [(-40, 11, 6), (0, 7, 3.5), (35, 4.2, 1.6)],
    "sequence": [(-10, 15, 8), (0, 4.4, 1.7), (35, 4.4, 1.6), (15, 10, 6)],
}

# Le flou de mise au point d'EEVEE domine sur l'iMac (3 s/image avec, 1,1 s sans en
# brouillon, mesure du 16/11/2026) et ne se voyait pas sur ce decor : il est reserve
# a la qualite « fin ».
QUALITY = {
    "brouillon": {"samples": 8, "ssr": False, "soft": False, "gtao": False, "dof": False},
    "normal": {"samples": 16, "ssr": False, "soft": True, "gtao": True, "dof": False},
    "fin": {"samples": 32, "ssr": True, "soft": True, "gtao": True, "dof": True},
}


def animate_camera(scene, motion: str, seconds: float, fps: int) -> int:
    """Anime la camera de la scene ; retourne le nombre d'images."""
    frames = max(2, int(round(seconds * fps)))
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
    return frames


def apply_quality(scene, quality: str) -> dict:
    q = QUALITY.get(quality, QUALITY["normal"])
    ev = scene.eevee
    ev.taa_render_samples = q["samples"]
    ev.use_ssr, ev.use_soft_shadows, ev.use_gtao = q["ssr"], q["soft"], q["gtao"]
    scene.camera.data.dof.use_dof = q["dof"]
    return q
