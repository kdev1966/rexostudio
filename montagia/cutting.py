"""Decoupe de la parole en propositions candidates + regles de coupe sures.

Le plan de coupe se decide proposition par proposition (et non par segment
whisper, qui melange souvent deux idees). Les cas evidents sont tranches ici
par des regles deterministes, plus fiables qu'un modele 3B :

- hesitation : proposition faite uniquement de "euh", "alors", "bref"...
- faux depart : "je recommence", "on reprend"... (et la prise ratee juste avant)
- repetition : une phrase redite peu apres -> on garde la DERNIERE prise

Le reste (digressions, hors sujet...) est classe par l'IA.
"""
from __future__ import annotations

import difflib
import re
import unicodedata

# Ponctuation latine et arabe (، virgule, ؛ point-virgule, ؟ point d'interrogation).
SENTENCE_END = (".", "!", "?", "…", "؟")
CLAUSE_END = (",", ";", ":", "،", "؛") + SENTENCE_END

SPLIT_GAP = 0.7            # pause qui separe deux propositions (s)
MAX_CLAUSE_SECONDS = 12.0  # au-dela, coupe a la plus grande pause interne
MIN_PART_SECONDS = 3.0     # ... sans creer de morceau plus court que ca
MIN_CLAUSE_SECONDS = 1.0   # plus court (et < 3 mots) : rattache a une voisine
MIN_CLAUSE_WORDS = 3
PAD = 0.12                 # marge gardee autour de la parole (s)
RETAKE_WINDOW = 5          # propositions suivantes comparees pour une reprise
RETAKE_RATIO = 0.75
RESTART_GAP = 3.0          # faux depart : prise ratee a moins de 3 s du marqueur

FILLERS = {"euh", "heu", "hum", "hmm", "bah", "ben", "eh", "alors", "bref",
           "bon", "enfin", "donc", "voila", "quoi", "genre"}
RESTART_PHRASES = ("je recommence", "on recommence", "je reprends", "on reprend",
                   "je refais", "on refait", "reprenons", "je me suis trompe",
                   "je me suis trompee", "on la refait", "je la refais",
                   # tunisien : "je recommence", "on recommence"
                   "\u0646\u0639\u0627\u0648\u062f", "\u0646\u0639\u0627\u0648\u062f\u0648")
RESTART_ALONE = {("attendez",), ("attends",), ("pardon",), ("excusez", "moi"),
                 ("non", "non")}

KEEP_TYPES = ("contenu", "introduction", "conclusion", "illustration")
RULE_LABELS = {"hesitation": "hesitation", "faux_depart": "faux depart",
               "repetition": "repetition"}
# Boucle de transcription : Whisper repete parfois en boucle une phrase
# inventee (vu en arabe : 4 fois la meme phrase en 20 s). On ne sait pas ce
# qui est vraiment dit : le passage est garde et signale, jamais coupe.
DOUBT_RULE = "boucle"
LOOP_MIN_WORDS = 3         # suite repetee d'au moins 3 mots ...
LOOP_MIN_REPEATS = 3       # ... au moins 3 fois ...
LOOP_SLACK_WORDS = 6       # ... a moins de (2 x longueur + 6) mots d'ecart


def normalize(text: str) -> list:
    """Mots en minuscules, sans accents, voyelles courtes arabes ni
    ponctuation - pour TOUTES les ecritures. (Une premiere version ne gardait
    que [a-z0-9] : un texte arabe se reduisait a ses mots anglais, et deux
    phrases differentes passaient pour une reprise.)"""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.findall(r"[^\W_]+", text)


def _text(words: list) -> str:
    return " ".join(w["text"] for w in words)


def split_clauses(words: list) -> list:
    """Coupe la suite de mots a chaque ponctuation et a chaque pause, puis
    redecoupe les passages trop longs (parole continue sans ponctuation,
    frequente en arabe : 7 min de podcast donnaient 3 passages)."""
    clauses, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if w["text"].endswith(CLAUSE_END) or nxt is None or nxt["start"] - w["end"] > SPLIT_GAP:
            clauses.append(cur)
            cur = []
    out = []
    for clause in clauses:
        out.extend(split_long(clause))
    return out


def split_long(clause: list) -> list:
    """Coupe un passage de plus de MAX_CLAUSE_SECONDS a sa plus grande pause
    entre deux mots (en gardant au moins MIN_PART_SECONDS de chaque cote),
    recursivement."""
    if len(clause) < 2 or clause[-1]["end"] - clause[0]["start"] <= MAX_CLAUSE_SECONDS:
        return [clause]
    best, best_gap = None, -1.0
    for i in range(1, len(clause)):
        left = clause[i - 1]["end"] - clause[0]["start"]
        right = clause[-1]["end"] - clause[i]["start"]
        if left < MIN_PART_SECONDS or right < MIN_PART_SECONDS:
            continue
        gap = clause[i]["start"] - clause[i - 1]["end"]
        # a pause egale, preferer le milieu (morceaux equilibres)
        score = gap - 0.001 * abs(left - right)
        if score > best_gap:
            best, best_gap = i, score
    if best is None:
        return [clause]
    return split_long(clause[:best]) + split_long(clause[best:])


def _is_filler(words: list) -> bool:
    tokens = normalize(_text(words))
    return bool(tokens) and all(t in FILLERS for t in tokens)


def _is_short(words: list) -> bool:
    return (words[-1]["end"] - words[0]["start"] < MIN_CLAUSE_SECONDS
            or len(words) < MIN_CLAUSE_WORDS)


def merge_short(clauses: list) -> list:
    """Rattache les fragments trop courts ("premiere etape,") a la proposition
    suivante, ou a la precedente s'ils terminent une phrase. Les hesitations
    restent isolees : elles seront coupees."""
    out = []
    pending = []                         # fragments en attente de la suite
    for clause in clauses:
        if _is_filler(clause):
            if pending:
                out.append(pending)
                pending = []
            out.append(clause)
            continue
        clause = pending + clause
        pending = []
        if _is_short(clause):
            ends_sentence = clause[-1]["text"].endswith(SENTENCE_END)
            if ends_sentence and out and not _is_filler(out[-1]) \
                    and not out[-1][-1]["text"].endswith(SENTENCE_END):
                out[-1] = out[-1] + clause
            elif ends_sentence:
                out.append(clause)
            else:
                pending = clause
            continue
        out.append(clause)
    if pending:
        if out and not _is_filler(out[-1]):
            out[-1] = out[-1] + pending
        else:
            out.append(pending)
    return out


def _is_restart(words: list) -> bool:
    tokens = normalize(_text(words))
    joined = " ".join(tokens)
    return (any(p in joined for p in RESTART_PHRASES)
            or tuple(tokens) in RESTART_ALONE)


def _retaken(a: list, b: list) -> bool:
    """b reprend a : meme phrase redite, ou a est un debut de b."""
    if len(a) < 2:
        return False
    if len(a) >= MIN_CLAUSE_WORDS and \
            difflib.SequenceMatcher(None, a, b).ratio() >= RETAKE_RATIO:
        return True
    head = b[:len(a)]
    return len(a) >= 2 and difflib.SequenceMatcher(None, a, head).ratio() >= 0.85 \
        and len(b) > len(a)


def find_loops(words: list, max_len: int = 6) -> list:
    """Intervalles (debut, fin) ou une meme suite de mots revient en boucle."""
    tokens, owner = [], []
    for index, word in enumerate(words):
        for token in normalize(word["text"]):
            tokens.append(token)
            owner.append(index)
    spans = []
    for n in range(LOOP_MIN_WORDS, max_len + 1):
        limit = 2 * n + LOOP_SLACK_WORDS
        positions = {}
        for i in range(len(tokens) - n + 1):
            gram = tuple(tokens[i:i + n])
            if len(set(gram)) >= LOOP_MIN_WORDS:       # pas "ha ha ha"
                positions.setdefault(gram, []).append(i)
        for found in positions.values():
            chain = [found[0]]
            for pos in found[1:] + [None]:
                if pos is not None and pos - chain[-1] < n:
                    continue                           # chevauche l'occurrence precedente
                if pos is not None and pos - chain[-1] <= limit:
                    chain.append(pos)
                    continue
                if len(chain) >= LOOP_MIN_REPEATS:
                    spans.append((words[owner[chain[0]]]["start"],
                                  words[owner[chain[-1] + n - 1]]["end"]))
                if pos is not None:
                    chain = [pos]
    spans.sort()
    merged = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _in_loop(clause: list, loops: list) -> bool:
    """La proposition est pour moitie (au moins) dans une boucle."""
    start, end = clause[0]["start"], clause[-1]["end"]
    inside = sum(max(0.0, min(end, b) - max(start, a)) for a, b in loops)
    return inside >= 0.5 * max(end - start, 1e-6)


def apply_rules(clauses: list) -> list:
    """Retourne, pour chaque proposition, la regle qui la coupe (ou None ;
    DOUBT_RULE signale une transcription douteuse, gardee)."""
    rules = [None] * len(clauses)
    norm = [normalize(_text(c)) for c in clauses]
    loops = find_loops([w for c in clauses for w in c])
    for i, clause in enumerate(clauses):
        if loops and _in_loop(clause, loops):
            rules[i] = DOUBT_RULE
        elif _is_filler(clause):
            rules[i] = "hesitation"
        elif _is_restart(clause):
            rules[i] = "faux_depart"
            # la prise ratee juste avant le marqueur
            for j in range(i - 1, -1, -1):
                if rules[j] is None:
                    if clause[0]["start"] - clauses[j][-1]["end"] <= RESTART_GAP:
                        rules[j] = "faux_depart"
                    break
    for i in range(len(clauses)):
        if rules[i] is not None:
            continue
        seen = 0
        for j in range(i + 1, len(clauses)):
            if rules[j] is not None:
                continue
            seen += 1
            if seen > RETAKE_WINDOW:
                break
            if _retaken(norm[i], norm[j]):
                rules[i] = "repetition"
                break
    return rules


def speech_candidates(words: list) -> list:
    """Propositions candidates (dict start/end/text/kind/rule), avec marges
    calees a mi-chemin des voisines pour ne jamais rogner un mot."""
    clauses = merge_short(split_clauses(words))
    rules = apply_rules(clauses)
    out = []
    for i, clause in enumerate(clauses):
        start, end = clause[0]["start"], clause[-1]["end"]
        prev_end = clauses[i - 1][-1]["end"] if i else 0.0
        next_start = clauses[i + 1][0]["start"] if i + 1 < len(clauses) else end + 2 * PAD
        start = max(0.0, start - min(PAD, (start - prev_end) / 2.0))
        end = end + min(PAD, max(0.0, next_start - end) / 2.0)
        out.append({"start": round(start, 3), "end": round(end, 3),
                    "text": _text(clause), "kind": "parole", "rule": rules[i]})
    return out


def merge_kept(candidates: list, keep: dict, max_gap: float = 0.35) -> list:
    """Segments du plan : propositions gardees consecutives fusionnees (un
    seul plan continu si la pause entre elles est courte)."""
    segments = []
    for cand in candidates:
        if not keep.get(cand["id"]):
            continue
        last = segments[-1] if segments else None
        if last and last["_last_index"] == cand["_index"] - 1 \
                and cand["start"] - last["end"] <= max_gap:
            last["end"] = cand["end"]
            last["id"] = last["id"].split("-")[0] + "-" + cand["id"]
            last["_last_index"] = cand["_index"]
            continue
        segments.append({"start": cand["start"], "end": cand["end"], "id": cand["id"],
                         "reason": label(cand), "_last_index": cand["_index"]})
    for seg in segments:
        seg.pop("_last_index", None)
    return segments


def label(cand: dict, words: int = 6) -> str:
    """Nom court d'un segment : ses premiers mots (marqueurs FilmCraft, UI)."""
    if cand.get("kind") == "visuel":
        return "plan sans parole"
    tokens = cand.get("text", "").split()
    return " ".join(tokens[:words]) + (" ..." if len(tokens) > words else "")
