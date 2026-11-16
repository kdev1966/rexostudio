"""Assistant photo a consigne (M5) : le studio ecrit ce qu'il veut, en francais
ou en tunisien ; l'IA locale (Gemma 4 E2B) traduit la consigne en une suite
d'etapes choisies dans une liste fermee d'outils locaux, puis Rexo Studio les
execute en tache de fond.

Le modele ne fait que choisir des outils : un schema JSON (grammaire de
llama.cpp) l'empeche d'en inventer. Tout ce qui demanderait de generer des
images (ajouter un objet, un decor decrit, changer un vetement...) est refuse
avec une explication : irrealiste sur l'iMac 2015.

Une etape qui doit savoir OU agir (« effacer_objet », « cadre_maries ») demande
au studio de tracer un cadre sur la photo avant l'execution.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import time

from . import ai, effects, photocraft
from . import tools as tools_mod

# Outils proposes a l'IA : nom -> (ce qu'il fait, pour l'IA et pour l'interface)
TOOLS = {
    "ameliorer": "corriger la lumière, les couleurs, la balance des blancs et le relief de la"
                 " photo (photo sombre, terne, jaune ou bleue, à embellir)",
    "detourer": "garder seulement les personnes, sur fond transparent",
    "cadre_maries": "le studio entoure les mariés d'un cadre pour garder toute la robe et la traîne"
                    " (à mettre avant detourer, fond_flou, fond_noir_et_blanc ou fond_uni quand la"
                    " consigne parle de la robe, de la traîne, ou de découper/isoler les mariés)",
    "fond_noir_et_blanc": "les personnes restent en couleur, tout le reste passe en noir et blanc",
    "fond_flou": "les personnes restent nettes, l'arrière-plan devient flou",
    "fond_uni": "remplacer l'arrière-plan par une couleur unie (paramètre couleur)",
    "effacer_objet": "faire disparaître UN objet ou UNE personne gênante (paramètre cible) ; le"
                     " studio l'entoure d'un cadre ; une étape par objet",
    "style": "rendu de couleur sur toute la photo (paramètre style)",
    "recadrer": "recadrer pour un format de diffusion (paramètre format)",
}
NEEDS_BOX = {"effacer_objet", "cadre_maries"}
# Effets qui s'appuient sur le detourage des personnes (le cadre des maries les complete)
PERSON_TOOLS = ("detourer", "fond_flou", "fond_noir_et_blanc", "fond_uni", "recadrer")
COLORS = ["blanc", "noir", "gris", "beige", "rose", "bleu"]
STYLES = ["vintage-chaud", "chaud", "froid", "noir-et-blanc", "lumineux", "contraste", "doux"]
FORMATS = ["4:5", "9:16", "1:1", "16:9"]

SCHEMA = {
    "type": "object",
    "properties": {
        "faisable": {"type": "boolean"},
        "etapes": {
            "type": "array",
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "outil": {"type": "string", "enum": list(TOOLS)},
                    "cible": {"type": "string"},
                    "couleur": {"type": "string", "enum": COLORS},
                    "style": {"type": "string", "enum": STYLES},
                    "format": {"type": "string", "enum": FORMATS},
                },
                "required": ["outil"],
            },
        },
        "toutes_les_photos": {"type": "boolean"},
        "message": {"type": "string"},
    },
    "required": ["faisable", "etapes", "toutes_les_photos", "message"],
}

SYSTEM = """Tu es l'assistant photo d'un studio de mariage en Tunisie. Le studio écrit une consigne \
en français ou en tunisien (darija, en lettres latines avec des chiffres comme 3, 7, 9, ou en \
lettres arabes). Tu la traduis en étapes, en choisissant UNIQUEMENT parmi ces outils locaux :

{outils}

Vocabulaire tunisien utile : na7i / ne7i / شيل = enlève, efface ; a3mel / عمل = fais ; \
khalli / خلي = laisse, garde ; l3rousa / العروسة = la mariée ; l3ris / العريس = le marié ; \
fond / خلفية = arrière-plan ; k7al w byadh / أكحل و أبيض = noir et blanc ; \
bel couleur = en couleur ; karhba / كرهبة = voiture ; قص = découpe ; حط = mets ; \
zid / زيد = ajoute ; sma = ciel ; ghroub chams = coucher de soleil ; ward = roses.

Règles :
- Le moins d'étapes possible, dans l'ordre où on les applique.
- effacer_objet : une étape par objet à enlever, avec "cible" = l'objet en quelques mots. \
Enlever ce qui EST DÉJÀ dans la photo (un fil, un panneau, une personne, même dans le ciel) est \
toujours faisable avec effacer_objet.
- fond_uni détoure déjà les personnes : ne mets pas detourer avant.
- style : une seule étape style, la plus précise (« chaud et vintage » = vintage-chaud).
- recadrer : publication Instagram ou Facebook en vertical = 4:5 ; story, reel, TikTok = 9:16 ; \
carré = 1:1 ; YouTube ou horizontal = 16:9.
- toutes_les_photos = true seulement si la consigne vise toute la série, toutes les photos, \
la soirée entière ; sinon false.
- Si la consigne demande d'AJOUTER ou d'INVENTER quelque chose qui n'est pas dans la photo \
(un objet, un décor décrit, un ciel, des pétales, changer un vêtement, une expression, la \
météo), c'est impossible ici : faisable = false, etapes = [], et "message" explique \
pourquoi en une phrase et propose ce qui est possible (par exemple remplacer le fond par une \
couleur, ou par une photo fournie par le studio).
- "message" : une phrase en français pour le studio, qui résume ce qui va être fait.

Exemples :
Consigne : enlève la poubelle à gauche et mets la photo en vertical pour Instagram
{{"faisable": true, "etapes": [{{"outil": "effacer_objet", "cible": "la poubelle à gauche"}}, \
{{"outil": "recadrer", "format": "4:5"}}], "toutes_les_photos": false, \
"message": "J'efface la poubelle, puis je recadre en 4:5 pour Instagram."}}
Consigne : khalli ken l3ris wel 3rousa w a3mel el fond mdhabeb
{{"faisable": true, "etapes": [{{"outil": "fond_flou"}}], "toutes_les_photos": false, \
"message": "Je floute l'arrière-plan, les mariés restent nets."}}
Consigne : mets un rendu froid sur toutes les photos du henné
{{"faisable": true, "etapes": [{{"outil": "style", "style": "froid"}}], "toutes_les_photos": true, \
"message": "J'applique un rendu froid à toutes les photos."}}
Consigne : ajoute un chapeau au marié
{{"faisable": false, "etapes": [], "toutes_les_photos": false, \
"message": "Ajouter un objet qui n'existe pas demande de générer une image, ce que cet ordinateur \
ne peut pas faire ; je peux en revanche effacer, détourer, flouter ou changer le fond."}}"""


class AssistantError(RuntimeError):
    pass


def system_prompt() -> str:
    tools = "\n".join("- %s : %s" % (name, text) for name, text in TOOLS.items())
    return SYSTEM.format(outils=tools)


# « seulement les maries » : invites et personnes derriere quittent le detourage
_COUPLE = re.compile(
    r"(seulement|uniquement|juste|que|ken|kenn|ghir|غير|كان|فقط)\s+(les\s+|le\s+|el\s+|l)?"
    r"(mari[ée]s|couple|3rous|3rousa|l3rous|العروس|العروسة|العرسان)", re.IGNORECASE)


def couple_requested(text: str) -> bool:
    return bool(_COUPLE.search(text or ""))


# « et » qui relie deux objets a effacer (francais, tunisien en lettres latines ou arabes)
_AND = re.compile(r"\s+(?:et|w|ou)\s+|\s+و\s*|،\s*|,\s*")

# Mots qui montrent que la robe ou la traine compte : Vision seul la perd souvent
DRESS_WORDS = ("robe", "traîne", "traine", "voile", "rouba", "roba", "فستان", "روبة", "ذيل",
               # decouper les maries : la robe entiere doit suivre
               "découp", "decoup", "détour", "detour", "isole", "قص")


def normalize(raw: dict, text: str = "") -> dict:
    """Plan propre : outils connus seulement, parametres par defaut, refus coherent.
    Regles fixes qui completent le petit modele : un seul style (le dernier, le plus
    precis), cadre des maries quand la consigne parle de la robe."""
    steps = []
    for step in raw.get("etapes") or []:
        tool = step.get("outil")
        if tool not in TOOLS:
            continue
        clean = {"outil": tool, "cadre": tool in NEEDS_BOX}
        if tool == "effacer_objet":
            # « le fil et le panneau » : un cadre par objet, donc une etape par objet
            target = (step.get("cible") or "l'objet à effacer").strip()[:80]
            parts = [p.strip(" ,") for p in _AND.split(target) if p.strip(" ,")]
            for part in parts[:-1] or []:
                steps.append({"outil": tool, "cadre": True, "cible": part})
            clean["cible"] = parts[-1] if parts else target
        if tool == "fond_uni":
            clean["couleur"] = step.get("couleur") if step.get("couleur") in COLORS else "blanc"
        if tool == "style":
            clean["style"] = step.get("style") if step.get("style") in STYLES else "chaud"
        if tool == "recadrer":
            clean["format"] = step.get("format") if step.get("format") in FORMATS else "4:5"
        steps.append(clean)
    # Le recadrage change la taille de l'image : les cadres traces par le studio ne
    # correspondraient plus. Il passe donc en dernier.
    steps = [s for s in steps if s["outil"] != "recadrer"] + [s for s in steps if s["outil"] == "recadrer"][:1]
    # L'amelioration (lumiere, couleurs, blancs) se fait avant tout le reste, une fois
    if any(s["outil"] == "ameliorer" for s in steps):
        steps = [{"outil": "ameliorer", "cadre": False}] + [s for s in steps if s["outil"] != "ameliorer"]
    styles = [s for s in steps if s["outil"] == "style"]
    if len(styles) > 1:
        keep = "vintage-chaud" if any(s["style"] == "vintage-chaud" for s in styles) else styles[-1]["style"]
        first = steps.index(styles[0])
        steps = [s for s in steps if s["outil"] != "style"]
        steps.insert(first, {"outil": "style", "cadre": False, "style": keep})
    lowered = (text or "").lower()
    # Publication Instagram ou Facebook = 4:5 ; seuls story, reel et TikTok sont en 9:16
    if any(w in lowered for w in ("instagram", "insta", "facebook", "fb")) and not any(
            w in lowered for w in ("story", "stories", "reel", "tiktok", "statut", "status")):
        for s in steps:
            if s["outil"] == "recadrer" and s["format"] in ("9:16", "4:5"):
                s["format"] = "4:5"
    if any(w in lowered for w in DRESS_WORDS):
        steps.insert(0, {"outil": "cadre_maries", "cadre": True})
    # Le cadre des maries ne sert qu'avant un effet sur les personnes : en tete, une fois
    if any(s["outil"] == "cadre_maries" for s in steps):
        steps = [s for s in steps if s["outil"] != "cadre_maries"]
        if any(s["outil"] in PERSON_TOOLS
               for s in steps):
            steps.insert(0, {"outil": "cadre_maries", "cadre": True})
    feasible = bool(raw.get("faisable")) and bool(steps)
    message = (raw.get("message") or "").strip()
    if not feasible:
        steps = []
        if not message:
            message = "Je n'ai pas trouvé d'outil local pour cette consigne."
    every = bool(raw.get("toutes_les_photos")) and feasible
    if every and any(s["cadre"] for s in steps):
        # Un cadre se trace photo par photo : pas d'application a toute la serie
        every = False
        message += " (Effacer ou garder la robe se fait photo par photo : choisissez une photo.)"
    return {"faisable": feasible, "etapes": steps, "toutes_les_photos": every, "message": message,
            "maries_seulement": feasible and couple_requested(text)}


def plan(text: str) -> dict:
    """Plan d'etapes pour une consigne ; leve AssistantError si l'IA est indisponible."""
    text = (text or "").strip()
    if not text:
        raise AssistantError("Écrivez ce que vous voulez faire sur la photo.")
    if len(text) > 500:
        raise AssistantError("Consigne trop longue (500 caractères au plus).")
    start = time.time()
    try:
        raw = ai.chat_json(system_prompt(), "Consigne : " + text, SCHEMA,
                           temperature=0.1, num_predict=400)
    except ai.LLMError as exc:
        raise AssistantError("IA indisponible : %s" % exc) from exc
    if not isinstance(raw, dict):
        raise AssistantError("Réponse illisible de l'IA")
    result = normalize(raw, text)
    result["secondes"] = round(time.time() - start, 1)
    return result


# --------------------------------------------------------------------------
# Execution d'un plan
# --------------------------------------------------------------------------

COLOR_RGB = {"blanc": "255,255,255", "noir": "0,0,0", "gris": "128,128,128",
             "beige": "225,210,185", "rose": "240,200,210", "bleu": "170,195,230"}
# Outil de l'assistant -> effet de rexo-segment
SEGMENT_EFFECT = {"detourer": "cutout", "fond_noir_et_blanc": "bw", "fond_flou": "blur",
                  "fond_uni": "uni", "style": "style", "recadrer": "crop", "ameliorer": "enhance"}


def with_enhance(steps: list) -> list:
    """Case « Améliorer d'abord la photo » : l'amelioration en premiere etape
    (les cadres deja attaches aux etapes ne bougent pas)."""
    if any(s["outil"] == "ameliorer" for s in steps):
        return steps
    return [{"outil": "ameliorer", "cadre": False}] + list(steps)
RESULT_DIR = os.path.join("06_Rendus", "Photos_effets")


def check_plan(steps: list, boxes: dict) -> list:
    """Re-verifie un plan renvoye par l'interface (le studio peut l'avoir modifie) :
    outils connus, un cadre pour chaque etape qui en demande un."""
    clean = normalize({"faisable": True, "etapes": steps or [], "toutes_les_photos": False,
                       "message": "-"})["etapes"]
    if not clean:
        raise AssistantError("Aucune étape à exécuter.")
    for i, step in enumerate(clean):
        if step["cadre"]:
            box = (boxes or {}).get(str(i))
            if not box or len(box) != 4:
                what = step.get("cible") or "les mariés"
                raise AssistantError("Tracez le cadre de l'étape %d (%s)." % (i + 1, what))
            step["box"] = [float(v) for v in box]
    return clean


def _ext_after(tool: str, current_ext: str) -> str:
    if tool == "detourer":
        return ".png"
    if tool in ("style", "recadrer"):
        return current_ext           # garde la transparence d'un detourage
    return ".jpg"


def run_steps(src: str, steps: list, work: str, out_base: str, log=None, couple: bool = False) -> str:
    """Applique les etapes a une photo ; chaque etape part du resultat de la
    precedente. Retourne le chemin du resultat (out_base + extension).
    couple : seulement les maries dans les effets sur les personnes."""
    log = log or (lambda _m: None)
    os.makedirs(work, exist_ok=True)
    key = os.path.basename(out_base)
    current, extra_mask, refined = src, None, None
    made = []
    try:
        for i, step in enumerate(steps):
            tool = step["outil"]
            if tool == "cadre_maries":
                log("Étape %d : PhotoCraft sélectionne les mariés dans le cadre" % (i + 1))
                extra_mask = os.path.join(work, "%s_cadre.png" % key)
                effects.couple_mask(src, step["box"], extra_mask)
                made.append(extra_mask)
                continue
            ext = _ext_after(tool, os.path.splitext(current)[1].lower() or ".jpg")
            out = os.path.join(work, "%s_%d%s" % (key, i, ext))
            if tool == "effacer_objet":
                log("Étape %d : effacer %s" % (i + 1, step.get("cible", "l'objet")))
                effects.erase(current, out, step["box"], work, key)
            else:
                args = [SEGMENT_EFFECT[tool], current, out]
                if tool == "fond_uni":
                    args += ["--color", COLOR_RGB.get(step.get("couleur"), "255,255,255")]
                if tool == "style":
                    args += ["--name", step.get("style", "chaud")]
                if tool == "recadrer":
                    args += ["--ratio", step.get("format", "4:5")]
                if tool in PERSON_TOOLS:
                    # Masque affine par MobileSAM, calcule une fois (meme geometrie
                    # jusqu'au recadrage, toujours en dernier)
                    if refined is None:
                        refined = effects.refined_mask(current, work, key, log=log, couple=couple)
                        if refined:
                            made.append(refined)
                    if refined:
                        args += ["--use-mask", refined]
                if extra_mask and tool in PERSON_TOOLS:
                    args += ["--add-mask", extra_mask]
                log("Étape %d : %s" % (i + 1, TOOLS[tool].split(" (")[0]))
                effects.segment(args)
            made.append(out)
            current = out
        if current == src:
            raise AssistantError("Le plan n'a produit aucune image.")
        final = out_base + os.path.splitext(current)[1]
        tools_mod.ensure_parent(final)
        shutil.move(current, final)
        return final
    finally:
        for path in made:
            if os.path.exists(path):
                os.remove(path)


def preview_path(event_dir: str, rel: str) -> str:
    """Base du resultat d'apercu d'une photo (sans extension), dans le cache."""
    return os.path.join(event_dir, effects.CACHE_DIR,
                        hashlib.sha1(rel.encode("utf-8")).hexdigest()[:16] + "_assistant")


def run_photo(event_dir: str, src: str, steps: list, job=None, couple: bool = False) -> dict:
    """Execute le plan sur une photo ; le resultat reste en apercu (cache)."""
    rel = os.path.relpath(src, event_dir)
    if rel.split(os.sep)[0] != "02_Photos" or not os.path.isfile(src):
        raise AssistantError("Photo invalide : %s" % rel)
    base = preview_path(event_dir, rel)
    for ext in (".jpg", ".png"):
        if os.path.exists(base + ext):
            os.remove(base + ext)
    log = job.add_log if job else None
    start = time.time()
    with _exclusive():
        out = run_steps(src, steps, os.path.join(event_dir, effects.CACHE_DIR, "travail"), base, log,
                        couple)
    return {"path": out, "rel": rel, "secondes": round(time.time() - start, 1)}


def run_all(event_dir: str, photos: list, steps: list, job=None, couple: bool = False) -> dict:
    """Execute le plan (sans cadre) sur toutes les photos : les resultats vont
    directement dans 06_Rendus/Photos_effets/Assistant_<date>/."""
    if any(s["cadre"] for s in steps):
        raise AssistantError("Un cadre se trace photo par photo : impossible sur toute la série.")
    folder = os.path.join(event_dir, RESULT_DIR, time.strftime("Assistant_%Y-%m-%d_%H%M%S"))
    done, failed = 0, []
    with _exclusive():
        for i, src in enumerate(photos):
            name = os.path.splitext(os.path.basename(src))[0]
            if job:
                job.set_progress(i / max(1, len(photos)), "Photo %d/%d : %s" % (i + 1, len(photos), name))
            try:
                run_steps(src, steps, os.path.join(event_dir, effects.CACHE_DIR, "travail"),
                          os.path.join(folder, tools_mod.safe_component(name, "photo")),
                          job.add_log if job else None, couple)
                done += 1
            except (effects.EffectError, AssistantError) as exc:
                failed.append({"photo": os.path.basename(src), "erreur": str(exc)})
                if job:
                    job.add_log("%s : %s" % (os.path.basename(src), exc))
    return {"folder": os.path.relpath(folder, event_dir), "done": done, "failed": failed}


def save(event_dir: str, src: str) -> str:
    """Copie le resultat d'apercu dans 06_Rendus/Photos_effets, sans ecraser."""
    rel = os.path.relpath(src, event_dir)
    base = preview_path(event_dir, rel)
    cached = next((base + e for e in (".jpg", ".png") if os.path.isfile(base + e)), "")
    if not cached:
        raise AssistantError("Résultat introuvable : relancez l'assistant")
    stem = tools_mod.safe_component(os.path.splitext(os.path.basename(src))[0], "photo")
    dest = tools_mod.unique_path(tools_mod.ensure_parent(
        os.path.join(event_dir, RESULT_DIR, stem + "_assistant" + os.path.splitext(cached)[1])))
    shutil.copyfile(cached, dest)
    return os.path.relpath(dest, event_dir)


def _image_size(path: str) -> tuple:
    out = tools_mod.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", path], timeout=60)
    values = dict(line.split(":") for line in out.splitlines()[1:] if ":" in line)
    return int(values["pixelWidth"]), int(values["pixelHeight"])


def export_psd(event_dir: str, src: str) -> str:
    """PSD du resultat de l'assistant pour PhotoCraft : la photo originale et le
    resultat en calques ; le resultat seul s'il a ete recadre (autre taille)."""
    rel = os.path.relpath(src, event_dir)
    base = preview_path(event_dir, rel)
    cached = next((base + e for e in (".jpg", ".png") if os.path.isfile(base + e)), "")
    if not cached:
        raise AssistantError("Résultat introuvable : relancez l'assistant")
    stem = tools_mod.safe_component(os.path.splitext(os.path.basename(src))[0], "photo")
    out = tools_mod.unique_path(tools_mod.ensure_parent(
        os.path.join(event_dir, RESULT_DIR, stem + "_assistant.psd")))
    original = base + "_original.png"
    try:
        info = effects.segment(["orient", src, original])
        if (int(info["width"]), int(info["height"])) == _image_size(cached):
            photocraft.layered_psd(original, cached, "", "plain", "Résultat de l'assistant",
                                   out, [event_dir])
        else:
            photocraft.to_psd(cached, out)
    except (photocraft.PhotoCraftError, tools_mod.CommandError, KeyError, ValueError) as exc:
        if os.path.exists(out) and os.path.getsize(out) == 0:
            os.remove(out)
        raise AssistantError("PSD impossible : %s" % exc) from exc
    finally:
        if os.path.exists(original):
            os.remove(original)
    return out


class _exclusive(object):
    """Un seul calcul d'effets a la fois (meme verrou que les apercus de la galerie)."""

    def __enter__(self):
        if not effects._LOCK.acquire(blocking=False):
            raise AssistantError("Un effet est déjà en cours de calcul : patientez")

    def __exit__(self, *exc):
        effects._LOCK.release()
