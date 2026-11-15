# 🎬 MontageIA — assistant de montage vidéo par IA, 100 % local

Un système d'assistance au montage vidéo qui utilise **qwen2.5:3b** sur **Ollama local**,
**whisper.cpp** pour la transcription, **ffmpeg** pour le montage réel et **FilmCraft**
pour continuer le montage à la main.
Aucune donnée ne sort de la machine, aucune dépendance Python à installer.

> **Principe de conception** : un modèle 3B n'est pas fiable pour écrire des
> commandes `ffmpeg`. Ici, l'IA ne fait que du **travail sémantique court et
> structuré** (JSON) ; c'est un moteur déterministe en Python qui applique
> les découpes, les recadrages et les exports. Le LLM ne calcule **jamais**
> un timecode : il sélectionne des segments pré-calculés, identifiés `S1`, `S2`…

---

## 1. Installation

```bash
cd ~/MontageIA                  # hors du Bureau : voir la note ci-dessous
./scripts/install_models.sh     # whisper.cpp statique + modèles + ffmpeg (tout vérifié)
./scripts/install_launcher.sh   # icône MontageIA sur le Bureau
```

Ne placez pas le dossier du projet sur le Bureau ni dans Documents : macOS interdit à
l'icône de lancement de lire ces dossiers protégés (« Operation not permitted »).
L'icône, elle, peut être sur le Bureau.

**Prérequis** (déjà présent sur cette machine) :

| Outil | Rôle | Où il vient |
|---|---|---|
| Ollama ≥ 0.12 | LLM local | `/usr/local/bin/ollama` |
| `qwen2.5:3b` | modèle | `ollama pull qwen2.5:3b` |
| whisper.cpp | transcription | `bin/whisper-cli` (compilé en statique) + `models/` |
| ffmpeg / ffprobe | média | `bin/` (build statique evermeet, SHA-256 épinglé) |
| FilmCraft ≥ 0.20 | éditeur vidéo, piloté en direct | `/Applications/FilmCraft.app` |

Aucun `pip install` : le projet n'utilise que la bibliothèque standard Python 3.9.

---

## 2. Utilisation

### Interface web (principale)

**Double-cliquez sur l'icône MontageIA du Bureau** : le serveur démarre en arrière-plan
(sans fenêtre de Terminal) et l'interface s'ouvre dans le navigateur. Un nouveau clic
rouvre simplement la page. Le bouton **Quitter** de l'interface retire le modèle IA de la
mémoire et arrête le serveur. Journal : `~/Library/Logs/MontageIA.log`.

Sans l'icône : `./start.sh` (ouvre `http://127.0.0.1:8080`, Ctrl+C pour arrêter).

Le parcours :

1. **Vidéo** — déposez votre rush (une vidéo déjà importée rouvre son projet).
2. **Préparer le montage** — un seul bouton : analyse, transcription (Whisper), puis plan de
   coupe (règles + IA). Les étapes séparées sont dans « Réglages avancés ».
3. **Montage** (onglet) — la liste des passages : cocher pour garder, décocher pour couper ;
   ▶ pour écouter un passage, « Aperçu du montage » pour enchaîner les passages gardés sans
   rendu. Le filtre « À vérifier » isole les suggestions de l'IA et les transcriptions douteuses.
4. **Exporter** — vidéo 16:9 et/ou 9:16, sous-titres incrustés, volume égalisé ; ou
   **Ouvrir dans FilmCraft** : clips calés à l'image, piste de sous-titres, un marqueur par
   coupe (`.fcproj`).

Le modèle IA reste en mémoire 5 min après sa dernière utilisation, puis Ollama le décharge
(`MONTAGIA_KEEP_ALIVE` pour changer ce délai).

### Mode terminal

```bash
./start.sh --cli                                   # mode interactif
./start.sh --cli video.mp4 plan "garde le plus marquant"
./start.sh --cli video.mp4 render 9:16
```

Commandes : `analyse`, `transcribe`, `plan`, `render 16:9`, `subs`, `filmcraft [16:9|9:16]`,
`pack`, `resume`, `chat <question>`.

---

## 3. Ce que fait l'IA (et ce qu'elle ne fait pas)

| Tâche | Modèle | Sortie |
|---|---|---|
| Plan de coupe | qwen2.5:3b | JSON `{segments:[{id, reason, trim_start, trim_end}], rationale}` |
| Meilleurs moments (trailer) | qwen2.5:3b | JSON `{segments:[{id, score, reason}]}` |
| Pack de publication | qwen2.5:3b | titres, description, hashtags, chapitres, accroche |
| Résumé & analyse | qwen2.5:3b | résumé, points clés, thèmes, questions |
| Correction des sous-titres | qwen2.5:3b | JSON `{lines:[{index, text}]}` (ponctuation, casse) |
| Chat sur la vidéo | qwen2.5:3b | texte libre, streaming |

**Ce que l'IA ne fait jamais** : calculer un timecode, écrire une commande shell,
modifier un fichier source. Les timecodes sont recalculés par le code à partir
d'identifiants — **aucune hallucination possible**.

---

## 4. Décisions d'efficience (mesurées sur cette machine)

iMac 27" 2015 · i5-5575R 4 cœurs · 16 Go RAM · Iris Pro 6200 · macOS 12.7.6

| Décision | Avant | Après | Gain |
|---|---|---|---|
| Détection de silence | ffmpeg décode la vidéo | `-vn -map 0:a:0` | **6,0 s → 0,25 s** (24×) |
| Transcription | `small`, sans VAD | `base` + beam 5 + **VAD Silero** | **74 s → 9,2 s** (8×) *et meilleure qualité* |
| Appels IA répétés | préfill 23 tok/s | préfixe stable → cache Ollama | **56 s → 4,5 s** (12×) |
| Rendu | libx264 | `h264_videotoolbox` | 5,3× → **11,8×** temps réel |
| Dépendances | `auto-editor` (PyAV) | ffmpeg natif | 0 dépendance Python |

Détails qui comptent :

- **Le VAD améliore la qualité *et* la vitesse** : les marqueurs `[MUSIC]` parasites
  disparaissent, les phrases sont regroupées, et 75 % de l'audio sans parole est sauté.
- **Les réglages Ollama par défaut sont les meilleurs** : forcer `num_batch` ou
  `num_thread` dégrade le préfill de 2,5×. On ne force rien.
- **Cache de préfixe** : la transcription est toujours en tête du message système,
  avec un budget de caractères fixe. Toutes les tâches IA d'une même vidéo
  partagent le même préfixe → la transcription n'est ré-analysée qu'une fois.
- **Raccourci de rendu** : si le plan ne retire rien et qu'aucune transformation
  n'est demandée, le fichier est simplement copié (instantané).
- **Cache disque des résultats IA** (clé = hash tâche + paramètres) : relancer un
  test de prompt ne recalcule rien.

---

## 5. Architecture

```
MontageIA/
├── start.sh                     lanceur (Ollama + serveur + navigateur)
├── scripts/install_models.sh    installation whisper.cpp + modèles
├── bin/whisper-cli              binaire natif
├── models/                      ggml-base.bin, ggml-small.bin, VAD Silero
├── montagia/
│   ├── config.py                chemins, seuils, détection des binaires
│   ├── tools.py                 exécution de processus, utils
│   ├── media.py                 ffprobe, silencedetect, loudness
│   ├── transcribe.py            whisper.cpp, SRT/VTT, remappage de timeline
│   ├── ai.py                    client Ollama (JSON Schema + streaming)
│   ├── prompts.py               prompts et schémas JSON
│   ├── edit.py                  moteur de rendu ffmpeg
│   ├── filmcraft.py             pilotage de FilmCraft (projet .fcproj)
│   ├── pipeline.py              orchestration
│   ├── project.py               état d'un projet en cours
│   ├── jobs.py                  tâches longues + progression
│   └── cli.py                   mode terminal
├── server/
│   ├── app.py                   serveur HTTP (SSE, threads)
│   └── static/                  index.html, app.js, style.css
└── workspace/                   media, exports, cache (généré)
```

**Flux d'une coupe :**

```
vidéo → silencedetect → segments de parole
      → whisper.cpp (+VAD) → segments horodatés
      → qwen2.5:3b (JSON) → sélection d'identifiants
      → résolution des timecodes → plan de coupe
      → ffmpeg select/aselect → rendu 16:9 ou 9:16
      → serveur de contrôle FilmCraft → projet .fcproj
```

---

## 6. API HTTP (tout est appelable en ligne de commande)

| Route | Effet |
|---|---|
| `GET /api/status` | état d'Ollama, ffmpeg, Whisper, FilmCraft |
| `POST /api/upload?name=` | téléversement (corps brut, streaming disque) |
| `POST /api/analyze` | détection des silences |
| `POST /api/transcribe` | transcription Whisper + VAD |
| `POST /api/plan` | plan de coupe IA |
| `POST /api/prepare` | analyse + transcription + plan en un traitement |
| `POST /api/plan/keep` | garder / couper un passage (plan recalculé) |
| `POST /api/project/delete` | supprime un projet et sa vidéo importée |
| `POST /api/quit` | décharge le modèle IA et arrête le serveur |
| `POST /api/trailer` | meilleurs moments |
| `POST /api/pack` | pack de publication |
| `POST /api/summary` | résumé et analyse |
| `POST /api/fixsubs` | correction des sous-titres |
| `POST /api/chat` | chat (SSE, streaming) |
| `POST /api/render` | export 16:9 / 9:16 |
| `POST /api/filmcraft` | envoi du montage dans FilmCraft |
| `GET /api/jobs/<id>/events` | progression en direct (SSE) |
| `GET /api/file?path=` | téléchargement / prévisualisation |

---

## 7. Résolution de problèmes

| Symptôme | Cause probable | Solution |
|---|---|---|
| « Ollama injoignable » | serveur arrêté | `ollama serve` |
| Transcription très lente | modèle `small` sélectionné | choisir `base` |
| Aucun silence détecté | seuil trop strict | `-30 dB` par défaut ; baisser via l'API `noise_db` |
| Sous-titres décalés | les timecodes sont recalculés automatiquement | — |
| « FilmCraft est déjà ouvert » | FilmCraft lancé à la main, sans pilotage | enregistrer, quitter FilmCraft ; MontageIA le relance |
| Port 8080 occupé | un autre service | `MONTAGIA_PORT=8090 ./start.sh` |
| L'icône ne démarre rien, « Operation not permitted » dans le journal | dossier du projet sur le Bureau ou dans Documents | déplacer le dossier (ex. `~/MontageIA`) puis relancer `./scripts/install_launcher.sh` |

---

## 8. Licences et crédits

- **qwen2.5:3b** — Alibaba, Apache 2.0
- **whisper.cpp** — MIT (Georgi Gerganov)
- **Ollama** — MIT
- **FilmCraft** — MIT ou Apache-2.0
- **FFmpeg** (build evermeet.cx) — GPL
- Vidéos de test : Wikimedia Commons (CC BY-SA) — `~/Desktop/Studio_IA/tests/`
