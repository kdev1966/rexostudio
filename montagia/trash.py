"""Mise a la Corbeille (jamais d'effacement definitif).

Passe par l'API systeme de macOS (NSFileManager.trashItemAtURL), celle du
Finder : l'element reste recuperable dans la Corbeille tant qu'elle n'est pas
videe, et aucune autorisation « Automatisation » n'est demandee.
"""
from __future__ import annotations

import os
import subprocess
import sys

# Pont JavaScript -> Objective-C d'osascript. Le resultat (URL dans la
# Corbeille) n'est pas lu : le lire fait planter osascript sur macOS 12.
_SCRIPT = ('ObjC.import("Foundation"); function run(argv) {'
           ' return $.NSFileManager.defaultManager.trashItemAtURLResultingItemURLError('
           '$.NSURL.fileURLWithPath(argv[0]), null, null) ? "ok" : "echec"; }')


class TrashError(RuntimeError):
    """Erreur affichable telle quelle."""


def to_trash(path: str) -> None:
    """Met path (fichier ou dossier) a la Corbeille ; leve TrashError sinon."""
    path = os.path.abspath(path)
    if not os.path.lexists(path):
        raise TrashError("Introuvable : %s" % os.path.basename(path))
    if sys.platform != "darwin":
        raise TrashError("Corbeille disponible sur macOS uniquement")
    try:
        out = subprocess.run(["osascript", "-l", "JavaScript", "-e", _SCRIPT, path],
                             capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        raise TrashError("Corbeille inaccessible : %s" % exc) from None
    if out.stdout.strip() != "ok" or os.path.lexists(path):
        raise TrashError("Impossible de mettre à la Corbeille : %s" % os.path.basename(path))
