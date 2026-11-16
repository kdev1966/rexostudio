"""Derushage d'un evenement (M1) : import des cartes, tri, proxies.

    import_card   copie verifiee d'une carte memoire vers 01_Rushes/Carte_n
                  (videos) et 02_Photos/Carte_n (photos) ; la carte n'est
                  jamais modifiee, chaque copie est relue et comparee (SHA-256)
    analyze       pour chaque rush : metadonnees, heure de tournage, vignette
                  et indices de qualite (luminosite, nettete, tremblement)
    make_proxies  copies legeres 960 px dans 04_Proxies (recreables)

Tout l'etat est dans <evenement>/.rexo/rushes.json, avec des chemins relatifs
au dossier de l'evenement : il peut etre deplace ou archive d'un bloc.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import tempfile
import threading
import time

from . import config, filmcraft, media, tools

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mts", ".m2ts", ".mxf", ".avi", ".mkv", ".3gp"}
PHOTO_EXT = {".jpg", ".jpeg", ".heic", ".heif", ".png", ".tif", ".tiff", ".dng", ".arw",
             ".cr2", ".cr3", ".nef", ".raf", ".orf", ".rw2"}

RUSHES_DIR = "01_Rushes"
PHOTOS_DIR = "02_Photos"
PROXIES_DIR = "04_Proxies"
STATE_FILE = "rushes.json"
THUMBS_DIR = "vignettes"
CHUNK = 8 * 1024 * 1024

# -- seuils de qualite (sur l'image reduite a 480 px, luminance 16-235) ------
# Etalonnes sur des rushes simules et un film de mariage reel (nuit comprise) ;
# a reajuster sur les rushes du studio.
BLACK_LUMA = 24        # cache objectif, camera dans le sac
DARK_LUMA = 48         # plan sous-expose
BRIGHT_LUMA = 195      # plan surexpose
BLUR_LIMIT = 9.0       # indice blurdetect (plus haut = plus flou)
SHAKE_LIMIT = 1.6      # tremblement : ecart median au mouvement lisse, en % de la largeur
SHORT_SECONDS = 2.0    # declenchement par erreur

ISSUES = {
    "noir": "Noir / cache objectif",
    "sombre": "Trop sombre",
    "surexpose": "Surexposé",
    "flou": "Flou",
    "tremble": "Tremblé",
    "court": "Très court",
}

_STATE_LOCK = threading.Lock()


class RushError(RuntimeError):
    """Erreur affichable telle quelle."""


# --------------------------------------------------------------------------
# Etat (.rexo/rushes.json)
# --------------------------------------------------------------------------

def _state_path(event_dir: str) -> str:
    return os.path.join(event_dir, ".rexo", STATE_FILE)


def load_state(event_dir: str) -> dict:
    try:
        with open(_state_path(event_dir), "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    data.setdefault("clips", {})       # chemin relatif -> analyse + choix
    data.setdefault("imports", [])     # historique des cartes importees
    data.setdefault("hashes", {})      # sha256 -> chemin relatif (doublons)
    for clip in data["clips"].values():
        # NaN / Infinity ne sont pas du JSON valide pour le navigateur.
        metrics = clip.get("metrics") or {}
        for key, value in list(metrics.items()):
            if isinstance(value, float) and not math.isfinite(value):
                metrics[key] = None
    return data


def save_state(event_dir: str, state: dict) -> None:
    path = _state_path(event_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "%s.%d.tmp" % (path, threading.get_ident())
    with _STATE_LOCK:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, path)


def _walk(base: str, exts: set) -> list:
    """Fichiers de base (recursif) dont l'extension est dans exts, tries ;
    fichiers et dossiers caches ignores."""
    found = []
    for current, dirs, files in os.walk(base):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(files):
            if not name.startswith(".") and os.path.splitext(name)[1].lower() in exts:
                found.append(os.path.join(current, name))
    return found


# --------------------------------------------------------------------------
# Sources (cartes memoire)
# --------------------------------------------------------------------------

def list_sources(volumes: str = "/Volumes") -> list:
    """Volumes montes contenant des videos ou des photos (cartes, disques)."""
    sources = []
    try:
        entries = sorted(os.scandir(volumes), key=lambda e: e.name)
    except OSError:
        return sources
    root_dev = os.stat("/").st_dev
    for entry in entries:
        try:
            if os.stat(entry.path).st_dev == root_dev:     # disque systeme
                continue
        except OSError:
            continue
        sources.append(describe_source(entry.path))
    return [s for s in sources if s["videos"] or s["photos"]]


def describe_source(path: str) -> dict:
    videos = _walk(path, VIDEO_EXT)
    photos = _walk(path, PHOTO_EXT)
    size = 0
    for f in videos + photos:
        try:
            size += os.path.getsize(f)
        except OSError:
            pass
    return {"path": path, "name": os.path.basename(path.rstrip("/")) or path,
            "videos": len(videos), "photos": len(photos), "size": size}


# --------------------------------------------------------------------------
# Import verifie
# --------------------------------------------------------------------------

def _sha256(path: str, progress=None) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(CHUNK)
            if not block:
                break
            digest.update(block)
            if progress:
                progress(len(block))
    return digest.hexdigest()


def _copy_verified(src: str, dst: str, progress=None) -> str:
    """Copie src -> dst en calculant l'empreinte, relit la copie et compare.
    Le fichier final n'apparait qu'une fois verifie (ecrit en .part puis
    renomme) ; dates d'origine conservees."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    part = dst + ".part"
    digest = hashlib.sha256()
    try:
        with open(src, "rb") as fin, open(part, "wb") as fout:
            while True:
                block = fin.read(CHUNK)
                if not block:
                    break
                digest.update(block)
                fout.write(block)
                if progress:
                    progress(len(block))
            fout.flush()
            os.fsync(fout.fileno())
        expected = digest.hexdigest()
        if _sha256(part) != expected:
            raise RushError("Copie corrompue (empreintes différentes) : %s" % os.path.basename(src))
        shutil.copystat(src, part)
        os.replace(part, dst)
        return expected
    finally:
        if os.path.exists(part):
            os.remove(part)            # notre fichier temporaire, jamais l'original


def next_card_name(event_dir: str) -> str:
    n = 1
    while (os.path.exists(os.path.join(event_dir, RUSHES_DIR, "Carte_%d" % n))
           or os.path.exists(os.path.join(event_dir, PHOTOS_DIR, "Carte_%d" % n))):
        n += 1
    return "Carte_%d" % n


def import_card(event_dir: str, source: str, job=None) -> dict:
    """Copie verifiee des videos et photos de source dans l'evenement.
    Un fichier deja importe (meme nom, taille et date, ou meme empreinte)
    n'est pas recopie : on peut relancer l'import d'une carte sans risque."""
    source = os.path.abspath(source)
    if not os.path.isdir(source):
        raise RushError("Source introuvable : %s" % source)
    if tools.is_within(event_dir, source) or tools.is_within(source, event_dir):
        raise RushError("La source ne peut pas être le dossier de l'événement")
    files = [(f, RUSHES_DIR) for f in _walk(source, VIDEO_EXT)] + \
            [(f, PHOTOS_DIR) for f in _walk(source, PHOTO_EXT)]
    if not files:
        raise RushError("Aucune vidéo ni photo dans %s" % source)

    state = load_state(event_dir)
    known = {(c.get("source_name"), c.get("size"), c.get("source_mtime"))
             for c in state["clips"].values()}
    known |= {tuple(x) for x in state.get("photo_keys", [])}
    todo = []
    for path, kind in files:
        st = os.stat(path)
        key = (os.path.basename(path), st.st_size, int(st.st_mtime))
        if key not in known:
            todo.append((path, kind, st, key))
    total = sum(st.st_size for _p, _k, st, _key in todo)
    free = shutil.disk_usage(event_dir).free
    if total > free * 0.98:
        raise RushError("Place insuffisante : %s à copier, %s libres"
                        % (tools.human_size(total), tools.human_size(free)))

    card = next_card_name(event_dir)
    log = job.add_log if job else (lambda _m: None)
    log("Source : %s — %d fichiers, %d déjà importés" % (source, len(files), len(files) - len(todo)))
    done = [0]
    start = time.time()

    def progress(n):
        done[0] += n
        if job and total:
            speed = done[0] / max(0.001, time.time() - start)
            job.set_progress(done[0] / total * 0.999, "Copie vérifiée : %s / %s (%s/s)" % (
                tools.human_size(done[0]), tools.human_size(total), tools.human_size(speed)))

    copied = skipped = 0
    for path, kind, _st, key in todo:
        rel = os.path.join(kind, card, os.path.relpath(path, source))
        dst = os.path.join(event_dir, rel)
        digest = _copy_verified(path, dst, progress)
        # Le hachage ne coute rien de plus : il sert aux doublons entre cartes.
        if digest in state["hashes"] and os.path.exists(os.path.join(event_dir, state["hashes"][digest])):
            os.remove(dst)              # doublon exact d'un fichier deja importe
            skipped += 1
            log("Doublon ignoré : %s" % os.path.basename(path))
            continue
        state["hashes"][digest] = rel
        if kind == RUSHES_DIR:
            state["clips"][rel] = {"source_name": key[0], "size": key[1], "source_mtime": key[2],
                                   "sha256": digest, "keep": None}
        else:
            state.setdefault("photo_keys", []).append(list(key))
        copied += 1
    for kind in (RUSHES_DIR, PHOTOS_DIR):
        _prune_empty(os.path.join(event_dir, kind, card))   # doublons : dossiers vides
    if not copied:
        log("Rien de nouveau : tous les fichiers de cette source sont déjà importés")
        return {"card": "", "copied": 0, "skipped": len(files), "bytes": 0}
    state["imports"].append({"card": card, "source": source, "at": time.time(),
                             "copied": copied, "skipped": len(files) - len(todo) + skipped})
    save_state(event_dir, state)
    log("%d fichiers copiés et vérifiés dans %s (%s)" % (copied, card, tools.human_size(total)))
    return {"card": card, "copied": copied, "skipped": len(files) - copied, "bytes": total}


def _prune_empty(path: str) -> None:
    """Supprime les dossiers VIDES sous path (et path s'il est vide) ;
    aucun fichier n'est jamais supprime ici."""
    if not os.path.isdir(path):
        return
    for current, _dirs, _files in os.walk(path, topdown=False):
        try:
            os.rmdir(current)          # echoue si le dossier contient quelque chose
        except OSError:
            pass


# --------------------------------------------------------------------------
# Analyse d'un rush
# --------------------------------------------------------------------------

_LM = re.compile(r"\(LM (-?\d+) (-?\d+) ")


def parse_motion(trf_text: str) -> list:
    """Mouvement global (dx, dy) par image : mediane des vecteurs locaux
    d'un fichier vidstabdetect au format texte (fileformat=1)."""
    motions = []
    for line in trf_text.splitlines():
        if not line.startswith("Frame "):
            continue
        vecs = _LM.findall(line)
        if not vecs:
            motions.append((0.0, 0.0))
            continue
        motions.append((statistics.median(int(v[0]) for v in vecs),
                        statistics.median(int(v[1]) for v in vecs)))
    return motions


def shake_index(motions: list, width: int, window: int = 5) -> float:
    """Tremblement en % de la largeur : ecart median entre le mouvement et sa
    moyenne glissante. Un panoramique regulier donne ~0, une camera a la
    main agitee donne une valeur elevee."""
    if len(motions) < window or width <= 0:
        return 0.0
    half = window // 2
    devs = []
    for i in range(half, len(motions) - half):
        around = motions[i - half:i + half + 1]
        mx = sum(m[0] for m in around) / window
        my = sum(m[1] for m in around) / window
        devs.append(((motions[i][0] - mx) ** 2 + (motions[i][1] - my) ** 2) ** 0.5)
    return round(statistics.median(devs) / width * 100, 3)


def parse_frames(meta_text: str) -> list:
    """Valeurs par image d'un fichier metadata=print (signalstats, blurdetect)."""
    frames, current = [], None
    for line in meta_text.splitlines():
        if line.startswith("frame:"):
            current = {}
            frames.append(current)
        elif current is not None and "=" in line:
            key, _, value = line.partition("=")
            try:
                number = float(value)
            except ValueError:
                continue
            if math.isfinite(number):         # blurdetect donne nan sur une image noire
                current[key.rsplit(".", 1)[-1]] = number
    return frames


def measure(path: str, duration: float) -> dict:
    """Une passe ffmpeg sur l'image reduite : luminance et nettete (4 i/s),
    mouvement de camera (12 i/s)."""
    ffmpeg = config.ffmpeg_bin()
    if not ffmpeg:
        raise RushError("ffmpeg introuvable")
    work = tempfile.mkdtemp(prefix="rexo-rush-")
    try:
        graph = ("[0:v]scale=480:-2,split[a][b];"
                 "[a]fps=4,signalstats,blurdetect=block_width=32:block_height=32,"
                 "metadata=print:file=meta.txt[o1];"
                 "[b]fps=12,vidstabdetect=result=motion.trf:fileformat=1:shakiness=5[o2]")
        tools.run([ffmpeg, "-hide_banner", "-v", "error", "-nostdin", "-i", path,
                   "-filter_complex", graph, "-map", "[o1]", "-f", "null", "-",
                   "-map", "[o2]", "-f", "null", "-"],
                  timeout=max(300, int(duration * 4)), cwd=work)
        with open(os.path.join(work, "meta.txt"), encoding="utf-8", errors="replace") as fh:
            frames = parse_frames(fh.read())
        with open(os.path.join(work, "motion.trf"), encoding="utf-8", errors="replace") as fh:
            motions = parse_motion(fh.read())
    finally:
        shutil.rmtree(work, ignore_errors=True)
    lumas = [f["YAVG"] for f in frames if "YAVG" in f]
    blurs = [f["blur"] for f in frames if "blur" in f]
    return {
        "luma": round(statistics.median(lumas), 1) if lumas else None,
        "luma_low": round(sorted(lumas)[len(lumas) // 10], 1) if lumas else None,
        "blur": round(statistics.median(blurs), 2) if blurs else None,
        "shake": shake_index(motions, 480),
        "samples": len(frames),
    }


def classify(metrics: dict, duration: float) -> list:
    """Defauts detectes (cles de ISSUES)."""
    issues = []
    luma = metrics.get("luma")
    if luma is not None:
        if luma < BLACK_LUMA:
            issues.append("noir")
        elif luma < DARK_LUMA:
            issues.append("sombre")
        elif luma > BRIGHT_LUMA:
            issues.append("surexpose")
    if "noir" not in issues:
        if (metrics.get("blur") or 0) > BLUR_LIMIT:
            issues.append("flou")
        if (metrics.get("shake") or 0) > SHAKE_LIMIT:
            issues.append("tremble")
    if 0 < duration < SHORT_SECONDS:
        issues.append("court")
    return issues


def shot_time(info_tags: dict, path: str) -> str:
    """Heure de tournage 'AAAA-MM-JJ HH:MM:SS' : celle ecrite par la camera
    (creation_time, gardee telle quelle : beaucoup de cameras y mettent
    l'heure locale), sinon la date du fichier (conservee a l'import)."""
    raw = (info_tags or {}).get("creation_time") or ""
    m = re.match(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})", raw)
    if m and not raw.startswith("1970"):
        return "%s %s" % m.groups()
    return datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M:%S")


def _tags(path: str) -> dict:
    ffprobe = config.ffprobe_bin()
    try:
        out = tools.run([ffprobe, "-v", "error", "-show_entries", "format_tags",
                         "-of", "json", path], timeout=60)
        return (json.loads(out).get("format") or {}).get("tags") or {}
    except (tools.CommandError, ValueError, OSError):
        return {}


def thumbnail(path: str, out: str, at: float) -> None:
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tools.run([config.ffmpeg_bin(), "-hide_banner", "-v", "error", "-nostdin", "-y",
               "-ss", "%.2f" % max(0.0, at), "-i", path, "-frames:v", "1",
               "-vf", "scale=320:-2", "-q:v", "4", out], timeout=120)


def analyze_clip(event_dir: str, rel: str) -> dict:
    path = os.path.join(event_dir, rel)
    info = media.probe(path)
    duration = info.get("duration") or 0.0
    metrics = measure(path, duration) if info.get("has_video") else {}
    thumb = os.path.join(".rexo", THUMBS_DIR,
                         hashlib.sha1(rel.encode("utf-8")).hexdigest()[:16] + ".jpg")
    try:
        thumbnail(path, os.path.join(event_dir, thumb), min(duration / 2, 3.0))
    except tools.CommandError:
        thumb = ""
    st = os.stat(path)
    return {
        "duration": round(duration, 2), "width": info.get("width"), "height": info.get("height"),
        "fps": round(info.get("fps") or 0, 3), "vcodec": info.get("vcodec"),
        "has_audio": info.get("has_audio"),
        "shot_at": shot_time(_tags(path), path),
        "metrics": metrics, "issues": classify(metrics, duration),
        "thumb": thumb, "analyzed_size": st.st_size, "analyzed_mtime": int(st.st_mtime),
    }


def sync_clips(event_dir: str, state: dict) -> list:
    """Rattache a l'etat les videos de 01_Rushes (copiees a la main comprises)
    et oublie celles qui n'existent plus. Retourne les chemins relatifs."""
    rels = [os.path.relpath(p, event_dir) for p in _walk(os.path.join(event_dir, RUSHES_DIR), VIDEO_EXT)]
    present = set(rels)
    for rel in list(state["clips"]):
        if rel not in present:
            del state["clips"][rel]
    for rel in rels:
        state["clips"].setdefault(rel, {"keep": None})
    return rels


def _needs_analysis(event_dir: str, rel: str, clip: dict) -> bool:
    try:
        st = os.stat(os.path.join(event_dir, rel))
    except OSError:
        return False
    return not ("issues" in clip and clip.get("analyzed_size") == st.st_size
                and clip.get("analyzed_mtime") == int(st.st_mtime))


def analyze(event_dir: str, job=None, force: bool = False) -> dict:
    state = load_state(event_dir)
    rels = sync_clips(event_dir, state)
    todo = [r for r in rels if force or _needs_analysis(event_dir, r, state["clips"][r])]
    log = job.add_log if job else (lambda _m: None)
    log("%d rushes, %d à analyser" % (len(rels), len(todo)))
    for i, rel in enumerate(todo):
        if job:
            job.set_progress(i / max(1, len(todo)), "Analyse %d/%d : %s" % (i + 1, len(todo), os.path.basename(rel)))
        try:
            result = analyze_clip(event_dir, rel)
        except (tools.CommandError, RushError, RuntimeError, ValueError) as exc:
            log("Analyse impossible : %s (%s)" % (rel, exc))
            continue
        clip = state["clips"][rel]
        clip.update(result)
        log("%s : %s" % (os.path.basename(rel), ", ".join(ISSUES[i] for i in result["issues"]) or "bon"))
        save_state(event_dir, state)
    save_state(event_dir, state)
    bad = sum(1 for r in rels if state["clips"][r].get("issues"))
    return {"clips": len(rels), "analyzed": len(todo), "issues": bad}


def is_kept(clip: dict) -> bool:
    """Choix du monteur s'il existe, sinon la proposition : garder un rush sans defaut."""
    if clip.get("keep") is not None:
        return bool(clip["keep"])
    return not clip.get("issues")


def set_keep(event_dir: str, rel: str, keep) -> dict:
    state = load_state(event_dir)
    if rel not in state["clips"]:
        raise RushError("Rush inconnu : %s" % rel)
    state["clips"][rel]["keep"] = None if keep is None else bool(keep)
    save_state(event_dir, state)
    return state["clips"][rel]


def clip_list(event_dir: str) -> list:
    """Rushes dans l'ordre chronologique de tournage, pour l'interface."""
    state = load_state(event_dir)
    rels = sync_clips(event_dir, state)
    items = []
    for rel in rels:
        clip = state["clips"][rel]
        parts = rel.split(os.sep)
        proxy = proxy_rel(rel)
        items.append({
            "rel": rel, "name": os.path.basename(rel),
            "card": parts[1] if len(parts) > 2 else "",
            "path": os.path.join(event_dir, rel),
            "thumb": os.path.join(event_dir, clip["thumb"]) if clip.get("thumb") else "",
            "proxy": os.path.join(event_dir, proxy) if os.path.isfile(os.path.join(event_dir, proxy)) else "",
            "analyzed": "issues" in clip,
            "duration": clip.get("duration"), "width": clip.get("width"), "height": clip.get("height"),
            "fps": clip.get("fps"), "shot_at": clip.get("shot_at", ""),
            "issues": clip.get("issues", []), "metrics": clip.get("metrics", {}),
            "keep": clip.get("keep"), "kept": is_kept(clip),
        })
    items.sort(key=lambda c: (c["shot_at"] or "9999", c["rel"]))
    return items


# --------------------------------------------------------------------------
# Proxies
# --------------------------------------------------------------------------

def proxy_rel(rel: str) -> str:
    inner = os.path.relpath(rel, RUSHES_DIR)
    return os.path.join(PROXIES_DIR, os.path.splitext(inner)[0] + "_proxy.mp4")


def _encoder() -> list:
    ffmpeg = config.ffmpeg_bin()
    try:
        out = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True,
                             text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        out = ""
    if "h264_videotoolbox" in out:
        return ["-c:v", "h264_videotoolbox", "-b:v", "3M"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "26"]


def make_proxies(event_dir: str, job=None, only_kept: bool = False) -> dict:
    """Proxies 960 px (H.264 + AAC) des rushes, deja faits sautes."""
    items = clip_list(event_dir)
    todo = [c for c in items if not c["proxy"] and (c["kept"] or not only_kept)]
    log = job.add_log if job else (lambda _m: None)
    log("%d proxies à créer (%d déjà prêts)" % (len(todo), sum(1 for c in items if c["proxy"])))
    encoder = _encoder()
    made = 0
    for i, clip in enumerate(todo):
        if job:
            job.set_progress(i / max(1, len(todo)), "Proxy %d/%d : %s" % (i + 1, len(todo), clip["name"]))
        out = os.path.join(event_dir, proxy_rel(clip["rel"]))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        part = out + ".part.mp4"
        try:
            tools.run([config.ffmpeg_bin(), "-hide_banner", "-v", "error", "-nostdin", "-y",
                       "-i", clip["path"], "-vf", "scale='min(960,iw)':-2", *encoder,
                       "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", part],
                      timeout=max(600, int((clip["duration"] or 60) * 6)))
            os.replace(part, out)
            made += 1
        except tools.CommandError as exc:
            log("Proxy impossible : %s (%s)" % (clip["name"], exc))
        finally:
            if os.path.exists(part):
                os.remove(part)
    return {"made": made, "total": len(items)}


# --------------------------------------------------------------------------
# Selection vers FilmCraft
# --------------------------------------------------------------------------

def _common(values: list):
    values = [v for v in values if v]
    return max(set(values), key=values.count) if values else None


def send_to_filmcraft(event_dir: str, job, title: str = "") -> dict:
    """Rushes gardes, dans l'ordre de tournage, en sequence FilmCraft
    enregistree dans 05_Montage/ puis ouverte."""
    kept = [c for c in clip_list(event_dir) if c["kept"] and c["analyzed"]]
    if not kept:
        raise RushError("Aucun rush gardé : analysez les rushes et cochez ceux à garder.")
    fps = filmcraft.fps_fraction(_common([c["fps"] for c in kept]) or 25)
    size = _common([(c["width"], c["height"]) for c in kept if c["width"]]) or (1920, 1080)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    out = os.path.join(event_dir, "05_Montage", "Selection_%s.fcproj" % stamp)
    state = load_state(event_dir)
    clips = [{"path": c["path"], "duration": c["duration"], "name": c["name"],
              "has_audio": state["clips"].get(c["rel"], {}).get("has_audio"),
              "note": "%s - %s" % (c["card"], c["shot_at"])} for c in kept]
    job.set_progress(0.1, "Connexion à FilmCraft")
    client = filmcraft.connect(log=job.add_log)
    job.set_progress(0.3, "Construction de la sélection dans FilmCraft (%d rushes)" % len(clips))
    result = filmcraft.build_selection(
        client, clips, out, fps, size, title=title or "Sélection " + os.path.basename(event_dir),
        notes="Sélection Rexo Studio : %d rushes gardés sur %d." % (len(kept), len(clip_list(event_dir))),
        log=job.add_log)
    summary = filmcraft.read_project(result["path"])
    seq = next((s for s in summary["sequences"] if s["clips"] == result["clips"]), None)
    job.add_log("Projet vérifié : %s" % (seq or "séquence introuvable"))
    filmcraft.open_in_app()
    job.set_progress(1.0, "Sélection ouverte dans FilmCraft")
    return {"path": result["path"], "clips": result["clips"], "duration": result["duration"],
            "valid": bool(seq)}
