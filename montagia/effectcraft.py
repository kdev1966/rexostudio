"""EffectCraft (motion design, meme editeur que PhotoCraft et FilmCraft), pilote en
direct par la chaine de production.

EffectCraft ne fait que du motion design et de la composition : titres (modeles
.ectemplate avec des champs « Title » / « Subtitle »), incrustation sur une video,
detourage video (Object Matte, SAM 2.1) et rendu. Serveur de controle local lance par
`EffectCraft --control <port>` : une requete JSON par ligne sur 127.0.0.1,
{"id", "method": "engine.execute", "params": {"command", "params"}}, une connexion
par requete. Pas de jeton (contrairement a FilmCraft) : seul un programme de la
machine peut le joindre.

Lecons des essais sur l'iMac (16/11/2026, EffectCraft 0.24.1) :
  - toujours une fenetre (pas de mode sans interface) ;
  - app.quit bloque sur « modifications non enregistrees » : enregistrer avant ;
  - les longues taches (rendu, suivi) se lancent sans « wait » et se suivent par
    jobs.list : une attente bloquante peut figer le fil principal ;
  - ne jamais relancer un suivi d'Object Matte deja en cours (EffectCraft se fige).
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import time

from . import config, tools

REQUIRED = ("file.newProject", "file.import", "file.saveAs", "app.quit", "script.run",
            "templates.create", "essential.exportTemplate", "essential.importTemplate",
            "essential.instance", "essential.set", "renderQueue.add", "renderQueue.render",
            "renderQueue.list", "jobs.list", "objectMatte.apply", "objectMatte.status")
DEFAULT_TITLE = "titre_simple"


class EffectCraftError(RuntimeError):
    pass


class Client(object):
    def __init__(self, port: int, host: str = "127.0.0.1", timeout: float = 120.0):
        self.host = host
        self.port = int(port)
        self.timeout = timeout
        self._next_id = 0

    def call(self, method: str, params: dict = None, timeout: float = None):
        self._next_id += 1
        request = {"id": self._next_id, "method": method, "params": params or {}}
        try:
            sock = socket.create_connection((self.host, self.port), timeout=timeout or self.timeout)
        except OSError as exc:
            raise EffectCraftError("EffectCraft injoignable sur le port %d (%s)" % (self.port, exc)) from exc
        try:
            sock.sendall((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = sock.recv(1 << 20)
                if not chunk:
                    break
                buf += chunk
        except OSError as exc:
            raise EffectCraftError("Echange avec EffectCraft interrompu (%s)" % exc) from exc
        finally:
            sock.close()
        try:
            reply = json.loads(buf.decode("utf-8"))
        except ValueError as exc:
            raise EffectCraftError("Réponse illisible d'EffectCraft") from exc
        if not reply.get("ok"):
            raise EffectCraftError("EffectCraft (%s) : %s" % (
                (params or {}).get("command", method), reply.get("error", "erreur inconnue")))
        return reply.get("result")

    def execute(self, command: str, params: dict = None, timeout: float = None):
        return self.call("engine.execute", {"command": command, "params": params or {}}, timeout)

    def script(self, code: str):
        """Script JavaScript facon After Effects (app.project...) ; retourne sa valeur."""
        result = self.execute("script.run", {"code": code}) or {}
        if not result.get("ok", False):
            raise EffectCraftError("Script EffectCraft : %s" % (result.get("error") or "échec"))
        return result.get("result")

    def ping(self) -> bool:
        try:
            self.execute("app.capabilities", timeout=5)
            return True
        except EffectCraftError:
            return False


# --------------------------------------------------------------------------
# Lancement et fermeture
# --------------------------------------------------------------------------

def installed() -> bool:
    return os.path.isfile(config.EFFECTCRAFT_BIN) and os.access(config.EFFECTCRAFT_BIN, os.X_OK)


def _running() -> bool:
    try:
        out = subprocess.run(["pgrep", "-x", "EffectCraft"], capture_output=True, text=True, timeout=5)
        return bool(out.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return False


def connect(log=None, wait: float = 90.0) -> Client:
    """Client vers l'EffectCraft pilote par Rexo Studio (le lance si besoin) ; verifie
    que les commandes utilisees par la chaine existent dans cette version."""
    log = log or (lambda _m: None)
    client = Client(config.EFFECTCRAFT_PORT)
    if not client.ping():
        if not installed():
            raise EffectCraftError("EffectCraft introuvable (%s)." % config.EFFECTCRAFT_APP)
        if _running():
            raise EffectCraftError(
                "EffectCraft est déjà ouvert sans le pilotage de Rexo Studio : enregistrez "
                "votre travail et quittez EffectCraft, Rexo Studio le relancera.")
        log_path = os.path.join(config.CACHE_DIR, "effectcraft.log")
        tools.ensure_parent(log_path)
        log("Lancement d'EffectCraft (pilotage sur le port %d)" % client.port)
        with open(log_path, "ab") as out:
            subprocess.Popen([config.EFFECTCRAFT_BIN, "--control", str(client.port)],
                             stdin=subprocess.DEVNULL, stdout=out, stderr=out,
                             start_new_session=True, close_fds=True)
        deadline = time.time() + wait
        while not client.ping():
            if time.time() > deadline:
                raise EffectCraftError("EffectCraft ne répond pas après %d s (voir %s)." % (wait, log_path))
            time.sleep(0.5)
    missing = missing_commands(client)
    if missing:
        raise EffectCraftError("Cette version d'EffectCraft n'a pas les commandes : %s" % ", ".join(missing))
    return client


def missing_commands(client: Client) -> list:
    known = {c.get("id") for c in client.execute("command.list") or []}
    return [c for c in REQUIRED if c not in known]


def close(client: Client, scratch_dir: str, wait: float = 30.0) -> None:
    """Ferme EffectCraft : le projet de travail est d'abord enregistre (sinon la
    fenetre « modifications non enregistrees » bloque la fermeture), puis efface."""
    path = os.path.join(scratch_dir, ".rexo-effectcraft.ecproj")
    try:
        client.execute("file.saveAs", {"path": path})
        client.execute("app.quit")
    except EffectCraftError:
        return
    deadline = time.time() + wait
    while _running() and time.time() < deadline:
        time.sleep(0.5)
    if os.path.exists(path):
        os.remove(path)


# --------------------------------------------------------------------------
# Taches longues : suivies par jobs.list (jamais d'attente bloquante)
# --------------------------------------------------------------------------

def wait_jobs(client: Client, progress=None, timeout: float = 3600, poll: float = 1.0) -> None:
    deadline = time.time() + timeout
    while True:
        running = (client.execute("jobs.list") or {}).get("running") or []
        if not running:
            return
        if progress:
            fractions = [j.get("fraction") for j in running if j.get("fraction") is not None]
            if fractions:
                progress(min(fractions))
        if time.time() > deadline:
            client.execute("jobs.cancel", {"job": "all"})
            raise EffectCraftError("EffectCraft dépasse %d min : tâche annulée" % (timeout // 60))
        time.sleep(poll)


def render(client: Client, comp: int, out: str, fmt: str = "h264", progress=None, **options) -> str:
    """Rend toute la composition (pas seulement la zone de travail). EffectCraft lit un
    chemin relatif depuis ~/Movies : on ne lui donne que des chemins absolus."""
    out = os.path.abspath(out)
    tools.ensure_parent(out)
    params = dict({"comp": comp, "format": fmt, "output": out, "timeSpan": "comp"}, **options)
    item = client.execute("renderQueue.add", params) or {}
    client.execute("renderQueue.render", {"wait": False})
    wait_jobs(client, progress)
    for entry in (client.execute("renderQueue.list") or {}).get("items", []):
        if entry.get("id") == item.get("id"):
            # Le nom est souvent reserve d'avance (fichier vide) : la taille fait foi
            if entry.get("status") != "Done" or not os.path.isfile(out) or os.path.getsize(out) == 0:
                raise EffectCraftError("Rendu EffectCraft : %s" % entry.get("statusLabel", "échec"))
            return out
    raise EffectCraftError("Rendu EffectCraft introuvable dans la file")


# --------------------------------------------------------------------------
# Titres
# --------------------------------------------------------------------------

def titles() -> list:
    folder = config.TITLES_DIR
    if not os.path.isdir(folder):
        return []
    return [{"id": n[:-11], "name": n[:-11].replace("_", " ").capitalize(), "path": os.path.join(folder, n)}
            for n in sorted(os.listdir(folder)) if n.endswith(".ectemplate") and not n.startswith(".")]


def title_path(title_id: str) -> str:
    for item in titles():
        if item["id"] == title_id:
            return item["path"]
    raise EffectCraftError("Modèle de titre introuvable : %s (dossier %s)" % (title_id, config.TITLES_DIR))


def ensure_default_title(client: Client, log=None) -> str:
    """Premier modele de titre, tire du modele « Title Card » d'EffectCraft sans son
    fond (le titre se pose sur la video). Les vrais titres du studio se font a part."""
    out = os.path.join(config.TITLES_DIR, DEFAULT_TITLE + ".ectemplate")
    if os.path.isfile(out):
        return out
    if log:
        log("EffectCraft : préparation du titre simple")
    tools.ensure_parent(out)
    created = client.execute("templates.create", {"id": "title-card"}) or {}
    comp = created.get("comp")
    # Sans fond, et descendu en bas de l'image : le titre ne couvre pas les maries
    client.script("var c = app.project.itemByID ? app.project.itemByID(%d) : app.project.item(%d);"
                  "for (var i = 1; i <= c.numLayers; i++) { var L = c.layer(i);"
                  " if (L.name == 'Background') { L.enabled = false; continue; }"
                  " var p = L.property('Position'); var v = p.value;"
                  " p.setValue([v[0], v[1] + c.height * 0.31, v[2] || 0]); } 1" % (comp, comp))
    client.execute("essential.exportTemplate", {"comp": comp, "path": out, "name": "Titre simple"})
    return out


_PLACE = """
(function () {
  var c = app.project.itemByID ? app.project.itemByID(%d) : null;
  if (!c) for (var j = 1; j <= app.project.numItems; j++) if (app.project.item(j).id == %d) c = app.project.item(j);
  for (var i = 1; i <= c.numLayers; i++) {
    var L = c.layer(i);
    if (L.id == %d) {
      var d = L.outPoint - L.inPoint;
      L.startTime = %s == 'end' ? Math.max(0, c.duration - d) : Math.min(%s, Math.max(0, c.duration - d));
      return L.startTime + ',' + d;
    }
  }
  return '';
})()
"""


def _set_texts(client: Client, layer: int, title: str, subtitle: str) -> None:
    """Remplit les champs du modele : « Title » / « Subtitle » (ou « Titre » /
    « Sous-titre »), sinon le premier et le second champ texte."""
    instance = client.execute("essential.instance", {"layer": layer}) or {}
    controls = [c for c in instance.get("controls", []) if c.get("type") == "text"]
    names = {(c.get("name") or "").lower(): c for c in controls}
    first = names.get("title") or names.get("titre") or (controls[0] if controls else None)
    second = names.get("subtitle") or names.get("sous-titre") or next(
        (c for c in controls if c is not first), None)
    if first is None:
        raise EffectCraftError("Le modèle de titre n'a aucun champ texte")
    # essential.instance donne l'identifiant du champ sous « control »
    client.execute("essential.set", {"layer": layer, "control": first["control"], "value": title})
    if second is not None:
        client.execute("essential.set", {"layer": layer, "control": second["control"], "value": subtitle or ""})


_ATTACH = """
(function () {
  var comp = null, img = null;
  for (var j = 1; j <= app.project.numItems; j++) {
    var it = app.project.item(j);
    if (it.id == %(comp)d) comp = it;
    if (it.id == %(item)d) img = it;
  }
  var L = comp.layers.add(img);
  L.name = %(label)s;
  L.threeDLayer = true;
  var standing = %(standing)s;
  // Debout : pieds sur l'emplacement, a sa hauteur ; cadre : centree, contenue dans le cadre
  var k = standing ? %(h)f / img.height
                   : Math.min(%(w)f / img.width, %(h)f / img.height);
  L.property("Transform").property("Anchor Point").setValue([img.width / 2, standing ? img.height : img.height / 2, 0]);
  L.property("Transform").property("Scale").setValue([k * 100, k * 100, k * 100]);
  L.parent = comp.layer(%(name)s);
  L.property("Transform").property("Position").setValue([0, 0, 0]);
  L.property("Transform").property("Y Rotation").setValue(0);
  return L.index;
})()
"""

_FRONT_ON_TOP = """
(function () {
  for (var j = 1; j <= app.project.numItems; j++) {
    var it = app.project.item(j);
    if (it.id == %d) { try { it.layer('PREMIER_PLAN').moveToBeginning(); return 1; } catch (e) { return 0; } }
  }
  return 0;
})()
"""


def compose(client: Client, generic_dir: str, info: dict, photos: dict, out: str, title: str = "",
            subtitle: str = "", title_template: str = "", log=None, progress=None) -> dict:
    """Ouvre l'animation generique (composition.jsx de Blender), accroche chaque photo a
    l'emplacement de meme nom, ajoute le titre (facultatif), passe le premier plan
    par-dessus et rend en H.264. photos : {nom d'emplacement: chemin de l'image}."""
    out = os.path.abspath(out)
    scale = float(info.get("pixels_per_meter") or 100)
    client.execute("file.newProject")
    with open(os.path.join(generic_dir, "composition.jsx"), "r", encoding="utf-8") as fh:
        comp = int(client.script(fh.read()))
    placed = []
    for place in info.get("placeholders", []):
        path = photos.get(place["name"])
        if not path:
            continue
        imported = client.execute("file.import", {"paths": [os.path.abspath(path)]}) or {}
        if imported.get("errors") or not imported.get("items"):
            raise EffectCraftError("Import de la photo impossible : %s" % os.path.basename(path))
        client.script(_ATTACH % {
            "comp": comp, "item": imported["items"][0], "name": json.dumps(place["name"]),
            "label": json.dumps("Photo " + place["name"]), "standing": json.dumps(place["kind"] == "debout"),
            "w": place["width_m"] * scale, "h": place["height_m"] * scale})
        placed.append(place["name"])
    if log:
        log("EffectCraft : %d photo(s) placée(s) (%s)" % (len(placed), ", ".join(placed) or "aucune"))
    if title.strip() and title_template:
        if log:
            log("EffectCraft : titre « %s »" % title.strip())
        added = client.execute("essential.importTemplate",
                               {"path": os.path.abspath(title_template), "comp": comp, "addToComp": True}) or {}
        if not added.get("layer"):
            raise EffectCraftError("Le modèle de titre n'a pas été posé")
        _set_texts(client, added["layer"], title.strip(), subtitle.strip())
        client.script(_PLACE % (comp, comp, added["layer"], json.dumps("end"), 0))
    if info.get("premier_plan"):
        client.script(_FRONT_ON_TOP % comp)
    render(client, comp, out, progress=progress)
    return {"path": out, "placed": placed, "duration": info.get("duration")}
