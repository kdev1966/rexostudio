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
| Pilotage FilmCraft (remplace Kdenlive) | `montagia/filmcraft.py` | ✅ testé en réel 16:9 et 9:16 |
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
| Whisper GPU | Metal (Iris Pro) | CPU seul `-ng` | 2,7 s → **1,4 s** (2×), plus de compilation Metal de ~55 s au 1er lancement |

**Installation autonome (15/11/2026)** : `~/Desktop/Studio_IA` n'existe plus. `./scripts/install_models.sh`
compile whisper.cpp v1.9.5 en **statique** (CMake 4.4.5 et commit vérifiés, `GGML_NATIVE=OFF` +
AVX2/FMA/F16C → le même binaire tourne sur l'iMac et sur le MacBook de dev) et télécharge
`ggml-base.bin` + `ggml-silero-v6.2.0.bin` avec vérification SHA-256.

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
9. **Sous-titres décalés si le plan a des doublons/chevauchements** → le plan est
   normalisé UNE fois (`pipeline.prepare_plan`) puis partagé par rendu, remappage et
   Kdenlive ; `resolve_selection` ignore les identifiants répétés.
10. **Flux SSE jamais terminés** (chat + événements de job) → `Connection: close` ;
    un job déjà fini à l'abonnement renvoie directement son état final.
11. **Requêtes d'autres sites acceptées** (`/api/open`, `/api/upload`) → contrôle
    `Host` / `Origin` + `Content-Type: application/json` obligatoire sur les POST.

12. **Éclair de sous-titre** (0,2 s d'une phrase presque coupée) → un morceau n'est gardé
    que s'il dure ≥ 0,4 s ou garde ≥ 50 % de la phrase (`transcribe.remap_segments`).

Tests : `python3 -m unittest discover -s tests` (stdlib, sans Ollama ni ffmpeg).

### FilmCraft (remplace Kdenlive depuis le 15/11/2026)

- Piloté en direct par son serveur de contrôle local (`--control <port>`, jeton aléatoire de
  64 hex dans `workspace/cache/filmcraft-session.json`, droits 0600). Port : `MONTAGIA_FILMCRAFT_PORT` (9877).
- **Tous les temps en ticks entiers** (254 016 000 000 / s). Piège : `"time": {"seconds": x}` est
  IGNORÉ par `timeline.place` (le clip part à 0 et écrase le précédent) → toujours des ticks.
- Plan **calé sur les images** (`filmcraft.frame_plan`) ; les sous-titres sont recalés sur ce même
  plan → synchrones avec la timeline FilmCraft.
- `file.newProject` REMPLACE le projet ouvert sans demander → `file.autoSaveNow` avant (copie de
  secours dans le dossier Auto-Save de FilmCraft).
- Si FilmCraft est déjà ouvert sans pilotage, MontageIA refuse avec un message (pas de 2ᵉ instance).

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

### Fait le 15/11/2026 (branche `fix/plan-sse-origin`)

- Outillage autonome (`bin/` + `models/`), FilmCraft à la place de Kdenlive.
- Incrustation des sous-titres testée (Helvetica via CoreText, accents OK).
- R1 délai réel des processus (`tools.CommandTimeout`), R2 uploads sans écrasement
  (`tools.unique_path`), R3 SRT temporaires uniques.
- Projets persistants (`workspace/projects/project_<id>.json`) + liste « Projets récents ».
- `/api/file` gère `Range` (aperçu vidéo, Safari) ; un seul job lourd à la fois.
- Vidéos peu parlées : `media.detect_scenes` (scdet) ; si la parole couvre < 50 % de la
  durée, les trous sont proposés à l'IA comme `[plan sans parole]` (PROMPT_VERSION v2).
  Les vidéos parlées gardent le comportement précédent.

### Plan de coupe refait (15/11/2026, mesuré sur l'iMac)

L'ancien plan (« liste des segments à garder ») gardait **47,2 s sur 47,6 s** d'une vidéo
pleine de défauts, avec une justification contraire. Nouveau fonctionnement :
- whisper **mot par mot** (`-ml 1 -sow` : temps recalés même avec le VAD — les temps des
  *tokens* `-ojf`, eux, restent sur la timeline compressée par le VAD, piège) ;
- `montagia/cutting.py` : propositions + règles sûres (hésitations seules, « je recommence »
  + prise ratée, prise redite → la dernière gardée) ;
- l'IA **classe** chaque passage restant (`prompts.SCHEMA_DECISIONS`), par lots de 40 ;
  garder/couper découle de la catégorie ; non classé = gardé ;
- justification **calculée** (le résumé de l'IA décrivait l'inverse de ses choix) ;
- sous-titres du montage reconstruits **mot par mot** (`transcribe.remap_words`).

Mesure, vidéo `cafe_filtre.mp4` 47,6 s, sans consigne : **32,5 s gardées**, faux départ +
4 hésitations (règles) + digression (IA) coupés, plan en **25 s au lieu de 87 s**.
Test de non-régression : `tests/fixtures/cafe_words.json` (vrais mots de cette vidéo).

### Essais sur de vraies vidéos (15/11/2026, iMac)

- `film001.mp4` (23 s, vertical) : **en anglais** (réaction à une bande-annonce Avengers),
  pas en français. Langue forcée « fr » → charabia ; en « auto » → anglais détecté.
  Dialogue sous musique : transcription pauvre. Type de contenu hors cible (pas de parole « montable »).
- `film002.mp4` (7 min, arabe tunisien + anglais/français) : transcription `base` très
  approximative ; plan de coupe en **230 s** (l'arabe coûte beaucoup de tokens) ;
  au moins une erreur nette (annonce du sujet coupée comme « digression »).
  → Pour l'arabe dialectal : tester whisper `small`/`medium`, et/ou un mode de coupe prudent.
- Bugs trouvés et corrigés grâce à ces vidéos : réponse IA tronquée (plafond de tokens),
  passages de 351 s (pas de ponctuation en arabe → passages bornés à 12 s), ponctuation arabe,
  plans visuels coupés en « digression », VAD qui jette la voix sous la musique.

### À faire (par ordre de priorité)

1. ~~Déployer sur l'iMac + parcours complet~~ ✅ fait (par l'API) : upload, analyse 1,6 s,
   transcription 6 s, plan 25 s, rendu 16:9 3,5 s, 9:16 5,2 s, FilmCraft 0,5 s.
   Déploiement : `git push imac fix/plan-sse-origin:refs/heads/deploy-incoming` puis, sur
   l'iMac, `git merge --ff-only deploy-incoming` et redémarrage de `start.sh`.
2. **Tester le mode terminal** `./start.sh --cli` sur l'iMac (`plan`, `render`, `filmcraft`, `chat`).
3. **Test du plan de coupe sur une vidéo française parlée** (vraie vidéo, pas une voix de synthèse).
4. **Mesurer `detect_scenes` sur l'iMac** (décode toute la vidéo) et le plan IA d'une vidéo sans voix.
5. **Bande-annonce (trailer)** : 181 s, c'est lent — réduire le nombre de candidats.
6. **Correction des sous-titres** : 135 s — découpage par lots de 25 lignes.
7. Supprimer `bin/whisper-cli.bak` (ancien binaire cassé) une fois tout validé.

### Éventuel (améliorations)

- Modèle `qwen2.5:1.5b` pour les tâches mécaniques (correction de sous-titres) → 2× plus rapide.
- La clé du cache IA contient `PROMPT_VERSION` mais pas le nom du modèle : penser à
  l'ajouter si `MONTAGIA_MODEL` change.
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
- ffmpeg/ffprobe sont dans `bin/` (builds statiques evermeet 9.0.2, installés par
  `scripts/install_models.sh`) ; Homebrew n'est pas installé. Kdenlive n'est plus utilisé.
- Production : **iMac de Najeh** (`najehstudio@192.168.1.166`, accès par clé SSH) ;
  développement sur un MacBook Pro 2015 (i7-4870HQ, sans ADX).
- `h264_videotoolbox` disponible et 2,2× plus rapide que libx264 sur cette machine.
- macOS 12.7.6 → `cgi` existe encore mais **ne doit plus être utilisé** (supprimé en 3.13).
