"""Rexo Atelier, en ligne de commande (techniciens).

    python3 -m atelier liste
    python3 -m atelier textures marble velvet [--refaire] | --liste
    python3 -m atelier materialcraft paquet.mcraft nom [graphe] [cle=valeur...]
    python3 -m atelier scene patio                       # scenes/patio.blend depuis son script
    python3 -m atelier animation patio sequence 9 normal [--titre "Patio de nuit"]
    python3 -m atelier livrer [id...]                    # zip a installer dans Rexo Studio
"""
import sys

from . import animation, config, materialcraft, texturecraft


def _textures(args):
    if "--liste" in args:
        client = texturecraft.connect(print)
        try:
            print(" ".join(texturecraft.materials(client)))
        finally:
            texturecraft.close(client)
        return 0
    wanted = [a for a in args if not a.startswith("--")]
    todo = wanted if "--refaire" in args else [m for m in wanted if not texturecraft.has_textures(m)]
    if not todo:
        print("Textures déjà prêtes : %s" % (", ".join(wanted) or "rien demandé"))
        return 0
    client = texturecraft.connect(print)
    try:
        unknown = [m for m in todo if m not in texturecraft.materials(client)]
        if unknown:
            print("Matériaux inconnus de TextureCraft : %s" % ", ".join(unknown))
            return 1
        for material in todo:
            texturecraft.export_material(client, material, log=print)
    finally:
        texturecraft.close(client)
    print("Textures dans %s" % config.TEXTURES_DIR)
    return 0


def _materialcraft(args):
    if len(args) < 2:
        print(__doc__)
        return 2
    package, name = args[0], args[1]
    graph = next((a for a in args[2:] if "=" not in a), None)
    values = dict(a.split("=", 1) for a in args[2:] if "=" in a)
    client = materialcraft.connect(print)
    try:
        materialcraft.export_material(client, package, name, values=values, graph=graph, log=print)
    finally:
        materialcraft.close(client)
    return 0


def _liste(_args):
    print("Scripts de décors : %s" % (", ".join(animation.builders()) or "aucun"))
    print("Décors construits : %s" % (", ".join(animation.scenes()) or "aucun"))
    print("Paquets prêts à livrer :")
    for info in animation.packages():
        print("  %-40s %s (%.0f s, %s)" % (info["id"], info["titre"], info["duree"], info["qualite"]))
    return 0


def _animation(args):
    title = ""
    if "--titre" in args:
        i = args.index("--titre")
        title = args[i + 1] if i + 1 < len(args) else ""
        args = args[:i] + args[i + 2:]
    if not args:
        print(__doc__)
        return 2
    scene = args[0]
    motion = args[1] if len(args) > 1 else "sequence"
    seconds = float(args[2]) if len(args) > 2 else 9.0
    quality = args[3] if len(args) > 3 else "normal"
    last = [0]

    def progress(f):
        if f - last[0] >= 0.1 or f >= 1:
            last[0] = f
            print("  %3.0f %%" % (100 * f), flush=True)

    animation.render(scene, motion, seconds, quality, title=title, progress=progress)
    return 0


COMMANDS = {
    "liste": _liste,
    "textures": _textures,
    "materialcraft": _materialcraft,
    "scene": lambda a: (animation.build_scene(a[0]), 0)[1] if a else (print(__doc__), 2)[1],
    "animation": _animation,
    "livrer": lambda a: (animation.deliver(a or None), 0)[1],
}


def main(argv):
    if not argv or argv[0] not in COMMANDS:
        print(__doc__)
        return 2
    try:
        return COMMANDS[argv[0]](argv[1:])
    except (animation.AnimationError, texturecraft.TextureCraftError) as exc:
        print("ERREUR : %s" % exc)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
