"""Prompts systemes et schemas JSON pour chaque tache IA.

DEUX REGLES IMPORTANTES :

1. Le modele ne fait jamais de calcul de timestamps. On lui presente des
   segments numerotes (S1, S2, ...) et il repond avec des identifiants :
   les temps reels sont recalcules par le code. Aucune hallucination possible.

2. La transcription est TOUJOURS en tete du message systeme, avec un budget
   de caracteres FIXE. Ollama met en cache le prefixe du prompt : toutes les
   taches IA sur la meme video partagent ainsi le meme prefixe et la
   transcription n'est plus re-analysee a chaque appel (gain mesure : 56 s
   -> 4,5 s). Ne jamais changer cet ordre.
"""
from __future__ import annotations

# Budget fixe du contexte (identique pour toutes les taches -> cache partage)
CONTEXT_CHARS = 6000
CANDIDATE_PREVIEW = 140
MAX_CANDIDATES = 60

# --------------------------------------------------------------------------
# Schemas JSON
# --------------------------------------------------------------------------

SCHEMA_CUT_PLAN = {
    "type": "object",
    "properties": {
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "reason": {"type": "string"},
                    "trim_start": {"type": "number"},
                    "trim_end": {"type": "number"},
                },
                "required": ["id", "reason"],
            },
        },
        "rationale": {"type": "string"},
        "style": {"type": "string"},
    },
    "required": ["segments", "rationale"],
}

SCHEMA_TRAILER = {
    "type": "object",
    "properties": {
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "score": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["id", "score", "reason"],
            },
        },
        "rationale": {"type": "string"},
    },
    "required": ["segments"],
}

SCHEMA_PACK = {
    "type": "object",
    "properties": {
        "titles": {"type": "array", "items": {"type": "string"}},
        "description": {"type": "string"},
        "short_description": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "chapters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                },
                "required": ["id", "title"],
            },
        },
        "hook": {"type": "string"},
    },
    "required": ["titles", "description", "hashtags"],
}

SCHEMA_SUBTITLES = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "number"},
                    "text": {"type": "string"},
                },
                "required": ["index", "text"],
            },
        },
    },
    "required": ["lines"],
}

SCHEMA_SUMMARY = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "key_points": {"type": "array", "items": {"type": "string"}},
        "topics": {"type": "array", "items": {"type": "string"}},
        "sentiment": {"type": "string"},
        "questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "key_points"],
}

# --------------------------------------------------------------------------
# Contextes systemes
# --------------------------------------------------------------------------

SYS_EDITOR = (
    "Tu es un monteur video professionnel francophone. Tu travailles sur des "
    "rushs deja transcrits. Tes reponses sont concises, utiles et conformes "
    "au schema JSON demande. Tu ne donnes jamais de timecodes : tu "
    "selectionnes uniquement des segments identifies par leur identifiant."
)

SYS_MARKETING = (
    "Tu es un redacteur francophone specialise dans les titres YouTube, TikTok "
    "et Instagram. Tu ecris des accroches percutantes mais honnetes. Tu "
    "reponds en JSON conforme au schema demande."
)

SYS_SUBTITLES = (
    "Tu es un correcteur de sous-titres professionnel francophone. Tu corriges "
    "uniquement la ponctuation, la casse et les erreurs de transcription "
    "evidentes. Tu ne traduis pas, tu ne resumes pas, tu ne supprimes aucun "
    "mot. Tu conserves exactement le meme nombre de lignes, dans le meme ordre, "
    "avec les memes index."
)

SYS_ANALYST = (
    "Tu es un analyste video francophone. Tu reponds de maniere concrete et "
    "factuelle, en JSON conforme au schema demande."
)


# --------------------------------------------------------------------------
# Construction des messages
# --------------------------------------------------------------------------

def build_context(transcript: str) -> str:
    """Bloc de contexte de taille FIXE et deterministe (cache Ollama).

    On garde le debut et la fin de la transcription, on coupe le milieu.
    """
    text = (transcript or "").strip()
    if not text:
        return "(aucune parole detectee dans la video)"
    if len(text) <= CONTEXT_CHARS:
        return text
    head = int(CONTEXT_CHARS * 0.65)
    tail = CONTEXT_CHARS - head
    return "%s\n[... %d caracteres elides ...]\n%s" % (
        text[:head], len(text) - CONTEXT_CHARS, text[-tail:])


def system_message(transcript: str, persona: str) -> str:
    """Message systeme : transcription d'abord (prefixe stable), puis persona."""
    return ("TRANSCRIPTION DE LA VIDEO (ne la repete pas, utilise-la comme reference) :\n"
            "%s\n\n%s" % (build_context(transcript), persona))


def candidate_lines(candidates: list, preview: int = CANDIDATE_PREVIEW) -> str:
    lines = []
    for cand in candidates:
        text = (cand.get("text") or "").strip()
        if len(text) > preview:
            text = text[:preview] + "..."
        lines.append("%s [%.1fs -> %.1fs] %s" % (
            cand["id"], cand["start"], cand["end"], text))
    return "\n".join(lines)


def build_cut_plan_prompt(candidates: list, duration: float, instruction: str = "",
                          style: str = "") -> str:
    style_txt = style or "standard"
    return (
        "Duree totale de la video : %.1f secondes.\n"
        "Voici les %d segments de parole detectes (identifiant [debut -> fin] texte) :\n\n%s\n\n"
        "Tache : selectionne les segments a KEEPER pour un montage propre de type \"%s\".\n"
        "%s"
        "Regles :\n"
        "- Conserve l'ordre chronologique.\n"
        "- Supprime les repetitions, les faux departs, les digressions et les silences.\n"
        "- Garde au moins 3 segments si la video en contient plus de 3.\n"
        "- N'invente jamais d'identifiant : utilise uniquement ceux listes ci-dessus.\n"
        "- trim_start / trim_end : facultatifs, en secondes, pour rogner un debut ou "
        "une fin de segment (mets 0 si tu ne rognes pas).\n"
        "- reason : 3 a 5 mots maximum decrivant le CONTENU du segment garde "
        "(ex: 'accroche sur l ocean', 'question d ouverture'). N'ecris jamais les regles "
        "ni la consigne dans reason.\n"
        "- rationale : 1 phrase expliquant le choix de l'ensemble.\n\n"
        "Reponds avec le schema JSON demande."
    ) % (
        duration, len(candidates), candidate_lines(candidates),
        style_txt,
        ("Consigne specifique de l'utilisateur : %s\n" % instruction) if instruction else "",
    )


def build_trailer_prompt(candidates: list, duration: float, target_seconds: float,
                         instruction: str = "") -> str:
    return (
        "Duree totale de la video : %.1f secondes. Objectif du trailer : environ %.0f secondes.\n"
        "Segments de parole disponibles :\n\n%s\n\n"
        "Tache : choisis les segments les plus accrocheurs et interessants pour un trailer "
        "court. Classe-les par importance decroissante : score 10 = meilleur, 1 = faible.\n"
        "%s"
        "Reponds avec le schema JSON demande (score entre 1 et 10)."
    ) % (
        duration, target_seconds, candidate_lines(candidates),
        ("Consigne : %s\n" % instruction) if instruction else "",
    )


def build_pack_prompt(segments: list, duration: float, tone: str = "",
                      extra: str = "") -> str:
    chapters = candidate_lines(segments, preview=90)
    return (
        "Duree de la video : %.0f secondes.\n"
        "Chapitres possibles (identifiant -> texte) :\n%s\n\n"
        "Tache : produis un pack de publication.\n"
        "%s%s"
        "Regles :\n"
        "- 5 titres accrocheurs, 60 caracteres maximum chacun.\n"
        "- Une description YouTube de 2 a 4 phrases qui donne envie de regarder.\n"
        "- Une version courte (1 phrase) pour les reseaux sociaux.\n"
        "- 8 a 12 hashtags, sans le caractere #.\n"
        "- Les chapitres reprennent les identifiants de segments si possible, sinon laisse "
        "le tableau vide.\n\n"
        "Reponds avec le schema JSON demande."
    ) % (
        duration, chapters[:3000],
        ("Ton souhaite : %s\n" % tone) if tone else "",
        ("Consigne : %s\n" % extra) if extra else "",
    )


def build_subtitle_chunk_prompt(lines: list) -> str:
    numbered = "\n".join("%d | %s" % (ln["index"], ln["text"]) for ln in lines)
    return (
        "Corrige les sous-titres ci-dessous (ponctuation, casse, erreurs d'orthographe "
        "evidentes). Conserve chaque ligne et son index.\n\n%s\n\n"
        "Reponds avec le schema JSON demande : une ligne par index, meme ordre."
    ) % numbered


def build_summary_prompt(duration: float) -> str:
    return (
        "Duree de la video : %.0f secondes.\n\n"
        "Tache : resume la video en francais, liste les points cles, les themes abordes, "
        "le ton general, et 3 questions auxquelles le contenu repond.\n\n"
        "Reponds avec le schema JSON demande."
    ) % duration


def build_chat_prompt(question: str, duration: float) -> str:
    return (
        "Duree de la video : %.0f secondes.\n\n"
        "Question de l'utilisateur : %s\n\n"
        "Reponds en francais, de maniere directe et concrete, en 2 a 6 phrases. "
        "Si l'information n'est pas dans la video, dis-le clairement."
    ) % (duration, question)
