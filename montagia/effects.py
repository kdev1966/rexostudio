"""Effets IA sur les photos d'un evenement (M5).

    detourage      les personnes sur fond transparent (PNG)
    noir-et-blanc  les personnes en couleur, le fond en noir et blanc
    fond-flou      les personnes nettes, le fond flou
    effacer        un objet designe par un cadre disparait, le decor est reconstitue

Le detourage vient d'Apple Vision (bin/rexo-segment, voir native/segment.swift) :
fiable sur les personnes, tetes et cheveux compris, mais une grande robe etalee
au sol lui echappe. Si le studio trace un cadre autour des maries, PhotoCraft fait
une Selection d'objet dans ce cadre (robe et traine comprises) et son masque est
ajoute a celui de Vision.

L'effacement tourne dans l'environnement d'effets (Python 3.11 + ONNX, processus
separe, effects_worker/erase.py) : MobileSAM detoure l'objet dans le cadre, MI-GAN
reconstitue le decor. Les photos que OpenCV ne lit pas (HEIC, RAW) sont d'abord
redressees en JPEG par rexo-segment.

Deroulement : un apercu est calcule dans <evenement>/.rexo/effets/ (cache de Rexo
Studio, seul l'apercu de la derniere photo est garde), puis, si le studio le
valide, copie dans 06_Rendus/Photos_effets/. L'original n'est jamais modifie.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading

from . import config, photocraft, rushes, tools

EFFECTS = {
    "detourage": {"label": "Détourage (fond transparent)", "tool": "cutout", "ext": ".png"},
    "noir-et-blanc": {"label": "Couleur sur fond noir et blanc", "tool": "bw", "ext": ".jpg"},
    "fond-flou": {"label": "Fond flou", "tool": "blur", "ext": ".jpg"},
    "effacer": {"label": "Effacer un objet", "tool": "erase", "ext": ".jpg", "needs_box": True},
    "ameliorer": {"label": "Améliorer seulement (lumière, couleurs, blancs, relief)",
                  "tool": "enhance", "ext": ".jpg"},
}
# Formats lus directement par OpenCV dans l'environnement d'effets
OPENCV_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
CACHE_DIR = os.path.join(".rexo", "effets")
# PSD a calques pour affiner dans PhotoCraft : (mode du masque, nom du calque d'effet)
PSD_LAYERS = {
    "detourage": ("keep", "Mariés (masque à affiner)"),
    "noir-et-blanc": ("outside", "Fond noir et blanc (masque à affiner)"),
    "fond-flou": ("outside", "Fond flou (masque à affiner)"),
    "effacer": ("inside", "Zone reconstituée (masque à affiner)"),
    "ameliorer": ("plain", "Photo améliorée"),
}
OUTPUT_DIR = os.path.join("06_Rendus", "Photos_effets")
# Grand cote de la copie donnee a PhotoCraft : son masque ne sert qu'a completer
# celui de Vision, inutile de lui faire traiter 24 Mpx.
PHOTOCRAFT_MAX = 2048

# Un effet a la fois : Vision et PhotoCraft occupent deja tous les coeurs.
_LOCK = threading.Lock()


class EffectError(RuntimeError):
    pass


def installed() -> bool:
    return os.path.isfile(config.SEGMENT_BIN) and os.access(config.SEGMENT_BIN, os.X_OK)


def env_installed() -> bool:
    """Environnement d'effets (ONNX) installe par scripts/install_effects_env.sh."""
    return os.access(config.EFFECTS_PYTHON, os.X_OK) and os.path.isfile(
        os.path.join(config.EFFECTS_WORKER_DIR, "erase.py"))


def available(effect: str) -> bool:
    if EFFECTS[effect]["tool"] == "erase":
        return env_installed()
    return installed()


def catalog() -> list:
    return [{"key": k, "label": v["label"], "needs_box": bool(v.get("needs_box")),
             "available": available(k)} for k, v in EFFECTS.items()]


def _photo_rel(event_dir: str, src: str) -> str:
    rel = os.path.relpath(src, event_dir)
    if (rel.split(os.sep)[0] != rushes.PHOTOS_DIR or not os.path.isfile(src)
            or os.path.splitext(src)[1].lower() not in rushes.PHOTO_EXT):
        raise EffectError("Photo invalide : %s" % rel)
    return rel


def _check(effect: str) -> dict:
    if effect not in EFFECTS:
        raise EffectError("Effet inconnu : %s" % effect)
    return EFFECTS[effect]


def _key(rel: str) -> str:
    return hashlib.sha1(rel.encode("utf-8")).hexdigest()[:16]


def _variant(framed: bool, enhanced: bool, couple: bool = False) -> str:
    return ("_cadre" if framed else "") + ("_ameliore" if enhanced else "") + ("_maries" if couple else "")


def preview_name(rel: str, effect: str, framed: bool, enhanced: bool = False,
                 couple: bool = False) -> str:
    return "%s_%s%s%s" % (_key(rel), effect, _variant(framed, enhanced, couple), EFFECTS[effect]["ext"])


def fg_name(rel: str, framed: bool, enhanced: bool = False, couple: bool = False) -> str:
    """Photo aux couleurs de bord nettoyees (detourage) : calque des maries du PSD."""
    return "%s_detourage%s_couleurs.jpg" % (_key(rel), _variant(framed, enhanced, couple))


def mask_name(rel: str, effect: str, framed: bool, enhanced: bool = False, couple: bool = False) -> str:
    """Masque de l'apercu (PNG, transparence = personnes ou zone effacee)."""
    return "%s_%s%s_masque.png" % (_key(rel), effect, _variant(framed, enhanced, couple))


def check_box(box, width: int, height: int) -> list:
    """Cadre [x, y, largeur, hauteur] en proportions de l'image (0 a 1, tel que
    trace dans l'apercu), converti en pixels et ramene dans l'image."""
    try:
        x, y, w, h = (float(v) for v in box)
    except (TypeError, ValueError):
        raise EffectError("Cadre invalide") from None
    x0, y0 = max(0.0, x) * width, max(0.0, y) * height
    x1, y1 = min(1.0, x + w) * width, min(1.0, y + h) * height
    if x1 - x0 < 16 or y1 - y0 < 16:
        raise EffectError("Cadre trop petit : tracez-le autour des mariés")
    return [round(v, 2) for v in (x0, y0, x1 - x0, y1 - y0)]


def _segment(args: list) -> dict:
    """Lance rexo-segment ; retourne sa reponse JSON."""
    if not installed():
        raise EffectError("Outil d'effets absent : lancez ./scripts/build_native.sh")
    return _run_json([config.SEGMENT_BIN] + args, "échec du détourage")


def _run_json(cmd: list, default_error: str, env=None) -> dict:
    """Lance un outil qui repond par une ligne JSON ; son message d'erreur
    ({"ok": false, "error": ...}) est remonte tel quel."""
    try:
        out = tools.run(cmd, timeout=600, env=env)
    except tools.CommandError as exc:
        message = default_error
        for line in (exc.stdout or "").splitlines():
            try:
                message = json.loads(line).get("error") or message
            except ValueError:
                continue
        raise EffectError("Effet impossible : %s" % message) from exc
    for line in reversed(out.splitlines()):
        try:
            return json.loads(line)
        except ValueError:
            continue
    raise EffectError("Réponse illisible de l'outil d'effets")


def _cleanup_cache(folder: str, keep_prefix: str) -> None:
    """Ne garde que les apercus de la photo en cours (les PNG pleine taille
    pesent des dizaines de Mo)."""
    for name in os.listdir(folder):
        if not name.startswith(keep_prefix):
            try:
                os.remove(os.path.join(folder, name))
            except OSError:
                pass


def _erase(src: str, out: str, box, folder: str, key: str, mask: str = "",
           enhance: bool = False) -> dict:
    """Efface l'objet du cadre (proportions de l'image redressee) ; enhance :
    la photo est d'abord amelioree (lumiere, couleurs, blancs, relief)."""
    if box is None:
        raise EffectError("Tracez un cadre autour de l'objet à effacer")
    if not env_installed():
        raise EffectError("Environnement d'effets absent : lancez ./scripts/install_effects_env.sh")
    try:
        fx, fy, fw, fh = (float(v) for v in box)
    except (TypeError, ValueError):
        raise EffectError("Cadre invalide") from None
    if fw < 0.005 or fh < 0.005:
        raise EffectError("Cadre trop petit : tracez-le autour de l'objet")
    readable = src
    tmp = ""
    if enhance:
        tmp = readable = os.path.join(folder, key + "_tmp_amelioree.jpg")
        _segment(["enhance", src, tmp])
    elif os.path.splitext(src)[1].lower() not in OPENCV_EXT:
        tmp = readable = os.path.join(folder, key + "_tmp_lisible.jpg")
        _segment(["orient", src, tmp])
    try:
        return _run_json([config.EFFECTS_PYTHON, os.path.join(config.EFFECTS_WORKER_DIR, "erase.py"),
                          readable, out, "--box", ",".join("%.6f" % v for v in (fx, fy, fw, fh))]
                         + (["--mask", mask] if mask else []),
                         "échec de l'effacement", env=config.effects_env())
    finally:
        if tmp and os.path.exists(tmp):
            os.remove(tmp)


# Affinage du masque des personnes par MobileSAM (REXO_REFINE=0 pour Vision seul)
REFINE = os.environ.get("REXO_REFINE", "1") != "0"


def refine_available() -> bool:
    return REFINE and env_installed() and os.path.isfile(
        os.path.join(config.EFFECTS_WORKER_DIR, "refine.py"))


def refined_mask(src: str, folder: str, key: str, enhance: bool = False, log=None,
                 couple: bool = False) -> str:
    """Masque des personnes de Vision affine par MobileSAM (effects_worker/refine.py) :
    les trainees de fond disparaissent, les mains restent ; couple : seulement les
    deux personnes principales (les maries). Retourne le chemin d'un PNG gris a donner
    a rexo-segment --use-mask (a effacer par l'appelant), ou "" si l'affinage n'est
    pas possible : l'effet se fait alors avec Vision seul."""
    if not refine_available():
        if couple and log:
            log("« Seulement les mariés » demande l'environnement d'effets : toutes les personnes restent")
        return ""
    vision = os.path.join(folder, key + "_tmp_vision.png")
    out = os.path.join(folder, key + "_tmp_affine.png")
    readable, tmp = src, ""
    try:
        # Masque de Vision sur la photo d'origine (rexo-segment l'y calcule toujours)
        info = _segment(["mask", src, vision, "--persons"])
        if os.path.splitext(src)[1].lower() not in OPENCV_EXT:
            tmp = readable = os.path.join(folder, key + "_tmp_lisible.jpg")
            _segment(["orient", src, tmp])
        boxes = ";".join(",".join(str(v) for v in b) for b in info.get("persons") or [])
        result = _run_json([config.EFFECTS_PYTHON, os.path.join(config.EFFECTS_WORKER_DIR, "refine.py"),
                            readable, vision, out, "--boxes", boxes] + (["--couple"] if couple else []),
                           "échec de l'affinage", env=config.effects_env())
        if log:
            found = result.get("persons", 0) + result.get("extra", 0)
            log("MobileSAM : %d personne(s)%s, %.0f %% du masque de Vision retiré" % (
                found, (", %d gardée(s) : les mariés" % result.get("kept", 0)) if couple else "",
                100 * result.get("removed", 0)))
        return out if os.path.isfile(out) else ""
    except EffectError as exc:
        if log:
            log("Affinage impossible, Vision seul : %s" % exc)
        return ""
    finally:
        for path in (vision, tmp):
            if path and os.path.exists(path):
                os.remove(path)


def couple_mask(src: str, box, out_png: str):
    """Masque complementaire du cadre autour des maries : PhotoCraft fait une
    Selection d'objet dans le cadre (proportions de l'image redressee), sur une
    copie redressee et reduite. Ecrit out_png (a donner a rexo-segment --add-mask)
    et retourne le cadre de l'objet trouve, en pixels de l'image."""
    if not photocraft.installed():
        raise EffectError("PhotoCraft introuvable : le cadre a besoin de PhotoCraft")
    small = os.path.splitext(out_png)[0] + "_copie.jpg"
    try:
        info = _segment(["orient", src, small, "--max", str(PHOTOCRAFT_MAX)])
        width, height = int(info["width"]), int(info["height"])
        rect = check_box(box, width, height)
        scale = min(1.0, PHOTOCRAFT_MAX / float(max(width, height)))
        try:
            found = photocraft.object_cutout(small, [v * scale for v in rect], out_png)
        except photocraft.PhotoCraftError as exc:
            raise EffectError(str(exc)) from exc
        return [round(v / scale) for v in found] if found else None
    finally:
        if os.path.exists(small):
            os.remove(small)


def segment(args: list) -> dict:
    """rexo-segment, pour les autres modules (assistant)."""
    return _segment(args)


def erase(src: str, out: str, box, folder: str, key: str) -> dict:
    """Efface l'objet du cadre, pour les autres modules (assistant)."""
    return _erase(src, out, box, folder, key)


def preview(event_dir: str, src: str, effect: str, box=None, log=None,
            enhance: bool = False, couple: bool = False) -> dict:
    """Calcule l'apercu d'un effet ; box = cadre en proportions de l'image
    redressee : autour des maries (PhotoCraft complete le detourage de Vision)
    ou, pour « effacer », autour de l'objet a faire disparaitre. enhance : la
    photo est d'abord amelioree (lumiere, couleurs, blancs, relief), et Vision
    travaille sur la photo amelioree."""
    spec = _check(effect)
    rel = _photo_rel(event_dir, src)
    if spec["tool"] == "enhance":
        box, enhance = None, False          # l'effet est l'amelioration elle-meme
    if spec["tool"] in ("enhance", "erase") or not refine_available():
        couple = False                      # sans detourage affine, l'option ne s'applique pas
    if not _LOCK.acquire(blocking=False):
        raise EffectError("Un effet est déjà en cours de calcul : patientez")
    try:
        folder = os.path.join(event_dir, CACHE_DIR)
        os.makedirs(folder, exist_ok=True)
        _cleanup_cache(folder, _key(rel) + "_")
        framed = box is not None
        out = os.path.join(folder, preview_name(rel, effect, framed, enhance, couple))
        alpha = os.path.join(folder, mask_name(rel, effect, framed, enhance, couple))
        common = {"effect": effect, "framed": framed, "enhanced": enhance, "couple": couple, "path": out}
        if spec["tool"] == "erase":
            result = _erase(src, out, box, folder, _key(rel), alpha, enhance)
            return dict(common, framed=True, width=result.get("width"),
                        height=result.get("height"), coverage=result.get("coverage", 0),
                        ms=result.get("ms", 0), score=result.get("score"), object_bounds=None)
        if spec["tool"] == "enhance":
            result = _segment(["enhance", src, out])
            return dict(common, width=result.get("width"), height=result.get("height"),
                        coverage=1, ms=result.get("ms", 0), object_bounds=None,
                        white_balance=result.get("white_balance"))
        args = [spec["tool"], src, out, "--save-alpha", alpha]
        if enhance:
            args.append("--enhance")
        refined = refined_mask(src, folder, _key(rel), enhance, log, couple)
        if refined:
            args += ["--use-mask", refined]
            common["refined"] = True
        if effect == "detourage":
            args += ["--save-fg", os.path.join(folder, fg_name(rel, framed, enhance, couple))]
        bounds = None
        try:
            if box is not None:
                mask = os.path.join(folder, _key(rel) + "_tmp_objet.png")
                try:
                    if log:
                        log("PhotoCraft : sélection d'objet dans le cadre")
                    bounds = couple_mask(src, box, mask)
                    if log:
                        log("Vision : détourage des personnes")
                    result = _segment(args + ["--add-mask", mask])
                finally:
                    if os.path.exists(mask):
                        os.remove(mask)
            else:
                result = _segment(args)
        finally:
            if refined and os.path.exists(refined):
                os.remove(refined)
        return dict(common, width=result.get("width"), height=result.get("height"),
                    coverage=result.get("coverage", 0), ms=result.get("ms", 0),
                    object_bounds=bounds, white_balance=result.get("white_balance"))
    finally:
        _LOCK.release()


def save(event_dir: str, src: str, effect: str, framed: bool, enhanced: bool = False,
         couple: bool = False) -> str:
    """Copie l'apercu valide dans 06_Rendus/Photos_effets ; retourne son chemin
    relatif a l'evenement. Un nom deja pris n'est jamais ecrase."""
    _check(effect)
    rel = _photo_rel(event_dir, src)
    cached = os.path.join(event_dir, CACHE_DIR, preview_name(rel, effect, framed, enhanced, couple))
    if not os.path.isfile(cached):
        raise EffectError("Aperçu introuvable : recalculez l'effet")
    stem = tools.safe_component(os.path.splitext(os.path.basename(src))[0], "photo")
    name = "%s_%s%s" % (stem, effect, EFFECTS[effect]["ext"])
    dest = tools.unique_path(tools.ensure_parent(os.path.join(event_dir, OUTPUT_DIR, name)))
    shutil.copyfile(cached, dest)
    return os.path.relpath(dest, event_dir)


def export_psd(event_dir: str, src: str, effect: str, framed: bool, log=None,
               enhanced: bool = False, couple: bool = False) -> str:
    """PSD a calques de l'apercu valide, pour l'affiner dans PhotoCraft : la photo
    (amelioree si l'effet l'a ete, pour que tout concorde), et le calque d'effet avec
    un masque de calque modifiable. Enregistre dans 06_Rendus/Photos_effets (jamais
    par-dessus un fichier) ; retourne son chemin."""
    _check(effect)
    rel = _photo_rel(event_dir, src)
    folder = os.path.join(event_dir, CACHE_DIR)
    cached = os.path.join(folder, preview_name(rel, effect, framed, enhanced, couple))
    alpha = os.path.join(folder, mask_name(rel, effect, framed, enhanced, couple))
    mode, layer_name = PSD_LAYERS[effect]
    if not (os.path.isfile(cached) and (mode == "plain" or os.path.isfile(alpha))):
        raise EffectError("Aperçu introuvable : recalculez l'effet")
    if not photocraft.installed():
        raise EffectError("PhotoCraft introuvable")
    stem = tools.safe_component(os.path.splitext(os.path.basename(src))[0], "photo")
    out = tools.unique_path(tools.ensure_parent(
        os.path.join(event_dir, OUTPUT_DIR, "%s_%s.psd" % (stem, effect))))
    # Photo redressee sans perte : memes dimensions que l'apercu et le masque
    base = os.path.join(folder, _key(rel) + "_base.png")
    try:
        _segment(["orient", src, base] + (["--enhance"] if enhanced else []))
        layer_source = cached
        if mode == "keep":
            # Calque des maries : la photo aux couleurs de bord nettoyees (sinon la photo)
            fg = os.path.join(folder, fg_name(rel, framed, enhanced, couple))
            layer_source = fg if os.path.isfile(fg) else base
        photocraft.layered_psd(base, layer_source, alpha, mode, layer_name, out, [event_dir],
                               base_name="Photo améliorée" if enhanced else "Photo originale")
    except photocraft.PhotoCraftError as exc:
        if os.path.exists(out) and os.path.getsize(out) == 0:
            os.remove(out)
        raise EffectError(str(exc)) from exc
    finally:
        if os.path.exists(base):
            os.remove(base)
    return out
