"""PhotoCraft (editeur photo, meme editeur que FilmCraft), pilote sans interface.

L'application livre un moteur sans fenetre, photocraft-cli :
    run      ouvre une image, enchaine des commandes du moteur, enregistre
    batch    applique une liste d'actions a tout un dossier
    serve    session ouverte qui repond a des lignes JSON (stdio ou 127.0.0.1)
    commands le registre des commandes (select.subject, select.object,
             layer.removeBackground, paint.remove, filtres, reglages...)
Chaque commande lancee par `run` imprime une ligne JSON
{"command": id, "result": ...} ; on les relit pour verifier le resultat.

Rexo Studio s'en sert pour la Selection d'objet dans un cadre (detourage de
la robe et de la traine, que Vision ne voit pas) et pour ouvrir un resultat
dans PhotoCraft afin que le studio le retouche a la main.
"""
from __future__ import annotations

import json
import os
import subprocess

from . import config, tools


class PhotoCraftError(RuntimeError):
    pass


def installed() -> bool:
    return os.path.isfile(config.PHOTOCRAFT_CLI) and os.access(config.PHOTOCRAFT_CLI, os.X_OK)


def run(src: str, commands: list, out: str, timeout: float = 300) -> list:
    """Ouvre src, execute les commandes [(id, params), ...] dans l'ordre et
    enregistre le resultat dans out (jamais par-dessus src).
    Retourne le resultat de chaque commande, dans l'ordre."""
    if not installed():
        raise PhotoCraftError("PhotoCraft introuvable (%s)." % config.PHOTOCRAFT_APP)
    if os.path.abspath(out) == os.path.abspath(src):
        raise PhotoCraftError("PhotoCraft n'ecrit jamais par-dessus l'original.")
    cmd = [config.PHOTOCRAFT_CLI, "run", src]
    for command_id, params in commands:
        cmd += ["--cmd", command_id, "--params", json.dumps(params or {})]
    cmd += ["--out", out]
    tools.ensure_parent(out)
    try:
        stdout = tools.run(cmd, timeout=timeout)
    except tools.CommandError as exc:
        raise PhotoCraftError("PhotoCraft : %s" % (exc.stderr.strip()[-300:] or exc.code)) from exc
    except subprocess.TimeoutExpired as exc:
        raise PhotoCraftError("PhotoCraft ne repond pas apres %d s." % timeout) from exc
    results = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            results.append(json.loads(line).get("result"))
        except ValueError:
            continue
    if not os.path.isfile(out):
        raise PhotoCraftError("PhotoCraft n'a pas enregistre le resultat.")
    return results


def object_cutout(src: str, rect: list, out: str) -> list:
    """Selection d'objet dans le cadre rect = [x, y, largeur, hauteur] (pixels
    de src), detouree sur fond transparent dans out (PNG).
    Retourne le cadre de l'objet trouve [x, y, largeur, hauteur]."""
    x, y, w, h = (int(round(v)) for v in rect)
    if w < 8 or h < 8:
        raise PhotoCraftError("Cadre trop petit.")
    results = run(src, [
        ("select.object", {"rect": [x, y, w, h], "mode": "replace"}),
        ("layer.layerMask.revealSelection", {}),
    ], out)
    found = results[0] if results else None
    if not isinstance(found, dict) or not found.get("selected"):
        raise PhotoCraftError("Aucun objet trouvé dans le cadre.")
    return found.get("bounds") or []


def open_in_app(path: str) -> None:
    """Ouvre un fichier dans PhotoCraft (avec son interface), pour retoucher."""
    if not os.path.isdir(config.PHOTOCRAFT_APP):
        raise PhotoCraftError("PhotoCraft introuvable (%s)." % config.PHOTOCRAFT_APP)
    subprocess.Popen(["open", "-a", config.PHOTOCRAFT_APP, path],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


# --------------------------------------------------------------------------
# Session sans interface (photocraft-cli serve, lignes JSON sur stdio)
# --------------------------------------------------------------------------

class Session(object):
    """Une session du moteur : un document ouvert, des commandes, un enregistrement.
    PhotoCraft ne lit que dans read_roots et n'ecrit que dans write_root."""

    def __init__(self, read_roots: list, write_root: str, timeout: float = 300):
        if not installed():
            raise PhotoCraftError("PhotoCraft introuvable (%s)." % config.PHOTOCRAFT_APP)
        cmd = [config.PHOTOCRAFT_CLI, "serve"]
        for root in read_roots:
            cmd += ["--automation-read-root", root]
        cmd += ["--automation-write-root", write_root]
        self.timeout = timeout
        self._id = 0
        self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, text=True, bufsize=1)

    def call(self, method: str, params: dict = None):
        self._id += 1
        request = {"id": self._id, "method": method, "params": params or {}}
        try:
            self._proc.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
            self._proc.stdin.flush()
            line = self._proc.stdout.readline()
        except (OSError, ValueError) as exc:
            raise PhotoCraftError("PhotoCraft s'est arrêté (%s)" % exc) from exc
        if not line:
            raise PhotoCraftError("PhotoCraft s'est arrêté sans répondre")
        reply = json.loads(line)
        if not reply.get("ok"):
            raise PhotoCraftError("PhotoCraft (%s) : %s" % (
                (params or {}).get("command", method), reply.get("error", "erreur inconnue")))
        return reply.get("result")

    def execute(self, command: str, **params):
        return self.call("engine.execute", {"command": command, "params": params})

    def close(self) -> None:
        try:
            self._proc.stdin.close()
            self._proc.wait(timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            self._proc.kill()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


# Comment le calque d'effet est masque dans le PSD
#   keep    : detourage ; calque « personnes » = effect_image (la photo aux couleurs de
#             bord nettoyees) + masque, original cache dessous
#   outside : fond traite (noir et blanc, flou, uni) ; masque = tout sauf les personnes
#   inside  : objet efface ; masque = la zone reconstituee
#   plain   : resultat entier (assistant), sans masque
PSD_MODES = ("keep", "outside", "inside", "plain")


def to_psd(src: str, out_psd: str) -> str:
    """Copie d'une image en PSD (un calque), quand il n'y a pas de masque a garder."""
    tools.ensure_parent(out_psd)
    try:
        tools.run([config.PHOTOCRAFT_CLI, "convert", src, out_psd], timeout=300)
    except tools.CommandError as exc:
        raise PhotoCraftError("PhotoCraft : %s" % (exc.stderr.strip()[-300:] or exc.code)) from exc
    return out_psd


def layered_psd(base: str, effect_image: str, alpha: str, mode: str, layer_name: str,
                out_psd: str, read_roots: list, base_name: str = "Photo originale") -> dict:
    """PSD a calques pour affiner un effet dans PhotoCraft :
    « Photo originale » en dessous, le calque d'effet au-dessus avec un masque
    de calque modifiable tire de alpha (PNG dont la transparence est le masque).
    base : la photo redressee (memes dimensions que effect_image et alpha)."""
    if mode not in PSD_MODES:
        raise PhotoCraftError("Mode de PSD inconnu : %s" % mode)
    tools.ensure_parent(out_psd)
    with Session(read_roots, os.path.dirname(out_psd)) as pc:
        pc.call("doc.open", {"path": base})
        original = pc.call("doc.inspect")["layers"][-1]["id"]
        layer = pc.call("doc.place", {"path": effect_image})["layer"]
        pc.execute("layer.rasterize.smartObject", layer=layer)
        if mode != "plain":
            shape = pc.call("doc.place", {"path": alpha})["layer"]
            pc.execute("select.loadSelection", channel="transparency", layer=shape)
            pc.execute("layer.delete", layer=shape)
            pc.execute("layer.select", layer=layer)
            if mode == "outside":
                pc.execute("select.inverse")
            pc.execute("layer.layerMask.revealSelection", layer=layer)
        pc.execute("layer.setProps", layer=layer, name=layer_name)
        try:
            pc.execute("layer.setProps", layer=original, name=base_name)
        except PhotoCraftError:
            pass                        # arriere-plan verrouille : il garde son nom
        if mode == "keep":
            pc.execute("layer.setProps", layer=original, visible=False)
        layers = pc.call("doc.inspect")["layers"]
        pc.call("doc.save", {"path": out_psd})
    if not os.path.isfile(out_psd):
        raise PhotoCraftError("PhotoCraft n'a pas enregistré le PSD.")
    return {"path": out_psd, "layers": [(item["name"], bool(item.get("hasMask"))) for item in layers]}
