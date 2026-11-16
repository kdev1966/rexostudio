"""Prepare avec TextureCraft les textures des modeles de scenes Blender (une fois par
machine, ou pour ajouter un materiau) dans modeles/textures/<materiau>/.

    python3 scripts/prepare_textures.py                 # materiaux du jardin simple
    python3 scripts/prepare_textures.py marble velvet   # ou ceux donnes
    python3 scripts/prepare_textures.py --liste         # les 93 materiaux de TextureCraft

Deja presentes, les textures sont gardees (--refaire pour les refaire).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from montagia import texturecraft  # noqa: E402

# Materiaux utilises par blender/build_template_jardin.py
JARDIN = ("marble", "gold_polished", "wood_oak", "plaster")


def main(argv):
    redo = "--refaire" in argv
    wanted = [a for a in argv if not a.startswith("--")] or list(JARDIN)
    todo = wanted if redo else [m for m in wanted if not texturecraft.has_textures(m)]
    if not todo and "--liste" not in argv:
        print("Textures deja pretes : %s" % ", ".join(wanted))
        return 0
    client = texturecraft.connect(print)
    try:
        known = texturecraft.materials(client)
        if "--liste" in argv:
            print(" ".join(known))
            return 0
        unknown = [m for m in todo if m not in known]
        if unknown:
            print("Materiaux inconnus de TextureCraft : %s" % ", ".join(unknown))
            return 1
        for material in todo:
            texturecraft.export_material(client, material, log=print)
    finally:
        texturecraft.close(client)
    print("Textures dans %s" % texturecraft.texture_dir("")[:-1])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
