"""Mode terminal : assistant de montage en ligne de commande.

Usage :
    python3 -m montagia.cli <video> [commande...]
    python3 -m montagia.cli            -> mode interactif
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from montagia import ai, config, edit, kdenlive, media, pipeline, prompts, tools, transcribe  # noqa: E402

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
        self.transcript = ""
        self.candidates = []
        self.plan = []
        self.duration = 0.0

    # -- etapes ------------------------------------------------------------
    def analyze(self):
        step("Analyse de %s" % self.name)
        info = media.probe(self.path)
        self.duration = info["duration"]
        ok("%dx%d | %.2f fps | %s | %.1f s" % (
            info["width"], info["height"], info["fps"], info["vcodec"], self.duration))
        t0 = time.time()
        silences = media.detect_silence(self.path)
        ok("%d silences detectes en %.2f s" % (len(silences), time.time() - t0))

    def transcribe(self, model=None, language="auto"):
        step("Transcription (whisper.cpp + VAD)")
        t0 = time.time()
        result = transcribe.transcribe(self.path, model=model, language=language,
                                       workdir=os.path.join(config.CACHE_DIR, "audio"))
        self.segments = result["segments"]
        self.transcript = transcribe.transcript_text(self.segments)
        self.candidates = pipeline.build_candidates(self.segments)
        ok("%d segments en %.1f s (langue: %s)" % (
            len(self.segments), time.time() - t0, result["language"]))
        return result

    def plan(self, instruction="", style="standard"):
        step("Plan de coupe par l'IA (%s)" % config.LLM_MODEL)
        if not self.candidates:
            self.transcribe()
        t0 = time.time()
        result = pipeline.ai_cut_plan(
            _FakeJob(), self.candidates, self.duration, self.transcript,
            instruction, style)
        self.plan = result["segments"]
        kept = result["kept_duration"]
        ok("%d segments retenus - %.1f s sur %.1f s (%.0f%%) en %.1f s" % (
            len(self.plan), kept, self.duration, kept / max(self.duration, 1) * 100,
            time.time() - t0))
        for seg in self.plan:
            say("    %6.1f -> %6.1f  %s" % (seg["start"], seg["end"],
                                           seg.get("reason", "")[:60]))
        if result.get("rationale"):
            say("    %s%s%s" % (DIM, result["rationale"][:220], RESET))
        return result

    def render(self, fmt="16:9", encoder=None, quality="standard", subtitles=""):
        step("Rendu %s" % fmt)
        if not self.plan:
            self.plan()
        base = tools.safe_component(self.name.rsplit(".", 1)[0], "montage")
        out = os.path.join(config.EXPORTS_DIR,
                           time.strftime("%Y%m%d-%H%M%S") + "_" + base + "_" +
                           fmt.replace(":", "x") + ".mp4")
        t0 = time.time()
        result = edit.export(self.path, self.plan, out, fmt=fmt, encoder=encoder,
                             quality=quality, subtitles=subtitles,
                             on_log=lambda m: print("   " + DIM + m + RESET))
        ok("%s (%.1f s de calcul)" % (result["path"], time.time() - t0))
        return result

    def kdenlive(self, profile="16:9"):
        step("Projet Kdenlive")
        if not self.plan:
            self.plan()
        base = tools.safe_component(self.name.rsplit(".", 1)[0], "projet")
        out = os.path.join(config.EXPORTS_DIR, base + ".kdenlive")
        kdenlive.build_project(self.path, self.plan, out, profile=profile,
                               title=self.name)
        check = kdenlive.validate(out)
        ok("%s - %s" % (out, check.get("message", "")))
        return out

    def chat(self, question):
        step("Question : %s" % question)
        system = prompts.system_message(self.transcript, prompts.SYS_ANALYST)
        user = prompts.build_chat_prompt(question, self.duration)
        for piece in ai.chat_stream(system, user):
            sys.stdout.write(piece)
            sys.stdout.flush()
        print("")


class _FakeJob(object):
    """Job silencieux pour reutiliser le pipeline depuis le CLI."""
    def set_progress(self, *a, **k):
        pass

    def add_log(self, *a, **k):
        pass


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
    kdenlive             genere le projet Kdenlive
    pack                 titres, description, hashtags
    resume               resume de la video
    chat <question>      pose une question sur la video
    open <chemin>        ouvre un fichier dans le Finder
""")
            continue
        if cmd == "open" and len(parts) > 1:
            os.system('open "%s"' % parts[1])
            continue
        if not assistant:
            assistant = Assistant(parts[0])
            assistant.analyze()
            assistant.transcribe()
            continue
        try:
            if cmd == "analyse":
                assistant.analyze()
            elif cmd == "transcribe":
                assistant.transcribe()
            elif cmd == "plan":
                assistant.plan(" ".join(parts[1:]))
            elif cmd == "render":
                fmt = parts[1] if len(parts) > 1 else "16:9"
                assistant.render(fmt)
            elif cmd == "subs":
                path = os.path.join(config.EXPORTS_DIR,
                                    tools.safe_component(assistant.name.rsplit(".", 1)[0], "srt") + ".srt")
                transcribe.write_srt(assistant.segments, path)
                ok(path)
            elif cmd == "kdenlive":
                assistant.kdenlive()
            elif cmd == "pack":
                result = pipeline.ai_pack(_FakeJob(), assistant.transcript,
                                          assistant.candidates, assistant.duration)
                for t in result.get("titles", []):
                    say("    - " + t)
                say("    " + (result.get("description") or "")[:200])
            elif cmd == "resume":
                result = pipeline.ai_summary(_FakeJob(), assistant.transcript,
                                             assistant.duration)
                say("    " + result.get("summary", ""))
                for k in result.get("key_points", []):
                    say("    * " + k)
            elif cmd == "chat" and len(parts) > 1:
                assistant.chat(" ".join(parts[1:]))
            else:
                warn("Commande inconnue : %s (tapez 'help')" % cmd)
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
    assistant.analyze()
    assistant.transcribe()
    command = args[1] if len(args) > 1 else "plan"
    if command == "plan":
        assistant.plan(" ".join(args[2:]))
    elif command == "render":
        assistant.render(args[2] if len(args) > 2 else "16:9")
    elif command == "kdenlive":
        assistant.kdenlive()
    elif command == "chat":
        assistant.chat(" ".join(args[2:]))
    else:
        interactive()


if __name__ == "__main__":
    main()
