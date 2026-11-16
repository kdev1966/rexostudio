"""Mode terminal : assistant de montage en ligne de commande.

Usage :
    python3 -m montagia.cli <video> [commande...]
    python3 -m montagia.cli            -> mode interactif
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from montagia import ai, config, edit, media, pipeline, prompts, tools, transcribe  # noqa: E402

RESET = "\033[0m"
ORANGE = "\033[38;5;208m"
GREEN = "\033[32m"
RED = "\033[31m"
DIM = "\033[2m"
BOLD = "\033[1m"


def say(msg=""):
    print(msg)


def step(msg):
    print("%s->%s %s" % (ORANGE, RESET, msg))


def ok(msg):
    print("%sOK%s %s" % (GREEN, RESET, msg))


def warn(msg):
    print("%s!%s %s" % (RED, RESET, msg))


class Assistant(object):
    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        self.name = os.path.basename(self.path)
        self.segments = []
        self.words = []
        self.transcript = ""
        self.candidates = []
        # ATTENTION : l'attribut ne doit pas s'appeler "plan" -> il masquerait
        # la methode plan() et l'appel assistant.plan(...) echouait avec
        # "TypeError: 'list' object is not callable".
        self.cut_plan = []
        self.duration = 0.0
        self.scenes = []
        self.language = ""

    def _build_candidates(self):
        return pipeline.build_candidates(self.segments, duration=self.duration,
                                         scenes=self.scenes, words=self.words)

    # -- etapes ------------------------------------------------------------
    def analyze(self):
        step("Analyse de %s" % self.name)
        info = media.probe(self.path)
        self.duration = info["duration"]
        ok("%dx%d | %.2f fps | %s | %.1f s" % (
            info["width"], info["height"], info["fps"], info["vcodec"], self.duration))
        t0 = time.time()
        silences = media.detect_silence(self.path) if info["has_audio"] else []
        ok("%d silences detectes en %.2f s" % (len(silences), time.time() - t0))
        if info["has_video"]:
            t0 = time.time()
            self.scenes = media.detect_scenes(self.path)
            ok("%d changements de plan en %.2f s" % (len(self.scenes), time.time() - t0))
        if self.segments:
            self.candidates = self._build_candidates()

    def ensure_analyzed(self):
        if not self.duration:
            self.analyze()

    def ensure_transcribed(self):
        if not self.candidates:
            self.transcribe()

    def transcribe(self, model=None, language="auto"):
        step("Transcription (whisper.cpp + VAD)")
        t0 = time.time()
        result = transcribe.transcribe(self.path, model=model, language=language,
                                       workdir=os.path.join(config.CACHE_DIR, "audio"))
        self.segments = result["segments"]
        self.words = result.get("words") or []
        self.language = result.get("language") or ""
        self.transcript = transcribe.transcript_text(self.segments)
        self.candidates = self._build_candidates()
        ok("%d segments en %.1f s (langue: %s)" % (
            len(self.segments), time.time() - t0, result["language"]))
        return result

    def plan(self, instruction="", style="standard"):
        step("Plan de coupe par l'IA (%s)" % config.LLM_MODEL)
        self.ensure_analyzed()
        self.ensure_transcribed()
        t0 = time.time()
        # Meme regle que l'interface : dans ces langues, les coupes de l'IA
        # sont seulement proposees (listees ci-dessous), pas appliquees.
        suggest = self.language in config.SUGGEST_ONLY_LANGUAGES
        result = pipeline.ai_cut_plan(
            _FakeJob(), self.candidates, self.duration, self.transcript,
            instruction, style, suggest_only=suggest)
        self.cut_plan = result["segments"]
        kept = result["kept_duration"]
        ok("%d segments retenus - %.1f s sur %.1f s (%.0f%%) en %.1f s" % (
            len(self.cut_plan), kept, self.duration,
            kept / max(self.duration, 1) * 100,
            time.time() - t0))
        for seg in self.cut_plan:
            say("    %6.1f -> %6.1f  %s" % (seg["start"], seg["end"],
                                           seg.get("reason", "")[:60]))
        if result.get("rationale"):
            say("    %s%s%s" % (DIM, result["rationale"], RESET))
        texts = {c["id"]: c for c in self.candidates}
        for d in result.get("decisions", []):
            if d.get("keep") and (d.get("suggested") or d.get("doubt")):
                cand = texts.get(d["id"], {})
                why = "transcription douteuse" if d.get("doubt") else "suggestion IA : " + d["type"]
                say("    %sa verifier%s %s %6.1f s  %s - %s" % (
                    ORANGE, RESET, d["id"], cand.get("start", 0.0), why,
                    (cand.get("text") or "")[:50]))
        return result

    def render(self, fmt="16:9", encoder=None, quality="standard", subtitles=""):
        step("Rendu %s" % fmt)
        if not self.cut_plan:
            self.plan()
        base = tools.safe_component(self.name.rsplit(".", 1)[0], "montage")
        out = os.path.join(config.EXPORTS_DIR,
                           time.strftime("%Y%m%d-%H%M%S") + "_" + base + "_" +
                           fmt.replace(":", "x") + ".mp4")
        t0 = time.time()
        result = edit.export(self.path, self.cut_plan, out, fmt=fmt, encoder=encoder,
                             quality=quality, subtitles=subtitles,
                             on_log=lambda m: print("   " + DIM + m + RESET))
        ok("%s (%.1f s de calcul)" % (result["path"], time.time() - t0))
        return result

    def filmcraft(self, profile="16:9"):
        step("Projet FilmCraft")
        if not self.cut_plan:
            self.plan()
        self.ensure_transcribed()
        base = tools.safe_component(self.name.rsplit(".", 1)[0], "projet")
        out = os.path.join(config.EXPORTS_DIR, base + ".fcproj")
        result = pipeline.build_filmcraft_job(
            _FakeJob(), self.path, self.cut_plan, out, profile=profile,
            title="%s - MontageIA" % self.name, subtitle_segments=self.segments,
            subtitle_words=self.words)
        (ok if result["valid"] else warn)("%s - %s" % (result["path"], result["message"]))
        return result

    def chat(self, question):
        step("Question : %s" % question)
        self.ensure_analyzed()
        self.ensure_transcribed()
        system = prompts.system_message(self.transcript, prompts.SYS_CHAT)
        user = prompts.build_chat_prompt(question, self.duration)
        for piece in ai.chat_stream(system, user):
            sys.stdout.write(piece)
            sys.stdout.flush()
        print("")

    def subs(self):
        """Ecrit le .srt de la transcription (sur la timeline de la source)."""
        step("Generation du fichier .srt")
        self.ensure_transcribed()
        path = os.path.join(config.EXPORTS_DIR,
                            tools.safe_component(self.name.rsplit(".", 1)[0], "srt") + ".srt")
        transcribe.write_srt(self.segments, path)
        ok("%s (%d lignes)" % (path, len(self.segments)))
        return path

    def pack(self, tone="", extra=""):
        step("Pack de publication")
        self.ensure_analyzed()
        self.ensure_transcribed()
        result = pipeline.ai_pack(_FakeJob(), self.transcript,
                                  self.candidates, self.duration, tone, extra)
        for t in result.get("titles", []):
            say("    - " + t)
        if result.get("description"):
            say("    " + result["description"][:300])
        if result.get("short_description"):
            say("    (court) " + result["short_description"][:200])
        if result.get("hashtags"):
            say("    " + " ".join("#" + h for h in result["hashtags"]))
        return result

    def summary(self):
        step("Resume de la video")
        self.ensure_analyzed()
        self.ensure_transcribed()
        result = pipeline.ai_summary(_FakeJob(), self.transcript, self.duration)
        say("    " + (result.get("summary") or ""))
        for k in result.get("key_points", []):
            say("    * " + k)
        return result


class _FakeJob(object):
    """Job silencieux pour reutiliser le pipeline depuis le CLI."""
    def set_progress(self, *a, **k):
        pass

    def add_log(self, *a, **k):
        pass


def run_command(assistant, cmd: str, parts: list):
    """Execute une commande sur l'assistant courant. Commun au mode
    interactif et au mode « une commande » du script."""
    if cmd in ("analyse", "analyze"):
        assistant.analyze()
    elif cmd == "transcribe":
        assistant.transcribe()
    elif cmd == "plan":
        assistant.plan(" ".join(parts[1:]))
    elif cmd == "render":
        assistant.render(parts[1] if len(parts) > 1 else "16:9")
    elif cmd == "subs":
        assistant.subs()
    elif cmd == "filmcraft":
        assistant.filmcraft(parts[1] if len(parts) > 1 else "16:9")
    elif cmd == "pack":
        assistant.pack()
    elif cmd in ("resume", "summary"):
        assistant.summary()
    elif cmd == "chat":
        if len(parts) < 2:
            raise ValueError("chat attend une question.")
        assistant.chat(" ".join(parts[1:]))
    else:
        warn("Commande inconnue : %s (tapez 'help')" % cmd)


def interactive():
    say("%sMontageIA%s - assistant de montage IA en terminal" % (BOLD + ORANGE, RESET))
    say("%sModele : %s | dossier de travail : %s%s" % (DIM, config.LLM_MODEL, config.WORKSPACE, RESET))
    say("")
    assistant = None
    while True:
        try:
            line = input("%smontage>%s " % (ORANGE, RESET)).strip()
        except (EOFError, KeyboardInterrupt):
            print("")
            return
        if not line:
            continue
        parts = line.split()
        cmd = parts[0].lower()
        if cmd in ("q", "quit", "exit"):
            return
        if cmd in ("?", "h", "help"):
            say("""
    <chemin video>        charge la video (analyse + transcription)
    analyse              detecte les silences
    transcribe           transcrit la video
    plan [consigne]      plan de coupe propose par l'IA
    render [16:9|9:16]   rend le plan de coupe
    subs                 genere le fichier .srt
    filmcraft [16:9|9:16] envoie le montage dans FilmCraft
    pack                 titres, description, hashtags
    resume               resume de la video
    chat <question>      pose une question sur la video
    open <chemin>        ouvre un fichier dans le Finder
""")
            continue
        if cmd == "open" and len(parts) > 1:
            # subprocess avec liste : pas d'interpreteur shell, donc pas
            # d'injection possible via le chemin saisi.
            try:
                subprocess.run(["open", parts[1]], check=False)
                ok("Ouvert : %s" % parts[1])
            except OSError as exc:
                warn("Ouverture impossible : %s" % exc)
            continue
        try:
            if not assistant:
                if not os.path.isfile(parts[0]):
                    warn("Fichier introuvable : %s" % parts[0])
                    continue
                assistant = Assistant(parts[0])
                assistant.analyze()
                assistant.transcribe()
                continue
            run_command(assistant, cmd, parts)
        except Exception as exc:            # noqa: BLE001
            warn("%s" % exc)


def main():
    config.ensure_dirs()
    args = sys.argv[1:]
    if not args:
        interactive()
        return
    path = args[0]
    if not os.path.isfile(path):
        warn("Fichier introuvable : %s" % path)
        sys.exit(1)
    assistant = Assistant(path)
    command = args[1] if len(args) > 1 else "plan"
    parts = args[1:]
    try:
        run_command(assistant, command.lower(), parts)
    except Exception as exc:                # noqa: BLE001
        warn("%s" % exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
