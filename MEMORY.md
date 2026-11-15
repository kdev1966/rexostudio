# 🧠 MEMORY — MontageIA

> **Fichier de reprise.** À lire en premier quand on reprend le projet.
> Dernière mise à jour : 15 novembre 2026.

---

## 1. Où en est-on

**Projet :** `~/Desktop/MontageIA/` — assistant de montage vidéo par IA, 100 % local.
**Ancien projet conservé :** `~/Desktop/Studio_IA/` (Python + Gradio + `ollama run` en CLI).
**Instantané Git :** commit `57992a0` — « MontageIA v1 ».

### Ce qui est TERMINÉ et vérifié ✅

| Module | Fichier | État |
|---|---|---|
| Config + détection binaires | `montagia/config.py` | ✅ |
| Exécution de processus | `montagia/tools.py` | ✅ |
| Analyse média (silences, loudness) | `montagia/media.py` | ✅ mesuré 0,25 s / 3 min |
| Transcription Whisper + VAD | `montagia/transcribe.py` | ✅ 9,2 s / 3 min |
| Client Ollama (JSON Schema + stream) | `montagia/ai.py` | ✅ |
| Prompts & schémas JSON | `montagia/prompts.py` | ✅ |
| Moteur de rendu ffmpeg | `montagia/edit.py` | ✅ 16:9 + 9:16 |
| Générateur de projet Kdenlive | `montagia/kdenlive.py` | ✅ validé par `melt` |
| Orchestration | `montagia/pipeline.py` | ✅ |
| État projet | `montagia/project.py` | ✅ |
| Tâches longues + progression | `montagia/jobs.py` | ✅ |
| Serveur web + SSE | `server/app.py` | ✅ |
| Interface (HTML/CSS/JS) | `server/static/` | ✅ |
| Mode terminal | `montagia/cli.py` | ✅ écrit, **pas encore testé** |
| README | `README.md` | ✅ |
| Installateur modèles | `scripts/install_models.sh` | ✅ |

### Test de bout en bout RÉUSSI (vlog Wikimedia Commons)

```
Upload 23,3 Mo  →  Analyse 9,4 s  →  Transcription 14,8 s  →  Plan IA 130 s
→  Correction sous-titres 135 s  →  Rendu 16:9 12,7 s  →  Rendu 9:16 8,0 s
→  Projet Kdenlive 0,6 s  →  Pack 114 s  →  Trailer 181 s  →  Chat OK
```

Vérifications : source 140,9 s → rendu **96,3 s** (44,6 s coupées) ;
vertical **1080×1920** correct ; `.kdenlive` accepté par MLT ; SRT aligné.

---

## 2. Décisions d'efficience (mesurées, ne pas les refaire)

iMac 27" 2015 · i5-5575R **4 cœurs** · 16 Go RAM · Iris Pro 6200 · macOS 12.7.6

| Décision | Avant | Après | Gain |
|---|---|---|---|
| Silence | ffmpeg décode la vidéo | `-vn -map 0:a:0` | 6,0 s → **0,25 s** (24×) |
| Transcription | `small` sans VAD | `base` + beam 5 + **VAD Silero** | 74 s → **9,2 s** (8×), meilleure qualité |
| IA répétée | préfill 23 tok/s | préfixe stable → cache Ollama | 56 s → **4,5 s** (12×) |
| Rendu | libx264 | `h264_videotoolbox` | 5,3× → **11,8×** temps réel |
| Dépendances | `auto-editor` (PyAV) | ffmpeg natif | 0 pip install |

**Pièges évités :**
- Forcer `num_batch` / `num_thread` sur Ollama **dégrade** le préfill de 2,5× → ne rien forcer.
- Le modèle VAD fourni dans `whisper.cpp/models/` s'appelait `for-tests-silero-v6.2.0-ggml.bin`
  (faux) → le vrai s'appelle `ggml-silero-v6.2.0.bin` (téléchargé via `download-vad-model.sh`).
- Sans VAD, Whisper remplit les SRT de marqueurs `[MUSIC]` parasites.

---

## 3. Bugs déjà corrigés (ne pas réintroduire)

1. **Timecodes de sous-titres après coupe** → `transcribe.remap_segments()` recalcule la
   timeline du montage. Utilisé par le rendu (incrustation) et par le projet Kdenlive.
2. **Motifs IA qui recopient les règles** → prompt corrigé (« reason : 3 à 5 mots
   décrivant le CONTENU »).
3. **`rationale` non persistée** → stockée dans `proj.results["plan_rationale"]`.
4. **`PROJECT_DIR` pointait vers le package** après déplacement de `config.py`
   dans `montagia/` → `PROJECT_DIR = dirname(PACKAGE_DIR)`.
5. **`-map` avant `-i`** dans `silencedetect` → option d'entrée invalide.
6. **Double lancement du job "analyze"** dans `_api_analyze` → corrigé.
7. **Expression cassée dans `prompts.build_cut_plan_prompt`** → bloc réécrit.
8. **`config.VIDEO_EXTENSIONS and ""`** (code mort) dans `_api_render` → corrigé.

---

## 4. Principes à respecter

- **Le LLM ne calcule JAMAIS un timecode.** Il renvoie des identifiants (`S1`, `S2`…) ;
  `pipeline.resolve_selection()` recalcule les temps réels.
- **Le LLM n'écrit JAMAIS de commande shell.** Aucun `shell=True` sur une sortie de modèle.
- **La transcription est toujours en tête du message système**, budget de caractères
  **FIXE** (`prompts.CONTEXT_CHARS = 6000`) → c'est ce qui fait fonctionner le cache
  de préfixe d'Ollama. Ne jamais changer cet ordre.
- **Schéma JSON obligatoire** pour toute sortie structurée (`ai.chat_json`).
- **Stdlib uniquement** : pas de `pip install`. Compatible Python 3.9 / macOS 12.

---

## 5. Ce qui reste à faire

### À faire (par ordre de priorité)

1. **Tester le mode terminal** `./start.sh --cli` — jamais exécuté. Vérifier `plan`,
   `render`, `chat`, et le parsing de `montagia/cli.py` (imports `prompts` corrigés
   après coup, à retester).
2. **Vérification visuelle de l'interface** — la capture d'écran a montré le bureau
   vide : Safari/Chrome ne se sont pas affichés. Relancer :
   `open -a "Google Chrome" http://127.0.0.1:8080` puis `screencapture -x /tmp/ui.png`.
3. **Test de l'incrustation des sous-titres** (`subtitles` filter libass + Helvetica)
   — jamais activé sur un rendu réel. Vérifier que la police se résout bien.
4. **Test du plan de coupe sur une vidéo française parlée** (les vidéos de test sont
   en néerlandais/anglais/documentaire).
5. **Bande-annonce (trailer)** : 181 s, c'est lent —songer à réduire le nombre de
   candidats envoyés au LLM ou à demander moins de segments.
6. **Correction des sous-titres** : 135 s — découpage par lots de 25 lignes,
   à ajuster si les transcriptions sont longues.
7. **Nettoyage des imports inutilisés** : `edit.py` (`math`, `json`), `tools.py` (`shlex`),
   `kdenlive.py` (`import re` dans la fonction).
8. **Pack de sous-titres vers Kdenlive** : vérifier que la piste `subtitle_feed`
   s'affiche bien à l'import (validé par MLT, pas visuellement dans Kdenlive).

### Éventuel (améliorations)

- Modèle `qwen2.5:1.5b` pour les tâches mécaniques (correction de sous-titres) → 2× plus rapide.
- Cache disque des vv-analyses déjà en place (`pipeline.cached_ai`) — vérifier qu'il
  ne sert pas de réponses périmées après un changement de prompt (la clé ne contient
  pas le prompt !).
- Chunking parallèle de la transcription pour les vidéos > 30 min (non implémenté).
- Réencodage intelligent : éviter le re-encode complet quand le plan ne change rien
  (déjà fait via le raccourci « copie directe »).

---

## 6. Commandes de reprise

```bash
# Interface web
cd ~/Desktop/MontageIA && ./start.sh          # http://127.0.0.1:8080

# Mode terminal
cd ~/Desktop/MontageIA && ./start.sh --cli

# Test rapide sans navigateur
python3 -m montagia.cli ~/Desktop/Studio_IA/tests/vlog_valentijn.webm plan

# Reinstaller les modèles (si supprimés)
./scripts/install_models.sh

# État du serveur
curl -s http://127.0.0.1:8080/api/status | python3 -m json.tool

# Vérifier l'import de tous les modules
python3 -c "import sys;sys.path.insert(0,'.');import montagia.cli,montagia.pipeline,server.app;print('OK')"
```

---

## 7. Fichiers de test

`~/Desktop/Studio_IA/tests/` (téléchargés depuis Wikimedia Commons, CC BY-SA) :

| Fichier | Format | Résolution | Durée | Intérêt |
|---|---|---|---|---|
| `test.mp4` | h264/aac | 1280×720 | 3 min 03 | documentaire musical EN (le plus dur : pas de silences) |
| `vlog_valentijn.webm` | VP8/Vorbis | 1280×720 | 2 min 21 | **vlog NL** — le test de référence |
| `atelier_menuiserie.webm` | VP9/Opus | **1080×1920** | 11 s | **vertical** → teste le chemin 9:16 |
| `cuisine_africaine.mpg` | MPEG2/MP2 | 1920×1080 | 16,6 s | **MPEG2** → teste l'ingestion d'un codec ancien |

---

## 8. À savoir sur la machine

- **Ollama doit tourner** : `ollama serve` (le `start.sh` le lance s'il est absent).
- `qwen2.5:3b` Q4_K_M, 1,9 Go — génération ≈ 8,5 tok/s.
- ffmpeg/ffprobe/melt viennent de **Kdenlive** (`/Applications/kdenlive.app/Contents/MacOS`),
  pas d'un `brew install` (Homebrew n'est pas installé).
- `h264_videotoolbox` disponible et 2,2× plus rapide que libx264 sur cette machine.
- macOS 12.7.6 → `cgi` existe encore mais **ne doit plus être utilisé** (supprimé en 3.13).
