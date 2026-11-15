# 🎬 MontageIA — assistant de montage vidéo par IA, 100 % local

Un système d'assistance au montage vidéo qui utilise **qwen2.5:3b** sur **Ollama local**,
**whisper.cpp** pour la transcription et **ffmpeg** pour le montage réel.
Aucune donnée ne sort de la machine, aucune dépendance Python à installer.

> **Principe de conception** : un modèle 3B n'est pas fiable pour écrire des
> commandes `ffmpeg`. Ici, l'IA ne fait que du **travail sémantique court et
> structuré** (JSON) ; c'est un moteur déterministe en Python qui applique
> les découpes, les recadrages et les exports. Le LLM ne calcule **jamais**
> un timecode : il sélectionne des segments pré-calculés, identifiés `S1`, `S2`…

---

## 1. Installation

```bash
cd ~/Desktop/MontageIA
./scripts/install_models.sh     # whisper.cpp + modèles (base, small, VAD)
./start.sh                      # ouvre http://127.0.0.1:8080
```

**Prérequis** (déjà présent sur cette machine) :

| Outil | Rôle | Où il vient |
|---|---|---|
| Ollama ≥ 0.12 | LLM local | `/usr/local/bin/ollama` |
| `qwen2.5:3b` | modèle | `ollama pull qwen2.5:3b` |
| whisper.cpp | transcription | `bin/whisper-cli` + `models/` |
| ffmpeg / ffprobe | média |fourni par Kdenlive |
| melt (MLT) | validation projet Kdenlive |fourni par Kdenlive |

Aucun `pip install` : le projet n'utilise que la bibliothèque standard Python 3.9.

---

## 2. Utilisation

### Interface web (principale)

```bash
./start.sh
```

`http://127.0.0.1:8080` — glisser-déposer, progression en direct, prévisualisation.

Le parcours :

1. **Média** — déposez votre rush.
2. **Analyser** — détection des silences (0,25 s pour 3 min de vidéo).
3. **Transcrire** — Whisper + VAD → segments horodatés (9 s pour 3 min).
4. **Plan de coupe IA** — l'IA choisit les segments à garder, avec justification.
5. **Rendu** — 16:9 et/ou 9:16, sous-titres optionnels, son normalisé.
6. **Projet Kdenlive** — un `.kdenlive` prêt à ouvrir, sous-titres compris.

### Mode terminal

```bash
./start.sh --cli
# ou directement :
python3 -m montagia.cli ~/Desktop/Studio_IA/tests/vlog_valentijn.webm plan "garde le plus marquant"
```

Commandes : `analyse`, `transcribe`, `plan`, `render 16:9`, `subs`, `kdenlive`,
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
│   ├── kdenlive.py              génération de projet .kdenlive (XML MLT)
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
      → XML MLT → projet .kdenlive
```

---

## 6. API HTTP (tout est appelable en ligne de commande)

| Route | Effet |
|---|---|
| `GET /api/status` | état d'Ollama, ffmpeg, Whisper, Kdenlive |
| `POST /api/upload?name=` | téléversement (corps brut, streaming disque) |
| `POST /api/analyze` | détection des silences |
| `POST /api/transcribe` | transcription Whisper + VAD |
| `POST /api/plan` | plan de coupe IA |
| `POST /api/trailer` | meilleurs moments |
| `POST /api/pack` | pack de publication |
| `POST /api/summary` | résumé et analyse |
| `POST /api/fixsubs` | correction des sous-titres |
| `POST /api/chat` | chat (SSE, streaming) |
| `POST /api/render` | export 16:9 / 9:16 |
| `POST /api/kdenlive` | projet Kdenlive |
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
| `.kdenlive` vide à l'ouverture | profil de projet | choisir 16:9 pour une source horizontale |
| Port 8080 occupé | un autre service | `MONTAGIA_PORT=8090 ./start.sh` |

---

## 8. Licences et crédits

- **qwen2.5:3b** — Alibaba, Apache 2.0
- **whisper.cpp** — MIT (Georgi Gerganov)
- **Ollama** — MIT
- **Kdenlive / MLT** — GPL
- Vidéos de test : Wikimedia Commons (CC BY-SA) — `~/Desktop/Studio_IA/tests/`
