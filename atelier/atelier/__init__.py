"""Rexo Atelier : fabrication des animations 3D livrees a Rexo Studio (techniciens).

L'atelier vit dans le depot de Rexo Studio (dossier atelier/) et partage avec lui le
contrat des paquets d'animation (commun/, a la racine du depot).
"""
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)
