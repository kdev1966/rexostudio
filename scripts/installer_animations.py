"""Installe dans Rexo Studio une livraison de l'atelier : zip d'animations 3D, ou
dossier d'une animation. Les animations vont dans bibliotheque/animations ; une
animation deja presente est remplacee.

    python3 scripts/installer_animations.py animations_20261117-0100.zip
    python3 scripts/installer_animations.py --liste
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from montagia import animations, config  # noqa: E402


def main(argv):
    if "--liste" in argv or not argv:
        items = animations.catalog()
        print("Bibliothèque : %s" % config.ANIMATIONS_DIR)
        for a in items:
            print("  %-36s %s (%.0f s)" % (a["id"], a["titre"], a["duree"] or 0))
        if not items:
            print("  (vide)")
        return 0 if items or "--liste" in argv else 2
    try:
        for path in argv:
            animations.install(path, log=print)
    except animations.AnimationError as exc:
        print("ERREUR : %s" % exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
