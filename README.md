# 🎬 Rexo Studio — dérushage et post-production vidéo assistés par IA, 100 % local

> Anciennement **MontageIA** (renommé le 16/11/2026, dossier compris : `~/RexoStudio` sur
> l'iMac). Le module Python garde son ancien nom (`montagia/`, variables `MONTAGIA_*`).

Un système d'assistance au montage vidéo qui utilise **Gemma 4 E2B** via **llama.cpp** (local),
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
cd ~/RexoStudio                 # hors du Bureau : voir la note ci-dessous
./scripts/install_models.sh       # whisper.cpp statique + modèles + ffmpeg (tout vérifié)
./scripts/build_native.sh         # bin/rexo-segment : détourage Apple Vision (effets photo)
./scripts/install_effects_env.sh  # .effets/ : Python 3.11 autonome + ONNX + MobileSAM, MI-GAN, Depth Anything
./scripts/install_launcher.sh     # icône Rexo Studio sur le Bureau
./scripts/check_install.sh        # vérifie tout par de vrais essais
```

Procédure complète pour une nouvelle machine, versions figées et mesures de référence :
**[docs/DEPLOIEMENT.md](docs/DEPLOIEMENT.md)**.

Ne placez pas le dossier du projet sur le Bureau ni dans Documents : macOS interdit à
l'icône de lancement de lire ces dossiers protégés (« Operation not permitted »).
L'icône, elle, peut être sur le Bureau.

**Prérequis** (déjà présent sur cette machine) :

| Outil | Rôle | Où il vient |
|---|---|---|
| llama.cpp b12428 | IA locale | `bin/llama-server` (compilé par le script, autonome) |
| Gemma 4 E2B Q4_0 | modèle (2,8 Go) | `models/` (SHA-256 vérifié ; repris de `~/.local/share/kdev-models` s'il y est) |
| Ollama + `qwen2.5:3b` | secours, facultatif | `MONTAGIA_LLM_BACKEND=ollama` |
| whisper.cpp | transcription | `bin/whisper-cli` (compilé en statique) + `models/` |
| ffmpeg / ffprobe | média | `bin/` (build statique evermeet, SHA-256 épinglé) |
| FilmCraft ≥ 0.20 | éditeur vidéo, piloté en direct | `/Applications/FilmCraft.app` |
| PhotoCraft ≥ 0.23 | éditeur photo, piloté sans interface (`photocraft-cli`) | `/Applications/PhotoCraft.app` |
| Outils Apple (`swiftc`) | compile `bin/rexo-segment` (Apple Vision) | `xcode-select --install` |
| Environnement d'effets | ONNX Runtime + modèles d'effets, processus séparé | `.effets/` (`install_effects_env.sh`) |

Le cœur n'utilise que la bibliothèque standard Python 3.9 (aucun `pip install`). Seuls les
effets IA (M5) tournent dans un environnement séparé, installé et vérifié par script.

---

## 2. Utilisation

### Interface web (principale)

**Double-cliquez sur l'icône Rexo Studio du Bureau** : le serveur démarre en arrière-plan
(sans fenêtre de Terminal) et l'interface s'ouvre dans le navigateur. Un nouveau clic
rouvre simplement la page. Le bouton **Quitter** de l'interface retire le modèle IA de la
mémoire et arrête le serveur. Journal : `~/Library/Logs/RexoStudio.log`.

Sans l'icône : `./start.sh` (ouvre `http://127.0.0.1:8080`, Ctrl+C pour arrêter).

**L'accueil, ce sont les événements** : un dossier par mariage,
henné, fiançailles, anniversaire, circoncision, remise de diplôme ou fête, rangé dans `~/RexoStudio/Evenements/`
(`REXO_EVENTS_DIR` pour une autre racine). La barre de recherche filtre en direct sur les
noms, le lieu, les notes, le type et la date (« novembre », « 2026-07 », « henne » sans
accent) ; les puces filtrent par type. « Nouvel événement » crée le dossier
`AAAA-MM-JJ_Type_Noms` et ses sous-dossiers (`01_Rushes` … `07_Livraison`, voir
`docs/adr/0001-evenement-dossier.md`) ; chaque carte ouvre l'événement ou un sous-dossier dans
le Finder. Les dossiers des clients ne sont jamais versionnés (`.gitignore`).

Le bouton « 🎬 Ouvrir » d'un événement le présente en **trois parties**, dans l'ordre du travail :

- **🎥 Vidéo** : import des cartes, dérushage, moments forts pour le générique ; sur chaque
  rush, ✂ détourage d'une personne et 💬 sous-titres d'un discours (`06_Rendus/Sous-titres`).
- **📷 Photo** : import, choix ★ des photos des mariés pour les clips 3D (le cadre tracé
  autour des mariés est gardé pour le clip), outils photo sur une image ou toute la série.
- **🎬 Montage** : titres du projet (noms et date de l'événement par défaut), générique des
  moments forts et clips 3D de la bibliothèque (EffectCraft), liste des rendus, puis
  **Ouvrir le montage dans FilmCraft** : un seul projet `05_Montage/Selection_<date>.fcproj`
  avec les rushes gardés en séquence et les rendus dans leurs chutiers (« Génériques »,
  « Détourages ») ; le film se termine dans FilmCraft (effets, post-production, étalonnage).

**Dérushage** (partie Vidéo, `montagia/rushes.py`) :

1. **Importer une carte mémoire** : les cartes branchées sont détectées dans `/Volumes` (ou
   indiquer un dossier). Vidéos vers `01_Rushes/Carte_n/`, photos vers `02_Photos/Carte_n/`,
   arborescence de la carte conservée. Chaque fichier est copié, **relu et comparé (SHA-256)**,
   n'apparaît qu'une fois vérifié et garde sa date d'origine ; la carte n'est jamais modifiée.
   Relancer l'import d'une carte ne recopie rien ; un même fichier sur deux cartes est repéré.
2. **Analyser les rushes** (automatique après un import) : heure de tournage (celle écrite par la
   caméra), vignette, et une passe ffmpeg sur l'image réduite qui mesure luminosité
   (`signalstats`), netteté (`blurdetect`) et tremblement (`vidstabdetect`). Défauts signalés :
   noir / cache objectif, trop sombre, surexposé, flou, tremblé, très court. Les rushes sans
   défaut sont **proposés** comme gardés ; la case « Garder » permet de changer d'avis (rien
   n'est supprimé).
3. **Créer les proxies** : copies 960 px dans `04_Proxies/` (lecture fluide, formats que le
   navigateur ne lit pas).
4. **Moments forts** : le meilleur passage de chaque rush gardé (`montagia/moments.py`),
   enregistré dans `.rexo/moments.json` et repris par le générique.

Seuils de qualité étalonnés sur des rushes simulés et sur 4 films de mariage réels (aucun faux
défaut sur 81 extraits, nuit et danse caméra à l'épaule comprises) ; à réajuster sur les
rushes bruts du studio. Pour tester sans images de clients : `./scripts/make_demo_event.sh`.

L'ancien parcours d'une vidéo parlée (coupe des hésitations, plan de coupe par l'IA) n'est
plus dans l'interface : inutile pour un film de mariage. Il reste disponible en mode terminal
ci-dessous.

Le moteur IA (`llama-server`) démarre à la première demande, reste en mémoire 5 min après sa
dernière utilisation, puis s'arrête (`MONTAGIA_LLM_IDLE=<secondes>` pour changer ce délai).
Journal du moteur : `workspace/cache/llama-server.log`.

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
| Plan de coupe | Gemma 4 E2B | JSON `{segments:[{id, reason, trim_start, trim_end}], rationale}` |
| Meilleurs moments (trailer) | Gemma 4 E2B | JSON `{segments:[{id, score, reason}]}` |
| Pack de publication | Gemma 4 E2B | titres, description, hashtags, chapitres, accroche |
| Résumé & analyse | Gemma 4 E2B | résumé, points clés, thèmes, questions |
| Correction des sous-titres | Gemma 4 E2B | JSON `{lines:[{index, text}]}` (ponctuation, casse) |
| Chat sur la vidéo | Gemma 4 E2B | texte libre, streaming |

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
| Moteur IA (plan de coupe film002, 7 min) | Ollama + qwen2.5:3b, 180 s | llama.cpp + Gemma 4 E2B | **180 s → 78 s** (2,3×) |
| Rendu | libx264 | `h264_videotoolbox` | 5,3× → **11,8×** temps réel |
| Dépendances | `auto-editor` (PyAV) | ffmpeg natif | 0 dépendance Python |

Détails qui comptent :

- **Le VAD améliore la qualité *et* la vitesse** : les marqueurs `[MUSIC]` parasites
  disparaissent, les phrases sont regroupées, et 75 % de l'audio sans parole est sauté.
- **Moteur IA (16/11/2026)** — même plan de coupe, mêmes appels, sur l'iMac :

  | Moteur + modèle | café | récit | film002 | Références FR |
  |---|---|---|---|---|
  | Ollama + qwen2.5:3b | 40 s | 24 s | 180 s | 2/2 |
  | Ollama + qwen2.5:1.5b | 34 s | 32 s | 150 s | 1/2 |
  | llama.cpp + qwen2.5:3b | 27 s | 20 s | 135 s | 2/2 |
  | llama.cpp + Qwen3.5-2B | 31 s | 23 s | 136 s | 1/2 |
  | **llama.cpp + Gemma 4 E2B** | **16 s** | **12 s** | **82 s** | **2/2** |

  Gemma lit le prompt à ~170 tokens/s (Q4_0 réorganisé par llama.cpp pour AVX2) contre ~30
  pour Ollama ; l'écriture (~12 tokens/s) devient le goulot. Réglages : 4 fils (cœurs
  physiques), flash attention, Accelerate, 1 seul emplacement. MacBook 2015 : café 25 s.
- **Whisper compressé (q8_0, q5_x) : pas retenu** — au mieux 10 % plus rapide sur l'iMac,
  mais 30 % du texte arabe change.
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
RexoStudio/
├── start.sh                     lanceur (serveur + navigateur ; Ollama si pas de llama.cpp)
├── scripts/install_models.sh    installation whisper.cpp + modèles
├── bin/whisper-cli              binaire natif
├── models/                      ggml-base.bin, ggml-small.bin, VAD Silero
├── montagia/
│   ├── config.py                chemins, seuils, détection des binaires
│   ├── tools.py                 exécution de processus, utils
│   ├── media.py                 ffprobe, silencedetect, loudness
│   ├── transcribe.py            whisper.cpp, SRT/VTT, remappage de timeline
│   ├── ai.py                    client IA (llama.cpp ou Ollama ; JSON Schema + streaming)
│   ├── llm_server.py            llama-server : démarrage à la demande, arrêt après inactivité
│   ├── prompts.py               prompts et schémas JSON
│   ├── edit.py                  moteur de rendu ffmpeg
│   ├── filmcraft.py             pilotage de FilmCraft (projet .fcproj)
│   ├── photocraft.py            pilotage de PhotoCraft sans interface (photocraft-cli)
│   ├── effects.py               effets photo : Vision + cadre PhotoCraft, aperçu, rendu
│   ├── pipeline.py              orchestration
│   ├── project.py               état d'un projet en cours
│   ├── jobs.py                  tâches longues + progression
│   └── cli.py                   mode terminal
├── native/segment.swift         outil Apple Vision (bin/rexo-segment)
├── vendor/embedkit/             socle d'IA embarquée repris de rawi (voir vendor/ORIGINE.md)
├── docs/DEPLOIEMENT.md          installer et vérifier sur une nouvelle machine
├── server/
│   ├── app.py                   serveur HTTP (SSE, threads)
│   └── static/                  index.html, app.js, style.css
└── workspace/                   media, exports, cache (généré)
```

**Flux d'une coupe :**

```
vidéo → silencedetect → segments de parole
      → whisper.cpp (+VAD) → segments horodatés
      → Gemma 4 E2B (JSON) → sélection d'identifiants
      → résolution des timecodes → plan de coupe
      → ffmpeg select/aselect → rendu 16:9 ou 9:16
      → serveur de contrôle FilmCraft → projet .fcproj
```

---

## 6. API HTTP (tout est appelable en ligne de commande)

| Route | Effet |
|---|---|
| `GET /api/status` | état du moteur IA, ffmpeg, Whisper, FilmCraft |
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
| « IA indisponible » | moteur IA non installé | `./scripts/install_models.sh` |
| « Le moteur IA s'est arrêté au démarrage » | modèle abîmé ou mémoire insuffisante | voir `workspace/cache/llama-server.log` |
| Transcription très lente | modèle `small` sélectionné | choisir `base` |
| Aucun silence détecté | seuil trop strict | `-30 dB` par défaut ; baisser via l'API `noise_db` |
| Sous-titres décalés | les timecodes sont recalculés automatiquement | — |
| « FilmCraft est déjà ouvert » | FilmCraft lancé à la main, sans pilotage | enregistrer, quitter FilmCraft ; Rexo Studio le relance |
| Port 8080 occupé | un autre service | `MONTAGIA_PORT=8090 ./start.sh` |
| L'icône ne démarre rien, « Operation not permitted » dans le journal | dossier du projet sur le Bureau ou dans Documents | déplacer le dossier (ex. `~/RexoStudio`) puis relancer `./scripts/install_launcher.sh` |

---

## 8. Licences et crédits

- **Gemma 4 E2B** — Google, Apache 2.0
- **llama.cpp** — MIT
- **qwen2.5:3b** (secours) — Alibaba, Apache 2.0
- **whisper.cpp** — MIT (Georgi Gerganov)
- **Ollama** (secours) — MIT
- **FilmCraft**, **PhotoCraft** — MIT ou Apache-2.0
- **MobileSAM** (et décodeur **SAM** de Meta) — Apache-2.0 ; **MI-GAN** — MIT ;
  **Depth Anything V2 Small** — Apache-2.0 ; **ONNX Runtime** — MIT ; **OpenCV** — Apache-2.0 ;
  **python-build-standalone** — licence de Python (PSF) ; **embedkit** — Apache-2.0
- **FFmpeg** (build evermeet.cx) — GPL
- Vidéos de test : Wikimedia Commons (CC BY-SA) — `~/Desktop/Studio_IA/tests/`
