"""Generation de projets Kdenlive (.kdenlive = XML MLT).

Le principe : l'IA propose un plan de coupe, ce module le convertit en
vrais clips Kdenlive avec leurs timecodes de source, plus une piste de
sous-titres. L'utilisateur ouvre le projet et peut continuer a monter.
"""
from __future__ import annotations

import os
import re
import time
import uuid
from xml.sax.saxutils import escape

from . import config, media, tools

PROFILES = {
    "16:9": {
        "description": "HD 1080p 30 fps",
        "width": 1920, "height": 1080,
        "display_aspect_num": 16, "display_aspect_den": 9,
    },
    "9:16": {
        "description": "HD 1080p vertical 30 fps",
        "width": 1080, "height": 1920,
        "display_aspect_num": 9, "display_aspect_den": 16,
    },
}


def _tc(seconds: float, use_comma: bool = False) -> str:
    """Timecode MLT : HH:MM:SS.mmm (ou ,mmm)."""
    if seconds < 0:
        seconds = 0.0
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    sep = "," if use_comma else "."
    return "%02d:%02d:%02d%s%03d" % (h, m, s, sep, ms)


def _fps(fps: float) -> tuple:
    if not fps or fps <= 0:
        return 30, 1
    if abs(fps - round(fps)) < 0.01:
        return int(round(fps)), 1
    num = int(round(fps * 1001))
    return num, 1001


def build_project(source: str, segments: list, out_path: str,
                  profile: str = "16:9", srt_path: str = "",
                  title: str = "Projet MontageIA",
                  notes: str = "") -> str:
    """Ecrit un projet .kdenlive."""
    info = media.probe(source)
    segments = [s for s in (segments or []) if float(s["end"]) > float(s["start"])]
    if not segments:
        raise RuntimeError("Aucun segment : rien a mettre dans le projet.")

    prof = PROFILES.get(profile, PROFILES["16:9"])
    fps_num, fps_den = _fps(info.get("fps") or 30)
    src_duration = info.get("duration") or max(s["end"] for s in segments)
    project_duration = sum(s["end"] - s["start"] for s in segments)

    lines = []
    add = lines.append
    add('<?xml version="1.0" encoding="utf-8"?>')
    add('<mlt LC_NUMERIC="C" version="7.28.0" title="%s" producer="avformat" root="%s">'
        % (escape(title), escape(os.path.dirname(source))))
    add('  <profile description="%s" width="%d" height="%d" progressive="1" '
        'sample_aspect_num="1" sample_aspect_den="1" display_aspect_num="%d" '
        'display_aspect_den="%d" frame_rate_num="%d" frame_rate_den="%d" colorspace="709"/>'
        % (escape(prof["description"]), prof["width"], prof["height"],
           prof["display_aspect_num"], prof["display_aspect_den"], fps_num, fps_den))

    # ---- Producteurs : un par clip (convention Kdenlive)
    for idx, seg in enumerate(segments):
        pid = "producer%d" % idx
        start = float(seg["start"])
        end = float(seg["end"])
        label = seg.get("reason") or seg.get("id") or "Clip %d" % (idx + 1)
        add('  <producer id="%s" in="%s" out="%s">' % (pid, _tc(start), _tc(end)))
        add('    <property name="length">%s</property>' % _tc(src_duration))
        add('    <property name="eof">pause</property>')
        add('    <property name="resource">%s</property>' % escape(source))
        add('    <property name="mlt_service">avformat-novalidate</property>')
        add('    <property name="seekable">1</property>')
        add('    <property name="audio_index">1</property>')
        add('    <property name="video_index">0</property>')
        add('    <property name="mute_on_pause">0</property>')
        add('    <property name="aspect_ratio">1</property>')
        add('    <property name="shotcut:caption">%s</property>' % escape(label))
        add('    <property name="kdenlive:clipname">%s</property>' % escape(label))
        add('    <property name="kdenlive:id">%s</property>' % uuid.uuid4())
        add('  </producer>')

    # ---- Piste principale (playlist)
    add('  <playlist id="playlist0">')
    add('    <property name="mlt_service">kdenlive</property>')
    add('    <property name="kdenlive:docproperties.creator">MontageIA</property>')
    add('    <property name="kdenlive:docproperties.date">%s</property>'
        % time.strftime("%Y-%m-%d"))
    add('    <property name="kdenlive:docproperties.title">%s</property>' % escape(title))
    if notes:
        add('    <property name="kdenlive:docproperties.keywords">%s</property>' % escape(notes))
    for idx, seg in enumerate(segments):
        add('    <entry producer="producer%d" in="%s" out="%s"/>'
            % (idx, _tc(float(seg["start"])), _tc(float(seg["end"]))))
    add('  </playlist>')

    # ---- Piste de fond (noir) : obligatoire pour que Kdenlive ouvre le projet
    add('  <playlist id="playlist1">')
    add('    <property name="mlt_service">kdenlive</property>')
    add('    <property name="kdenlive:playlistid">2</property>')
    add('    <entry producer="blacktrack" in="%s" out="%s"/>'
        % (_tc(0), _tc(max(project_duration - 0.04, 0.04))))
    add('  </playlist>')

    add('  <producer id="blacktrack" in="%s" out="%s">'
        % (_tc(0), _tc(max(project_duration - 0.04, 0.04))))
    add('    <property name="length">%s</property>' % _tc(src_duration))
    add('    <property name="eof">pause</property>')
    add('    <property name="resource">0x00000000</property>')
    add('    <property name="mlt_service">color</property>')
    add('    <property name="mlt_image_format">rgba</property>')
    add('    <property name="set.test_audio">0</property>')
    add('  </producer>')

    # ---- Tractor
    add('  <tractor id="tractor0" title="%s" global_feed="1" in="%s" out="%s">'
        % (escape(title), _tc(0), _tc(max(project_duration - 0.04, 0.04))))
    add('    <property name="kdenlive:documentid">%s</property>' % uuid.uuid4())
    add('    <property name="kdenlive:projectprofile">%s</property>'
        % escape(prof["description"]))
    add('    <track producer="playlist0"/>')
    add('    <track producer="playlist1"/>')

    # ---- Piste de sous-titres (MLT subtitle_feed)
    if srt_path and os.path.isfile(srt_path):
        add('    <filter id="filter0">')
        add('      <property name="mlt_service">subtitle_feed</property>')
        add('      <property name="resource">%s</property>' % escape(srt_path))
        add('      <property name="feed">1</property>')
        add('      <property name="kdenlive:id">%s</property>' % uuid.uuid4())
        add('    </filter>')

    add('  </tractor>')
    add('</mlt>')

    tools.ensure_parent(out_path)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return out_path


def validate(path: str) -> dict:
    """Verifie que le projet est lisible par MLT (via melt)."""
    melt = config.melt_bin()
    if not melt:
        return {"ok": False, "message": "melt introuvable (Kdenlive non installe ?)"}
    try:
        out = tools.run([melt, "-consumer", "xml", path], timeout=180)
    except tools.CommandError as exc:
        return {"ok": False, "message": (exc.stderr or exc.stdout or "")[-500:]}
    ok = "<mlt" in out
    duration = 0.0
    matches = re.findall(r'out="(\d+):(\d+):(\d+)[.,](\d+)"', out)
    if matches:
        h, mnt, s, ms = matches[-1]
        duration = int(h) * 3600 + int(mnt) * 60 + int(s) + int(ms) / 1000.0
    return {"ok": ok, "duration": duration,
            "message": "Projet valide par MLT" if ok else "MLT n'a pas reconnu le projet"}
